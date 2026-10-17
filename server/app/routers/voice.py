from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.models import SpeakRequest, Speaker
from app.services import elevenlabs

router = APIRouter(prefix="/voice")


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
