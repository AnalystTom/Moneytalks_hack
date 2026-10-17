from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import AskRequest, ChatRequest, RunRequest
from app.services import council, ingest

router = APIRouter(prefix="/council")
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(stream) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream", headers=HEADERS)


async def _run(run_id: str) -> dict:
    run = await council.get_run(run_id)
    if not run:
        raise HTTPException(404, "unknown run_id")
    if not run["verdicts"]:
        raise HTTPException(409, "the opening run has not finished yet")
    return run


@router.post("/run")
async def run(req: RunRequest) -> StreamingResponse:
    brief = await ingest.get_brief(req.brief_id)
    if not brief:
        raise HTTPException(404, "unknown brief_id")
    _, stream = council.start_run(brief, req.question, req.roast)
    return _sse(stream)


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    return _sse(council.chat(await _run(req.run_id), req.run_id, req.text, req.to, req.roast))


@router.post("/ask")  # older clients: one named member; same stream as chat
async def ask(req: AskRequest) -> StreamingResponse:
    return _sse(council.chat(await _run(req.run_id), req.run_id, req.question, [req.member], req.roast))
