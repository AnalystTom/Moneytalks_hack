import { members } from "./contract";
import type { Speaker } from "./contract";
import type { PlaybackState } from "./speech";

export default function ReadAloud({
  id,
  member,
  playback,
  onClick,
}: {
  id: string;
  member: Speaker;
  playback?: PlaybackState;
  onClick: () => void;
}) {
  const status = playback?.id === id ? playback.status : undefined;
  const name =
    member === "chair" ? "the chair" : members[member].name.split(" ").pop();
  const label =
    status === "loading"
      ? `Cancel loading ${name}'s answer`
      : status === "playing"
        ? `Stop reading ${name}'s answer`
        : `Read ${name}'s answer aloud`;
  return (
    <button
      type="button"
      className="read-aloud"
      aria-label={label}
      title={label}
      aria-pressed={!!status}
      onClick={onClick}
    >
      {status === "loading" ? (
        <span aria-hidden="true" className="speech-loading">
          ◌
        </span>
      ) : (
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {status === "playing" ? (
            <path d="M6 6h12v12H6z" />
          ) : (
            <>
              <path d="M11 4 6 8H3v8h3l5 4Z" />
              <path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" />
            </>
          )}
        </svg>
      )}
    </button>
  );
}
