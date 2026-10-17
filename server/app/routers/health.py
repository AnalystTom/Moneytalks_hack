from fastapi import APIRouter

from app.config import env, model
from app.services import anchor, elevenlabs

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "llm": model() if env("NICRRON_API_KEY") else "unavailable",
        "voice": elevenlabs.enabled(),
        "prism": bool(env("PRISMTRACE_API_KEY") and env("PRISMTRACE_PROJECT_ID")),
        "search": anchor.enabled(),
    }
