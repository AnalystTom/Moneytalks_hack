import type { CouncilEvent, Member } from "./contract";

export type Pose =
  "idle" | "researching" | "speaking" | "revealing" | "drumming";
export type AnimationState = Partial<Record<Member, Pose>>;
type AnimationEvent =
  | CouncilEvent
  | { event: "presentation.done"; data: { member: Member } }
  | { event: "chair.revealed" }
  | { event: "audio.playing" | "audio.stopped"; data: { member: Member } };

export function animateEvent(
  state: AnimationState,
  event: AnimationEvent,
): AnimationState {
  switch (event.event) {
    case "run.started":
    case "run.done":
    case "run.error":
      return {};
    case "member.status": {
      const { member, status } = event.data;
      const pose =
        status === "researching" || status === "thinking"
          ? "researching"
          : status === "speaking"
            ? "speaking"
            : "idle";
      return { ...state, [member]: pose };
    }
    case "member.verdict":
      return { ...state, [event.data.member]: "revealing" };
    case "presentation.done":
      return state[event.data.member] === "revealing"
        ? { ...state, [event.data.member]: "idle" }
        : state;
    case "chair.summary":
      return { buffett: "drumming" };
    case "chair.revealed":
      return { buffett: "revealing" };
    case "member.audio":
    case "audio.stopped":
      return { ...state, [event.data.member]: "idle" };
    case "audio.playing":
      return { ...state, [event.data.member]: "speaking" };
    default:
      return state;
  }
}

// Shorten returned text only; never compose a new opinion for a member.
export function bubbleLine(text: string): string {
  const sentence =
    text
      .trim()
      .replace(/\s+/g, " ")
      .match(/^.*?[.!?](?=\s|$)|^.+$/)?.[0] || "";
  const words = sentence.split(" ");
  const preview = words.slice(0, 15).join(" ");
  const bounded =
    preview.length > 100
      ? preview.slice(0, 100).replace(/\s+\S*$/, "")
      : preview;
  return bounded.length < sentence.length
    ? `${bounded.replace(/[,:;.!?]+$/, "")}…`
    : sentence;
}
