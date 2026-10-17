from fastapi import APIRouter, HTTPException, Query

from app.services import plaid

router = APIRouter(prefix="/plaid")


@router.get("/transactions")
async def transactions(days: int = Query(90, ge=1, le=730)) -> dict:
    try:
        txns = await plaid.get_transactions(days)
    except plaid.PlaidError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"count": len(txns), "transactions": txns}
