import httpx

from app.config import env, voice_id

URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


async def speak(member: str, text: str) -> bytes:
    """MP3 bytes of `text` in the member's cloned voice."""
    key, voice = env("ELEVENLABS_API_KEY"), voice_id(member)
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set", 503)
    if not voice:
        raise VoiceError(f"ELEVENLABS_VOICE_{member.upper()} is not set", 503)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                URL.format(voice_id=voice), params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Accept": "audio/mpeg"},
                json={"text": text, "model_id": env("ELEVENLABS_MODEL", "eleven_multilingual_v2")},
            )
    except httpx.HTTPError as e:
        raise VoiceError(f"ElevenLabs could not be reached: {e}") from e
    if r.status_code != 200 or not r.content:
        raise VoiceError(f"ElevenLabs returned HTTP {r.status_code}")
    return r.content
