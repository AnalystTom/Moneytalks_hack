import { readFileSync } from "node:fs";
import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { streamCouncil } from "./contract";
import type { Verdict } from "./contract";

const hooks = vi.hoisted(() => ({
  values: [] as unknown[],
  next: 0,
  effects: [] as (() => unknown)[],
}));
vi.mock("react", async (importOriginal) => {
  const react = await importOriginal<typeof import("react")>();
  function useState(initial: unknown) {
    const index = hooks.next++;
    if (!(index in hooks.values)) hooks.values[index] = initial;
    return [
      hooks.values[index],
      (value: unknown) => {
        hooks.values[index] =
          typeof value === "function" ? value(hooks.values[index]) : value;
      },
    ];
  }
  return {
    ...react,
    useState,
    useRef: (current: unknown) => useState({ current })[0],
    useEffect: (effect: () => unknown) => {
      hooks.effects.push(effect);
    },
  };
});
vi.mock("./contract", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./contract")>()),
  streamCouncil: vi.fn(),
}));

type Props = {
  [key: string]: unknown;
  children?: ReactNode;
  ref?: { current: unknown };
  disabled?: boolean;
  onClick?: () => void;
  onSubmit?: (event: { preventDefault: () => void }) => void;
  onChange?: (event: { target: { value: string; files?: File[] } }) => void;
};
function find(node: ReactNode, key: string, value: string): Props | undefined {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<Props>(child)) continue;
    if (child.props[key] === value) return child.props;
    const nested = find(child.props.children, key, value);
    if (nested) return nested;
  }
}
function get(key: string, value: string): Props {
  hooks.next = 0;
  const props = find(App(), key, value);
  if (!props) throw new Error(`Missing ${key}=${value}`);
  return props;
}
function submit(className: string) {
  get("className", className).onSubmit!({ preventDefault() {} });
}
async function idle() {
  await vi.waitFor(() =>
    expect(get("aria-label", "Send message")).toBeDefined(),
  );
}
const verdict: Verdict = {
  member: "buffett",
  signal: "HOLD",
  headline: "Returned portfolio answer. More context for details.",
  reasons: ["Returned reason"],
  sources: [],
  tickers: [],
  analysis: "",
  positions: [],
  advice: [],
};
async function replySession() {
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "run.started", data: { run_id: "parent" } });
      await receive({ event: "member.verdict", data: verdict });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(1200);
  get("className", "reply-button").onClick!();
  get("id", "message").onChange!({ target: { value: "Why hold?" } });
}

beforeEach(async () => {
  hooks.values = [];
  hooks.next = 0;
  hooks.effects = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (input === "/demo-portfolio.json")
      return Response.json(
        JSON.parse(
          readFileSync(
            new URL("../../data/portfolio.json", import.meta.url),
            "utf8",
          ),
        ),
      );
    if (input === "/demo-persona.md")
      return new Response(
        readFileSync(new URL("../../data/PERSONA.md", import.meta.url), "utf8"),
      );
    return Response.json({
      brief_id: "brief",
      summary: "Portfolio received",
      voice: true,
    });
  });
  vi.mocked(streamCouncil).mockReset();
  vi.mocked(streamCouncil).mockImplementation(async (_, __, ___, receive) => {
    await receive({ event: "run.started", data: { run_id: "parent" } });
    await receive({ event: "run.done", data: { run_id: "parent" } });
  });
  get("className", "chat-form");
  hooks.effects[0]();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Jordan’s portfolio loaded",
    ),
  );
  get("id", "message").onChange!({ target: { value: "Should I hold?" } });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("auto-ingests the checked-in context and renders only chat with one composer", async () => {
  expect(fetch).toHaveBeenCalledWith(
    "/api/ingest",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).toContain("Jordan’s portfolio loaded");
  expect(html).not.toContain("brief-form");
  expect(html).not.toContain("Upload portfolio");
  expect(html).not.toContain("Preview backend");
  expect(html.match(/<textarea/g)).toHaveLength(1);
  submit("chat-form");
  await idle();
  expect(streamCouncil).toHaveBeenCalledWith(
    "/api/council/run",
    expect.objectContaining({ brief_id: "brief", question: "Should I hold?" }),
    expect.any(AbortSignal),
    expect.any(Function),
  );
});

