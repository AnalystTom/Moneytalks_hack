from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import ingest

router = APIRouter()
MAX_PORTFOLIO, MAX_PERSONA = 1_000_000, 64_000


async def _read(f: UploadFile, limit: int) -> bytes:
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{f.filename} is larger than {limit} bytes")
    return data


@router.post("/ingest")
async def post_ingest(
    portfolio: UploadFile = File(...),
    persona: UploadFile = File(...),
    plaid: bool = Form(False),
) -> dict:
    try:
        holdings = ingest.parse_holdings(portfolio.filename or "", await _read(portfolio, MAX_PORTFOLIO))
        text = (await _read(persona, MAX_PERSONA)).decode("utf-8-sig")
    except ValueError as e:  # includes JSON and unicode decode errors
        raise HTTPException(422, str(e)) from e
    brief_id, summary = await ingest.build_brief(holdings, text, plaid)
    return {"brief_id": brief_id, "summary": summary}
