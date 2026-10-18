import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SpeechPlayback } from "./speech";

let rejectPlayback = false;
class Player {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeupdate: (() => void) | null = null;
  play = vi.fn(async () => {
    if (rejectPlayback) {
      rejectPlayback = false;
      throw new Error("Playback rejected");
    }
  });
  pause = vi.fn();
  load = vi.fn();
  removeAttribute = vi.fn();
  constructor(public src: string) {
    players.push(this);
  }
}
let players: Player[];
let changed: ReturnType<typeof vi.fn>;
let error: ReturnType<typeof vi.fn>;
let speech: SpeechPlayback;
const audioResponse = () =>
  new Response(new Blob(["test audio"]), {
    headers: { "Content-Type": "audio/mpeg" },
  });
beforeEach(() => {
  vi.useFakeTimers();
  players = [];
  rejectPlayback = false;
  changed = vi.fn();
  error = vi.fn();
  speech = new SpeechPlayback(changed, error);
  vi.stubGlobal("Audio", Player);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-audio");
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
    await speech.toggle("first", "burry", "Returned answer");
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
    await speech.toggle("first", "burry", "Returned answer");
    expect(fetch).toHaveBeenCalledOnce();
    expect(players[0].pause).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    expect(changed).toHaveBeenLastCalledWith(undefined);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops the previous clip before starting another, ignoring stale callbacks", async () => {
    await speech.toggle("first", "burry", "First");
    const ended = players[0].onended!;
    const failed = players[0].onerror!;
    await speech.toggle("second", "chair", "Second");
    expect(players[0].pause).toHaveBeenCalledOnce();
    expect(players[1].play).toHaveBeenCalledOnce();
    ended();
    failed();
    expect(changed).toHaveBeenLastCalledWith({
      id: "second",
      status: "playing",
    });
    expect(error).toHaveBeenLastCalledWith("");
    players[1].onended!();
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
      const first = speech.toggle("first", "burry", "First");
      const signal = vi.mocked(fetch).mock.calls[0][1]!.signal!;
      await speech.toggle(
        button === "same" ? "first" : "second",
        "buffett",
        "Second",
      );
      expect(signal.aborted).toBe(true);
      release(audioResponse());
      await first;
      expect(players).toHaveLength(button === "same" ? 0 : 1);
      if (button === "different")
        expect(players[0].play).toHaveBeenCalledOnce();
    },
  );

  it.each(["server", "content", "play", "media", "request timeout", "stall"])(
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
      const pending = speech.toggle("first", "burry", "First");
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
      await speech.toggle("first", "burry", "Retry");
      expect(changed).toHaveBeenLastCalledWith({
        id: "first",
        status: "playing",
      });
    },
  );

  it("reads long answers completely in endpoint-sized chunks", async () => {
    const text = "Full returned answer. ".repeat(160).trim();
    await speech.toggle("long", "chair", text);
    const ended = players[0].onended!;
    ended();
    await vi.advanceTimersByTimeAsync(0);
    const parts = vi
      .mocked(fetch)
      .mock.calls.map(
        ([, init]) => JSON.parse(String(init!.body)).text as string,
      );
    expect(parts).toHaveLength(2);
    expect(parts.every((part) => part.length <= 2500)).toBe(true);
    expect(parts.join(" ")).toBe(text);
    ended();
    expect(fetch).toHaveBeenCalledTimes(2);
    players[1].onended!();
    expect(vi.getTimerCount()).toBe(0);
  });
});
