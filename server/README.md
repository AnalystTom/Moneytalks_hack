# server - FastAPI backend (see [spec](../data/spec.md))

Implements the council described in [council/README.md](council/README.md): a neutral coordinator plus five
specialists (Buffett, Dalio, Burry, Leopold, Cramer), then a routed text chat. With no `OPENAI_API_KEY` it streams deterministic canned
events, so the frontend can build against it with no keys. Plaid and market data are stubs behind
`app/services/`; specialist research uses PRISM Knowledge Base retrieval, not the unused Anchor stub.
Tracing and retrieval no-op without both `PRISMTRACE_API_KEY` and `PRISMTRACE_PROJECT_ID`.
See [docs/prism.md](../docs/prism.md) for KB seeding and historical judging evidence.

## Run

```sh
cd server
uv sync --python 3.12
uv run uvicorn app.main:app --reload --port 8000 --env-file ../.env   # --env-file optional
uv run pytest
```

Demo without the web app: open `http://localhost:8000/demo`, click **Load Jordan**, convene, then chat
(template chips fill the input; the voice switch is a disabled v1 placeholder).

## Deploy (Cloudflare)

One Worker named `council` serves `web/dist` as static assets and the FastAPI app (Python Workers) under `/api/*`.
Briefs and runs are stored in D1 (see below), so they survive the Durable Object being evicted or redeployed;
`worker.py` still forwards every `/api` request to a single Durable Object, which keeps them cached in memory.

From the repository root, with Node 22 and `uv` on PATH:

```sh
npx wrangler login          # once
./set-secrets.sh .env       # uploads nonempty supported settings as Worker secrets
./deploy.sh                 # builds web/, then runs `pywrangler deploy`
```

`set-secrets.sh` parses dotenv assignments, including `export`, quotes, inline comments and variable interpolation.
It rejects malformed assignments before uploading and selects nonempty values with `OPENAI_`, `PRISMTRACE_`,
`ELEVENLABS_`, `ANCHOR_`, `PLAID_` or `CORS_` prefixes. Omitted or empty values do not delete existing secrets.

Public URL: https://council.thomasmann2001.workers.dev. `deploy.sh` is the redeploy; secrets persist across deploys.
`worker.py` copies the names in `ENV_NAMES` from the Worker env into `os.environ` before importing the app,
so settings such as CORS are available during app construction; add new consumed env names there.
Non-Python data the app reads at runtime (`council/*.md`) is bundled via `rules` in `wrangler.jsonc`.

### D1 database

`wrangler.jsonc` binds the D1 database `council` as `DB`, available inside the Durable Object as `self.env.DB`.
`app/services/store.py` keeps briefs and runs there as JSON documents in a `docs(kind, id, body)` table it creates
on first use, so there is no schema or seed script. From `server/`, run SQL against the live database with `npx wrangler d1 execute council --remote --command "SELECT 1"`.

## Env names

Copy `../.env.example` to `../.env`; the server loads it on startup (shell variables win). All optional.

| name | effect |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_MODEL` | set the key for live LLM answers (`https://api.openai.com/v1`); no key = canned events. An unset model selects `gpt-6-luna`; other model names are used as given |
| `ELEVENLABS_API_KEY` | required for `/api/voice/speak` and `/api/voice/transcribe`; 503 without it |
| `ELEVENLABS_VOICE_BUFFETT` / `_DALIO` / `_BURRY` / `_LEOPOLD` / `_CRAMER` / `_CHAIR`, `ELEVENLABS_VOICE_ID` | per-speaker voice overrides the shared voice; if neither is set, speech uses the first available premade voice returned by ElevenLabs, or 503 if none is available |
| `ELEVENLABS_MODEL` | speech model, default `eleven_v4`; add to `.env` to override |
| `OPENAI_CONCURRENCY` | max OpenAI calls in flight, default 4; 429s are retried with backoff |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | key and project enable PRISM tracing and member-specific KB retrieval; host defaults to `https://prism.blockconvey.com` |
| `COUNCIL_VERSION` | `v1` disables KB retrieval; default `v2`. Local only, not forwarded by the Worker |
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
# -> {"brief_id":"...","summary":"$10,000 in VOO, -30%; $4,200 bank cash; 10-year horizon, moderate risk"}

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

# transcribe a microphone recording
curl -F file=@question.webm localhost:8000/api/voice/transcribe
# -> {"text":"<actual ElevenLabs transcript>"}
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

Payload schemas live in [`app/models.py`](app/models.py); coordinator behavior is described in
[council/README.md](council/README.md). The frontend's presentation and follow-up controls are documented
in the [web journey](../web/README.md#journey).

### Personal details

`POST /api/ingest/text` accepts one JSON `text` string (1–4,000 characters). It needs `OPENAI_API_KEY`
to extract a profile and at least one holding with a ticker and a share count or dollar amount.
Request validation or rejected extraction returns 422; an unconfigured model returns 503;
model HTTP failures return 502. Extraction schemas and validation live in
[`app/services/profile.py`](app/services/profile.py).

```sh
curl -H 'content-type: application/json' \
  -d '{"text":"I am Sam, 31. 40 shares of AAPL at $150, $8k in VOO, $12k cash. Goal: house deposit in 5 years."}' \
  localhost:8000/api/ingest/text
```

The response adds a context `card` and a `missing` list to the usual `brief_id` and `summary`.
Reported dollar amounts stay amounts; this path fetches no market prices and connects no bank account.
Repeated tickers are consolidated, retaining supplied lots; totals and share-weighted cost basis are
calculated only when all required lot values are present. Missing shares, cost basis and profile details
remain unknown and are called out on the card. Valuation and profit/loss are marked unavailable when
their inputs are absent. Missing cash stays unknown; explicit zero cash is retained. Cash-dependent
totals and ratios require known cash and holdings value; brokerage/net-worth ratios also require nonzero net worth.

The submitted text goes to OpenAI; the resulting brief is stored as described under [D1 database](#d1-database).
The ingest call's PRISM metadata policy is documented in [PRISM proofs](../docs/prism.md).

## Known limits

For storage limits, see [Deploy (Cloudflare)](#deploy-cloudflare). No answer caching or replay yet;
canned `member.audio` URLs 503 without ElevenLabs keys; KB sources are empty without configured,
available member documents (there is no live web-search fallback);
chat replies arrive whole (no token streaming); `/demo` is a dev page, not the product UI.
