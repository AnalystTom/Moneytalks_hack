from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models import SpeakRequest
from app.services import council, elevenlabs

router = APIRouter(prefix="/voice")


async def _speak(member: str, text: str) -> Response:
    try:
        return Response(await elevenlabs.speak(member, text), media_type="audio/mpeg")
    except elevenlabs.VoiceError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/speak")
async def post_speak(req: SpeakRequest) -> Response:
    return await _speak(req.member, req.text)


@router.get("/line/{line_id}")  # the `audio_url` in member.audio events; only speaks lines the council wrote
async def get_line(line_id: str) -> Response:
    if line_id not in council.LINES:
        raise HTTPException(404, "unknown line")
    return await _speak(*council.LINES[line_id])
