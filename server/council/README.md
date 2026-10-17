# Council - agentic system design

Status: **server implemented** (`app/services/council.py`, `app/services/coordinator.py`, demo at `/demo`); web app pending. This extends `../../spec.md` from four members to a
neutral coordinator plus five specialists; the deltas against the spec are listed at the end.

## Scope

| | v0 (hackathon) | v1 |
|---|---|---|
| Council | Opening run: plan, parallel research, verdict cards, coordinator ruling | - |
| Chat | Text box with prompt-template chips; coordinator routes every turn | - |
| Voice | Per-member text-to-speech of verdicts and replies (existing `/api/voice/speak`) | Voice mode switch: live, hands-free conversation via ElevenLabs Agents |
| Demo user | Jordan Mitchell (`data/PERSONA.md` + `data/portfolio.json`) | - |

## What it does

The user brings two things:

- **Persona file** (`data/PERSONA.md`): who they are, net worth, every account, goals.
- **Portfolio file** (`data/portfolio.json`): the one account they chose to connect, a brokerage
  account with positions and summary stats. It is part of the total assets in the persona file, not
  separate from it; the other accounts are self-reported balances.

A **coordinator** merges them into one client brief, writes a tailored assignment for each of five
**specialists**, and runs them in parallel. Each specialist researches the web through its own lens,
then returns a short analysis, a verdict with a conviction level, and concrete advice. The coordinator
checks the answers against their sources, delivers a ruling, and then runs the conversation.

```
 PERSONA.md ─┐
             ├─> [1 Ingest] ─> client brief ─> [2 Plan] ─> 5 assignments
 portfolio ──┘                                               │
                     ┌──────────┬──────────┬─────────┬───────┴──┐
                     v          v          v         v          v
                  Buffett     Dalio      Burry    Leopold     Cramer      [3 Research + analyse, parallel]
                     └──────────┴──────────┴────┬────┴──────────┘
                                                v
                              [4 Verify citations] ─> [5 Ruling] ─> [6 Chat] <-> user
```

## The roster and tone tiers

| Member | Lens (from `data/specialist.csv`) | Tone tier | Role on the council |
|---|---|---|---|
| **Ray Dalio** | Global macro, risk parity | **Serious / specialist** | Regimes, rates, correlations, how risk is spread across the whole balance sheet |
| **Warren Buffett** | Value, moats, long holds | **Serious / specialist** | Business quality and price; plain-spoken, but every line is substance |
| **Michael Burry** | Contrarian, bubbles, leverage | **Serious / specialist** | The forensic bear: valuation extremes, crowded trades, what breaks |
| **Leopold Aschenbrenner** | Thematic AI | Intense, conviction-driven | Compute, power, who wins the AI build-out |
| **Jim Cramer** | Active trading, catalysts | **Funny** | Comic relief who still makes a real point (concentration, homework) |

- **Serious tier:** numbers first, specific figures from sources, the mechanism named, no jokes.
- **Funny tier:** every joke rides on a real, sourced point; never invents facts to land a punchline.
- **Roast mode** (existing toggle, or the "Roast me" chip for one turn) makes all five roast;
  the coordinator stays the straight man.

## Pipeline

### 1. Ingest -> client brief

Merge both files into one structured brief that every agent receives verbatim:

- Profile: name, age, location, horizon (inferred from age and goals if missing), goals, implied risk tolerance.
- Balance sheet: every account from PERSONA.md, with the connected brokerage account as one line of it.
- Connected brokerage detail: equity, cash, positions with weight, P/L, sector, beta, role (from portfolio.json).
- Pre-computed facts, so agents never do arithmetic: top-5 weights, sector mix, portfolio beta, yield,
  winners/losers, biggest drag, brokerage as % of net worth, total cash as % of net worth.
- Data quality note: brokerage figures are live/connected; other balances are self-reported.

### 2. Plan (coordinator)

The coordinator reads the brief and writes one **assignment** per specialist:

