from fastapi import APIRouter

from app.config import env, voice_id, SPEAKERS

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "llm": "nicrron" if env("NICRRON_API_KEY") else "canned",
        "voice": bool(env("ELEVENLABS_API_KEY")) and all(voice_id(m) for m in SPEAKERS),
        "prism": bool(env("PRISMTRACE_API_KEY")),
    }
