import csv
import io
import json
import re
import uuid

from app.services import market, plaid

BRIEFS: dict[str, dict] = {}  # shortcut: in-memory, lost on restart; move to D1 with the Cloudflare port
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


def facts(holdings: list[dict], prices: dict[str, float], broker_cash: float, net_worth: float | None) -> dict:
    """Pre-computed portfolio facts so agents never do arithmetic."""
    rows = []
    for h in holdings:
        px = prices[h["ticker"]]
        rows.append({**h, "price": px, "value": h["shares"] * px, "cost": h["shares"] * h["cost_basis"]})
    value = sum(r["value"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    for r in rows:
        r["weight_pct"] = round(r["value"] / value * 100, 1) if value else 0.0
        r["pnl_pct"] = round((r["value"] - r["cost"]) / r["cost"] * 100, 1) if r["cost"] else 0.0
        r["value"], r["cost"] = round(r["value"], 2), round(r["cost"], 2)
    rows.sort(key=lambda r: -r["value"])
    sectors: dict[str, float] = {}
    for r in rows:
        sectors[r.get("sector", "Unknown")] = sectors.get(r.get("sector", "Unknown"), 0) + r["weight_pct"]
    out = {
        "positions": rows,
        "holdings_value": round(value, 2),
        "cost_basis": round(cost, 2),
        "unrealized_pl": round(value - cost, 2),
        "unrealized_pl_pct": round((value - cost) / cost * 100, 1) if cost else 0.0,
        "top5": [f"{r['ticker']} {r['weight_pct']}%" for r in rows[:5]],
        "sector_mix_pct": {k: round(v, 1) for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])},
        "winners": sum(r["pnl_pct"] > 0 for r in rows),
        "losers": sum(r["pnl_pct"] < 0 for r in rows),
        "best": rows and max(rows, key=lambda r: r["pnl_pct"])["ticker"],
        "worst": rows and min(rows, key=lambda r: r["pnl_pct"])["ticker"],
    }
    weighted = lambda k: sum(r[k] * r["value"] for r in rows) / value  # noqa: E731  exact weights, not rounded ones
    if value and all("beta" in r for r in rows):
        out["portfolio_beta"] = round(weighted("beta"), 2)
    if value and all("div_yield" in r for r in rows):
        out["est_yield_pct"] = round(weighted("div_yield"), 2)
    if broker_cash:
        out["broker_cash"] = round(broker_cash, 2)
        out["broker_equity"] = round(value + broker_cash, 2)
        out["broker_cash_pct"] = round(broker_cash / (value + broker_cash) * 100, 1)
    if net_worth:
        out["net_worth"] = net_worth
        out["brokerage_pct_of_net_worth"] = round((value + broker_cash) / net_worth * 100, 1)
    return out


async def build_brief(holdings: list[dict], persona: str, use_plaid: bool, account: dict | None = None) -> tuple[str, str]:
    """Merge the sources into a stored brief; returns (brief_id, one-line summary)."""
    tickers = [h["ticker"] for h in holdings]
    last = await market.prices(tickers, {h["ticker"]: h.get("price", h["cost_basis"]) for h in holdings})
    last.update({h["ticker"]: h["price"] for h in holdings if "price" in h})  # a broker snapshot's own price wins
    broker_cash = float((account or {}).get("cash") or 0)
    f = facts(holdings, last, broker_cash, _money(persona, r"Net Worth"))
    bank = await plaid.sandbox_balances() if use_plaid else None
    shown = ", ".join(tickers[:4]) + (f" +{len(tickers) - 4} more" if len(tickers) > 4 else "")
    parts = [f"${f['holdings_value']:,.0f} in {shown}, {f['unrealized_pl_pct']:+.0f}%"]
    cash = broker_cash + (bank["cash"] if bank else 0)
    if cash:
        parts.append(f"${cash:,.0f} cash")
    if profile := profile_line(persona):
        parts.append(profile)
    summary = "; ".join(parts)
    brief_id = uuid.uuid4().hex
    BRIEFS[brief_id] = {
        "holdings": holdings, "prices": last, "value": f["holdings_value"], "pnl_pct": f["unrealized_pl_pct"], "bank": bank,
        "account": account, "facts": f, "persona": persona, "summary": summary,
    }
    return brief_id, summary