it.each(["request failure", "cancellation", "stream error", "early end"])(
  "preserves the message and permits retry after %s",
  async (failure) => {
    if (failure === "cancellation") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        (_, __, signal) =>
          new Promise<void>((_, reject) =>
            signal.addEventListener("abort", () => reject(signal.reason)),
          ),
      );
    } else if (failure === "stream error") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        async (_, __, ___, receive) => {
          await receive({
            event: "run.error",
            data: { message: "Unavailable" },
          });
          throw new Error("Unavailable");
        },
      );
    } else vi.mocked(streamCouncil).mockRejectedValueOnce(new Error(failure));
    submit("chat-form");
    if (failure === "cancellation") {
      await vi.waitFor(() => expect(streamCouncil).toHaveBeenCalledOnce());
      get("aria-label", "Cancel session").onClick!();
    }
    await idle();
    expect(get("id", "message").value).toBe("Should I hold?");
    submit("chat-form");
    await idle();
    expect(streamCouncil).toHaveBeenCalledTimes(2);
    expect(get("id", "message").value).toBe("");
  },
);

it("cancels during health loading before opening a stream and permits retry", async () => {
  let release!: (response: Response) => void;
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  submit("chat-form");
  get("aria-label", "Cancel session").onClick!();
  release(Response.json({ voice: true }));
  await idle();
  expect(streamCouncil).not.toHaveBeenCalled();
  submit("chat-form");
  await idle();
  expect(streamCouncil).toHaveBeenCalledOnce();
});

it.each([
  ["unknown brief_id", false, "reload", false],
  ["unknown run_id", true, "replace", false],
  ["unknown brief_id", false, "replace", true],
  ["unknown run_id", true, "reload", true],
] as const)(
  "recovers from %s (follow-up: %s, recovery: %s, stream error: %s)",
  async (detail, follow, recovery, streamed) => {
    vi.useFakeTimers();
    if (follow) await replySession();
    const message = follow ? "Why hold?" : "Should I hold?";
    const fetchContext = vi.mocked(fetch).getMockImplementation()!;
    const { streamCouncil: requestCouncil } =
      await vi.importActual<typeof import("./contract")>("./contract");
    vi.mocked(streamCouncil).mockImplementationOnce(requestCouncil);
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      if (input === "/api/council/run" || input === "/api/council/chat")
        return streamed
          ? new Response(
              `event: run.error\ndata: ${JSON.stringify({ message: detail })}\n\n`,
              { headers: { "Content-Type": "text/event-stream" } },
            )
          : Response.json({ detail }, { status: 404 });
      return fetchContext(input, options);
    });
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    );
    expect(get("id", "message").value).toBe(message);
    expect(get("aria-label", "Send message").disabled).toBe(true);
    expect(get("className", "error").children).toContain("context expired");
    expect(() => get("className", "reply-target")).toThrow("Missing");
    if (follow) expect(get("className", "reply-button").disabled).toBe(true);
    const calls = vi.mocked(streamCouncil).mock.calls.length;
    submit("chat-form");
    expect(streamCouncil).toHaveBeenCalledTimes(calls);

    vi.mocked(fetch).mockImplementation(async (input, options) =>
      input === "/api/ingest"
        ? Response.json({ brief_id: "fresh", summary: "Portfolio received" })
        : fetchContext(input, options),
    );
    if (recovery === "reload") {
      get("className", "context-retry").onClick!();
    } else {
      expect(get("aria-label", "Replace portfolio").disabled).toBe(false);
      get("aria-label", "Replace portfolio").onChange!({
        target: {
          value: "",
          files: [
            new File(
              ["ticker,shares,cost_basis\nAAPL,2,100"],
              "replacement.csv",
            ),
          ],
        },
      });
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      recovery === "reload"
        ? "Jordan’s portfolio loaded"
        : "replacement.csv loaded",
    );
    expect(get("aria-label", "Send message").disabled).toBe(false);
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/run",
      { brief_id: "fresh", question: message, roast: false },
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(get("id", "message").value).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("shows real returned answers and ruling as avatar messages with full details", async () => {
  vi.useFakeTimers();
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "member.verdict", data: verdict });
      await receive({
        event: "chair.summary",
        data: {
          overall_signal: "HOLD",
          summary: "Returned final ruling",
          consensus: "Returned consensus",
          dissent: ["Returned dissent"],
          actions: [],
          suggestions: [],
          positions: [],
        },
      });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("chat-form");
  await vi.advanceTimersByTimeAsync(1200);
  expect(get("active", "buffett").animation).toEqual({ buffett: "drumming" });
  await vi.advanceTimersByTimeAsync(1700);
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  for (const text of [
    "Should I hold?",
    verdict.headline,
    "Returned reason",
    "Returned final ruling",
    "Returned consensus",
    "Returned dissent",
    "chat-avatar",
  ])
    expect(html).toContain(text);
});

