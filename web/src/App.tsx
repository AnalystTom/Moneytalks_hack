import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  apiError,
  ingestPortfolio,
  members,
  portfolioFile,
  sourceUrl,
  streamCouncil,
} from "./contract";
import type { Chair, CouncilEvent, Member, Source, Verdict } from "./contract";
const Boardroom = lazy(() => import("./Boardroom"));
const memberIds = Object.keys(members) as Member[];
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
        <span className={`signal ${verdict.signal.toLowerCase()}`}>
          {verdict.signal}
        </span>
      </div>
      <h3>{verdict.headline}</h3>
      <p className="muted">
        {Math.round(verdict.confidence * 100)}% confidence
        {verdict.tickers.length ? ` · ${verdict.tickers.join(", ")}` : ""}
      </p>
      <details open={open || undefined}>
        <summary>
          View more <span>↗</span>
        </summary>
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
  const [portfolio, setPortfolio] = useState<File>();
  const [persona, setPersona] = useState("");
  const [personaName, setPersonaName] = useState("");
  const [plaid, setPlaid] = useState(false);
  const [demo, setDemo] = useState(false);
  const [question, setQuestion] = useState("");
  const [roast, setRoast] = useState(false);
  const [sound, setSound] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [stage, setStage] = useState("Your seat is waiting.");
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");
  const [runId, setRunId] = useState("");
  const [active, setActive] = useState<Member>();
  const [selected, setSelected] = useState<Member>();
  const [presented, setPresented] = useState<Verdict>();
  const [statuses, setStatuses] = useState<Partial<Record<Member, string>>>({});
  const [sources, setSources] = useState<Partial<Record<Member, Source[]>>>({});
  const [verdicts, setVerdicts] = useState<Partial<Record<Member, Verdict>>>(
    {},
  );
  const [chair, setChair] = useState<Chair>();
  const [drumming, setDrumming] = useState(false);
  const [followMember, setFollowMember] = useState<Member>("buffett");
  const [followQuestion, setFollowQuestion] = useState("");
  const [conversation, setConversation] = useState<
    { question: string; member: Member; verdict?: Verdict }[]
  >([]);
  const [audioMessage, setAudioMessage] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const controller = useRef<AbortController | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const soundEnabled = useRef(sound);
  const audioContext = useRef<AudioContext | null>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const [runFinished, setRunFinished] = useState(false);

  useEffect(() => {
    soundEnabled.current = sound;
    if (!sound) audio.current?.pause();
  }, [sound]);
  useEffect(
    () => () => {
      controller.current?.abort();
      audio.current?.pause();
      void audioContext.current?.close();
    },
    [],
  );
  useEffect(() => {
    if (summary)
      transcriptEnd.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
  }, [summary, chair, conversation, busy]);

  function unlockSound() {
    if (!sound) return;
    try {
      audioContext.current ??= new AudioContext();
      void audioContext.current.resume().catch(() => {});
    } catch {
      /* Speech remains available through the audio player. */
    }
  }
  async function drumRoll() {
    setDrumming(true);
    setActive("buffett");
    setStage("The council has spoken. Warren has the floor.");
    const context = audioContext.current;
    if (soundEnabled.current && context?.state === "running") {
      for (let i = 0; i < 23; i++) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = "triangle";
        oscillator.frequency.value = 95 + i * 3;
        const time = context.currentTime + i * 0.065;
        gain.gain.setValueAtTime(0.0001, time);
        gain.gain.exponentialRampToValueAtTime(0.12, time + 0.004);
        gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.055);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start(time);
        oscillator.stop(time + 0.06);
      }
    }
    await pause(1700);
    setDrumming(false);
  }
  async function playAudio(url: string, signal: AbortSignal) {
    // Only same-origin backend speech is allowed; never load an arbitrary tracking URL.
    const parsed = new URL(url, window.location.origin);
    if (
      parsed.origin !== window.location.origin ||
      !parsed.pathname.startsWith("/api/voice/")
    ) {
      setAudioMessage("The server returned an unsupported audio URL.");
      return;
    }
    setAudioUrl(parsed.href);
    const player = audio.current;
    if (!player || signal.aborted) return;
    player.src = parsed.href;
    if (!soundEnabled.current) return;
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        player.onended = null;
        player.onerror = null;
        player.onpause = null;
        player.onplaying = null;
        player.ontimeupdate = null;
        signal.removeEventListener("abort", finish);
        player.pause();
        resolve();
      };
      const stalled = () => {
        if (settled) return;
        setAudioMessage(
          "Voice playback timed out. All answers remain in the transcript.",
        );
        finish();
      };
      let position = player.currentTime;
      let timeout = setTimeout(stalled, 30000);
      signal.addEventListener("abort", finish, { once: true });
      player.onended = finish;
      player.onpause = finish;
      player.onplaying = () => {
        if (!settled) setAudioMessage("");
      };
      player.ontimeupdate = () => {
        if (settled || player.currentTime === position) return;
        position = player.currentTime;
        clearTimeout(timeout);
        timeout = setTimeout(stalled, 30000);
      };
      player.onerror = () => {
        if (settled) return;
        setAudioMessage(
          "Voice unavailable from the server. All answers remain in the transcript.",
        );
        finish();
      };
      void player.play().catch(() => {
        if (settled) return;
        setAudioMessage(
          "Voice could not play automatically. Use the audio controls to retry.",
        );
        finish();
      });
    });
  }
  async function receive(
    event: CouncilEvent,
    signal: AbortSignal,
    follow: boolean,
  ) {
    if (signal.aborted) return;
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
        if (event.data.status === "speaking") setActive(event.data.member);
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
        setPresented(event.data);
        setActive(event.data.member);
        setStage(`${members[event.data.member].name} has a verdict.`);
        if (follow)
          setConversation((previous) =>
            previous.map((item, i) =>
              i === previous.length - 1
                ? { ...item, verdict: event.data }
                : item,
            ),
          );
        else
          setVerdicts((previous) => ({
            ...previous,
            [event.data.member]: event.data,
          }));
        await pause(1200);
        break;
      case "chair.summary":
        await drumRoll();
        if (!signal.aborted) {
          setChair(event.data);
          setStage("Warren’s ruling is in.");
        }
        break;
      case "member.audio":
        await playAudio(event.data.audio_url, signal);
        break;
      case "run.done":
        setRunFinished(true);
        setStage(
          follow ? "Your follow-up is complete." : "The floor is yours.",
        );
        setActive(undefined);
        break;
      case "run.error":
        setStage("The council could not finish.");
        break;
    }
  }
  async function loadDemo() {
    setError("");
    setLoadingDemo(true);
    try {
      const [response, profile] = await Promise.all([
        fetch("/demo-portfolio.json"),
        fetch("/demo-persona.md"),
      ]);
      if (!response.ok || !profile.ok)
        throw new Error(
          "The demo portfolio is unavailable. Upload your own portfolio to continue.",
        );
      const [snapshot, profileText] = await Promise.all([
        response.json(),
        profile.text(),
      ]);
      setPortfolio(portfolioFile(snapshot));
      setDemo(true);
      setPlaid(true);
      setPersona(profileText);
      setPersonaName("PERSONA.md · demo profile");
      setQuestion("Keep dollar-cost averaging, sell, or move somewhere else?");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load demo.");
    } finally {
      setLoadingDemo(false);
    }
  }
  async function execute(follow: boolean) {
    const abort = new AbortController();
    controller.current = abort;
    const timedOut = () => abort.abort("The council timed out. Please retry.");
    let timeout = setTimeout(timedOut, 180000);
    const receiveEvent = async (event: CouncilEvent) => {
      clearTimeout(timeout);
      try {
        await receive(event, abort.signal, follow);
      } finally {
        if (!abort.signal.aborted) timeout = setTimeout(timedOut, 180000);
      }
    };
    setBusy(true);
    setError("");
    setAudioMessage("");
    if (!follow) setRunFinished(false);
    unlockSound();
    try {
      if (follow) {
        setConversation((previous) => [
          ...previous,
          { question: followQuestion, member: followMember },
        ]);
        setSources((previous) => ({ ...previous, [followMember]: [] }));
        await streamCouncil(
          "/api/council/ask",
          {
            run_id: runId,
            member: followMember,
            question: followQuestion,
            roast,
          },
          abort.signal,
          receiveEvent,
        );
        setFollowQuestion("");
      } else {
        if (!portfolio) throw new Error("Upload a portfolio first.");
        setSummary("");
        setRunId("");
        setChair(undefined);
        setVerdicts({});
        setPresented(undefined);
        setSources({});
        setStatuses({});
        setConversation([]);
        setSelected(undefined);
        setStage("Preparing your client brief…");
        const form = new FormData();
        form.append("portfolio", await ingestPortfolio(portfolio));
        form.append(
          "persona",
          new File([persona], "persona.md", { type: "text/markdown" }),
        );
        form.append("plaid", String(plaid));
        const response = await fetch("/api/ingest", {
          method: "POST",
          body: form,
          signal: abort.signal,
        });
        if (!response.ok) throw await apiError(response);
        const brief = await response.json();
        if (
          typeof brief.brief_id !== "string" ||
          typeof brief.summary !== "string"
        )
          throw new Error("The server returned an invalid client brief.");
        setSummary(brief.summary);
        await streamCouncil(
          "/api/council/run",
          { brief_id: brief.brief_id, question, roast },
          abort.signal,
          receiveEvent,
        );
      }
    } catch (cause) {
      setError(
        abort.signal.aborted
          ? String(abort.signal.reason || "Council cancelled.")
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
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void execute(false);
  }
  const hasResults = !!summary;
  const selectedVerdict = selected
    ? presented?.member === selected
      ? presented
      : verdicts[selected]
    : undefined;
  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Council home">
          <span className="brand-icon">♜</span> COUNCIL
          <span className="brand-dot">.</span>
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
          <button
            className="sound-button"
            onClick={() => setSound(!sound)}
            aria-pressed={sound}
          >
            {sound ? "♪ Sound on" : "♪ Sound off"}
          </button>
        </div>
      </header>
      <main className="layout">
        <section
          className={`stage ${drumming ? "drumming" : ""}`}
          aria-label="Council boardroom"
        >
          <div className="scene-heading">
            <p className="eyebrow">YOUR PORTFOLIO. FOUR PERSPECTIVES.</p>
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
                statuses={statuses}
                verdicts={
                  active && presented?.member === active
                    ? { ...verdicts, [active]: presented }
                    : verdicts
                }
                sources={sources}
                onSelect={setSelected}
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
          <div className="member-strip">
            {memberIds.map((member) => (
              <button
                key={member}
                onClick={() => setSelected(member)}
                className={active === member ? "active" : ""}
              >
                <span className={`portrait-mini ${member}`} />
                <span>
                  <strong>{members[member].name}</strong>
                  <small>{members[member].role}</small>
                </span>
                {verdicts[member] && (
                  <b
                    className={`signal ${verdicts[member]!.signal.toLowerCase()}`}
                  >
                    {verdicts[member]!.signal}
                  </b>
                )}
              </button>
            ))}
          </div>
        </section>
        <aside className="panel" aria-label="Council chat and brief">
          <div className="panel-scroll">
            <div className="panel-intro">
              <p className="eyebrow">
                {hasResults ? "THE CONVERSATION" : "BEFORE WE BEGIN"}
              </p>
              <h2>{hasResults ? "Council notes" : "Your brief"}</h2>
              <p className="muted">
                {hasResults
                  ? "Every perspective, in one place."
                  : "Bring your context. Get their perspective."}
              </p>
            </div>
            <div className="server-notice">
              Preview backend: market data, bank data and research may be sample
              responses. Source availability is shown below.
            </div>
            {!hasResults && (
              <form onSubmit={submit} className="brief-form">
                <div className="section-label">
                  <span>01 / THE CONTEXT</span>
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy || loadingDemo}
                    onClick={() => void loadDemo()}
                  >
                    {loadingDemo ? "Loading…" : "Load demo ↗"}
                  </button>
                </div>
                <label className="upload-card">
                  <span className="input-icon">↥</span>
                  <span>
                    <strong>{portfolio?.name || "Upload portfolio"}</strong>
                    <small>
                      {portfolio
                        ? "Ready to send · replace file"
                        : "CSV or JSON · ticker, shares, cost_basis"}
                    </small>
                  </span>
                  <span>↗</span>
                  <input
                    type="file"
                    accept=".csv,.json"
                    disabled={busy}
                    aria-label="Upload portfolio"
                    onChange={(event) => {
                      setPortfolio(event.target.files?.[0]);
                      setDemo(false);
                    }}
                  />
                </label>
                <button
                  type="button"
                  className={`upload-card ${plaid ? "connected" : ""}`}
                  disabled={busy}
                  onClick={() => setPlaid(!plaid)}
                  aria-pressed={plaid}
                >
                  <span className="input-icon">▥</span>
                  <span>
                    <strong>
                      {plaid ? "Sandbox requested" : "Include Plaid sandbox"}
                    </strong>
                    <small>
                      {plaid
                        ? "Server will fetch sample bank data"
                        : "Optional · no real account connection"}
                    </small>
                  </span>
                  <span className="badge">SANDBOX</span>
                </button>
                <label className="upload-card">
                  <span className="input-icon">▤</span>
                  <span>
                    <strong>{personaName || "Upload persona.md"}</strong>
                    <small>Your goals, horizon & risk tolerance</small>
                  </span>
                  <span>↗</span>
                  <input
                    type="file"
                    accept=".md,.txt,text/plain,text/markdown"
                    disabled={busy}
                    aria-label="Upload persona.md"
                    onChange={async (event) => {
                      const file = event.target.files?.[0];
                      if (!file) return;
                      try {
                        setPersona(await file.text());
                        setPersonaName(file.name);
                      } catch {
                        setError(
                          "Could not read your profile. Type it below instead.",
                        );
                      }
                    }}
                  />
                </label>
                <label className="field-label" htmlFor="persona">
                  Your profile <span>or write it here</span>
                </label>
                <textarea
                  id="persona"
                  value={persona}
                  disabled={busy}
                  onChange={(event) => {
                    setPersona(event.target.value);
                    setPersonaName("Written profile");
                  }}
                  required
                  rows={2}
                  placeholder="Goals, time horizon, risk tolerance…"
                />
                {demo && (
                  <p className="demo-note">
                    Demo loaded: teammate’s synthetic broker snapshot, the
                    checked-in demo profile and the sandbox bank request.
                  </p>
                )}
                <div className="section-label question-label">
                  02 / THE QUESTION
                </div>
                <label className="field-label" htmlFor="question">
                  What’s on your mind?
                </label>
                <textarea
                  id="question"
                  value={question}
                  disabled={busy}
                  onChange={(event) => setQuestion(event.target.value)}
                  required
                  rows={3}
                  placeholder="What should the council consider?"
                />
                <button
                  className="primary"
                  disabled={
                    busy ||
                    loadingDemo ||
                    !portfolio ||
                    !persona.trim() ||
                    !question.trim()
                  }
                >
                  {busy ? "Convening…" : "Convene the council"} <span>→</span>
                </button>
                <p className="form-footnote">Four opinions. Your decision.</p>
              </form>
            )}
            {hasResults && (
              <div className="transcript" aria-live="polite">
                <article className="brief-summary">
                  <p className="eyebrow">CLIENT BRIEF · SERVER RECEIPT</p>
                  <p>{summary}</p>
                  <blockquote>{question}</blockquote>
                  {demo && <small>Demo snapshot · synthetic broker data</small>}
                </article>
                <div className="research">
                  <h3>
                    On the table{" "}
                    <span>{busy ? "IN PROGRESS" : "RESEARCH"}</span>
                  </h3>
                  {memberIds.map((member) => (
                    <details key={member}>
                      <summary>
                        <span>{members[member].name}</span>
                        <small>{statuses[member] || "Waiting"}</small>
                      </summary>
                      <Sources sources={sources[member] || []} />
                    </details>
                  ))}
                </div>
                {Object.values(verdicts).map((verdict) => (
                  <VerdictCard key={verdict.member} verdict={verdict} />
                ))}
                {chair && (
                  <article className="ruling">
                    <p className="eyebrow">THE CHAIR’S FINAL WORD</p>
                    <div className="card-top">
                      <h2>Warren’s ruling</h2>
                      <span
                        className={`signal ${chair.overall_signal.toLowerCase()}`}
                      >
                        {chair.overall_signal}
                      </span>
                    </div>
                    <p>{chair.summary}</p>
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
                  </article>
                )}
                {conversation.map((item, i) => (
                  <div key={i} className="follow-entry">
                    <p className="user-question">
                      To {members[item.member].name}
                      <br />
                      <strong>{item.question}</strong>
                    </p>
                    {item.verdict ? (
                      <VerdictCard verdict={item.verdict} />
                    ) : (
                      <p className="muted">
                        {busy
                          ? "Waiting for an answer…"
                          : "No answer returned."}
                      </p>
                    )}
                  </div>
                ))}
                <div ref={transcriptEnd} />
              </div>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {audioMessage && (
              <p className="audio-note" role="status">
                {audioMessage}
              </p>
            )}
            <audio
              ref={audio}
              controls={!!audioUrl}
              className={audioUrl ? "audio-player" : "hidden"}
              aria-label="Council voice playback"
            />
            {busy && (
              <button
                className="text-button cancel"
                onClick={() => {
                  audio.current?.pause();
                  controller.current?.abort(
                    "Council cancelled. Your inputs are preserved.",
                  );
                }}
              >
                Cancel session
              </button>
            )}
            {hasResults && !busy && (
              <form
                className="follow-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void execute(true);
                }}
              >
                <p className="eyebrow">THE FLOOR IS YOURS</p>
                <h3>Ask a follow-up</h3>
                <label className="field-label" htmlFor="member">
                  Council member
                </label>
                <select
                  id="member"
                  value={followMember}
                  onChange={(event) =>
                    setFollowMember(event.target.value as Member)
                  }
                >
                  {memberIds.map((member) => (
                    <option key={member} value={member}>
                      {members[member].name}
                    </option>
                  ))}
                </select>
                <label className="field-label" htmlFor="follow-question">
                  Your question
                </label>
                <textarea
                  id="follow-question"
                  value={followQuestion}
                  onChange={(event) => setFollowQuestion(event.target.value)}
                  required
                  rows={2}
                  placeholder="Go a little deeper…"
                />
                <button
                  className="primary"
                  disabled={!runId || !followQuestion.trim() || !runFinished}
                >
                  Ask {members[followMember].name.split(" ")[0]} <span>→</span>
                </button>
                {!runFinished && (
                  <p className="muted">
                    Complete a new council session before asking a follow-up.
                  </p>
                )}
                <button
                  type="button"
                  className="text-button start-over"
                  onClick={() => {
                    setSummary("");
                    setRunId("");
                    setRunFinished(false);
                    setChair(undefined);
                    setVerdicts({});
                    setPresented(undefined);
                    setSources({});
                    setStatuses({});
                    setConversation([]);
                    setSelected(undefined);
                    setError("");
                    setAudioUrl("");
                    audio.current?.pause();
                    setStage("Your seat is waiting.");
                  }}
                >
                  Edit brief & start a new session ↗
                </button>
              </form>
            )}
          </div>
        </aside>
      </main>
      <footer>
        <span>
          COUNCIL <span className="brand-dot">/</span> A MEETING OF MINDS
        </span>
        <p>Parody personas, not financial advice.</p>
        <span>YOUR MONEY. YOUR CALL.</span>
      </footer>
      {selected && (
        <MemberDialog onClose={() => setSelected(undefined)}>
          <p className="eyebrow">{members[selected].role}</p>
          <h2>{members[selected].name}</h2>
          {selectedVerdict ? (
            <VerdictCard verdict={selectedVerdict} open />
          ) : (
            <>
              <p className="muted">
                {statuses[selected] ||
                  "No verdict yet. Convene the council to begin."}
              </p>
              <Sources sources={sources[selected] || []} />
            </>
          )}
        </MemberDialog>
      )}
    </div>
  );
}
