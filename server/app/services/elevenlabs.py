import logging

import httpx

from app.config import env
from app.services import personas

log = logging.getLogger(__name__)
URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
VOICES_URL = "https://api.elevenlabs.io/v1/voices"
_voices: list[dict] | None = None  # the account's voice list, fetched once
_voice_ids: dict[str, str] = {}
_audio: dict[tuple[str, str], bytes] = {}  # spoken lines, oldest evicted past CACHE_LINES so arbitrary GET /voice/speak text cannot grow memory
CACHE_LINES = 64


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(env("ELEVENLABS_API_KEY"))


async def _account_voices(client: httpx.AsyncClient, key: str) -> list[dict]:
    global _voices
    if _voices is None:
        r = await client.get(VOICES_URL, headers={"xi-api-key": key})
        if r.status_code != 200:
            raise VoiceError(f"ElevenLabs voice list returned HTTP {r.status_code}")
        _voices = r.json().get("voices", [])
    return _voices


async def voice_for(client: httpx.AsyncClient, key: str, member: str) -> str:
    """ELEVENLABS_VOICE_<MEMBER> if set, else the account voice whose name matches the persona, else the persona's fallback voice. Never creates voices."""
    if member in _voice_ids:
        return _voice_ids[member]
    chosen = env(f"ELEVENLABS_VOICE_{member.upper()}")
    if not chosen:
        persona = personas.load().get(member)
        voices = await _account_voices(client, key)
        wanted = [n.lower() for n in persona.voice_names] if persona else []
        match = next((v for v in voices if any(n in v["name"].lower() for n in wanted)), None)
        if not match:
            fallback = persona.voice_fallback.lower() if persona else ""
            match = next((v for v in voices if fallback and v["name"].lower().startswith(fallback)), None) or (voices[0] if voices else None)
            if not match:
                raise VoiceError("the ElevenLabs account has no voices", 503)
            log.warning("no ElevenLabs voice named for %s; using fallback voice %r", member, match["name"])
        else:
            log.info("%s speaks with ElevenLabs voice %r", member, match["name"])
        chosen = match["voice_id"]
    _voice_ids[member] = chosen
    return chosen


async def speak(member: str, text: str) -> bytes:
    """MP3 bytes of `text` in the member's voice."""
    if (audio := _audio.get((member, text))) is not None:
        return audio
    key = env("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set", 503)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            voice = await voice_for(client, key, member)
            r = await client.post(
                URL.format(voice_id=voice), params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Accept": "audio/mpeg"},
                json={"text": text, "model_id": env("ELEVENLABS_MODEL", "eleven_multilingual_v2")},
            )
    except httpx.HTTPError as e:
        raise VoiceError(f"ElevenLabs could not be reached: {e}") from e
    if r.status_code != 200 or not r.content:
        raise VoiceError(f"ElevenLabs returned HTTP {r.status_code}")
    _audio[(member, text)] = r.content
    while len(_audio) > CACHE_LINES:
        del _audio[next(iter(_audio))]
    return r.content
