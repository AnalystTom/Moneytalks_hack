import { useEffect, useRef, useState } from "react";
import { apiError } from "./contract";

type Props = {
  disabled: boolean;
  onTranscript: (text: string) => void;
  onBusyChange: (busy: boolean) => void;
};

export default function VoiceInput({
  disabled,
  onTranscript,
  onBusyChange,
}: Props) {
  const [state, setState] = useState("idle");
  const [message, setMessage] = useState("");
  const recording = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const mounted = useRef(true);
  const active = useRef(false);

  function releaseMicrophone() {
    clearTimeout(timer.current);
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
      if (recording.current) recording.current.onerror = null;
      if (recording.current?.state === "recording") recording.current.stop();
      releaseMicrophone();
    };
  }, []);

  async function start() {
    if (active.current || disabled) return;
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setMessage(
        "Microphone recording needs a supported browser on HTTPS. You can type your question.",
      );
      return;
    }
    active.current = true;
    setMessage("");
    setState("permission");
    onBusyChange(true);
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = media;
      const recorder = new MediaRecorder(media);
      recording.current = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        recorder.onstop = null;
        if (recorder.state === "recording") recorder.stop();
        releaseMicrophone();
        active.current = false;
        setState("idle");
        onBusyChange(false);
        setMessage("Recording failed. Please try again or type your question.");
      };
      recorder.onstop = async () => {
        releaseMicrophone();
        if (!mounted.current) return;
        setState("transcribing");
        const abort = new AbortController();
        controller.current = abort;
        const timeout = setTimeout(() => abort.abort(), 75000);
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType });
          if (!blob.size)
            throw new Error("The recording is empty. Please try again.");
          if (blob.size > 5 * 1024 * 1024)
            throw new Error(
              "The recording exceeds 5 MB. Please record a shorter question.",
            );
          const form = new FormData();
          form.append("file", blob, "question");
          const response = await fetch("/api/voice/transcribe", {
            method: "POST",
            body: form,
            signal: abort.signal,
          });
          if (!response.ok) throw await apiError(response);
          const result = await response.json();
          if (!result || typeof result.text !== "string" || !result.text.trim())
            throw new Error("No speech was detected. Please try again.");
          if (mounted.current) {
            onTranscript(result.text.trim());
            setMessage("Transcribed. Review your question, then send it.");
          }
        } catch (cause) {
          if (mounted.current)
            setMessage(
              abort.signal.aborted
                ? "Transcription timed out. Please try again."
                : cause instanceof Error
                  ? cause.message
                  : "Transcription failed. Please type your question.",
            );
        } finally {
          clearTimeout(timeout);
          active.current = false;
          if (mounted.current) {
            setState("idle");
            onBusyChange(false);
          }
        }
      };
      recorder.start();
      setState("recording");
      timer.current = setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 60000);
    } catch (cause) {
      releaseMicrophone();
      active.current = false;
      if (mounted.current) {
        setState("idle");
        onBusyChange(false);
        setMessage(
          cause instanceof DOMException && cause.name === "NotAllowedError"
            ? "Microphone permission was denied. Allow access in your browser or type your question."
            : "Microphone unavailable. Check your input device or type your question.",
        );
      }
    }
  }

  return (
    <div className="voice-input">
      <button
        type="button"
        className="text-button"
        disabled={
          disabled || state === "permission" || state === "transcribing"
        }
        aria-pressed={state === "recording"}
        onClick={() => {
          if (state === "recording") {
            if (recording.current?.state === "recording")
              recording.current.stop();
          } else void start();
        }}
      >
        {state === "recording"
          ? "Stop recording"
          : state === "transcribing"
            ? "Transcribing…"
            : state === "permission"
              ? "Waiting for microphone…"
              : "Speak your question"}
      </button>
      <p className="muted" role="status">
        {state === "recording"
          ? "Listening. Stop when you finish (60-second limit)."
          : message ||
            "Your recording is sent to ElevenLabs for transcription."}
      </p>
    </div>
  );
}
