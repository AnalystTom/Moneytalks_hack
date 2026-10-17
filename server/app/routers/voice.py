from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.models import SpeakRequest, Speaker
from app.services import elevenlabs

router = APIRouter(prefix="/voice")
MAX_AUDIO_BYTES = 5 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(file: UploadFile) -> dict:
    try:
        content_type = (file.content_type or "").split(";")[0].strip()
        if content_type not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg"}:
            raise HTTPException(415, "Record audio in WebM, Ogg, MP4, WAV or MP3 format.")
        audio = await file.read(MAX_AUDIO_BYTES + 1)
        if not audio:
            raise HTTPException(422, "The recording is empty. Please try again.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "The recording exceeds 5 MB. Please record a shorter question.")
        return {"text": await elevenlabs.transcribe(audio, content_type)}
    except elevenlabs.VoiceError as e:
        raise HTTPException(e.status, str(e)) from e
    finally:
        await file.close()


async def _speak(member: str, text: str) -> Response:
    try:
        return Response(await elevenlabs.speak(member, text), media_type="audio/mpeg")
    except elevenlabs.VoiceError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/speak")
async def post_speak(req: SpeakRequest) -> Response:
    return await _speak(req.member, req.text)


@router.get("/speak")  # the `audio_url` in member.audio events points here so an <audio> tag can play it
async def get_speak(member: Speaker, text: str = Query(min_length=1, max_length=2500)) -> Response:
    return await _speak(member, text)
