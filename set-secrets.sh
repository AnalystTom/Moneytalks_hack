#!/bin/sh
# Upload the keys in an env file (default ./.env) as Worker secrets. Values are piped, never printed.
set -eu
cd "$(dirname "$0")"
ENV_FILE=${1:-.env}
python3 - "$ENV_FILE" <<'PY' | (cd server && npx wrangler secret bulk)
import json, sys
secrets = {}
for line in open(sys.argv[1]):
    key, _, value = line.strip().partition("=")
    value = value.strip("\"'")
    if value and key.startswith(("NICRRON_", "PRISMTRACE_", "ELEVENLABS_", "ANCHOR_", "PLAID_", "CORS_")):
        secrets[key] = value
print(json.dumps(secrets))
PY
