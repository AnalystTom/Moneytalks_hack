# server - FastAPI backend (see ../spec.md)

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
(`member.audio.audio_url` is `GET /api/voice/line/<id>`, which only speaks lines the council wrote; playable in an `<audio>` tag);
`run.done` (or `run.error`).

## Known limits

Briefs and runs live in memory (lost on restart); no answer caching or replay yet (spec says D1);
canned `member.audio` URLs 503 without ElevenLabs keys; uploads capped at 1 MB / 64 KB, stores keep the last 500 entries; `POST /api/voice/speak` (required by the contract) has no auth or rate limit, so put it behind auth/limits and set `CORS_ORIGINS` before a public deploy; sources are the Anchor stub's placeholder.