it("shows context failure, disables send, and retries the real loading path", async () => {
  const fetchContext = vi.mocked(fetch).getMockImplementation()!;
  hooks.values = [];
  hooks.next = 0;
  hooks.effects = [];
  vi.mocked(fetch).mockResolvedValue(
    new Response("Unavailable", { status: 503 }),
  );
  get("className", "chat-form");
  hooks.effects[0]();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    ),
  );
  expect(get("aria-label", "Send message").disabled).toBe(true);
  expect(get("className", "error").children).toContain("unavailable");
  vi.mocked(fetch).mockImplementation(fetchContext);
  get("className", "context-retry").onClick!();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "Jordan’s portfolio loaded",
    ),
  );
});

it("clears old answers only after a replacement portfolio is accepted", async () => {
  vi.useFakeTimers();
  await replySession();
  vi.useRealTimers();
  const label = "Jordan’s portfolio loaded";
  vi.mocked(fetch).mockResolvedValueOnce(
    Response.json({ detail: "Invalid holdings" }, { status: 422 }),
  );
  const replace = () =>
    get("aria-label", "Replace portfolio").onChange!({
      target: {
        value: "",
        files: [
          new File(["ticker,shares,cost_basis\nAAPL,2,100"], "replacement.csv"),
        ],
      },
    });
  replace();
  await vi.waitFor(() =>
    expect(get("className", "error").children).toBe("Invalid holdings"),
  );
  expect(get("className", "context-chip").children).toBe(label);
  hooks.next = 0;
  expect(renderToStaticMarkup(App())).toContain(verdict.headline);
  replace();
  await vi.waitFor(() =>
    expect(get("className", "context-chip").children).toBe(
      "replacement.csv loaded",
    ),
  );
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  expect(html).not.toContain(verdict.headline);
  expect(html).not.toContain("reply-target");
  expect(html).not.toContain("chat-avatar");
});

