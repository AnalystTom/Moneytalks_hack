from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import AskRequest, RunRequest
from app.services import council, ingest, personas

router = APIRouter(prefix="/council")
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(stream) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream", headers=HEADERS)


@router.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    brief = ingest.BRIEFS.get(req.brief_id)
    if not brief:
        raise HTTPException(404, "unknown brief_id")
    _, stream = council.start_run(brief, req.question, req.roast)
    return _sse(stream)


@router.post("/ask")
async def ask(req: AskRequest) -> StreamingResponse:
    prior = council.RUNS.get(req.run_id)
    if not prior:
        raise HTTPException(404, "unknown run_id")
    if req.member not in personas.load():
        raise HTTPException(422, f"unknown member {req.member!r}")
    return _sse(council.ask(prior, req.run_id, req.member, req.question, req.roast))
