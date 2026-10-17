# server - FastAPI backend (see [spec](../data/spec.md))

Implements the council described in [council/README.md](council/README.md): a neutral coordinator plus five
specialists (Buffett, Dalio, Burry, Leopold, Cramer), then a routed text chat. With no `NICRRON_API_KEY` it streams deterministic canned
events, so the frontend can build against it with no keys. Anchor search, Plaid and market data are stubs
behind `app/services/`; PRISM tracing no-ops without `PRISMTRACE_API_KEY`.

## Run

```sh
cd server
uv sync --python 3.12
uv run uvicorn app.main:app --reload --port 8000 --env-file ../.env   # --env-file optional
uv run pytest
```

Demo without the web app: open `http://localhost:8000/demo`, click **Load Jordan**, convene, then chat
(template chips fill the input; the voice switch is a disabled v1 placeholder).

## Env names

Copy `../.env.example` to `../.env`. All optional.

| name | effect |
|---|---|
| `NICRRON_API_KEY`, `NICRRON_MODEL` | set the key for live LLM answers (`https://api.nicrron.ai/v1`); unset = canned events |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_BUFFETT` / `_DALIO` / `_BURRY` / `_LEOPOLD` / `_CRAMER` / `_CHAIR` | `/api/voice/speak`; 503 until the key and that speaker's voice id are set |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | PRISM spans: plan, each member, verification failures, ruling, routing, each chat reply |
| `CORS_ORIGINS` | comma-separated, default `*` |
| `ANCHOR_API_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET` | reserved for the stubs; unused today |

## Endpoints

```sh
curl localhost:8000/api/health

# ingest: broker snapshot (data/portfolio.json shape) or CSV/JSON holdings (cost_basis per share) + persona.md
curl -F portfolio=@../data/portfolio.json -F persona=@../data/PERSONA.md localhost:8000/api/ingest
# -> {"brief_id":"...","summary":"$283,741 in PLTR, SPY, NVDA, TSLA +10 more, +23%; $18,431 cash; Jordan Mitchell, 38"}
printf 'ticker,shares,cost_basis\nVOO,20,714.29\n' > portfolio.csv
printf '# Alex\n10-year horizon, moderate risk\n' > persona.md
curl -F portfolio=@portfolio.csv -F persona=@persona.md -F plaid=true localhost:8000/api/ingest
# -> {"brief_id":"...","summary":"$10,000 in VOO, -30%; $4,200 cash; 10-year horizon, moderate risk"}

# council run (SSE); add "roast": true for roast mode
curl -N -X POST localhost:8000/api/council/run -H 'content-type: application/json' \
  -d '{"brief_id":"<brief_id>","question":"Keep dollar-cost averaging, sell, or move?"}'

# chat turn after the run (run_id is in run.started); the coordinator routes unless "to" names members
curl -N -X POST localhost:8000/api/council/chat -H 'content-type: application/json' \
  -d '{"run_id":"<run_id>","text":"Burry and Leopold disagree on NVDA. Settle it."}'
# /api/council/ask {"run_id","member","question"} still works: a chat turn with to=[member]

# speech
curl -X POST localhost:8000/api/voice/speak -H 'content-type: application/json' \
  -d '{"member":"buffett","text":"Be fearful when others are greedy."}' -o buffett.mp3
```

Run events, in order: `run.started`; `orchestrator.plan` per member (`member`, `focus_tickers`, `shared_tickers`,
`questions`); then the five members in parallel, each in three stages:
`member.status` researching -> lens `member.source` -> analysing -> `member.analysis` (`headline`, `analysis`,
`reasons`, `names`; no calls) -> checking names -> per-name `member.source` (with `ticker`) -> deciding ->
`member.verdict` (the analysis plus `positions[]`: `ticker`, `signal`, `conviction` low/mid/high, `rationale`;
`advice[]`; `sources`). Then `chair.summary` (`consensus`, per-name `positions[]` rulings with `calls`,
`signal`, `conviction`, `consensus`; `dissent`, `actions`, `summary`, `suggestions`); a speaking ->
`member.audio` -> done triple per member, then the chair; `run.done` (or `run.error`).

Chat events: `run.started`; `chat.routed` (`members`, `reason`; `["chair"]` = the coordinator answers itself);
per speaker `member.reply` (`member`, `text`, `sources`) and its audio triple; `chat.closed` (`text`, `suggestions`);
`run.done`.

Coordinator rules live in `app/services/coordinator.py` (canned path and guard rails on LLM output):
numbers must appear in the brief or the member's sources (one retry, then stripped); calls only on held
names the member researched; `high` on a name needs a quoted source on it; per-name rulings: unanimous 3+
high, 2 agreeing mid, a lone call capped at mid, a tie is a HOLD "split".

## Known limits

Briefs and runs live in memory (lost on restart); no answer caching or replay yet (spec says D1);
canned `member.audio` URLs 503 without ElevenLabs keys; sources are the Anchor stub's placeholder;
chat replies arrive whole (no token streaming); `/demo` is a dev page, not the product UI.
