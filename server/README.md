# server - FastAPI backend (see [spec](../data/spec.md))

Implements the spec's server-to-scene contract. With no `NICRRON_API_KEY` it streams deterministic canned
events, so the frontend can build against it with no keys. Anchor search, Plaid and market data are stubs
behind `app/services/`; PRISM tracing and Knowledge Base search no-op without `PRISMTRACE_API_KEY`. See [docs/prism.md](../docs/prism.md) for the PRISM proofs; `scripts/kb_seed.py` uploads the per-member Knowledge Base and `scripts/seed_runs.py` seeds runs.

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
| `NICRRON_API_KEY`, `NICRRON_MODEL` | set the key for live LLM answers (`https://api.nicrron.ai/v1`); unset = canned events |
| `ELEVENLABS_API_KEY` | server-only key for transcription and spoken replies; 503 when missing |
| `ELEVENLABS_VOICE_BUFFETT` / `_CRAMER` / `_BURRY` / `_LEOPOLD` | optional member voice; overrides `ELEVENLABS_VOICE_ID` |
| `ELEVENLABS_VOICE_ID` | optional shared voice; when unset, fetch an available premade voice from ElevenLabs (requires voice-list access) |
| `ELEVENLABS_MODEL` | speech model, default `eleven_v4` via Text to Dialogue; existing TTS models such as `eleven_multilingual_v2` remain supported via Text to Speech |
| `PRISMTRACE_API_KEY`, `PRISMTRACE_PROJECT_ID`, `PRISMTRACE_HOST` | PRISM trace + span per member |
| `COUNCIL_VERSION` | `v1` turns PRISM Knowledge Base retrieval off (the pre-KB backend, used to seed the PRISM comparison); default `v2`. Local only, not uploaded as a Worker secret |
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

# transcribe a microphone recording
curl -F file=@question.webm localhost:8000/api/voice/transcribe
# -> {"text":"<actual ElevenLabs transcript>"}
```

## Voice conversations

In the chat panel, select **Speak your question**, allow microphone access, then select
**Stop recording**. Scribe v2 transcribes the recording into the question field. Existing typed text is
preserved; review and send with the chat send button. Reply to a member's returned message to direct
your next spoken question to that member. Replies play in order when
**Sound on** is enabled. The audio controls let you pause or replay the latest reply; **Sound off** skips
automatic playback. This is push-to-talk, with a review step before each question is sent.

Recording requires HTTPS (or localhost), browser microphone permission and MediaRecorder support.
The microphone stops after 60 seconds, on errors or when the form unmounts. Uploads over 5 MB, unsupported
formats and empty recordings return explicit errors. Provider failures preserve your typed question and
the council transcript. There is no browser speech-recognition fallback or fabricated transcription.

The browser sends recordings only to `/api/voice/transcribe`; the server sends them to ElevenLabs using
`scribe_v2`. Speech uses `eleven_v4` by default, with long replies split into requests of at most 2,000
characters. Audio and text incur ElevenLabs usage. Each voice operation sends a tool trace to PRISM,
including the actual model, transcript or audio byte count, and failure status; raw audio is not sent to
PRISM. Voice traces currently have independent session IDs. Keys never reach the browser. A restricted
key needs Speech to Text and speech-generation access, plus voice-list access unless a voice ID is set.

Model references: [ElevenLabs models](https://elevenlabs.io/docs/overview/models),
[Scribe transcription](https://elevenlabs.io/docs/api-reference/speech-to-text/convert),
[Text to Dialogue](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert).

Events and payloads are the spec's table. Order: `run.started`; the three other members in parallel
(`member.status` researching -> `member.source` -> thinking -> `member.verdict`); then Warren's own
verdict; `chair.summary`; a `member.status` speaking -> `member.audio` -> done triple per member
(`member.audio.audio_url` is `GET /api/voice/speak?member=&text=`, playable in an `<audio>` tag);
`run.done` (or `run.error`).

## Known limits

For storage limits, see [Deploy (Cloudflare)](#deploy-cloudflare). No answer caching or replay yet;
canned `member.audio` URLs 503 without an ElevenLabs key; sources are the Anchor stub's placeholder.