it.each([
  [false, false],
  [false, true],
  [true, false],
  [true, true],
])(
  "retries the accepted upload after expiry (follow-up: %s, rejected replacement: %s)",
  async (follow, rejected) => {
    vi.useFakeTimers();
    const sentContext = async () => {
      const body = vi
        .mocked(fetch)
        .mock.calls.filter(([path]) => path === "/api/ingest")
        .at(-1)?.[1]?.body;
      if (!(body instanceof FormData)) throw new Error("Missing ingest form");
      return Object.fromEntries(
        await Promise.all(
          Array.from(body, async ([key, value]) => [
            key,
            typeof value === "string" ? value : await value.text(),
          ]),
        ),
      );
    };
    const initial = await sentContext();
    const csv = "ticker,shares,cost_basis\nMSFT,7,200";
    const holdings = JSON.stringify({
      holdings: [{ ticker: "MSFT", shares: 7, cost_basis: 200 }],
    });
    const uploaded = follow
      ? new File(
          [
            JSON.stringify({
              positions: [{ symbol: "MSFT", qty: 7, avg_entry_price: 200 }],
            }),
          ],
          "uploaded.json",
        )
      : new File([csv], "uploaded.csv");
    const replace = (file: File) =>
      get("aria-label", "Replace portfolio").onChange!({
        target: { value: "", files: [file] },
      });
    replace(uploaded);
    await vi.advanceTimersByTimeAsync(0);
    const accepted = await sentContext();
    expect(accepted).toEqual({
      portfolio: follow ? holdings : csv,
      persona: initial.persona,
      plaid: "false",
    });
    expect(get("className", "context-chip").children).toBe(
      `${uploaded.name} loaded`,
    );
    await replySession();
    if (!follow) get("className", "reply-target").onClick!();
    if (rejected) {
      vi.mocked(fetch).mockResolvedValueOnce(
        Response.json({ detail: "Invalid holdings" }, { status: 422 }),
      );
      replace(new File(["invalid"], "rejected.csv"));
      await vi.advanceTimersByTimeAsync(0);
      expect(get("className", "error").children).toBe("Invalid holdings");
      expect(get("className", "context-chip").children).toBe(
        `${uploaded.name} loaded`,
      );
    }
    vi.mocked(streamCouncil).mockRejectedValueOnce(
      new Error(follow ? "unknown run_id" : "unknown brief_id"),
    );
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(get("className", "context-chip").children).toBe(
      "Portfolio unavailable",
    );
    vi.mocked(fetch).mockClear();
    get("className", "context-retry").onClick!();
    await vi.advanceTimersByTimeAsync(0);
    expect(await sentContext()).toEqual(accepted);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(get("className", "context-chip").children).toBe(
      `${uploaded.name} loaded`,
    );
    expect(get("id", "message").value).toBe("Why hold?");
    expect(get("aria-label", "Send message").disabled).toBe(false);
    hooks.next = 0;
    expect(renderToStaticMarkup(App())).toContain(verdict.headline);
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/run",
      { brief_id: "brief", question: "Why hold?", roast: false },
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(vi.getTimerCount()).toBe(0);
  },
);

