import type { ReactNode } from "react";
import { bubbleLine } from "./animation";
import type { AnimationState } from "./animation";
import { members, sourceUrl } from "./contract";
import type { Chair, Member, Source, Speaker, Verdict } from "./contract";

type Props = {
  active?: Member;
  animation?: AnimationState;
  statuses: Partial<Record<Member, string>>;
  verdicts: Partial<Record<Member, Verdict>>;
  sources: Partial<Record<Member, Source[]>>;
  chair?: Chair;
  onSelect: (member: Member) => void;
  readAloud?: (id: string, member: Speaker, text: string) => ReactNode;
};
const seats: Member[] = ["leopold", "burry", "buffett", "dalio", "cramer"];

function SignalIcon({ signal }: { signal?: Verdict["signal"] }) {
  return (
    <svg
      className="bubble-icon"
      viewBox="0 0 48 48"
      role="img"
      aria-label={signal || "Pending"}
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {signal === "BUY" || signal === "SELL" ? (
        <g transform={signal === "SELL" ? "rotate(180 24 24)" : undefined}>
          <path d="M16 22 25 9c2-3 7-1 6 3l-2 9h10c3 0 4 2 3 5l-4 13H16Z" />
          <path d="M6 22h10v18H6Z" />
        </g>
      ) : signal === "HOLD" ? (
        <>
          <circle cx="24" cy="24" r="18" />
          <path d="M19 16v16m10-16v16" />
        </>
      ) : (
        <>
          <path d="M12 6h24M12 42h24M15 6c0 10 0 11 9 18-9 7-9 8-9 18M33 6c0 10 0 11-9 18 9 7 9 8 9 18" />
          <path d="m18 35 6-5 6 5" />
        </>
      )}
    </svg>
  );
}

export default function Boardroom({
  active,
  animation = {},
  statuses,
  verdicts,
  sources,
  chair,
  onSelect,
  readAloud,
}: Props) {
  return (
    <div className="boardroom">
      <div className="council-seats">
        {seats.map((member) => {
          const verdict = verdicts[member];
          const ruling = member === "buffett" ? chair : undefined;
          const signal = ruling?.overall_signal || verdict?.signal;
          const sourceCount = (sources[member] || []).filter((source) =>
            sourceUrl(source.url),
          ).length;
          const line = bubbleLine(
            ruling?.speech_bubble ||
              ruling?.summary ||
              verdict?.speech_bubble ||
              verdict?.headline ||
              statuses[member] ||
              (sourceCount
                ? `Reviewing ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}…`
                : "No verdict yet."),
          );
          const pose = animation[member] || "idle";
          return (
            <article
              key={member}
              className={`council-seat ${member} ${pose} ${active === member ? "active" : ""}`}
              data-pose={pose}
              aria-label={members[member].name}
            >
              <div className="bubble-wrap">
                <button
                  key={ruling?.summary || verdict?.headline || "pending"}
                  className="speech-bubble"
                  onClick={() => onSelect(member)}
                  aria-label={`View ${members[member].name}: ${signal || "Pending"}. ${line}`}
                >
                  <SignalIcon signal={signal} />
                  <span className="bubble-copy">
                    <small>
                      {ruling ? "Council ruling" : signal || "Pending"}
                    </small>
                    <span className="bubble-line">{line}</span>
                    <span className="bubble-more">View more ↗</span>
                  </span>
                </button>
                {(ruling || verdict) &&
                  readAloud?.(
                    `scene-${member}`,
                    ruling ? "chair" : member,
                    ruling?.speech_bubble ||
                      ruling?.summary ||
                      verdict?.speech_bubble ||
                      verdict?.headline ||
                      "",
                  )}
              </div>
              <button
                className="member-portrait"
                onClick={() => onSelect(member)}
                aria-label={`View ${members[member].name}`}
              >
                <img src={`/portraits/${member}.png`} alt="" />
              </button>
              <button className="seat-label" onClick={() => onSelect(member)}>
                <strong>{members[member].name}</strong>
                <small>{members[member].role}</small>
              </button>
            </article>
          );
        })}
      </div>
      <div className="table-surface" aria-hidden="true">
        <div className="curved-table" />
      </div>
    </div>
  );
}
