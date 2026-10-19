import { animateEvent, bubbleLine } from "./animation";
import type { AnimationState } from "./animation";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  apiError,
  contextCard,
  ingestPortfolio,
  members,
  portfolioFile,
  sourceUrl,
  streamCouncil,
} from "./contract";
import type {
  Chair,
  ContextCard,
  CouncilEvent,
  Member,
  Source,
  Speaker,
  Verdict,
} from "./contract";
import VoiceInput from "./VoiceInput";
import { SpeechPlayback } from "./speech";
import type { PlaybackState } from "./speech";
import ReadAloud from "./ReadAloud";
const Boardroom = lazy(() => import("./Boardroom"));
const pause = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

function Sources({ sources }: { sources: Source[] }) {
  const valid = sources.filter((source) => sourceUrl(source.url));
  return valid.length ? (
    <ul className="sources">
      {valid.map((source, i) => (
        <li key={`${source.url}-${i}`}>
          <a href={sourceUrl(source.url)} target="_blank" rel="noreferrer">
            {source.title} ↗
          </a>
          {source.quote && <blockquote>{source.quote}</blockquote>}
        </li>
      ))}
    </ul>
  ) : (
    <p className="muted">Source links unavailable.</p>
  );
}
function VerdictCard({
  verdict,
  open = false,
}: {
  verdict: Verdict;
  open?: boolean;
}) {
  return (
    <article className="verdict-card">
      <div className="card-top">
        <span>{members[verdict.member].name}</span>
        {verdict.signal && (
          <span className={`signal ${verdict.signal.toLowerCase()}`}>
            {verdict.signal}
          </span>
        )}
      </div>
      <h3>{bubbleLine(verdict.speech_bubble || verdict.headline)}</h3>
      <p className="muted">
        {verdict.positions.length
          ? verdict.positions
              .map(
                (call) => `${call.ticker} ${call.signal} · ${call.conviction}`,
              )
              .join(" · ")
          : "No calls returned."}
      </p>
      <details open={open || undefined}>
        <summary>
          View more <span>↗</span>
        </summary>
        <p>{verdict.analysis || verdict.headline}</p>
        {verdict.positions.map((call) => (
          <p key={call.ticker}>
            <b className={`signal ${call.signal.toLowerCase()}`}>
              {call.ticker} {call.signal}
            </b>{" "}
            <small>{call.conviction} conviction</small> {call.rationale}
          </p>
        ))}
        <ul className="reasons">
          {verdict.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
        <h4>Sources</h4>
        <Sources sources={verdict.sources} />
      </details>
    </article>
  );
}

function ChairRuling({
  chair,
  open = false,
}: {
  chair: Chair;
  open?: boolean;
}) {
  return (
    <article className="ruling">
      <div className="card-top">
        <h2>Council ruling</h2>
        {chair.overall_signal && (
          <span className={`signal ${chair.overall_signal.toLowerCase()}`}>
            {chair.overall_signal}
          </span>
        )}
      </div>
      <p>{bubbleLine(chair.speech_bubble || chair.summary)}</p>
      <details open={open || undefined}>
        <summary>View more ↗</summary>
        <p>{chair.summary}</p>
        {chair.positions.length > 0 && (
          <p className="ruling-chips">
            {chair.positions.map((name) => (
              <b
                key={name.ticker}
                className={`signal ${name.signal.toLowerCase()}`}
              >
                {name.ticker} {name.signal} · {name.conviction}
              </b>
            ))}
          </p>
        )}
        <h4>Consensus</h4>
        <p>{chair.consensus}</p>
        <h4>Dissent</h4>
        {chair.dissent.length ? (
          <ul>
            {chair.dissent.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        ) : (
          <p>No dissent returned.</p>
        )}
        {chair.actions.length > 0 && (
          <>
            <h4>Actions</h4>
            <ul>
              {chair.actions.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </details>
    </article>
  );
}

function MemberDialog({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="member-modal"
      aria-label="Council member details"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <button
        className="close"
        autoFocus
        onClick={onClose}
        aria-label="Close member details"
      >
        ×
      </button>
      {children}
    </dialog>
  );
}

export default function App() {
  const [context, setContext] = useState<{ briefId: string; label: string }>();
  const [contextSummary, setContextSummary] = useState<ContextCard>();
  const [loadingContext, setLoadingContext] = useState(true);
  const [question, setQuestion] = useState("");
  const [roast, setRoast] = useState(false);
  const [animation, setAnimation] = useState<AnimationState>({});
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("Your seat is waiting.");
  const [error, setError] = useState("");
  const [runId, setRunId] = useState("");
  const [runFinished, setRunFinished] = useState(false);
  const [active, setActive] = useState<Member>();
  const [selected, setSelected] = useState<Member>();
  const [replyTo, setReplyTo] = useState<Member>();
  const [statuses, setStatuses] = useState<Partial<Record<Member, string>>>({});
  const [sources, setSources] = useState<Partial<Record<Member, Source[]>>>({});
  const [verdicts, setVerdicts] = useState<Partial<Record<Member, Verdict>>>(
    {},
  );
  const [chair, setChair] = useState<Chair>();
  const [drumming, setDrumming] = useState(false);
  const [messages, setMessages] = useState<
    (
      | { kind: "user"; text: string }
      | { kind: "verdict"; verdict: Verdict }
      | { kind: "chair"; chair: Chair }
      | { kind: "routed"; members: Speaker[]; reason: string }
      | { kind: "reply"; member: Speaker; text: string }
    )[]
  >([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [audioMessage, setAudioMessage] = useState("");
  const [playback, setPlayback] = useState<PlaybackState>();
  const speech = useRef<SpeechPlayback | null>(null);
  const controller = useRef<AbortController | null>(null);
  const contextController = useRef<AbortController | null>(null);
  const persona = useRef("");
  const acceptedPortfolio = useRef<
    { file: File; label: string; snapshot?: unknown } | undefined
  >(undefined);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    contextController.current = abort;
    void loadContext(abort.signal);
    return () => abort.abort();
  }, []);
  useEffect(
    () => () => {
      controller.current?.abort();
      contextController.current?.abort();
      stopSpeech();
    },
    [],
  );
  useEffect(() => {
    const scroll = transcriptEnd.current?.parentElement;
    if (scroll) scroll.scrollTop = scroll.scrollHeight;
  }, [messages, busy]);

  async function loadContext(
    signal: AbortSignal,
    replacement?: File,
  ): Promise<string | undefined> {
    setLoadingContext(true);
    setError("");
    try {
      let file = replacement ?? acceptedPortfolio.current?.file;
      let snapshot = acceptedPortfolio.current?.snapshot;
      if (replacement?.name.toLowerCase().endsWith(".json"))
        snapshot = JSON.parse(await replacement.text());
      else if (replacement) snapshot = undefined;
      if (!file || !persona.current) {
        const [portfolioResponse, profileResponse] = await Promise.all([
          fetch("/demo-portfolio.json", { signal }),
          fetch("/demo-persona.md", { signal }),
        ]);
        if (!portfolioResponse.ok || !profileResponse.ok)
          throw new Error("Portfolio context is unavailable. Please retry.");
        persona.current = await profileResponse.text();
        snapshot = await portfolioResponse.json();
        file ??= portfolioFile(snapshot);
      }
      file = await ingestPortfolio(file);
      const form = new FormData();
      form.append("portfolio", file);
      form.append(
        "persona",
        new File([persona.current], "persona.md", { type: "text/markdown" }),
      );
      form.append("plaid", "false");
      const response = await fetch("/api/ingest", {
        method: "POST",
        body: form,
        signal,
      });
      if (!response.ok) throw await apiError(response);
      const brief = await response.json();
      if (
        typeof brief.brief_id !== "string" ||
        typeof brief.summary !== "string"
      )
        throw new Error("The server returned an invalid client brief.");
      signal.throwIfAborted();
      const name = persona.current
        .match(/\|\s*\*\*Name\*\*\s*\|\s*([^|]+)/)?.[1]
        ?.trim()
        .split(/\s+/)[0];
      const label = replacement
        ? `${replacement.name} loaded`
        : (acceptedPortfolio.current?.label ??
          (name ? `${name}’s portfolio loaded` : "Portfolio loaded"));
      acceptedPortfolio.current = { file, label, snapshot };
      setContextSummary(contextCard(snapshot, persona.current));
      setContext({ briefId: brief.brief_id, label });
      setRunId("");
      setRunFinished(false);
      setReplyTo(undefined);
      if (replacement) {
        setMessages([]);
        setVerdicts({});
        setChair(undefined);
        setStatuses({});
        setSources({});
        setSelected(undefined);
        setStage("Your seat is waiting.");
        stopSpeech();
      }
      return brief.brief_id;
    } catch (cause) {
      if (!signal.aborted)
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not load portfolio context.",
        );
    } finally {
      if (!signal.aborted) setLoadingContext(false);
    }
  }
  function stopSpeech() {
    speech.current?.stop();
  }
  function readAloud(id: string, member: Speaker, text: string) {
    return (
      <ReadAloud
        id={id}
        member={member}
        playback={playback}
        onClick={() => {
          speech.current ??= new SpeechPlayback(setPlayback, setAudioMessage);
          void speech.current.toggle(id, member, text);
        }}
      />
    );
  }
  async function receive(event: CouncilEvent, signal: AbortSignal) {
    if (signal.aborted) return;
    setAnimation((previous) => animateEvent(previous, event));
    switch (event.event) {
      case "run.started":
        setRunId(event.data.run_id);
        break;
      case "member.status":
        setStatuses((previous) => ({
          ...previous,
          [event.data.member]: event.data.status,
        }));
        if (event.data.status === "researching")
          setStage("The council is doing its homework.");
        if (event.data.status === "speaking" && event.data.member !== "chair")
          setActive(event.data.member);
        if (event.data.status === "done")
          setActive((previous) =>
            previous === event.data.member ? undefined : previous,
          );
        break;
      case "member.source":
        setSources((previous) => ({
          ...previous,
          [event.data.member]: [
            ...(previous[event.data.member] || []),
            event.data,
          ],
        }));
        break;
      case "member.verdict":
        setActive(event.data.member);
        setStage(`${members[event.data.member].name} has a verdict.`);
        setVerdicts((previous) => ({
          ...previous,
          [event.data.member]: event.data,
        }));
        if (event.data.member === "buffett") setChair(undefined);
        setMessages((previous) => [
          ...previous,
          { kind: "verdict", verdict: event.data },
        ]);
        await pause(1200);
        setAnimation((previous) =>
          animateEvent(previous, {
            event: "presentation.done",
            data: { member: event.data.member },
          }),
        );
        break;
      case "chair.summary":
        setDrumming(true);
        setActive("buffett");
        setStage("The council has spoken. Warren has the floor.");
        await pause(1700);
        setDrumming(false);
        if (!signal.aborted) {
          setChair(event.data);
          setMessages((previous) => [
            ...previous,
            { kind: "chair", chair: event.data },
          ]);
          setAnimation((previous) =>
            animateEvent(previous, { event: "chair.revealed" }),
          );
          setSuggestions(event.data.suggestions);
          setStage("The council ruling is in.");
        }
        break;
      case "chat.routed":
        setMessages((previous) => [
          ...previous,
          { kind: "routed", ...event.data },
        ]);
        break;
      case "member.reply":
        setMessages((previous) => [
          ...previous,
          { kind: "reply", member: event.data.member, text: event.data.text },
        ]);
        break;
      case "chat.closed":
        if (event.data.text)
          setMessages((previous) => [
            ...previous,
            { kind: "reply", member: "chair", text: event.data.text },
          ]);
        setSuggestions(event.data.suggestions);
        break;
      case "member.audio":
        // Speech is requested only by an explicit click on an answer.
        break;
      case "run.done":
        setRunFinished(true);
        setStage("The floor is yours.");
        setActive(undefined);
        break;
      case "run.error":
        setStage("The council could not finish.");
        break;
    }
  }
  async function execute(text = question) {
    if (busy || voiceBusy || loadingContext || !context || !text.trim()) return;
    const message = text.trim();
    const follow = !!runId && runFinished;
    const abort = new AbortController();
    controller.current = abort;
    const timedOut = () => abort.abort("The council timed out. Please retry.");
    let timeout = setTimeout(timedOut, 180000);
    const receiveEvent = async (event: CouncilEvent) => {
      clearTimeout(timeout);
      try {
        await receive(event, abort.signal);
      } finally {
        if (!abort.signal.aborted) timeout = setTimeout(timedOut, 180000);
      }
    };
    stopSpeech(); // a new question never waits for the previous answers to finish being read aloud
    setBusy(true);
    setError("");
    setAudioMessage("");
    if (!follow) setRunFinished(false);
    setMessages((previous) => [...previous, { kind: "user", text: message }]);
    setQuestion("");
    try {
      abort.signal.throwIfAborted();
      const lost = (cause: unknown, detail: string) =>
        !abort.signal.aborted &&
        cause instanceof Error &&
        cause.message === detail;
      const freshRun = async () => {
        setRunId("");
        setSuggestions([]);
        setChair(undefined);
        setVerdicts({});
        setSources({});
        setStatuses({});
        setSelected(undefined);
        setStage("The council is considering your question.");
        const run = (briefId: string) =>
          streamCouncil(
            "/api/council/run",
            { brief_id: briefId, question: message, roast },
            abort.signal,
            receiveEvent,
          );
        try {
          await run(context.briefId);
        } catch (cause) {
          // The server forgot the brief: re-ingest the context we still
          // hold and retry once before surfacing an error.
          if (lost(cause, "unknown brief_id")) {
            const briefId = await loadContext(abort.signal);
            if (!briefId) throw cause;
            setStage("The council is considering your question.");
            await run(briefId);
          } else throw cause;
        }
      };
      if (follow) {
        setSuggestions([]);
        try {
          await streamCouncil(
            "/api/council/chat",
            {
              run_id: runId,
              text: message,
              to: replyTo ? [replyTo] : [],
              roast,
            },
            abort.signal,
            receiveEvent,
          );
        } catch (cause) {
          // The server forgot the session: answer the follow-up as a fresh one.
          if (!lost(cause, "unknown run_id")) throw cause;
          await freshRun();
        }
      } else {
        await freshRun();
      }
    } catch (cause) {
      const expired =
        !abort.signal.aborted &&
        cause instanceof Error &&
        ["unknown brief_id", "unknown run_id"].includes(cause.message);
      if (expired) {
        setContext(undefined);
        setRunId("");
        setRunFinished(false);
        setReplyTo(undefined);
      }
      setQuestion(message);
      setError(
        abort.signal.aborted
          ? String(abort.signal.reason || "Council cancelled.")
          : expired
            ? "Portfolio context expired. Retry loading it or replace the portfolio."
            : cause instanceof Error
              ? cause.message
              : "The council could not connect.",
      );
      setStage("Session interrupted. You can retry.");
    } finally {
      clearTimeout(timeout);
      setBusy(false);
      setDrumming(false);
      setActive(undefined);
      setAnimation({});
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void execute();
  }
  const hasResults = messages.some((message) => message.kind !== "user");
  const selectedVerdict = selected ? verdicts[selected] : undefined;
  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Council home">
          C<span className="brand-dot">O</span>UNCIL
        </a>
        <div className="brand-note">
          DIFFERENT PERSPECTIVES.
          <br />A CLEARER YOU.
        </div>
        <div className="top-actions">
          <label className="toggle">
            <input
              type="checkbox"
              checked={roast}
              disabled={busy}
              onChange={(event) => setRoast(event.target.checked)}
            />
            <span className="switch" />
            Roast mode
          </label>
        </div>
      </header>
      <main className="layout">
        <section
          className={`stage ${drumming ? "drumming" : ""}`}
          aria-label="Council boardroom"
        >
          <div className="scene-heading">
            <p className="eyebrow">
              YOUR PORTFOLIO. THE COUNCIL’S PERSPECTIVE.
            </p>
            <h1>
              {drumming
                ? "One final word."
                : chair
                  ? "The verdict is in."
                  : "Take your seat."}
            </h1>
            <p>{drumming ? "A drum roll for the chair…" : stage}</p>
          </div>
          <div className="scene">
            <Suspense
              fallback={
                <div className="scene-fallback">Preparing the boardroom…</div>
              }
            >
              <Boardroom
                active={active}
                animation={animation}
                statuses={statuses}
                verdicts={verdicts}
                sources={sources}
                chair={chair}
                onSelect={setSelected}
                readAloud={readAloud}
              />
            </Suspense>
          </div>
          {drumming && (
            <div className="drum-overlay" role="status">
              <span>● ● ●</span>
              <h2>Warren’s ruling</h2>
              <p>The chair has the floor.</p>
            </div>
          )}
          <div className="table-caption">
            <span className="live-dot" />
            <span>
              {busy
                ? "COUNCIL IN SESSION"
                : hasResults
                  ? "SESSION TRANSCRIPT READY"
                  : "THE BOARDROOM IS OPEN"}
            </span>
            <span className="caption-line" />
            <span>EST. MMXXVI</span>
          </div>
        </section>
        <aside className="panel chat-panel" aria-label="Council chat">
          <div className="chat-context">
            <span className="context-chip" role="status">
              {loadingContext
                ? "Loading portfolio…"
                : context?.label || "Portfolio unavailable"}
            </span>
            {!context && !loadingContext && (
              <button
                className="context-retry"
                onClick={() => {
                  const abort = new AbortController();
                  contextController.current = abort;
                  void loadContext(abort.signal);
                }}
              >
                Retry
              </button>
            )}
            <label className="attach-context" title="Replace portfolio">
              <span aria-hidden="true">⌁</span>
              <input
                type="file"
                accept=".csv,.json"
                aria-label="Replace portfolio"
                disabled={busy || voiceBusy || loadingContext}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    contextController.current?.abort();
                    const abort = new AbortController();
                    contextController.current = abort;
                    void loadContext(abort.signal, file);
                  }
                  event.target.value = "";
                }}
              />
            </label>
          </div>
          <div
            className="chat-messages"
            role="log"
            aria-label="Council messages"
            aria-live="polite"
          >
            {contextSummary && (
              <article className="chat-message context-card">
                <small>{contextSummary.title}</small>
                <ul>
                  {contextSummary.lines.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </article>
            )}
            {!messages.length && (
              <p className="chat-empty">
                What would you like the council to consider?
              </p>
            )}
            {messages.map((message, index) =>
              message.kind === "user" ? (
                <article className="chat-message user-message" key={index}>
                  <small>You</small>
                  <p>{message.text}</p>
                </article>
              ) : message.kind === "routed" ? (
                <p className="chat-status" key={index}>
                  Asking{" "}
                  {message.members
                    .map((member) =>
                      member === "chair"
                        ? "the chair"
                        : members[member].name.split(" ").pop(),
                    )
                    .join(" and ")}{" "}
                  · {message.reason}
                </p>
              ) : message.kind === "reply" ? (
                <article className="chat-message member-message" key={index}>
                  <img
                    className="chat-avatar"
                    src={`/portraits/${message.member === "chair" ? "buffett" : message.member}.png`}
                    alt=""
                  />
                  <div>
                    <small>
                      {message.member === "chair"
                        ? "The chair"
                        : members[message.member].name}
                    </small>
                    <p>{message.text}</p>
                    {readAloud(`chat-${index}`, message.member, message.text)}
                  </div>
                </article>
              ) : (
                <article className="chat-message member-message" key={index}>
                  <img
                    className="chat-avatar"
                    src={`/portraits/${message.kind === "chair" ? "buffett" : message.verdict.member}.png`}
                    alt=""
                  />
                  <div>
                    {message.kind === "chair" ? (
                      <ChairRuling chair={message.chair} />
                    ) : (
                      <VerdictCard verdict={message.verdict} />
                    )}
                    {readAloud(
                      `chat-${index}`,
                      message.kind === "chair"
                        ? "chair"
                        : message.verdict.member,
                      message.kind === "chair"
                        ? message.chair.summary
                        : message.verdict.analysis || message.verdict.headline,
                    )}
                    <button
                      className="reply-button"
                      disabled={busy || !runFinished}
                      onClick={() =>
                        setReplyTo(
                          message.kind === "chair"
                            ? "buffett"
                            : message.verdict.member,
                        )
                      }
                    >
                      Reply
                    </button>
                  </div>
                </article>
              ),
            )}
            {busy && (
              <p className="chat-status" role="status">
                {stage}
              </p>
            )}
            <div ref={transcriptEnd} />
          </div>
          <div className="chat-composer">
            {suggestions.length > 0 && !busy && (
              <div className="chips">
                {suggestions.map((chip) => (
                  <button
                    type="button"
                    key={chip}
                    onClick={() => void execute(chip)}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {audioMessage && (
              <p className="audio-note" role="status">
                {audioMessage}
              </p>
            )}
            {replyTo && (
              <button
                className="reply-target"
                onClick={() => setReplyTo(undefined)}
              >
                To {members[replyTo].name} ×
              </button>
            )}
            <VoiceInput
              disabled={busy || loadingContext || !context}
              onBusyChange={(value) => {
                if (value) stopSpeech();
                setVoiceBusy(value);
              }}
              onTranscript={(text) =>
                setQuestion((previous) =>
                  [previous.trim(), text].filter(Boolean).join(" "),
                )
              }
            />
            <form className="chat-form" onSubmit={submit}>
              <textarea
                id="message"
                aria-label="Message the council"
                placeholder="Ask the council…"
                rows={2}
                value={question}
                disabled={busy || voiceBusy}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void execute();
                  }
                }}
              />
              {busy ? (
                <button
                  type="button"
                  className="cancel-send"
                  aria-label="Cancel session"
                  onClick={() => {
                    stopSpeech();
                    controller.current?.abort(
                      "Council cancelled. Your message is preserved.",
                    );
                  }}
                >
                  ■
                </button>
              ) : (
                <button
                  className="send-message"
                  aria-label="Send message"
                  disabled={
                    voiceBusy || loadingContext || !context || !question.trim()
                  }
                >
                  ↑
                </button>
              )}
            </form>
            <p className="chat-disclaimer">
              Parody personas · not financial advice.
            </p>
          </div>
        </aside>
      </main>
      {selected && (
        <MemberDialog onClose={() => setSelected(undefined)}>
          <p className="eyebrow">{members[selected].role}</p>
          <h2>{members[selected].name}</h2>
          {selected === "buffett" && chair && (
            <ChairRuling chair={chair} open />
          )}
          {selectedVerdict ? (
            <VerdictCard verdict={selectedVerdict} open />
          ) : selected === "buffett" && chair ? null : (
            <>
              <p className="muted">
                {statuses[selected] ||
                  "No verdict yet. Send a message to begin."}
              </p>
              <Sources sources={sources[selected] || []} />
            </>
          )}
        </MemberDialog>
      )}
    </div>
  );
}