- `focus_tickers`: the 2-4 holdings most relevant to that lens (e.g. Leopold gets NVDA, AMD, PLTR, MSFT).
- `questions`: 2-3 specific questions to answer (e.g. Dalio: "The brokerage is ~94% equities at beta
  1.53 and holds 38% of net worth; how does the whole balance sheet behave in a stagflation regime?").
- `search_budget`: max queries (default 4) and max sources to cite (default 3).

This is what makes it agentic rather than five copies of one prompt: each agent gets a different job.

### 3. Each specialist, in parallel: analyse -> research names -> advise

Portfolio analysis and decisions on names are separate stages. There is **no buy/hold/sell call on the
whole portfolio**; calls are only ever on individual held names, and only after researching them.

1. **Analyse the portfolio** (no calls). A couple of lens searches from the member's playbook
   (`<member>.md`), then the analysis: headline, 2-4 sentences, 2-3 observations, and the **names** it
   wants to check (2-3 of its own picks, held names only).
2. **Research each name.** For every name to check: web searches for latest news and for earnings /
   analyst views / valuation (Anchor; PRISM Knowledge Base later). Sources are tagged with their ticker.
   The names are the two biggest holdings (`shared_tickers`, called by every member so the council
   can vote on them) plus the member's own picks, max 5.
3. **Advise.** The analysis, the per-name research and the brief go in together; out come one
   **call per researched name** (BUY / HOLD / SELL + conviction + rationale) and 1-3 portfolio-level
   advice items.

Specialists do not see each other's work during the opening run, so their first calls are
independent. Cross-talk starts in chat.

### 4. Verify (coordinator)

Before anything is shown: every number and quote in a specialist's output must appear in the brief or
in its own sources. Failures get one retry with the failing claims listed; a second failure drops that
claim. Calls are kept only for held names the member actually researched; `high` conviction on a name
needs a quoted source on that name, otherwise it drops to `mid`. This is also the PRISM Evaluator proof.

### 5. Ruling (coordinator)

A **ruling per name**, from the members' actual calls:

| Calls on a name | Ruling |
|---|---|
| 3+ members, all agree | that signal, `high` |
| 2 members agree | that signal, `mid` (`high` if both are high) |
| 1 member | their call, conviction capped at `mid` |
| clear majority, not unanimous | majority signal, `mid` at 3+ callers, else `low` |
| tie | `HOLD`, `low`, marked "split" |

Plus a consensus line (the strongest call), dissent per name, up to 4 **actions** (top rulings first,
then merged advice credited to every member), a 3-4 sentence spoken summary, and 2-3 follow-up chips
(a split name first: "Michael and Leopold split on NVDA. Settle it.").

## Verdict (per specialist)

```json
{
  "member": "burry",
  "headline": "The biggest winner has become the biggest risk",
  "analysis": "2-4 sentences, in character, about the whole portfolio and balance sheet. No calls.",
  "reasons": ["...", "..."],
  "names": ["PLTR", "SPY", "NVDA", "AAPL", "TSLA"],
  "positions": [
    {"ticker": "PLTR", "signal": "SELL", "conviction": "high", "rationale": "19.2% of holdings after +163.1%..."},
    {"ticker": "NVDA", "signal": "SELL", "conviction": "mid", "rationale": "..."}
  ],
  "advice": [{"action": "Cap any single name at 10% of holdings", "tickers": [], "why": "..."}],
  "sources": [{"title": "...", "url": "...", "quote": "...", "ticker": "PLTR"}]
}
```

- `conviction` on a call: `high` = the lens applies squarely and that name's sources clearly support
  it; `mid` = sound but mixed; `low` = thin evidence.
- Events: `member.analysis` (stage 1, as soon as it is ready), `member.source` (with `ticker` for
  per-name research), `member.verdict` (the full object above). Statuses: researching -> analysing ->
  checking names -> deciding.
- Cards show each call as a coloured badge with a 1-3 pip meter (e.g. `SELL ●●○`).

## Conversation (v0: text)

The opening run is just the start. After it, the user chats with the council in the text box. Every
turn goes through one loop:

```
 user turn (typed, or a tapped template chip)
        │
        v
 [Route] coordinator picks who answers ──> 1 member | 2-3 members | whole council | coordinator only
        │
        v
 [Answer] each chosen member: reuse the run's sources, or search again if the question needs new facts
        │
        v
 [Reply] streamed text in chat (+ that member's text-to-speech), one speaker at a time
        │
        v
 [Close] coordinator hands the floor back to the user, refreshes the chips
```

### Who answers (routing)

| User says | Who answers |
|---|---|
| Names a member: "Burry, why sell PLTR?", taps a seat, or types `@burry` | That member only |
| Asks to compare: "Buffett and Leopold disagree on NVDA, settle it" | Those two; the second may rebut the first |
| A general question: "What should I do with my $60k of savings?" | Coordinator picks the 1-2 most relevant members by lens |
| "Everyone" / "council", or a changed core fact | All five, short answers, then a one-line coordinator update |
| About the conversation: "Who was most bullish?", "Summarise" | Coordinator only |

### Cross-talk and pacing

Members may address each other, but the **user and the coordinator run the room**:

- A member speaks only when the coordinator routes the turn to them; nobody jumps in unprompted.
- Within a routed multi-member turn, a member may respond to another member by name, at most one
  rebuttal each per turn ("Leopold, that's a bubble." / "Michael, the capex is real.").
- Max 3 speakers per turn, except "everyone" turns (all five, one or two sentences each).
- The coordinator closes every multi-member turn with one line that hands back to the user
  ("Two views on NVDA. Want Burry's trim plan or Leopold's add plan?"). No member-to-member loops.
- **Length:** a single member reply is 2-4 sentences (about 40-90 words); a multi-member turn is
  about 200 words in total. Shorter than a verdict card, longer than a one-liner.

### What each turn knows (memory)

- The client brief, the original assignments, every verdict and its sources.
- The full chat history for this session, so "why?" and "what about AMD then?" resolve correctly.
- New facts the user gives mid-chat ("I'm retiring in 5 years") update the brief, and the coordinator
  flags which earlier verdicts this might change.

### Chat panel

```
┌──────────────────────────────── chat (right ~30%) ────────────────────────────────┐
│  ... messages: user turns, member replies (avatar + name + text + sources) ...    │
│                                                                                   │
│  Try:  [Burry, why sell PLTR?] [Buffett vs Leopold on NVDA] [My $60k savings?]    │
│        [Everyone: I retire in 5 years] [Who was most bullish?]  [Roast me]        │
│  ┌───────────────────────────────────────────────────────────┐  ┌──────────────┐  │
│  │ Ask the council...   (@ to pick a member)                  │  │ 🎙 Voice (v1)│  │
│  └───────────────────────────────────────────────────────────┘  └──────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

**Prompt templates** sit as one-tap chips directly above the input, one per routing pattern, so the
user (and the demo audience) learns what the council can do just by looking:

| Chip | Fills the input with | Routes to |
|---|---|---|
| Ask one member | "Burry, why sell PLTR?" | burry |
| Settle a debate | "Buffett and Leopold disagree on NVDA. Settle it." | buffett, leopold |
| Use my cash | "What should I do with my $60k of savings?" | coordinator picks |
| Change the facts | "Everyone: I'm retiring in 5 years. Does that change anything?" | all five |
| Recap | "Who was most bullish, and who disagreed?" | coordinator |
| Roast me | "Roast my portfolio." | all five, roast mode for that turn |

- Tapping a chip fills the input instead of sending it, so the user can edit tickers or amounts first.
- Chips are filled from the brief: the largest position replaces PLTR, the savings balance replaces
  $60k, the most-disputed ticker replaces NVDA. With no brief yet, the static wording above is shown.
- After each turn, chips refresh to 2-3 follow-ups from the coordinator's closing line.
- The templates live in one data file in `web/` so they can be edited without touching components.
- In v0 the voice switch is shown disabled with a "v1" label, so the layout does not change later.

## Voice mode (v1: ElevenLabs real-time)

Not in the hackathon build. Design kept here so v0 does not block it.

Flipping the switch starts a live, hands-free conversation: the user just talks, can interrupt, and the
council answers in each member's own voice. Built on **ElevenLabs Agents**:

```
 browser mic ──WebRTC/WebSocket──> ElevenLabs Agent ── speech-to-text, turn-taking, interruptions
                                        │
                                        │ each user turn as an OpenAI-style chat request ("custom LLM")
                                        v
                                 our server /v1/chat/completions
                                   route -> member(s) answer (same pipeline as text chat)
                                   reply wrapped in voice tags: <burry>...</burry><leopold>...</leopold>
                                        │
                                        v
 browser speaker <───── audio ──── ElevenLabs Agent ── speaks each tagged segment in that member's voice
```

- **One agent, six voices.** ElevenLabs multi-voice support switches voice on XML-style tags (up to 10
  voices per agent: 5 members + the coordinator fit), mapped to `ELEVENLABS_VOICE_<MEMBER>`.
- **Our server stays the brain.** The agent's custom LLM points at our server, so routing, prompts,
  research and citation checks are the same code for text and voice.
- **Session link.** The browser gets a short-lived session token from `POST /api/voice/session {run_id}`;
  the API key never reaches the browser, and voice turns share the run's memory with typed turns.
- **Scene sync.** Voice tags on transcript segments tell the 3D scene who to spotlight; the server
  still emits `chat.routed` / `member.status` so cards and sources appear as in text mode.
- **Latency.** Members reply from the run's sources by default; a new search is announced by the
  coordinator so silence is filled.
- **Fallback.** If the session fails, the switch drops back to text.

To confirm in the ElevenLabs docs first: the custom-LLM request shape and streaming, whether voice tags
pass through a custom LLM unchanged, and the session-token endpoint.

## Guardrails

- Parody personas, not financial advice: shown in the UI and appended to every ruling.
- No invented prices, quotes or statistics; portfolio numbers come only from the brief.
- No fabricated quotes attributed to the real people; "style cues" in member files are tone, not things
  they said.
- Opening run: specialists don't see each other (independent first verdicts). Chat: they see the history.

## Files

| File | Purpose |
|---|---|
| `README.md` | This design |
| `orchestrator.md` | Coordinator brief: plan, verify, rule, route and pace the chat |
| `buffett.md`, `dalio.md`, `burry.md`, `leopold.md`, `cramer.md` | One system prompt per specialist: lens, tone tier, voice, research playbook, what to flag |
| `../../data/PERSONA.md`, `../../data/portfolio.json` | Demo user Jordan Mitchell |

## Changes this implies to `spec.md`

v0:

1. **Coordinator is a separate, neutral agent**, no longer Warren. Warren is one of five equal specialists.
2. `member` enum gains `dalio`; new voice env `ELEVENLABS_VOICE_DALIO`; five seats plus the
   coordinator at the head of the table in the 3D scene.
3. `member.verdict` drops the whole-portfolio `signal`/`confidence`; it carries the analysis, `names`,
   per-name `positions[]` (signal + conviction low/mid/high) and `advice[]`. New `member.analysis` event.
   `chair.summary` drops `overall_signal`; adds per-name `positions[]` rulings and `actions[]`.
4. New event `orchestrator.plan` (`member`, `focus_tickers`, `questions`) so the UI can show the
   hand-out before research starts.
5. Ingest accepts the `portfolio.json` shape (`symbol`/`qty`/`avg_entry_price`) alongside the current
   `ticker`/`shares`/`cost_basis` CSV, and treats it as one account within the persona's net worth.
6. `POST /api/council/ask` (one named member) generalises to `POST /api/council/chat`
   `{run_id, text, to?: member[]}`: `to` empty means the coordinator routes. Same SSE stream, plus
   `chat.routed` (`members[]`, `reason`), `member.reply` (`member`, `text`, `sources`) and
   `chat.closed` (`text`, `suggestions[]`). (Built: replies arrive whole, not token-streamed.)
7. The run keeps session memory (chat history, updated brief) keyed by `run_id`.
8. Demo user changes from Alex to Jordan Mitchell.

v1:

9. `POST /api/voice/session` and `POST /v1/chat/completions` (custom LLM for the ElevenLabs agent),
   env `ELEVENLABS_AGENT_ID`, and a publicly reachable server URL.

## Decisions log

| # | Question | Decision |
|---|---|---|
| 1 | Who orchestrates | Neutral central coordinator, not one of the five |
| 2 | Serious tier | Dalio, Buffett, Burry; Leopold intense; Cramer funny |
| 3 | Brokerage vs. persona | Brokerage is one connected account within Jordan's total assets |
| 4 | Verdict shape | Portfolio analysis (no call), then BUY / HOLD / SELL + conviction per researched name, plus advice |
| 5 | Demo user | Jordan Mitchell |
| 6 | Cross-talk | Allowed within routed turns; coordinator and user triage; medium length |
| 7 | Phasing | v0 = council + text chat; v1 = real-time voice |
