import { beforeEach, afterEach, expect, it, vi } from "vitest";
import VoiceInput from "./VoiceInput";

const hooks = vi.hoisted(() => ({
  values: [] as unknown[],
  next: 0,
  cleanup: undefined as (() => void) | undefined,
}));
vi.mock("react", () => {
  function useState(initial: unknown) {
    const index = hooks.next++;
    if (!(index in hooks.values)) hooks.values[index] = initial;
    return [
      hooks.values[index],
      (value: unknown) => {
        hooks.values[index] = value;
      },
    ];
  }
  return {
    useState,
    useRef: (current: unknown) => useState({ current })[0],
    useEffect: (effect: () => () => void) => {
      hooks.cleanup ??= effect();
    },
  };
});

class Recorder {
  static latest: Recorder;
  state = "inactive";
  mimeType = "audio/webm";
  onstop: (() => Promise<void>) | null = null;
  onerror: (() => void) | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  constructor() {
    Recorder.latest = this;
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
  }
  async finish() {
    this.stop();
    this.ondataavailable?.({ data: new Blob(["recorded speech"]) });
    await this.onstop?.();
  }
}
const stop = vi.fn();
const onTranscript = vi.fn();
const onBusyChange = vi.fn();
const getUserMedia = vi.fn();
function view() {
  hooks.next = 0;
  return VoiceInput({ disabled: false, onTranscript, onBusyChange });
}
function click() {
  view().props.children[0].props.onClick();
}
function message() {
  return view().props.children[1].props.children;
}

beforeEach(() => {
  hooks.values = [];
  hooks.next = 0;
  hooks.cleanup = undefined;
  vi.clearAllMocks();
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop }] });
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ text: "Why hold?" })),
  );
});
afterEach(() => {
  hooks.cleanup?.();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("releases the microphone and forwards only the provider transcript", async () => {
  click();
  await vi.waitFor(() => expect(Recorder.latest.state).toBe("recording"));
  await Recorder.latest.finish();
  expect(stop).toHaveBeenCalledOnce();
  expect(onTranscript).toHaveBeenCalledWith("Why hold?");
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
  const [url, options] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe("/api/voice/transcribe");
  expect((options!.body as FormData).get("file")).toBeInstanceOf(Blob);
  expect(message()).toContain("Review your question");
});

it("keeps the question unchanged when the provider fails", async () => {
  vi.mocked(fetch).mockResolvedValue(
    Response.json({ detail: "Voice service unavailable" }, { status: 503 }),
  );
  click();
  await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalled());
  await Recorder.latest.finish();
  expect(onTranscript).not.toHaveBeenCalled();
  expect(message()).toBe("Voice service unavailable");
  expect(onBusyChange).toHaveBeenLastCalledWith(false);
});

it("handles denied microphone permission without sending audio", async () => {
  getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
  click();
  await vi.waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  expect(message()).toContain("permission was denied");
  expect(fetch).not.toHaveBeenCalled();
});

it("stops capture on unmount and does not transcribe", async () => {
  click();
  await vi.waitFor(() => expect(Recorder.latest.state).toBe("recording"));
  hooks.cleanup?.();
  await Recorder.latest.finish();
  expect(stop).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
});

it("releases a microphone granted after unmount", async () => {
  let grant!: (value: unknown) => void;
  getUserMedia.mockImplementation(
    () =>
      new Promise((resolve) => {
        grant = resolve;
      }),
  );
  click();
  hooks.cleanup?.();
  grant({ getTracks: () => [{ stop }] });
  await vi.waitFor(() => expect(stop).toHaveBeenCalledOnce());
  expect(fetch).not.toHaveBeenCalled();
});

it("bounds recordings to sixty seconds", async () => {
  vi.useFakeTimers();
  click();
  await Promise.resolve();
  expect(Recorder.latest.state).toBe("recording");
  await vi.advanceTimersByTimeAsync(60000);
  expect(Recorder.latest.state).toBe("inactive");
});

it("aborts transcription when the form unmounts", async () => {
  let signal: AbortSignal | undefined;
  vi.mocked(fetch).mockImplementation(
    (_, options) =>
      new Promise((_, reject) => {
        signal = options?.signal as AbortSignal;
        signal.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      }),
  );
  click();
  await vi.waitFor(() => expect(Recorder.latest.state).toBe("recording"));
  const pending = Recorder.latest.finish();
  hooks.cleanup?.();
  await pending;
  expect(signal?.aborted).toBe(true);
  expect(onTranscript).not.toHaveBeenCalled();
});

it("recovers from a recorder failure and releases capture", async () => {
  click();
  await vi.waitFor(() => expect(Recorder.latest.state).toBe("recording"));
  Recorder.latest.onerror?.();
  expect(stop).toHaveBeenCalledOnce();
  expect(onBusyChange).toHaveBeenLastCalledWith(false);
  expect(message()).toContain("Recording failed");
  expect(fetch).not.toHaveBeenCalled();
});

it("shows an explicit state when recording is unsupported", () => {
  vi.stubGlobal("navigator", {});
  click();
  expect(message()).toContain("supported browser on HTTPS");
  expect(onBusyChange).not.toHaveBeenCalled();
});
