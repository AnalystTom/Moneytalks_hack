# server - FastAPI backend (see [spec](../data/spec.md))

Implements the spec's server-to-scene contract. With no `NICRRON_API_KEY` it streams deterministic canned
events, so the frontend can build against it with no keys. Anchor search, Plaid and market data are stubs
behind `app/services/`; PRISM tracing no-ops without `PRISMTRACE_API_KEY`.

## Run

```sh
cd server
uv sync --python 3.12
uv run uvicorn app.main:app --reload --port 8000 --env-file ../.env   # --env-file optional
uv run pytest
```

## Deploy (Cloudflare)

One Worker named `council` serves `web/dist` as static assets and the FastAPI app (Python Workers) under `/api/*`.
Because briefs and runs live in memory, `worker.py` forwards every `/api` request to a single Durable Object so
ingest and run hit the same instance; state is lost when that object is evicted or redeployed.

```sh
npx wrangler login          # once
./set-secrets.sh .env       # uploads NICRRON_*, PRISMTRACE_*, ELEVENLABS_* ... as Worker secrets
./deploy.sh                 # builds web/, then `pywrangler deploy` (needs node 22 and uv)
```

Live at https://council.thomasmann2001.workers.dev. `deploy.sh` is the redeploy; secrets persist across deploys.
`worker.py` copies the names in `ENV_NAMES` from the Worker env into `os.environ`; add new env names there.
Non-Python data the app reads at runtime (`council/*.md`) is bundled via `rules` in `wrangler.jsonc`.

## Env names

Copy `../.env.example` to `../.env`. All optional.

| name | effect |
|---|---|
| `NICRRON_API_KEY`, `NICRRON_MODEL` | set the key for live LLM answers (`https://api.nicrron.ai/v1`); unset = canned events |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_BUFFETT` / `_CRAMER` / `_BURRY` / `_LEOPOLD` | `/api/voice/speak`; 503 until the key and that member's voice id are set |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | PRISM trace + span per member |
| `CORS_ORIGINS` | comma-separated, default `*` |
| `ANCHOR_API_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET` | reserved for the stubs; unused today |

## Endpoints

```sh
curl localhost:8000/api/health

# ingest: CSV/JSON portfolio (cost_basis is per share) + persona.md
printf 'ticker,shares,cost_basis\nVOO,20,714.29\n' > portfolio.csv
printf '# Alex\n10-year horizon, moderate risk\n' > persona.md
curl -F portfolio=@portfolio.csv -F persona=@persona.md -F plaid=true localhost:8000/api/ingest
# -> {"brief_id":"...","summary":"$10,000 in VOO, -30%; $4,200 cash; 10-year horizon, moderate risk"}

# council run (SSE); add "roast": true for roast mode
curl -N -X POST localhost:8000/api/council/run -H 'content-type: application/json' \
  -d '{"brief_id":"<brief_id>","question":"Keep dollar-cost averaging, sell, or move?"}'

# follow-up to one member; run_id is in the run.started event
curl -N -X POST localhost:8000/api/council/ask -H 'content-type: application/json' \
  -d '{"run_id":"<run_id>","member":"burry","question":"Why sell?"}'

# speech
curl -X POST localhost:8000/api/voice/speak -H 'content-type: application/json' \
  -d '{"member":"buffett","text":"Be fearful when others are greedy."}' -o buffett.mp3
```

Events and payloads are the spec's table. Order: `run.started`; the three other members in parallel
(`member.status` researching -> `member.source` -> thinking -> `member.verdict`); then Warren's own
verdict; `chair.summary`; a `member.status` speaking -> `member.audio` -> done triple per member
(`member.audio.audio_url` is `GET /api/voice/speak?member=&text=`, playable in an `<audio>` tag);
`run.done` (or `run.error`).

## Known limits

Briefs and runs live in memory (lost on restart); no answer caching or replay yet (spec says D1);
canned `member.audio` URLs 503 without ElevenLabs keys; sources are the Anchor stub's placeholder.
