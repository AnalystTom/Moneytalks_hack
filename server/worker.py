"""Cloudflare Python Worker entry: serves the FastAPI app under /api; web/dist is served as static assets.

The app keeps briefs and runs in memory (see app/services/ingest.py), so every request is forwarded to one
Durable Object instance instead of whichever isolate the Worker lands on.
"""
import os

import asgi
from workers import DurableObject, WorkerEntrypoint

# Environment bindings consumed by app settings.
ENV_NAMES = (
    "CORS_ORIGINS", "NICRRON_API_KEY", "NICRRON_MODEL", "PRISMTRACE_API_KEY", "PRISMTRACE_PROJECT_ID",
    "PRISMTRACE_ORG_ID", "PRISMTRACE_HOST", "ELEVENLABS_API_KEY", "ELEVENLABS_MODEL", "ELEVENLABS_VOICE_ID", "ANCHOR_API_KEY", "PLAID_CLIENT_ID", "PLAID_SECRET",
    "NICRRON_CONCURRENCY", *(f"ELEVENLABS_VOICE_{m}" for m in ("BUFFETT", "DALIO", "BURRY", "LEOPOLD", "CRAMER", "CHAIR")),
)


class Council(DurableObject):
    async def fetch(self, request):
        # app.config reads os.environ; Workers only expose secrets/vars on the env binding.
        for key in ENV_NAMES:
            value = getattr(self.env, key, None)
            if isinstance(value, str):
                os.environ[key] = value
        from app.main import app

        return await asgi.fetch(app, request.js_object, self.env)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # shortcut: one Durable Object serves all traffic and loses briefs/runs on eviction, move them to D1 (spec) before real load.
        stub = self.env.COUNCIL.getByName("main")
        return await stub.fetch(request.js_object)
