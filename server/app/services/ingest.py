import csv
import io
import json
import uuid

from app.services import market, plaid
from app.services.store import put

MAX_HOLDINGS = 200
BRIEFS: dict[str, dict] = {}  # shortcut: in-memory, lost on restart; move to D1 with the Cloudflare port


def parse_holdings(filename: str, raw: bytes) -> list[dict]:
    """Holdings from CSV (ticker,shares,cost_basis) or JSON (list, or {"holdings": [...]}); cost_basis is per share."""
    text = raw.decode("utf-8-sig")
    rows = json.loads(text) if filename.lower().endswith(".json") else list(csv.DictReader(io.StringIO(text)))
    if isinstance(rows, dict):
        rows = rows.get("holdings", [])
    try:
        holdings = [
            {"ticker": str(r["ticker"]).strip().upper(), "shares": float(r["shares"]), "cost_basis": float(r["cost_basis"])}
            for r in rows
        ]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"each holding needs ticker, shares and cost_basis ({e!r})") from e
    if not holdings or len(holdings) > MAX_HOLDINGS:
        raise ValueError(f"portfolio needs 1-{MAX_HOLDINGS} holdings")
    return holdings


async def build_brief(holdings: list[dict], persona: str, use_plaid: bool) -> tuple[str, str]:
    """Merge the three sources into a stored brief; returns (brief_id, one-line summary)."""
    tickers = [h["ticker"] for h in holdings]
    last = await market.prices(tickers, {h["ticker"]: h["cost_basis"] for h in holdings})
    value = sum(h["shares"] * last[h["ticker"]] for h in holdings)
    cost = sum(h["shares"] * h["cost_basis"] for h in holdings)
    pnl = (value - cost) / cost * 100 if cost else 0.0
    bank = await plaid.sandbox_balances() if use_plaid else None
    parts = [f"${value:,.0f} in {', '.join(tickers)}, {pnl:+.0f}%"]
    if bank:
        parts.append(f"${bank['cash']:,.0f} cash")
    profile = next((ln.strip() for ln in persona.splitlines() if ln.strip() and not ln.startswith("#")), "")
    if profile:
        parts.append(profile[:80])
    summary = "; ".join(parts)
    brief_id = uuid.uuid4().hex
    put(BRIEFS, brief_id, {
        "holdings": holdings, "prices": last, "value": value, "pnl_pct": pnl, "bank": bank,
        "persona": persona, "summary": summary,
    })
    return brief_id, summary
