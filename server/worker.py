"""Cloudflare Python Worker entry: serves the FastAPI app under /api; web/dist is served as static assets.

Briefs and runs are written to D1 (app/services/store.py) so they survive the Durable Object being evicted or
redeployed; requests still go to one Durable Object instance so its in-memory cache stays warm.
"""
import os
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import asgi
from workers import DurableObject, WorkerEntrypoint, Response

# Environment bindings consumed by app settings.
ENV_NAMES = (
    "CORS_ORIGINS", "OPENAI_API_KEY", "OPENAI_MODEL", "PRISMTRACE_API_KEY", "PRISMTRACE_PROJECT_ID",
    "PRISMTRACE_ORG_ID", "PRISMTRACE_HOST", "ELEVENLABS_API_KEY", "ELEVENLABS_MODEL", "ELEVENLABS_VOICE_ID", "ANCHOR_API_KEY", "PLAID_CLIENT_ID", "PLAID_SECRET",
    "OPENAI_CONCURRENCY", *(f"ELEVENLABS_VOICE_{m}" for m in ("BUFFETT", "DALIO", "BURRY", "LEOPOLD", "CRAMER", "CHAIR")),
)


class Council(DurableObject):
    async def fetch(self, request):
        if request.method in ("GET", "POST") and unquote(urlsplit(str(request.url)).path) == "/api/voice/speak":
            try:
                limit = int(getattr(self.env, "SPEECH_DAILY_REQUEST_LIMIT", None) or "10")
                if limit < 0 or limit > 1000:
                    raise ValueError("Invalid speech allowance")
            except (ValueError, TypeError):
                return Response.json({"detail": "Speech allowance is not configured correctly."}, status=503)
            day = datetime.now(timezone.utc).date().isoformat()
            stored = (await self.ctx.storage.get("speech-usage")) or ""
            prior_day, _, prior_count = str(stored).partition("|")
            count = int(prior_count) if prior_day == day else 0
            if count >= limit:
                return Response.json({"detail": "Daily speech allowance reached. Try again tomorrow."}, status=429,
                                     headers={"Cache-Control": "no-store"})
            # Reserve before ASGI/provider work. DO storage gates serialize this read/write across requests and eviction.
            await self.ctx.storage.put("speech-usage", f"{day}|{count + 1}")
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
