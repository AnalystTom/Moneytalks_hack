from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import ingest

router = APIRouter()


@router.post("/ingest")
async def post_ingest(
    portfolio: UploadFile = File(...),
    persona: UploadFile = File(...),
    plaid: bool = Form(False),
) -> dict:
    try:
        holdings = ingest.parse_holdings(portfolio.filename or "", await portfolio.read())
        text = (await persona.read()).decode("utf-8-sig")
    except ValueError as e:  # includes JSON and unicode decode errors
        raise HTTPException(422, str(e)) from e
    brief_id, summary = await ingest.build_brief(holdings, text, plaid)
    return {"brief_id": brief_id, "summary": summary}
