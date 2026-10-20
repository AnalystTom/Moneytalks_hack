import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services import ingest, llm, profile

router = APIRouter()


@router.post("/ingest")
async def post_ingest(
    portfolio: UploadFile = File(...),
    persona: UploadFile = File(...),
    plaid: bool = Form(False),
) -> dict:
    try:
        holdings, account = ingest.parse_portfolio(portfolio.filename or "", await portfolio.read())
        text = (await persona.read()).decode("utf-8-sig")
    except ValueError as e:  # includes JSON and unicode decode errors
        raise HTTPException(422, str(e)) from e
    brief_id, summary = await ingest.build_brief(holdings, text, plaid, account, net_worth=ingest._money(text, r"Net Worth"))
    return {"brief_id": brief_id, "summary": summary}


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=profile.MAX_CHARS)


@router.post("/ingest/text")
async def post_ingest_text(body: TextIn) -> dict:
    """One block of free text (name, positions, cash, goals) -> the same brief as /ingest, plus a context card."""
    if not llm.enabled():
        raise HTTPException(503, "Entering your own details needs the model, which isn't configured on this server.")
    try:
        return await profile.build(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "The model couldn't read your details right now. Please try again.") from e
