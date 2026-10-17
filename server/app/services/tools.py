"""The tools in agents/skill.md: what each worker may call, and the dispatcher that runs them."""
import csv
import json
import logging

from app.config import DATA_DIR
from app.services import anchor

log = logging.getLogger(__name__)

POSITION_FIELDS = (
    "name", "sector", "weight", "pnl_pct", "current_price", "market_value", "beta", "div_yield",
    "wk52_high", "wk52_low", "pct_off_high", "style", "cap_label", "role", "days_held",
)


def _spec(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []},
    }}


SPECS = {
    "portfolio_lookup": _spec(
        "portfolio_lookup", "The client's holdings with weights, P&L, beta, yield and 52-week range, plus the account summary.",
        {"ticker": {"type": "string", "description": "One symbol; omit for the whole portfolio."}},
    ),
    "persona_profile": _spec("persona_profile", "The client's own profile: age, goals, horizon, risk tolerance, where the money is held.", {}),
    "specialist_row": _spec(
        "specialist_row", "A council member's specialist-sheet row: style, philosophy, what they would flag.",
        {"persona": {"type": "string", "description": "Member name, e.g. 'Michael Burry'; omit for your own row."}},
    ),
    "web_search": _spec(
        "web_search", "Live web search; returns titles, URLs and verbatim quotes you may cite.",
        {"query": {"type": "string", "description": "Ticker plus topic works best."}}, ["query"],
    ),
}


def specs() -> list[dict]:
    """web_search is offered only when Anchor is configured."""
    return [s for name, s in SPECS.items() if name != "web_search" or anchor.enabled()]


def _snapshot() -> dict:
    try:
        return json.loads((DATA_DIR / "portfolio.json").read_text())
    except (OSError, ValueError):
        return {}


def _portfolio(brief: dict, ticker: str | None = None) -> dict:
    positions = {p["symbol"]: p for p in _snapshot().get("positions", [])}
    holdings = []
    for h in brief["holdings"]:
        if ticker and h["ticker"] != ticker.upper():
            continue
        extra = {k: v for k, v in positions.get(h["ticker"], {}).items() if k in POSITION_FIELDS}
        holdings.append({"ticker": h["ticker"], "shares": h["shares"], "cost_basis": h["cost_basis"], **extra})
    if ticker and not holdings:
        return {"error": f"{ticker.upper()} is not in the client's portfolio"}
    return {"summary": brief["summary"], "account": _snapshot().get("summary", {}), "bank": brief.get("bank"), "holdings": holdings}


def _profile(brief: dict) -> dict:
    text = brief.get("persona") or ""
    if not text.strip() and (DATA_DIR / "PERSONA.md").exists():
        text = (DATA_DIR / "PERSONA.md").read_text()
    return {"profile": text[:6000]}


def _specialist(persona, who: str | None) -> dict:
    try:
        rows = list(csv.DictReader((DATA_DIR / "specialist.csv").open(newline="")))
    except OSError:
        return {"error": "specialist sheet not found"}
    want = (who or persona.specialist).lower()
    row = next((r for r in rows if r["Persona"].lower() == want or want in r["Persona"].lower()), None)
    return row or {"error": f"no row for {who!r}", "available": [r["Persona"] for r in rows]}


async def call(name: str, args: dict, brief: dict, persona) -> dict:
    """Run one tool for a worker; failures come back as {"error": ...} so the model can recover."""
    try:
        if name == "portfolio_lookup":
            return _portfolio(brief, args.get("ticker"))
        if name == "persona_profile":
            return _profile(brief)
        if name == "specialist_row":
            return _specialist(persona, args.get("persona"))
        if name == "web_search" and anchor.enabled():
            return {"results": [s.model_dump() for s in await anchor.search(str(args["query"]))]}
        return {"error": f"unknown tool {name!r}"}
    except Exception as e:  # a failed tool must not kill the worker
        log.warning("tool %s failed: %s", name, e)
        return {"error": f"{name} failed: {e}"}
