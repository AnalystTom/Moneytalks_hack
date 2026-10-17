# Council - spec

MONEY TALKS 2 hackathon, Money Intelligence track. Submission: Saturday 2026-10-17, 4:00 PM ET.

## Pitch

You sit at the head of a boardroom table. A neutral coordinator assigns research to five parody specialists - Warren Buffett, Ray Dalio, Michael Burry, Leopold Aschenbrenner and Jim Cramer - who return portfolio analysis and per-ticker Buy / Hold / Sell calls with conviction labels. The coordinator rules on those calls and routes follow-up chat. See the [council design](../server/council/README.md) for the pipeline and the [server limits](../server/README.md#known-limits) for research availability.

ICP: retail investors managing their own money.
Not financial advice: the UI shows a persistent "parody personas, not financial advice" notice.

## User journey (v0, ~2 min demo)

The implemented input, boardroom, ruling and follow-up flow is maintained in the
[web journey](../web/README.md#journey). The checked-in demo context is Jordan Mitchell's
`data/portfolio.json` and `data/PERSONA.md`; it is not a live connected account.
The separate [server demo](../server/README.md#run) also supports an opening run and routed chat.

**Roast mode** (toggle): the council roasts the user's portfolio instead of advising politely - same flow, comedic voice.

Answer caching and replay are not implemented; see [storage limits](../server/README.md#deploy-cloudflare).

## Screen

- Left ~70%: HTML/CSS boardroom with a curved table and separate generated cartoon portrait cutouts. The active member's bubble is highlighted. BUY and SELL use thumbs-up/down icons, HOLD uses a pause icon, and pending members show an hourglass. Bubble previews and detail selection follow the [web journey](../web/README.md#journey). No WebGL is required.
- Right ~30%: React chat panel - the input step, ingest summary, chair summary, follow-ups.
- Narrow screens: two columns of members, with Warren first, and the chat panel below the boardroom. The main content scrolls vertically for long answers while the parody notice remains visible in the footer.
- Design direction: stone-grey / charcoal neutral palette and flat cut-paper cartoon members.

## Server-to-scene contract

The scene and chat only render events; they never call models.

The authoritative endpoint and SSE sequence documentation is in
[server/README.md](../server/README.md#endpoints); request and payload schemas are defined in
[`server/app/models.py`](../server/app/models.py). Presentation mapping belongs to the
[web journey](../web/README.md#journey).

## Council members

One file per member in `server/council/<member>.md`: philosophy, voice, signature phrases, what they research, and the documents in their PRISM Knowledge Base (e.g. Berkshire letters for Buffett, _Situational Awareness_ for Leopold).

## Stack

- Backend: Python (FastAPI) on Cloudflare Python Workers, with D1 holding briefs and runs (cached events are still planned). See [deployment](../server/README.md#deploy-cloudflare) for current storage. If Python Workers blocks a needed dependency, move the backend to Cloudflare Containers.
- Frontend: React (Vite + TypeScript) with an HTML/CSS boardroom, served as the Worker's static assets.
- LLM: Nicrron API (OpenAI-compatible, `https://api.nicrron.ai/v1`).
- Research: per-member PRISM Knowledge Base retrieval; live web search is not connected.
- Voice: ElevenLabs text-to-speech, one cloned voice per member (`ELEVENLABS_VOICE_<MEMBER>`).
- Bank data: Plaid Sandbox over HTTP (`/sandbox/public_token/create` -> `/item/public_token/exchange` -> balances and transactions; no Link UI in v0).
- Market data: TBD (current prices for holdings).
- Financial-analysis skills: built by KJ; members call them through one shared tool interface (stubbed until KJ's piece lands).
- PRISM (plain HTTP; the `prismtrace-sdk` Python package does not run inside Workers):
  - Traces and historical judging evidence: see [docs/prism.md](../docs/prism.md).
  - Knowledge Base: each member is a PRISM agent with its own documents; retrieval via `POST .../api/knowledge-base/search` with `agent_id`.
  - `server/scripts/seed_runs.py` runs 50+ council runs over varied inputs so PRISM has data before any fixing.

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
