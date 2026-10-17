# server - FastAPI backend (see [spec](../data/spec.md))

Implements the spec's server-to-scene contract. Without `NICRRON_API_KEY`, runs and follow-ups emit an explicit `run.error`. Market values, returns and bank balances are explicitly unavailable; ingestion stores only submitted holdings and profile data. PRISM tracing requires both `PRISMTRACE_API_KEY` and `PRISMTRACE_PROJECT_ID`.

## Agents

Persona, orchestration and tool guidance lives in `agents/` as plain markdown:

| file | what |
|---|---|
| `agents/orchestrator.md` | system prompt of the chair/orchestrator: hands out research, then rules |
| `agents/skill.md` | worker tool guidance; callable schemas and dispatch live in `app/services/tools.py` |
| `agents/personas/<name>.md` | one worker per file: front matter (`member` id, name, `order`, `chair`, voice hints) + who they are, voice, what they research and flag |

A run: the orchestrator uses the [configured Nicrron model](#env-names) to write a research assignment per persona; one worker per
persona file then runs in parallel, each with its own message context and its own tool-calling loop, and
returns a cited verdict. The chair receives the full uploaded profile and holdings in both assignment and ruling phases.
An unusable assignment leaves workers to research without a personalised assignment; an unusable ruling
emits `run.error` instead of a computed replacement. Speech is requested through ElevenLabs when configured.
Follow-ups give the named worker its latest completed verdict's headline and reasons, plus access to the same brief through tools.
**Adding a council member requires a file in `agents/personas/` and frontend support for its id and presentation.** Roast mode only changes tone. Client holdings and profile come only from their uploaded brief. The specialist sheet comes from
`data/specialist.csv` inside `server/` (override the folder with `DATA_DIR`).

PRISM: one trace per agent (the orchestrator and each worker), all with `session_id` = the run id; spans are
the workers, every LLM call and every tool call (including ElevenLabs). The ids are in `run.done`
(see the [stream contract](../data/spec.md#server-to-scene-contract)); read one back with `GET <PRISMTRACE_HOST>/api/traces/<id>` and `/api/spans/<id>`.
Trace ids report successful submission, not independent read-back verification. Persona reference-document lists
do not load documents into PRISM or perform Knowledge Base retrieval.

Voices: `ELEVENLABS_VOICE_<MEMBER>` wins; otherwise the account voice whose name matches the persona's
`voice_names`; otherwise the persona's `voice_fallback` voice (logged). If neither configured name resolves,
speech returns a voice-unavailable error (503), without selecting an arbitrary account voice. Voices are never created or cloned.

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
`ELEVENLABS_`, `ANCHOR_`, `PLAID_` or `CORS_` prefixes, plus the exact `DATA_DIR` setting. Omitted or empty values do not delete existing secrets.

Public URL: https://council.thomasmann2001.workers.dev. `deploy.sh` is the redeploy; secrets persist across deploys.
`worker.py` copies the names in `ENV_NAMES` from the Worker env into `os.environ` before importing the app,
so settings such as CORS are available during app construction; add new consumed env names there.
Non-Python data the app reads at runtime (`agents/personas/*.md`, `agents/orchestrator.md`, `agents/skill.md` and `data/specialist.csv`) is bundled with preserved paths via `rules` in `wrangler.jsonc`. Custom data directories must also be bundled at the configured path.

### D1 database

`wrangler.jsonc` binds the D1 database `council` as `DB`, available inside the Durable Object as `self.env.DB`.
The app does not use this binding yet; no D1 schema or seed script is included. From `server/`, run SQL against
the live database with `npx wrangler d1 execute council --remote --command "SELECT 1"`.

## Env names

Copy `../.env.example` to `../.env`. `NICRRON_API_KEY` is required for council answers.

| name | effect |
|---|---|
| `NICRRON_API_KEY`, `NICRRON_MODEL` | set the key for live LLM answers (`https://api.nicrron.ai/v1`); unset = explicit unavailable error. The model is `anthropic/claude-opus-5-5` unless `NICRRON_MODEL` names another (`nicrron/auto` counts as unset) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_<MEMBER>` | speech requires the key and a resolvable persona/fallback voice or explicit voice id; `<MEMBER>` is the uppercase persona id |
| `ELEVENLABS_MODEL` | speech model, default `eleven_multilingual_v2`; add to `.env` to override |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | key and project id enable tracing; host defaults to `https://prism.blockconvey.com` |
| `CORS_ORIGINS` | comma-separated, default `*` |
| `ANCHOR_API_KEY` | turns on the workers' `web_search` tool (Anchor) |
| `DATA_DIR` | folder with `specialist.csv`; default `server/data` |
| `PLAID_CLIENT_ID`, `PLAID_SECRET` | reserved for a future Plaid integration; unused today |

## Endpoints

`GET /api/health` reports configuration: `llm` is the selected model id or `unavailable`, `voice` indicates an
ElevenLabs key, `prism` indicates both required PRISM settings, and `search` indicates an Anchor key.
`ok: true` reports that the endpoint responded; these fields do not verify provider connectivity or voice availability.

```sh
curl localhost:8000/api/health

# ingest: CSV/JSON portfolio (cost_basis is per share) + persona.md
printf 'ticker,shares,cost_basis\nVOO,20,714.29\n' > portfolio.csv
printf '# Alex\n10-year horizon, moderate risk\n' > persona.md
curl -F portfolio=@portfolio.csv -F persona=@persona.md -F plaid=true localhost:8000/api/ingest
# -> {"brief_id":"...","summary":"Holdings: VOO; Market value and returns unavailable; Bank balances unavailable; 10-year horizon, moderate risk"}

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

Event payloads and ordering are defined in the [stream contract](../data/spec.md#server-to-scene-contract).

## Known limits

For storage limits, see [Deploy (Cloudflare)](#deploy-cloudflare). No answer caching or replay yet;
`member.audio` URLs 503 without an ElevenLabs key. Without `ANCHOR_API_KEY` there is no web search, so
verdict sources are data citations with no URL (the UI shows only linked sources). Source validation requires
a matching tool title/URL and an excerpt of returned evidence; it does not verify every claim or number in the verdict.
Worker tool results are passed in full; PRISM trace input/output text is separately capped at 8,000 characters
(worker LLM-span input records only the first 4,000 characters of the last message). The Anchor call is untested
against the live service. A `--env-file` run needs `python-dotenv` (a dependency now).
