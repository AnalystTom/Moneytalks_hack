import csv
import io
import json
import re
import uuid

from app.services import market, plaid, store

BRIEFS: dict[str, dict] = {}  # cache in front of the durable store
EXTRA = ("name", "sector", "beta", "div_yield", "role")  # optional broker-snapshot fields kept per holding


def _broker_holding(p: dict) -> dict:
    """One position from a broker snapshot ({"positions": [...]}, e.g. data/portfolio.json)."""
    h = {"ticker": str(p["symbol"]).strip().upper(), "shares": float(p["qty"]), "cost_basis": float(p["avg_entry_price"])}
    if p.get("current_price") is not None:
        h["price"] = float(p["current_price"])
    h.update({k: p[k] for k in EXTRA if p.get(k) is not None})
    return h


def parse_portfolio(filename: str, raw: bytes) -> tuple[list[dict], dict | None]:
    """(holdings, broker account) from CSV (ticker,shares,cost_basis), a JSON list or {"holdings": [...]},
    or a broker snapshot {"account": {...}, "positions": [...]}; cost_basis is per share."""
    text = raw.decode("utf-8-sig")
    rows = json.loads(text) if filename.lower().endswith(".json") else list(csv.DictReader(io.StringIO(text)))
    account = None
    try:
        if isinstance(rows, dict) and "positions" in rows:
            account = rows.get("account") if isinstance(rows.get("account"), dict) else None
            holdings = [_broker_holding(p) for p in rows["positions"]]
        else:
            if isinstance(rows, dict):
                rows = rows.get("holdings", [])
            holdings = [
                {"ticker": str(r["ticker"]).strip().upper(), "shares": float(r["shares"]), "cost_basis": float(r["cost_basis"])}
                for r in rows
            ]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"each holding needs ticker, shares and cost_basis ({e!r})") from e
    if not holdings:
        raise ValueError("portfolio has no holdings")
    return holdings, account


def parse_holdings(filename: str, raw: bytes) -> list[dict]:
    return parse_portfolio(filename, raw)[0]


def _money(text: str, label: str) -> float | None:
    m = re.search(label + r"[^$\n]*\$\s*([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    return float(m.group(1).replace(",", "")) if m else None


def profile_line(persona: str) -> str:
    """Short profile for the summary: "Name, 38" from a persona table, else the first plain line."""
    name = re.search(r"\*\*Name\*\*\s*\|\s*([^|\n]+)", persona)
    age = re.search(r"\*\*Age\*\*\s*\|\s*(\d+)", persona)
    if name:
        return name.group(1).strip() + (f", {age.group(1)}" if age else "")
    plain = (ln.strip() for ln in persona.splitlines())
    return next((ln for ln in plain if ln and not ln.startswith(("#", "|", "-", "_"))), "")[:80]


def facts(holdings: list[dict], prices: dict[str, float], broker_cash: float | None, net_worth: float | None) -> dict:
    """Pre-computed portfolio facts so agents never do arithmetic."""
    rows = []
    for h in holdings:
        px = prices.get(h["ticker"])
        shares, basis = h.get("shares"), h.get("cost_basis")
        value = h.get("amount")
        if value is None and shares is not None and px is not None:
            value = shares * px
        cost = shares * basis if shares is not None and basis is not None else None
        rows.append({**h, "price": px, "value": value, "cost": cost})
    value = sum(r["value"] for r in rows) if rows and all(r["value"] is not None for r in rows) else None
    cost = sum(r["cost"] for r in rows) if rows and all(r["cost"] is not None for r in rows) else None
    for r in rows:
        r["weight_pct"] = round(r["value"] / value * 100, 1) if value else (0.0 if value == 0 else None)
        r["pnl_pct"] = round((r["value"] - r["cost"]) / r["cost"] * 100, 1) if r["value"] is not None and r["cost"] else None
        for key in ("value", "cost"):
            if r[key] is not None:
                r[key] = round(r[key], 2)
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    sectors: dict[str, float] = {}
    for r in rows:
        if r["weight_pct"] is not None:
            sectors[r.get("sector", "Unknown")] = sectors.get(r.get("sector", "Unknown"), 0) + r["weight_pct"]
    complete_pnl = bool(rows) and all(r["pnl_pct"] is not None for r in rows)
    out = {
        "positions": rows,
        "holdings_value": round(value, 2) if value is not None else None,
        "cost_basis": round(cost, 2) if cost is not None else None,
        "unrealized_pl": round(value - cost, 2) if value is not None and cost is not None else None,
        "unrealized_pl_pct": round((value - cost) / cost * 100, 1) if value is not None and cost else None,
        "top5": [f"{r['ticker']} {r['weight_pct']}%" if r["weight_pct"] is not None else f"{r['ticker']} (weight unavailable)" for r in rows[:5]],
        "sector_mix_pct": {k: round(v, 1) for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])},
        "winners": sum(r["pnl_pct"] > 0 for r in rows) if complete_pnl else None,
        "losers": sum(r["pnl_pct"] < 0 for r in rows) if complete_pnl else None,
        "best": max(rows, key=lambda r: r["pnl_pct"])["ticker"] if rows and complete_pnl else None,
        "worst": min(rows, key=lambda r: r["pnl_pct"])["ticker"] if rows and complete_pnl else None,
        "broker_cash": round(broker_cash, 2) if broker_cash is not None else None,
    }
    weighted = lambda k: sum(r[k] * r["value"] for r in rows) / value  # noqa: E731  exact weights, not rounded ones
    if value and all("beta" in r for r in rows):
        out["portfolio_beta"] = round(weighted("beta"), 2)
    if value and all("div_yield" in r for r in rows):
        out["est_yield_pct"] = round(weighted("div_yield"), 2)
    if broker_cash is not None and value is not None:
        out["broker_equity"] = round(value + broker_cash, 2)
        if value + broker_cash:
            out["broker_cash_pct"] = round(broker_cash / (value + broker_cash) * 100, 1)
    if net_worth is not None:
        out["net_worth"] = net_worth
        if net_worth and value is not None and broker_cash is not None:
            out["brokerage_pct_of_net_worth"] = round((value + broker_cash) / net_worth * 100, 1)
    return out


