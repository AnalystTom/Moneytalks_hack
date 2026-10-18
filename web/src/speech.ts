import { apiError } from "./contract";
import type { Speaker } from "./contract";

export type PlaybackState = { id: string; status: "loading" | "playing" };

// One owner for every scene and transcript button, including in-flight requests.
export class SpeechPlayback {
  private abort?: AbortController;
  private player?: HTMLAudioElement;
  private url?: string;
  private timer?: ReturnType<typeof setTimeout>;
  private id?: string;

  constructor(
    private changed: (state?: PlaybackState) => void,
    private error: (message: string) => void,
  ) {}

  stop() {
    this.abort?.abort();
    this.abort = undefined;
    clearTimeout(this.timer);
    if (this.player) {
      this.player.onended =
        this.player.onerror =
        this.player.ontimeupdate =
          null;
      this.player.pause();
      this.player.removeAttribute("src");
      this.player.load();
      this.player = undefined;
    }
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = undefined;
    this.id = undefined;
    this.changed(undefined);
  }

  async toggle(id: string, member: Speaker, text: string) {
    const stopping = this.id === id;
    this.stop();
    this.error("");
    if (stopping || !text.trim()) return;
    this.id = id;
    const abort = new AbortController();
    this.abort = abort;
    const fail = (message: string) => {
      if (this.abort !== abort) return;
      this.stop();
      this.error(message);
    };
    // The endpoint accepts 2,500 characters; read long answers in full, in order.
    let remaining = text.trim();
    const next = async () => {
      if (abort.signal.aborted) return;
      this.changed({ id, status: "loading" });
      let end = Math.min(remaining.length, 2500);
      if (remaining.length > end) {
        const space = remaining.lastIndexOf(" ", end);
        if (space > 0) end = space;
      }
      const part = remaining.slice(0, end);
      remaining = remaining.slice(end).trimStart();
      this.timer = setTimeout(
        () => fail("Voice request timed out. Tap the speaker to retry."),
        60000,
      );
      try {
        const response = await fetch("/api/voice/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ member, text: part }),
          signal: abort.signal,
        });
        if (!response.ok) throw await apiError(response);
        if (!response.headers.get("content-type")?.startsWith("audio/"))
          throw new Error(
            "The voice service returned no audio. Tap the speaker to retry.",
          );
        const blob = await response.blob();
        if (abort.signal.aborted) return;
        clearTimeout(this.timer);
        this.url = URL.createObjectURL(blob);
        const player = new Audio(this.url);
        this.player = player;
        const progress = () => {
          if (abort.signal.aborted || this.player !== player) return;
          clearTimeout(this.timer);
          this.timer = setTimeout(
            () => fail("Voice playback stalled. Tap the speaker to retry."),
            30000,
          );
        };
        player.ontimeupdate = progress;
        player.onerror = () => {
          if (this.player === player)
            fail("Voice could not play. Tap the speaker to retry.");
        };
        player.onended = () => {
          if (abort.signal.aborted || this.player !== player) return;
          clearTimeout(this.timer);
          player.onended = player.onerror = player.ontimeupdate = null;
          URL.revokeObjectURL(this.url!);
          this.url = undefined;
          this.player = undefined;
          if (remaining) void next();
          else this.stop();
        };
        progress();
        await player.play().catch(() => {
          if (this.player === player)
            fail("Voice could not play. Tap the speaker to retry.");
        });
        if (!abort.signal.aborted && this.player === player)
          this.changed({ id, status: "playing" });
      } catch (cause) {
        if (!abort.signal.aborted)
          fail(
            cause instanceof Error
              ? cause.message
              : "Voice unavailable. Tap the speaker to retry.",
          );
      }
    };
    await next();
  }
}
