import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SpeechPlayback } from "./speech";

let rejectPlayback = false;
let rejectAuthorization = false;
let inGesture = false;
let authorization: Promise<void> | undefined;
class Player {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeupdate: (() => void) | null = null;
  authorized = false;
  clips: string[] = [];
  play = vi.fn(async () => {
    if (inGesture) {
      if (rejectAuthorization) {
        rejectAuthorization = false;
        throw new Error("Authorization rejected");
      }
      this.authorized = true;
    }
    if (!this.authorized) throw new Error("User gesture required");
    if (this.src.startsWith("blob:")) this.clips.push(this.src);
    if (rejectPlayback && this.src.startsWith("blob:")) {
      rejectPlayback = false;
      throw new Error("Playback rejected");
    }
    if (!this.src.startsWith("blob:")) await authorization;
  });
  pause = vi.fn();
  load = vi.fn();
  removeAttribute = vi.fn(() => {
    this.src = "";
  });
  constructor(public src = "") {
    players.push(this);
  }
}
let players: Player[];
let changed: ReturnType<typeof vi.fn>;
let error: ReturnType<typeof vi.fn>;
let speech: SpeechPlayback;
function click(...args: Parameters<SpeechPlayback["toggle"]>) {
  inGesture = true;
  try {
    return speech.toggle(...args);
  } finally {
    inGesture = false;
  }
}
const audioResponse = () =>
  new Response(new Blob(["test audio"]), {
    headers: { "Content-Type": "audio/mpeg" },
  });
beforeEach(() => {
  vi.useFakeTimers();
  players = [];
  rejectPlayback = false;
  rejectAuthorization = false;
  inGesture = false;
  authorization = undefined;
  changed = vi.fn();
  error = vi.fn();
  speech = new SpeechPlayback(changed, error);
  vi.stubGlobal("Audio", Player);
  let clip = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(
    () => `blob:clip-${++clip}`,
  );
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => audioResponse()),
  );
});
afterEach(() => {
  speech.stop();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("explicit speech playback", () => {
  it("makes no request until clicked, reports loading/playing, and toggles off", async () => {
    expect(fetch).not.toHaveBeenCalled();
    expect(players).toHaveLength(0);
    const pending = click("first", "burry", "Returned answer");
    expect(players).toHaveLength(1);
    expect(players[0].play).toHaveBeenCalledOnce();
    expect(players[0].authorized).toBe(true);
    await pending;
    expect(players[0].clips).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/voice/speak",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ member: "burry", text: "Returned answer" }),
      }),
    );
    expect(changed).toHaveBeenCalledWith({ id: "first", status: "loading" });
    expect(changed).toHaveBeenLastCalledWith({
      id: "first",
      status: "playing",
    });
    await click("first", "burry", "Returned answer");
    expect(fetch).toHaveBeenCalledOnce();
    expect(players[0].pause).toHaveBeenCalledTimes(2);
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    expect(changed).toHaveBeenLastCalledWith(undefined);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops the previous clip before starting another, ignoring stale callbacks", async () => {
    await click("first", "burry", "First");
    const ended = players[0].onended!;
    const failed = players[0].onerror!;
    const progress = players[0].ontimeupdate!;
    await click("second", "chair", "Second");
    expect(players).toHaveLength(1);
    expect(players[0].pause).toHaveBeenCalledTimes(3);
    expect(players[0].clips).toHaveLength(2);
    ended();
    failed();
    progress();
    expect(changed).toHaveBeenLastCalledWith({
      id: "second",
      status: "playing",
    });
    expect(error).toHaveBeenLastCalledWith("");
    players[0].onended!();
    expect(changed).toHaveBeenLastCalledWith(undefined);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["same", "different"])(
    "cancels loading on a %s button click and discards the late response",
    async (button) => {
      let release!: (response: Response) => void;
      vi.mocked(fetch).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            release = resolve;
          }),
      );
      const first = click("first", "burry", "First");
      await vi.advanceTimersByTimeAsync(0);
      const signal = vi.mocked(fetch).mock.calls[0][1]!.signal!;
      await click(button === "same" ? "first" : "second", "buffett", "Second");
      expect(signal.aborted).toBe(true);
      release(audioResponse());
      await first;
      expect(players).toHaveLength(1);
      expect(players[0].clips).toHaveLength(button === "same" ? 0 : 1);
    },
  );

  it.each([
    "authorization",
    "server",
    "content",
    "play",
    "media",
    "request timeout",
    "stall",
  ])(
    "reports %s failure, frees resources and allows retry",
    async (failure) => {
      if (failure === "server")
        vi.mocked(fetch).mockResolvedValueOnce(
          Response.json({ detail: "Voice unavailable" }, { status: 503 }),
        );
      if (failure === "content")
        vi.mocked(fetch).mockResolvedValueOnce(Response.json({}));
      if (failure === "request timeout")
        vi.mocked(fetch).mockImplementationOnce(() => new Promise(() => {}));
      if (failure === "play") rejectPlayback = true;
      if (failure === "authorization") rejectAuthorization = true;
      const pending = click("first", "burry", "First");
      if (failure === "media") {
        await vi.advanceTimersByTimeAsync(0);
        players[0].onerror!();
      } else if (failure === "request timeout")
        await vi.advanceTimersByTimeAsync(60000);
      else {
        await pending;
        if (failure === "stall") await vi.advanceTimersByTimeAsync(30000);
      }
      expect(error).toHaveBeenLastCalledWith(
        expect.stringMatching(
          /unavailable|no audio|could not play|timed out|stalled/,
        ),
      );
      expect(changed).toHaveBeenLastCalledWith(undefined);
      await click("first", "burry", "Retry");
      expect(players).toHaveLength(1);
      expect(changed).toHaveBeenLastCalledWith({
        id: "first",
        status: "playing",
      });
    },
  );

  it("reads long answers completely in endpoint-sized chunks", async () => {
    const text = "Full returned answer. ".repeat(260).trim();
    await click("long", "chair", text);
    const ended = players[0].onended!;
    const failed = players[0].onerror!;
    ended();
    await vi.advanceTimersByTimeAsync(0);
    ended();
    failed();
    expect(error).toHaveBeenLastCalledWith("");
    expect(fetch).toHaveBeenCalledTimes(2);
    players[0].onended!();
    await vi.advanceTimersByTimeAsync(0);
    const parts = vi
      .mocked(fetch)
      .mock.calls.map(
        ([, init]) => JSON.parse(String(init!.body)).text as string,
      );
    expect(parts).toHaveLength(3);
    expect(parts.every((part) => part.length <= 2500)).toBe(true);
    expect(parts.join(" ")).toBe(text);
    expect(players).toHaveLength(1);
    expect(players[0].clips).toHaveLength(3);
    players[0].onended!();
    expect(changed).toHaveBeenLastCalledWith(undefined);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["stop", "replace"])(
    "ignores late authorization after %s",
    async (action) => {
      let authorize!: () => void;
      authorization = new Promise<void>((resolve) => {
        authorize = resolve;
      });
      const pending = click("first", "burry", "First");
      authorization = undefined;
      if (action === "stop") speech.stop();
      else await click("second", "chair", "Second");
      authorize();
      await pending;
      expect(players).toHaveLength(1);
      expect(players[0].clips).toHaveLength(action === "stop" ? 0 : 1);
      expect(fetch).toHaveBeenCalledTimes(action === "stop" ? 0 : 1);
      if (action === "replace") {
        expect(changed).toHaveBeenLastCalledWith({
          id: "second",
          status: "playing",
        });
        players[0].onended!();
      }
      expect(vi.getTimerCount()).toBe(0);
    },
  );
});
