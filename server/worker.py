"""Cloudflare Python Worker entry: serves the FastAPI app under /api; web/dist is served as static assets.

Briefs and runs are written to D1 (app/services/store.py) so they survive the Durable Object being evicted or
redeployed; requests still go to one Durable Object instance so its in-memory cache stays warm.
"""
import os

import asgi
from workers import DurableObject, WorkerEntrypoint

# Environment bindings consumed by app settings.
ENV_NAMES = (
    "CORS_ORIGINS", "OPENAI_API_KEY", "OPENAI_MODEL", "PRISMTRACE_API_KEY", "PRISMTRACE_PROJECT_ID",
    "PRISMTRACE_ORG_ID", "PRISMTRACE_HOST", "ELEVENLABS_API_KEY", "ELEVENLABS_MODEL", "ELEVENLABS_VOICE_ID", "ANCHOR_API_KEY", "PLAID_CLIENT_ID", "PLAID_SECRET",
    "OPENAI_CONCURRENCY", *(f"ELEVENLABS_VOICE_{m}" for m in ("BUFFETT", "DALIO", "BURRY", "LEOPOLD", "CRAMER", "CHAIR")),
)


class Council(DurableObject):
    async def fetch(self, request):
        # app.config reads os.environ; Workers only expose secrets/vars on the env binding.
        for key in ENV_NAMES:
            value = getattr(self.env, key, None)
            if isinstance(value, str):
                os.environ[key] = value
        from app.main import app
        from app.services import store

        store.bind(getattr(self.env, "DB", None))
        return await asgi.fetch(app, request.js_object, self.env)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # shortcut: one Durable Object serves all traffic, shard by brief/run id before real load.
        stub = self.env.COUNCIL.getByName("main")
        return await stub.fetch(request.js_object)
