# server - FastAPI backend (see [spec](../data/spec.md))

Implements the spec's server-to-scene contract. With no `NICRRON_API_KEY` it streams deterministic canned
events, so the frontend can build against it with no keys. Plaid and market data are stubs behind
`app/services/`; PRISM tracing no-ops without `PRISMTRACE_API_KEY`.

## Agents

Everything the agents know lives in `agents/` as plain markdown:

| file | what |
|---|---|
| `agents/orchestrator.md` | system prompt of the chair/orchestrator: hands out research, then rules |
| `agents/skill.md` | the tools every worker can call (`portfolio_lookup`, `persona_profile`, `specialist_row`, `web_search` only when `ANCHOR_API_KEY` is set) |
| `agents/personas/<name>.md` | one worker per file: front matter (`member` id, name, `order`, `chair`, voice hints) + who they are, voice, what they research and flag |

A run: the orchestrator (Claude Opus 5.5 via Nicrron) writes a research assignment per persona; one worker per
persona file then runs in parallel, each with its own message context and its own tool-calling loop, and
returns a verdict (`signal`, `confidence`, `headline`, `reasons`, `sources`, `tickers`, plus a short speech-bubble
`line`); the chair rules (`chair.summary`); each line is spoken in ElevenLabs. **Adding a council member is
adding a file in `agents/personas/`.** Roast mode only changes tone. Tool data comes from `../data/`
(`portfolio.json`, `PERSONA.md`, `specialist.csv`; override the folder with `DATA_DIR`).

PRISM: one trace per agent (the orchestrator and each worker), all with `session_id` = the run id; spans are
the workers, every LLM call and every tool call (including ElevenLabs). The ids are in `run.done`
(`trace_id`, `traces`); read one back with `GET <PRISMTRACE_HOST>/api/traces/<id>` and `/api/spans/<id>`.

Voices: `ELEVENLABS_VOICE_<MEMBER>` wins; otherwise the account voice whose name matches the persona's
`voice_names`; otherwise the persona's `voice_fallback` voice (logged). Voices are never created or cloned.

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

From the repository root, with Node 22 and `uv` on PATH:

```sh
npx wrangler login          # once
./set-secrets.sh .env       # uploads nonempty supported settings as Worker secrets
./deploy.sh                 # builds web/, then runs `pywrangler deploy`
```

`set-secrets.sh` parses dotenv assignments, including `export`, quotes, inline comments and variable interpolation.
It rejects malformed assignments before uploading and selects nonempty values with `NICRRON_`, `PRISMTRACE_`,
`ELEVENLABS_`, `ANCHOR_`, `PLAID_` or `CORS_` prefixes. Omitted or empty values do not delete existing secrets.

Public URL: https://council.thomasmann2001.workers.dev. `deploy.sh` is the redeploy; secrets persist across deploys.
`worker.py` copies the names in `ENV_NAMES` from the Worker env into `os.environ` before importing the app,
so settings such as CORS are available during app construction; add new consumed env names there.
Non-Python data the app reads at runtime (`council/*.md`) is bundled via `rules` in `wrangler.jsonc`.

### D1 database

`wrangler.jsonc` binds the D1 database `council` as `DB`, available inside the Durable Object as `self.env.DB`.
The app does not use this binding yet; no D1 schema or seed script is included. From `server/`, run SQL against
the live database with `npx wrangler d1 execute council --remote --command "SELECT 1"`.

## Env names

Copy `../.env.example` to `../.env`. All optional.

| name | effect |
|---|---|
| `NICRRON_API_KEY`, `NICRRON_MODEL` | set the key for live LLM answers (`https://api.nicrron.ai/v1`); unset = canned events. The model is `anthropic/claude-opus-5-5` unless `NICRRON_MODEL` names another (`nicrron/auto` counts as unset) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_BUFFETT` / `_CRAMER` / `_BURRY` / `_LEOPOLD` | speech; the key alone is enough (voices are matched by name), the voice ids override |
| `ELEVENLABS_MODEL` | speech model, default `eleven_multilingual_v2`; add to `.env` to override |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | PRISM trace + span per member |
| `CORS_ORIGINS` | comma-separated, default `*` |
| `ANCHOR_API_KEY` | turns on the workers' `web_search` tool (Anchor) |
| `DATA_DIR` | folder with `portfolio.json`, `PERSONA.md`, `specialist.csv`; default `../data` |
| `PLAID_CLIENT_ID`, `PLAID_SECRET` | reserved for the Plaid stub; unused today |

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
`run.done` (or `run.error`). `member.verdict` also carries `line` (the speech-bubble text) and `run.done` carries the
PRISM `trace_id` and per-member `traces`.

## Known limits

For storage limits, see [Deploy (Cloudflare)](#deploy-cloudflare). No answer caching or replay yet;
canned `member.audio` URLs 503 without an ElevenLabs key. Without `ANCHOR_API_KEY` there is no web search, so
verdict sources are data citations with no URL (the UI shows only linked sources). The Anchor call is untested
against the live service. A `--env-file` run needs `python-dotenv` (a dependency now).
