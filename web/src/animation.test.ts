import { describe, expect, it } from "vitest";
import { animateEvent, bubbleLine } from "./animation";
import type { AnimationState } from "./animation";
import type { CouncilEvent, Verdict } from "./contract";

const verdict: Verdict = {
  member: "leopold",
  signal: "HOLD",
  confidence: 0.7,
  headline: "Returned answer",
  reasons: [],
  sources: [],
  tickers: [],
};
describe("stream-driven persona motion", () => {
  it("researches, reveals and speaks only while audio plays, then settles", () => {
    let state: AnimationState = {};
    const advance = (event: Parameters<typeof animateEvent>[1]) =>
      (state = animateEvent(state, event));
    advance({
      event: "member.status",
      data: { member: "leopold", status: "researching" },
    });
    expect(state.leopold).toBe("researching");
    advance({
      event: "member.status",
      data: { member: "burry", status: "thinking" },
    });
    expect(state.burry).toBe("researching");
    advance({ event: "member.verdict", data: verdict });
    expect(state).toMatchObject({ leopold: "revealing", burry: "researching" });
    advance({ event: "presentation.done", data: { member: "leopold" } });
    expect(state.leopold).toBe("idle");
    advance({
      event: "member.status",
      data: { member: "leopold", status: "speaking" },
    });
    expect(state.leopold).toBe("speaking");
    advance({
      event: "member.audio",
      data: { member: "leopold", audio_url: "/api/voice/speak" },
    });
    expect(state.leopold).toBe("idle");
    advance({ event: "audio.playing", data: { member: "leopold" } });
    expect(state.leopold).toBe("speaking");
    advance({ event: "audio.stopped", data: { member: "leopold" } });
    expect(state.leopold).toBe("idle");
    advance({
      event: "chair.summary",
      data: {
        summary: "Returned ruling",
        overall_signal: "HOLD",
        consensus: "Returned consensus",
        dissent: [],
      },
    });
    expect(state).toEqual({ buffett: "drumming" });
    advance({ event: "chair.revealed" });
    expect(state).toEqual({ buffett: "revealing" });
    advance({ event: "run.done", data: { run_id: "run" } });
    expect(state).toEqual({});
  });
  it.each(["run.started", "run.error"])("clears motion on %s", (event) => {
    expect(
      animateEvent({ burry: "speaking" }, { event, data: {} } as CouncilEvent),
    ).toEqual({});
  });
});
describe("returned bubble previews", () => {
  it("uses one sentence with at most fifteen words without inventing copy", () => {
    expect(
      bubbleLine("Keep the allocation steady. More context stays in details."),
    ).toBe("Keep the allocation steady.");
    expect(
      bubbleLine(
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen.",
      ),
    ).toBe(
      "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen…",
    );
    expect(bubbleLine("x".repeat(200))).toBe("x".repeat(100) + "…");
    expect(bubbleLine(" ")).toBe("");
  });
});
