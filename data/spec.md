# Council - spec

MONEY TALKS 2 hackathon, Money Intelligence track. Submission: Saturday 2026-10-17, 4:00 PM ET.

## Pitch

You sit at the head of a boardroom table. A council of legendary investors - Warren Buffett, Jim Cramer, Michael Burry, Leopold Aschenbrenner, Ray Dalio - reads your portfolio, bank account and profile, researches live, and each gives you a cited Buy / Hold / Sell verdict.

ICP: retail investors managing their own money.
Not financial advice: the UI shows a persistent "parody personas, not financial advice" notice.

## User journey (v0, ~2 min demo)

1. **User input (one step).** One screen collects all three sources, then one "Convene the council" button:
   - Stock portfolio: holdings upload (CSV or JSON: ticker, shares, cost basis).
   - Bank account: Plaid Sandbox connection.
   - `persona.md`: the user's own profile (age, goals, horizon, risk tolerance, constraints).
   - Demo shortcut: "Load Alex" prefills all three (portfolio $10,000 in an S&P 500 ETF, down 30%; Plaid sandbox account; Alex's `persona.md`).
   - Alex asks: "I'm down 30%. Keep dollar-cost averaging, sell, or move somewhere else?"
2. **Ingest.** The server merges the three sources into one client brief and shows a one-line summary in chat ("$10k in VOO, -30%; $4.2k cash; 10-year horizon, moderate risk").
3. **Council researches.** All five members research in parallel with separate contexts; linked web sources are available when Anchor is configured. The current scene has four portrait seats; Dalio appears in the member strip and transcript. Each speech bubble shows the member's current status, or a count of available sources when no status has arrived. Select a member to view source links in expanded details.
4. **Verdicts.** Members reveal one by one: signal, confidence, headline, 2-3 reasons, cited sources.
   - Buffett - fundamentals
   - Cramer - trend following
   - Burry - contrarian / bear case
   - Leopold - AI thesis
   - Dalio - global macro
5. **Drum roll.** Before the final call, a drum-roll beat builds tension.
6. **Warren's ruling.** Warren is the orchestrator at the head of the table: he hands out the research, then gives the final summary - consensus, dissent, overall call.
7. **Follow-up.** The user asks one named member a question in chat; only that member answers.

**Roast mode** (toggle): the council roasts the user's portfolio instead of advising politely - same flow, comedic voice.

Planned: cache answers per input + question so the stage demo survives a bad network, replaying the same events as a live run. Current persistence limits are in the [backend guide](../server/README.md#known-limits).

## Screen

- Left ~70%: HTML/CSS boardroom with a curved table and separate generated cartoon portrait cutouts. Warren (orchestrator) sits at the head; Leopold on the left; Burry and Cramer on the right. All four speech bubbles stay in the layout, grow with their returned headlines (Warren’s returned summary for the final ruling), and are never line-clamped. The active member’s bubble is highlighted. BUY and SELL use thumbs-up/down icons, HOLD uses a pause icon, and pending members show an hourglass. "View more" expands the displayed answer; see the [web journey](../web/README.md#journey) for detail selection and follow-up behavior. No WebGL is required.
- Right ~30%: React chat panel - the input step, ingest summary, chair summary, follow-ups.
- Narrow screens: two columns of members, with Warren first, and the chat panel below the boardroom. The main content scrolls vertically for long answers while the parody notice remains visible in the footer.
- Design direction: stone-grey / charcoal neutral palette and flat cut-paper cartoon members.

## Server-to-scene contract

The scene and chat only render events; they never call models.

- `POST /api/ingest` - multipart: portfolio file, Plaid sandbox flag, `persona.md` -> `{brief_id, summary}`.
- `POST /api/council/run` - `{brief_id, question}` -> Server-Sent Events stream.
- `POST /api/council/ask` - `{run_id, member, question}` -> same stream shape, one member only.
- `POST /api/voice/speak` - `{member, text}` -> `audio/mpeg`; voice resolution and requirements are in the [backend guide](../server/README.md#agents).
- `GET /api/voice/speak?member=&text=` - playable audio URL used by `member.audio`.
- `run` and `ask` accept `roast: bool`.

Events (`event:` name, JSON `data:`):

| event | data |
|---|---|
| `run.started` | `run_id` |
| `member.status` | `member`, `status`: `researching` / `thinking` / `speaking` / `done` |
| `member.source` | `member`, `title`, `url` |
| `member.verdict` | `member`, `signal`: `BUY` / `HOLD` / `SELL`, `confidence` 0-1, `headline`, `reasons[]`, `sources[]` (`title`, `url`, `quote`), `tickers[]`, `line` (spoken text) |
| `chair.summary` | `overall_signal`, `consensus`, `dissent[]`, `summary` (spoken by Warren) |
| `member.audio` | `member`, `audio_url` (ElevenLabs speech for that member's line) |
| `run.done` | `run_id`, `trace_id` (nullable); council runs also include `traces` (member id -> submitted trace id). Follow-ups return the worker trace id only. |
| `run.error` | `message` |

Backend member ids come from the `member` front matter in `server/agents/personas/`; the frontend accepts the ids in `web/src/contract.ts`.

Order: `run.started`; workers emit `member.status` researching, optional `member.source` and thinking events
as tools run, then `member.verdict`. Warren researches concurrently but his verdict is held until the others
have reported. Next comes `chair.summary`, then speaking -> `member.audio` -> done for each non-chair
member in persona order, followed by Warren speaking the ruling, then `run.done`. A follow-up emits only
the named member's events and no chair summary. Failures emit `run.error`; missing model configuration
produces no verdicts. Audio URLs may fail independently when speech is unavailable.

## Council members

Persona files and orchestration are described in the [backend guide](../server/README.md#agents).

## Stack

- Backend: Python (FastAPI) on Cloudflare Python Workers, with D1 planned for briefs, runs and cached events. See [deployment](../server/README.md#deploy-cloudflare) for current storage limits. If Python Workers blocks a needed dependency, move the backend to Cloudflare Containers.
- Frontend: React (Vite + TypeScript) with an HTML/CSS boardroom, served as the Worker's static assets.
- LLM: Nicrron API (OpenAI-compatible, `https://api.nicrron.ai/v1`).
- Web search: Anchor.
- Voice: ElevenLabs text-to-speech; see the [backend voice configuration](../server/README.md#agents).
- Bank data: Plaid Sandbox over HTTP (`/sandbox/public_token/create` -> `/item/public_token/exchange` -> balances and transactions; no Link UI in v0).
- Market data: TBD (current prices for holdings).
- Financial-analysis skills: built by KJ; members call them through one shared tool interface (stubbed until KJ's piece lands).
- PRISM (plain HTTP; the `prismtrace-sdk` Python package does not run inside Workers):
  - Current trace delivery and read-back: see the [backend guide](../server/README.md#agents).
  - Planned Knowledge Base: each member has its own uploaded documents; retrieval via `POST .../api/knowledge-base/search` with `agent_id`.
  - Planned `server/scripts/seed_runs.py`: 50+ council runs over varied inputs so PRISM has data before any fixing; this script is not implemented.

For supported settings, see [Env names](../server/README.md#env-names); for Worker secret uploads, see [Deploy (Cloudflare)](../server/README.md#deploy-cloudflare).

## Repo layout

- `spec.md` - this file.
- `server/` - FastAPI backend.
- `web/` - React frontend.

The earlier TypeScript starter (working Nicrron call + PRISM trace and span ingest) is in commit `d8f4499`; use it as the reference for endpoints and payloads.

## PRISM proofs (required for judging)

1. Knowledge Base: a run whose retrieval step used a member's uploaded documents.
2. Root Cause: a cluster of 3+ failed runs (e.g. a member invents a price or quote) and why.
3. Evaluator: "every number and quote is in the sources", scored v1 vs v2 on the same inputs.

## Later

|           | v1                                                    | v2                      |
| --------- | ----------------------------------------------------- | ----------------------- |
| UI        | Talking heads                                         | Live voice conversation |
| Research  | Deep research; earnings (Apple, Comcast); NA + Europe | Socials                 |
| Bank data | Plaid Link (real connect flow)                        | -                       |

## Out of scope for v0

Talking heads, real accounts, auth, Plaid Link UI.
