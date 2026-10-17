import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { members, streamCouncil } from "./contract";
import type { Member, Verdict } from "./contract";

const hooks = vi.hoisted(() => ({ values: [] as unknown[], next: 0 }));
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
    useEffect: () => {},
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
  await vi.waitFor(() => {
    expect(get("className", "follow-form")).toBeDefined();
  });
}

beforeEach(() => {
  hooks.values = [];
  hooks.next = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    Response.json({ brief_id: "brief", summary: "Portfolio received" }),
  );
  vi.mocked(streamCouncil).mockReset();
  vi.mocked(streamCouncil).mockImplementation(async (_, __, ___, receive) => {
    await receive({ event: "run.started", data: { run_id: "parent" } });
    await receive({ event: "run.done", data: { run_id: "parent" } });
  });
  get("aria-label", "Upload portfolio").onChange!({
    target: {
      value: "",
      files: [
        new File(["ticker,shares,cost_basis\nAAPL,2,100"], "holdings.csv"),
      ],
    },
  });
  get("id", "persona").onChange!({ target: { value: "Long-term investor" } });
  get("id", "question").onChange!({ target: { value: "Should I hold?" } });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it.each(["request failure", "cancellation", "stream error", "early end"])(
  "allows another follow-up after %s without a new parent session",
  async (failure) => {
    submit("brief-form");
    await idle();
    get("id", "follow-question").onChange!({ target: { value: "Why hold?" } });
    if (failure === "cancellation") {
      vi.mocked(streamCouncil).mockImplementationOnce(
        (_, __, signal) =>
          new Promise<void>((_, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          }),
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
    } else {
      vi.mocked(streamCouncil).mockRejectedValueOnce(
        new Error(
          failure === "early end" ? "Connection ended early" : "HTTP 503",
        ),
      );
    }
    submit("follow-form");
    if (failure === "cancellation")
      get("className", "text-button cancel").onClick!();
    await idle();
    expect(get("className", "primary").disabled).toBe(false);
    expect(get("id", "follow-question").value).toBe("Why hold?");
    submit("follow-form");
    await idle();
    expect(streamCouncil).toHaveBeenLastCalledWith(
      "/api/council/chat",
      expect.objectContaining({ run_id: "parent", text: "Why hold?" }),
      expect.any(AbortSignal),
      expect.any(Function),
    );
    expect(get("id", "follow-question").value).toBe("");
  },
);

it("requires completion again when a new parent session fails", async () => {
  submit("brief-form");
  await idle();
  get("className", "text-button start-over").onClick!();
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "run.started", data: { run_id: "new-parent" } });
      throw new Error("HTTP 503");
    },
  );
  submit("brief-form");
  await idle();
  get("id", "follow-question").onChange!({ target: { value: "Why hold?" } });
  expect(get("className", "primary").disabled).toBe(true);
});

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
        submit("brief-form");
        await vi.advanceTimersByTimeAsync(0);
        get("id", "follow-question").onChange!({
          target: { value: "Why hold?" },
        });
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
      submit(follow ? "follow-form" : "brief-form");
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
      expect(get("className", "follow-form")).toBeDefined();
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
      submit("brief-form");
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
      expect(get("className", "follow-form")).toBeDefined();
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
      submit("brief-form");
      await vi.advanceTimersByTimeAsync(0);
      if (reason === "error") player.onerror!();
      if (reason === "pause") player.pause();
      if (reason === "cancel")
        get("className", "text-button cancel").onClick!();
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
    submit("brief-form");
    await vi.advanceTimersByTimeAsync(0);
    player.onended!();
    await vi.advanceTimersByTimeAsync(180000);
    expect(get("className", "error").children).toContain("timed out");
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["timeout", "ended", "error", "pause", "cancel"])(
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
      submit("brief-form");
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
        get("className", "text-button cancel").onClick!();
      else if (reason === "ended") previous.ended();
      else if (reason === "error") previous.error();
      else previous.pause();
      await vi.advanceTimersByTimeAsync(0);
      if (reason === "cancel") {
        get("className", "text-button start-over").onClick!();
        spokenStream();
        submit("brief-form");
        await vi.advanceTimersByTimeAsync(0);
      }
      expect(player.play).toHaveBeenCalledTimes(2);
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 3 : 1);
      expect(player.src).not.toContain("leopold");
      const nextEnded = player.onended;
      const nextProgress = player.ontimeupdate;
      expect(nextEnded).toBeTypeOf("function");
      player.currentTime = 1;
      for (const callback of Object.values(previous)) callback();
      expect(player.onended).toBe(nextEnded);
      expect(player.ontimeupdate).toBe(nextProgress);
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 3 : 1);
      if (reason === "timeout" || reason === "error")
        expect(get("className", "audio-note").children).toContain(
          reason === "timeout" ? "timed out" : "unavailable",
        );
      else expect(() => get("className", "audio-note")).toThrow("Missing");
      player.onplaying!();
      for (let i = 0; i < 4; i++) {
        await vi.advanceTimersByTimeAsync(10000);
        player.currentTime += 10;
        player.ontimeupdate!();
      }
      expect(player.pause).toHaveBeenCalledTimes(reason === "cancel" ? 3 : 1);
      player.onended!();
      await vi.advanceTimersByTimeAsync(0);
      expect(get("className", "follow-form")).toBeDefined();
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});

