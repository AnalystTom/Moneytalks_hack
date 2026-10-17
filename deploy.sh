#!/bin/sh
# Build the web app and deploy web + server to Cloudflare as the `council` Worker (uses the wrangler login).
set -eu
cd "$(dirname "$0")"
(cd web && npm ci --no-audit --no-fund && npm run build)
# pywrangler needs uv >= 0.12.3 on PATH; --with puts a recent one in the tool env.
cd server && uvx --with 'uv>=0.12.3' --from workers-py pywrangler deploy
