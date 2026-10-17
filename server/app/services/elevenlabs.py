import json
import uuid
from textwrap import wrap
from urllib.parse import quote

import httpx

from app.config import env, voice_id
from app.services import prism

BASE_URL = "https://api.elevenlabs.io"


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def api_key() -> str:
    key = env("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set", 503)
    return key


async def speak(member: str, text: str) -> bytes:
    """Generate actual MP3 audio; member voice overrides the shared voice."""
    key = api_key()
    if not text.strip():
        raise VoiceError("Supply nonempty text to speak.", 422)
    model = env("ELEVENLABS_MODEL", "eleven_v4")
    output, ok = "", False
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            voice = voice_id(member)
            if not voice:
                listing = await client.get(
                    f"{BASE_URL}/v2/voices", headers={"xi-api-key": key},
                    params={"category": "premade", "page_size": 1, "include_total_count": "false"},
                )
                listing.raise_for_status()
                voices = listing.json().get("voices", [])
                if not voices or not isinstance(voices[0].get("voice_id"), str) or not voices[0]["voice_id"].strip():
                    raise VoiceError("No available ElevenLabs voice. Set ELEVENLABS_VOICE_ID.", 503)
                voice = voices[0]["voice_id"]
            audio = bytearray()
            # Dialogue requests support up to 2,000 characters reliably; keep every word of longer replies.
            for part in wrap(text, 2000, replace_whitespace=False, drop_whitespace=False):
                dialogue = model == "eleven_v4"
                path = "/v1/text-to-dialogue" if dialogue else f"/v1/text-to-speech/{quote(voice, safe='')}"
                payload = {"inputs": [{"text": part, "voice_id": voice}]} if dialogue else {"text": part}
                response = await client.post(
                    BASE_URL + path, params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key, "Accept": "audio/mpeg"},
                    json={**payload, "model_id": model},
                )
                response.raise_for_status()
                if not response.content or response.headers.get("content-type", "").split(";")[0] != "audio/mpeg":
                    raise VoiceError("ElevenLabs returned no MP3 audio.")
                audio.extend(response.content)
            output = json.dumps({"bytes": len(audio), "voice_id": voice})
            ok = True
            return bytes(audio)
    except httpx.HTTPStatusError as exc:
        output = f"ElevenLabs returned HTTP {exc.response.status_code}."
        raise VoiceError(output) from exc
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        output = "ElevenLabs could not be reached or returned an invalid response."
        raise VoiceError(output) from exc
    except VoiceError as exc:
        output = str(exc)
        raise
    finally:
        await prism.span(uuid.uuid4().hex, "voice.speak", "tool", text, output, ok, model=model)


async def transcribe(audio: bytes, content_type: str) -> str:
    key = api_key()
    output, ok = "", False
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{BASE_URL}/v1/speech-to-text", headers={"xi-api-key": key},
                files={"file": ("question", audio, content_type)},
                data={"model_id": "scribe_v2", "tag_audio_events": "false"},
            )
            response.raise_for_status()
            text = response.json().get("text")
            if not isinstance(text, str) or not text.strip():
                raise VoiceError("No speech was detected. Please try again.", 422)
            output, ok = text.strip(), True
            return output
    except httpx.HTTPStatusError as exc:
        output = f"ElevenLabs transcription returned HTTP {exc.response.status_code}."
        raise VoiceError(output) from exc
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        output = "ElevenLabs transcription could not be reached or returned an invalid response."
        raise VoiceError(output) from exc
    except VoiceError as exc:
        output = str(exc)
        raise
    finally:
        await prism.span(uuid.uuid4().hex, "voice.transcribe", "tool", f"{len(audio)} bytes ({content_type})", output, ok, model="scribe_v2")