it("shows the chair ruling and renders chat turns from the council", async () => {
  vi.useFakeTimers();
  const call = (ticker: string, signal: Verdict["signal"]) => ({
    ticker,
    signal,
    conviction: "high" as const,
    rationale: `Returned ${ticker} rationale`,
  });
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({ event: "run.started", data: { run_id: "parent" } });
      for (const member of Object.keys(members) as Member[]) {
        await receive({
          event: "member.verdict",
          data: {
            member,
            signal: "SELL",
            headline: `Returned ${member} individual verdict`,
            confidence: 0.9,
            reasons: ["Returned individual reason"],
            sources: [],
            tickers: ["NVDA"],
            analysis: "",
            advice: [],
            positions: [call("NVDA", "SELL")],
          },
        });
      }
      await receive({
        event: "chair.summary",
        data: {
          overall_signal: "SELL",
          summary: "Returned initial chair summary",
          consensus: "Returned consensus",
          dissent: ["Returned dissent"],
          actions: ["Returned action"],
          suggestions: ["Returned chip"],
          positions: [
            {
              ticker: "NVDA",
              signal: "SELL",
              conviction: "high",
              consensus: "Returned name consensus",
            },
          ],
        },
      });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("brief-form");
  await vi.advanceTimersByTimeAsync(9000);
  hooks.next = 0;
  const app = App();
  function boardroom(node: ReactNode): Props | undefined {
    for (const child of Children.toArray(node)) {
      if (!isValidElement<Props>(child)) continue;
      if (child.props.verdicts) return child.props;
      const nested = boardroom(child.props.children);
      if (nested) return nested;
    }
  }
  const board = boardroom(app) as unknown as {
    chair: unknown;
    verdicts: Record<string, unknown>;
    onSelect: (member: string) => void;
  };
  expect(board.chair).toMatchObject({
    summary: "Returned initial chair summary",
  });
  expect(board.verdicts.dalio).toMatchObject({ signal: "SELL" });
  board.onSelect("chair");
  hooks.next = 0;
  const html = renderToStaticMarkup(App());
  const dialog = html.slice(html.indexOf("<dialog"), html.indexOf("</dialog>"));
  for (const text of [
    "Council ruling",
    "Returned initial chair summary",
    "NVDA SELL",
    "Returned consensus",
    "Returned dissent",
    "Returned action",
  ])
    expect(dialog).toContain(text);
  expect(html).toContain("Returned chip");

  get("id", "follow-question").onChange!({ target: { value: "@burry NVDA?" } });
  vi.mocked(streamCouncil).mockImplementationOnce(
    async (_, __, ___, receive) => {
      await receive({
        event: "chat.routed",
        data: { members: ["burry"], reason: "named in the question" },
      });
      await receive({
        event: "member.reply",
        data: { member: "burry", text: "Returned burry reply" },
      });
      await receive({
        event: "chat.closed",
        data: { text: "", suggestions: ["Returned next chip"] },
      });
      await receive({ event: "run.done", data: { run_id: "parent" } });
    },
  );
  submit("follow-form");
  await vi.advanceTimersByTimeAsync(1200);
  expect(streamCouncil).toHaveBeenLastCalledWith(
    "/api/council/chat",
    { run_id: "parent", text: "@burry NVDA?", roast: false },
    expect.any(AbortSignal),
    expect.any(Function),
  );
  hooks.next = 0;
  const chat = renderToStaticMarkup(App());
  for (const text of [
    "Asking Burry",
    "Returned burry reply",
    "Returned next chip",
  ])
    expect(chat).toContain(text);
});
