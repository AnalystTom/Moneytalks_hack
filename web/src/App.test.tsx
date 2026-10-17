import { Children, isValidElement } from "react";
import type { ReactNode } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { streamCouncil } from "./contract";

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
      "/api/council/ask",
      expect.objectContaining({ run_id: "parent", question: "Why hold?" }),
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
    "lets progressing speech finish naturally (follow-up: %s)",
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
        player.currentTime = 0;
        player.onended!();
        await vi.advanceTimersByTimeAsync(0);
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
});
