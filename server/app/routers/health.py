from fastapi import APIRouter

from app.config import env

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "llm": "openai" if env("OPENAI_API_KEY") else "canned",
        "voice": bool(env("ELEVENLABS_API_KEY")),
        "prism": bool(env("PRISMTRACE_API_KEY")),
    }
