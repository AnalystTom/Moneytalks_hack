# Council - spec

MONEY TALKS 2 hackathon, Money Intelligence track. Submission: Saturday 2026-10-17, 4:00 PM ET.

## Pitch

You sit at the head of a boardroom table. A council of legendary investors - Warren Buffett, Jim Cramer, Michael Burry, Leopold Aschenbrenner - hears your situation, researches it live, and each gives you a cited Buy / Hold / Sell verdict.

ICP: retail investors managing their own money.

## Screen

- Left ~70%: first-person POV boardroom. Four stylised, comical persona portraits seated around the table. The speaking persona lights up; verdict cards land on the table.
- Right ~30%: chat panel (profile, question, follow-ups).
- Design direction: high-stakes financial council, boardroom drama. Generated imagery.

## v0 demo journey (~2 min)

1. Pick demo user **Alex**: $10,000, all in the S&P 500, down 30%.
2. Alex asks: "I'm down 30%. Keep dollar-cost averaging, sell, or move somewhere else?"
3. Council convenes: each seat shows "researching..." with its live searches and sources (all four research in parallel).
4. Verdicts reveal one by one: signal (Buy / Hold / Sell), 2-3 reasons, cited sources.
   - Buffett - fundamentals (e.g. "Buy Apple because X and Y")
   - Cramer - trend following
   - Burry - contrarian / bear case
   - Leopold - AI thesis
5. Chair summary: consensus, dissent, overall call.
6. Follow-up to one named persona; only that persona answers.

Answers are cached per demo user + question so the stage demo survives a bad network.

## v0 stack

- Backend: Python (FastAPI) on Cloudflare Python Workers, with D1 (demo users, persona profiles, runs, cached research). If Python Workers blocks a needed dependency, move the backend to Cloudflare Containers.
- Frontend: React (Vite + TypeScript), served as the Worker's static assets.
- LLM: Nicrron API (OpenAI-compatible, `https://api.nicrron.ai/v1`).
- Web search: Anchor.
- Financial-analysis skills: built by KJ; personas call them through one shared tool interface (stubbed until KJ's piece lands).
- PRISM (plain HTTP from the backend; the `prismtrace-sdk` Python package does not run inside Workers):
  - Traces: `POST https://prism.blockconvey.com/api/traces`, header `X-PRISMtrace-Key`, one session id per council run.
  - Knowledge Base: each persona is a PRISM agent with its own documents (e.g. Berkshire letters); retrieval via `POST .../api/knowledge-base/search` with `agent_id`.

## PRISM proofs (required for judging)

1. Knowledge Base: a run whose retrieval step used the persona's uploaded documents.
2. Root Cause: a cluster of 3+ failed runs (e.g. persona invents a price or quote) and why.
3. Evaluator: "every number and quote is in the sources", scored v1 vs v2 on the same inputs.

## Later

| | v1 | v2 |
|---|---|---|
| UI | Talking heads | Cloned voices (ElevenLabs) |
| Research | Deep research; earnings (Apple, Comcast); NA + Europe | Socials |
| Personal data | Plaid sandbox -> context | - |

## Out of scope for v0

Voices, talking heads, real accounts, auth, more than one demo user.
