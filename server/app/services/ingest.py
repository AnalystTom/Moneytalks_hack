import csv
import io
import json
import uuid

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
    if not holdings:
        raise ValueError("portfolio has no holdings")
    return holdings


async def build_brief(holdings: list[dict], persona: str, use_plaid: bool) -> tuple[str, str]:
    """Store submitted holdings and profile; returns (brief_id, one-line summary)."""
    tickers = [h["ticker"] for h in holdings]
    parts = [f"Holdings: {', '.join(tickers)}", "Market value and returns unavailable"]
    if use_plaid:
        parts.append("Bank balances unavailable")
    profile = next((ln.strip() for ln in persona.splitlines() if ln.strip() and not ln.startswith("#")), "")
    if profile:
        parts.append(profile[:80])
    summary = "; ".join(parts)
    brief_id = uuid.uuid4().hex
    BRIEFS[brief_id] = {
        "holdings": holdings, "prices": None, "value": None, "pnl_pct": None, "bank": None,
        "persona": persona, "summary": summary,
    }
    return brief_id, summary