describe("spoken answers", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("window", { location: { origin: "http://localhost" } });
  });

  function audioPlayer() {
    const player = {
      src: "",
      currentTime: 0,
      ended: false,
      onended: null as (() => void) | null,
      onpause: null as (() => void) | null,
      onplaying: null as (() => void) | null,
      ontimeupdate: null as (() => void) | null,
      onerror: null as (() => void) | null,
      play: vi.fn(async () => {}),
      pause: vi.fn((): void => {
        player.onpause?.();
      }),
    };
    get("aria-label", "Council voice playback").ref!.current = player;
    return player;
  }

  function spokenStream() {
    vi.mocked(streamCouncil).mockImplementationOnce(
      async (_, __, signal, receive) => {
        await receive({ event: "run.started", data: { run_id: "parent" } });
        await receive({
          event: "member.audio",
          data: { member: "buffett", audio_url: "/api/voice/speak" },
        });
        signal.throwIfAborted();
        await receive({ event: "run.done", data: { run_id: "parent" } });
      },
    );
  }

  it.each([false, true])(
    "finishes progressing speech through pause, microtasks, then ended (follow-up: %s)",
    async (follow) => {
      if (follow) {
        await replySession();
      }
      const player = audioPlayer();
      const speakers = follow
        ? (["buffett"] as const)
        : (["leopold", "cramer", "burry", "buffett"] as const);
      vi.mocked(streamCouncil).mockImplementationOnce(
        async (_, __, signal, receive) => {
          await receive({ event: "run.started", data: { run_id: "parent" } });
          for (const member of speakers) {
            await receive({
              event: "member.audio",
              data: { member, audio_url: `/api/voice/speak?member=${member}` },
            });
            signal.throwIfAborted();
          }
          await receive({ event: "run.done", data: { run_id: "parent" } });
        },
      );
      submit("chat-form");
      await vi.advanceTimersByTimeAsync(0);
      for (let i = 0; i < speakers.length; i++) {
        expect(player.play).toHaveBeenCalledTimes(i + 1);
        player.onplaying!();
        for (let seconds = 0; seconds < (follow ? 200 : 50); seconds += 10) {
          await vi.advanceTimersByTimeAsync(10000);
          player.currentTime += 10;
          player.ontimeupdate?.();
        }
        expect(player.pause).toHaveBeenCalledTimes(i);
        player.ended = true;
        const source = player.src;
        player.onpause!();
        await vi.advanceTimersByTimeAsync(0);
        expect(player.play).toHaveBeenCalledTimes(i + 1);
        expect(player.pause).toHaveBeenCalledTimes(i);
        expect(player.src).toBe(source);
        player.onended!();
        await vi.advanceTimersByTimeAsync(0);
        player.ended = false;
        player.currentTime = 0;
      }
      expect(player.pause).toHaveBeenCalledTimes(speakers.length);
      expect(get("aria-label", "Send message")).toBeDefined();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each([false, true])(
    "reports and releases audio with no progress (started: %s)",
    async (started) => {
      const player = audioPlayer();
      if (!started)
        player.play.mockImplementation(() => new Promise<void>(() => {}));
      spokenStream();
      submit("chat-form");
      await vi.advanceTimersByTimeAsync(0);
      if (started) {
        player.onplaying!();
        await vi.advanceTimersByTimeAsync(10000);
        player.currentTime = 10;
        player.ontimeupdate!();
      }
      for (let i = 0; i < 5; i++) {
        await vi.advanceTimersByTimeAsync(5000);
        player.ontimeupdate?.();
      }
      expect(player.pause).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(5000);
      expect(player.pause).toHaveBeenCalledOnce();
      expect(get("className", "audio-note").children).toContain("timed out");
      expect(get("aria-label", "Send message")).toBeDefined();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each(["error", "autoplay rejection", "pause", "cancel"])(
    "releases playback and its timer after %s",
    async (reason) => {
      const player = audioPlayer();
      if (reason === "autoplay rejection")
        player.play.mockRejectedValue(new Error("Not allowed"));
      spokenStream();
      submit("chat-form");
      await vi.advanceTimersByTimeAsync(0);
      if (reason === "error") player.onerror!();
      if (reason === "pause") player.pause();
      if (reason === "cancel") get("aria-label", "Cancel session").onClick!();
      await vi.advanceTimersByTimeAsync(0);
      expect(player.pause).toHaveBeenCalled();
      if (reason === "error")
        expect(get("className", "audio-note").children).toContain(
          "unavailable",
        );
      if (reason === "autoplay rejection")
        expect(get("className", "audio-note").children).toContain(
          "automatically",
        );
      if (reason === "cancel")
        expect(get("className", "error").children).toContain("cancelled");
      expect(player.ontimeupdate).toBeNull();
      expect(player.onplaying).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each(["disabled", "unknown"])(
    "never loads audio when voice capability is %s",
    async (capability) => {
      vi.mocked(fetch).mockImplementation(async () =>
        Response.json({
          brief_id: "brief",
          summary: "Portfolio received",
          ...(capability === "disabled" ? { voice: false } : {}),
        }),
      );
      const player = audioPlayer();
      spokenStream();
      submit("chat-form");
      await vi.advanceTimersByTimeAsync(1200);
      expect(player.play).not.toHaveBeenCalled();
      expect(player.src).toBe("");
      expect(get("aria-label", "Send message")).toBeDefined();
    },
  );

  it("stops requesting voice after a playback failure", async () => {
    const player = audioPlayer();
    vi.mocked(streamCouncil).mockImplementationOnce(
      async (_, __, ___, receive) => {
        for (const member of ["leopold", "buffett"] as const)
          await receive({
            event: "member.audio",
            data: { member, audio_url: `/api/voice/speak?member=${member}` },
          });
        await receive({ event: "run.done", data: { run_id: "parent" } });
      },
    );
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    player.onerror!();
    await vi.advanceTimersByTimeAsync(1200);
    expect(player.play).toHaveBeenCalledOnce();
    expect(player.src).toContain("leopold");
    expect(get("aria-label", "Council voice playback").controls).toBe(false);
    expect(get("aria-label", "Send message")).toBeDefined();
  });

  it("still times out a server that stops responding after speech", async () => {
    const player = audioPlayer();
    vi.mocked(streamCouncil).mockImplementationOnce(
      async (_, __, signal, receive) => {
        await receive({
          event: "member.audio",
          data: { member: "buffett", audio_url: "/api/voice/speak" },
        });
        await new Promise<void>((_, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      },
    );
    submit("chat-form");
    await vi.advanceTimersByTimeAsync(0);
    player.onended!();
    await vi.advanceTimersByTimeAsync(180000);
    expect(get("className", "error").children).toContain("timed out");
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["timeout", "ended", "pause", "cancel"])(
    "ignores settled callbacks and source-replacement rejection after %s",
    async (reason) => {
      const player = audioPlayer();
      player.pause.mockImplementation(() => {});
      let rejectFirst!: (reason: Error) => void;
      player.play.mockImplementationOnce(
        () =>
          new Promise<void>((_, reject) => {
            rejectFirst = reject;
          }),
      );
      let source = "";
      Object.defineProperty(player, "src", {
        get: () => source,
        set: (value: string) => {
          const replacing = !!source;
          source = value;
          if (replacing)
            queueMicrotask(() =>
              rejectFirst(new DOMException("Source replaced", "AbortError")),
            );
        },
      });
      vi.mocked(streamCouncil).mockImplementationOnce(
        async (_, __, signal, receive) => {
          await receive({ event: "run.started", data: { run_id: "parent" } });
          for (const member of ["leopold", "buffett"] as const) {
            await receive({
              event: "member.audio",
              data: { member, audio_url: `/api/voice/speak?member=${member}` },
            });
            signal.throwIfAborted();
          }
          await receive({ event: "run.done", data: { run_id: "parent" } });
        },
      );
      submit("chat-form");
      await vi.advanceTimersByTimeAsync(0);
      const previous = {
        ended: player.onended!,
        pause: player.onpause!,
        playing: player.onplaying!,
        progress: player.ontimeupdate!,
        error: player.onerror!,
      };
      if (reason === "timeout") await vi.advanceTimersByTimeAsync(30000);
      else if (reason === "cancel")
        get("aria-label", "Cancel session").onClick!();
      else if (reason === "ended") previous.ended();
      else previous.pause();
      await vi.advanceTimersByTimeAsync(0);
      if (reason === "cancel") {
        spokenStream();
        submit("chat-form");
        await vi.advanceTimersByTimeAsync(0);
      }
      expect(player.play).toHaveBeenCalledTimes(2);
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 2 : 1);
      expect(player.src).not.toContain("leopold");
      const nextEnded = player.onended;
      const nextProgress = player.ontimeupdate;
      expect(nextEnded).toBeTypeOf("function");
      player.currentTime = 1;
      for (const callback of Object.values(previous)) callback();
      expect(player.onended).toBe(nextEnded);
      expect(player.ontimeupdate).toBe(nextProgress);
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 2 : 1);
      if (reason === "timeout")
        expect(get("className", "audio-note").children).toContain("timed out");
      else expect(() => get("className", "audio-note")).toThrow("Missing");
      player.onplaying!();
      for (let i = 0; i < 4; i++) {
        await vi.advanceTimersByTimeAsync(10000);
        player.currentTime += 10;
        player.ontimeupdate!();
      }
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 2 : 1);
      player.onended!();
      await vi.advanceTimersByTimeAsync(0);
      expect(get("aria-label", "Send message")).toBeDefined();
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});