async def build_brief(holdings: list[dict], persona: str, use_plaid: bool, account: dict | None = None, note: str = "",
                      *, prices: dict[str, float] | None = None, net_worth: float | None = None) -> tuple[str, str]:
    """Merge the sources into a stored brief; returns (brief_id, one-line summary)."""
    tickers = [h["ticker"] for h in holdings]
    last = prices if prices is not None else await market.prices(tickers, {h["ticker"]: h.get("price", h["cost_basis"]) for h in holdings})
    last.update({h["ticker"]: h["price"] for h in holdings if h.get("price") is not None})
    broker_cash = (account or {}).get("cash")
    if broker_cash is not None:
        broker_cash = float(broker_cash)
    f = facts(holdings, last, broker_cash, net_worth)
    bank = await plaid.sandbox_balances() if use_plaid else None
    shown = ", ".join(tickers[:4]) + (f" +{len(tickers) - 4} more" if len(tickers) > 4 else "")
    valuation = "No holdings provided" if not holdings else f"${f['holdings_value']:,.0f} in {shown}" if f["holdings_value"] is not None else f"{shown}: total valuation unavailable"
    profit = f"{f['unrealized_pl_pct']:+.0f}%" if f["unrealized_pl_pct"] is not None else "profit/loss unavailable"
    parts = [f"{valuation}, {profit}"]
    if broker_cash is not None:
        cash = broker_cash + (bank["cash"] if bank else 0)
        parts.append(f"${cash:,.0f} cash")
    elif bank:
        parts.append(f"${bank['cash']:,.0f} bank cash")
    if profile := profile_line(persona):
        parts.append(profile)
    if note:
        parts.append(note)
    summary = "; ".join(parts)
    brief_id = uuid.uuid4().hex
    brief = BRIEFS[brief_id] = {
        "holdings": holdings, "prices": last, "value": f["holdings_value"], "pnl_pct": f["unrealized_pl_pct"], "bank": bank,
        "account": account, "facts": f, "persona": persona, "summary": summary,
    }
    await store.save("brief", brief_id, brief)
    return brief_id, summary


async def get_brief(brief_id: str) -> dict | None:
    if brief_id not in BRIEFS and (brief := await store.load("brief", brief_id)):
        BRIEFS[brief_id] = brief
    return BRIEFS.get(brief_id)
