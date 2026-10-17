#!/bin/sh
# Upload the keys in an env file (default ./.env) as Worker secrets. Values are piped, never printed.
set -eu
cd "$(dirname "$0")"
ENV_FILE=${1:-.env}
SECRETS=$(uv run --no-project --with python-dotenv python - "$ENV_FILE" <<'PY'
import json, sys
from dotenv import dotenv_values
from dotenv.parser import parse_stream

with open(sys.argv[1], encoding="utf-8") as stream:
    for binding in parse_stream(stream):
        if binding.error:
            sys.exit(f"Invalid dotenv assignment at line {binding.original.line}")
    stream.seek(0)
    secrets = {
        key: value for key, value in dotenv_values(stream=stream).items()
        if value and key.startswith(("NICRRON_", "PRISMTRACE_", "ELEVENLABS_", "ANCHOR_", "PLAID_", "CORS_"))
    }
print(json.dumps(secrets))
PY
)
printf '%s\n' "$SECRETS" | (cd server && npx wrangler secret bulk)
