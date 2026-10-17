"""Position analysis: enrichment, concentration, exposures, risk flags.

Pure functions over the broker's position dicts. No I/O, no opinions -- this
module only measures. Interpretation lives in styles.py.
"""

from datetime import datetime, timezone

import reference

CAP_LABEL = {"mega": "Mega cap", "large": "Large cap", "small": "Small cap",
             "etf": "ETF", "unknown": "Unknown"}


def _days_held(opened_at):
    if not opened_at:
        return None
    try:
        dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


def _role(weight, info, pnl_pct):
    """Crude 'what job does this hold do' bucket, used by the style lenses."""
    if info["cap"] == "etf":
        return "core"
    if info["style"] == "spec" or not info["profitable"]:
        return "speculative"
    if weight >= 8.0 and info["cap"] == "mega":
        return "core"
    return "satellite"


def enrich(positions):
    """Attach reference data, weights, P&L and holding period to each position."""
    total_mv = sum(abs(p["market_value"]) for p in positions) or 1.0
    rows = []
    for p in positions:
        info = reference.info(p["symbol"])
        weight = abs(p["market_value"]) / total_mv * 100.0
        pnl_pct = p["unrealized_plpc"] * 100.0
        hi = info["wk52_high"]
        rows.append(dict(
            p,
            name=info["name"], sector=info["sector"], beta=info["beta"],
            div_yield=info["div_yield"], cap=info["cap"],
            cap_label=CAP_LABEL.get(info["cap"], info["cap"]),
            style=info["style"], profitable=info["profitable"],
            fcf_positive=info["fcf_positive"],
            wk52_high=hi, wk52_low=info["wk52_low"],
            weight=round(weight, 2), pnl_pct=round(pnl_pct, 2),
            days_held=_days_held(p.get("opened_at")),
            annual_income=round(p["market_value"] * info["div_yield"] / 100.0, 2),
            pct_off_high=(round((p["current_price"] / hi - 1) * 100.0, 1)
                          if hi else None),
            role=_role(weight, info, pnl_pct),
        ))
    rows.sort(key=lambda r: r["market_value"], reverse=True)
    return rows


def summary(account, rows):
    mv = sum(r["market_value"] for r in rows)
    cost = sum(r["cost_basis"] for r in rows)
    income = sum(r["annual_income"] for r in rows)
    invested = mv / account["equity"] * 100.0 if account["equity"] else 0.0
    winners = [r for r in rows if r["unrealized_pl"] > 0]
    losers = [r for r in rows if r["unrealized_pl"] < 0]
    return dict(
        equity=round(account["equity"], 2), cash=round(account["cash"], 2),
        market_value=round(mv, 2), cost_basis=round(cost, 2),
        unrealized_pl=round(mv - cost, 2),
        unrealized_pl_pct=round((mv / cost - 1) * 100.0, 2) if cost else 0.0,
        cash_pct=round(100.0 - invested, 2), invested_pct=round(invested, 2),
        position_count=len(rows),
        portfolio_beta=round(sum(r["weight"] / 100.0 * r["beta"] for r in rows), 2),
        est_annual_income=round(income, 2),
        est_yield=round(income / mv * 100.0, 2) if mv else 0.0,
        winners=len(winners), losers=len(losers),
        best=max(rows, key=lambda r: r["pnl_pct"])["symbol"] if rows else None,
        worst=min(rows, key=lambda r: r["pnl_pct"])["symbol"] if rows else None,
        largest_drag=round(min([r["unrealized_pl"] for r in rows] or [0]), 2),
    )


def concentration(rows):
    ws = sorted((r["weight"] for r in rows), reverse=True)
    hhi = sum((w / 100.0) ** 2 for w in ws)
    return dict(
        top1=round(ws[0], 2) if ws else 0.0,
        top3=round(sum(ws[:3]), 2), top5=round(sum(ws[:5]), 2),
        hhi=round(hhi, 4),
        effective_positions=round(1 / hhi, 1) if hhi else 0.0,
        names=[dict(symbol=r["symbol"], weight=r["weight"]) for r in rows[:5]],
    )


def sector_exposure(rows):
    buckets = {}
    for r in rows:
        buckets[r["sector"]] = buckets.get(r["sector"], 0.0) + r["weight"]
    out = []
    for sector, w in sorted(buckets.items(), key=lambda kv: -kv[1]):
        bench = reference.BENCHMARK_SECTOR_WEIGHTS.get(sector)
        out.append(dict(sector=sector, weight=round(w, 2), benchmark=bench,
                        delta=round(w - bench, 2) if bench is not None else None))
    return out


def factor_tilts(rows):
    def share(pred):
        return round(sum(r["weight"] for r in rows if pred(r)), 2)
    return dict(
        growth=share(lambda r: r["style"] == "growth"),
        value=share(lambda r: r["style"] == "value"),
        blend=share(lambda r: r["style"] == "blend"),
        speculative=share(lambda r: r["style"] == "spec"),
        etf=share(lambda r: r["cap"] == "etf"),
        single_name=share(lambda r: r["cap"] != "etf"),
        unprofitable=share(lambda r: not r["profitable"]),
        high_beta=share(lambda r: r["beta"] >= 1.5),
        low_beta=share(lambda r: r["beta"] <= 0.8),
        core=share(lambda r: r["role"] == "core"),
        satellite=share(lambda r: r["role"] == "satellite"),
        speculative_role=share(lambda r: r["role"] == "speculative"),
        short_term=share(lambda r: (r["days_held"] or 999) < 90),
        long_term=share(lambda r: (r["days_held"] or 0) >= 365),
    )


def risk_flags(summ, conc, sectors, tilts, rows):
    """Threshold checks. Each flag is an observation, not a recommendation."""
    flags = []

    def add(level, title, detail):
        flags.append(dict(level=level, title=title, detail=detail))

    if conc["top1"] >= 15:
        top = rows[0]
        add("high", f"Single-name concentration: {top['symbol']} is {conc['top1']}%",
            f"One position drives a large share of outcomes. A 20% move in "
            f"{top['symbol']} alone swings the book about "
            f"{conc['top1'] * 0.20:.1f}%.")
    if conc["top3"] >= 45:
        add("medium", f"Top 3 holdings are {conc['top3']}% of the book",
            f"Effective diversification is about {conc['effective_positions']} "
            f"independent positions despite holding {summ['position_count']} tickers.")
    hot = [s for s in sectors if s["delta"] is not None and s["delta"] >= 15]
    for s in hot:
        add("high" if s["delta"] >= 25 else "medium",
            f"{s['sector']} overweight: {s['weight']}% vs {s['benchmark']}% benchmark",
            f"+{s['delta']} points versus a broad-market weighting. Sector-wide "
            f"news moves most of the portfolio at once.")
    if summ["portfolio_beta"] >= 1.3:
        add("medium", f"Portfolio beta {summ['portfolio_beta']}",
            f"Historically this book would move roughly "
            f"{summ['portfolio_beta']:.2f}x the index in both directions.")
    if tilts["unprofitable"] >= 5:
        add("medium", f"{tilts['unprofitable']}% in currently unprofitable companies",
            "These names tend to be the most rate- and sentiment-sensitive part "
            "of a portfolio.")
    deep = [r for r in rows if r["pnl_pct"] <= -25]
    for r in deep:
        add("medium", f"{r['symbol']} is {r['pnl_pct']}% below average entry",
            f"Unrealized loss of ${abs(r['unrealized_pl']):,.0f} on a "
            f"{r['weight']}% position, held {r['days_held'] or '?'} days.")
    if summ["cash_pct"] <= 7:
        add("low", f"Cash is {summ['cash_pct']}% of equity",
            "Little dry powder for adding to positions or covering a margin event.")
    if tilts["speculative_role"] >= 10:
        add("medium", f"{tilts['speculative_role']}% in speculative holdings",
            "Position sizing here usually matters more than the thesis.")
    order = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: order[f["level"]])
    return flags


def analyze(account, positions):
    rows = enrich(positions)
    summ = summary(account, rows)
    conc = concentration(rows)
    sectors = sector_exposure(rows)
    tilts = factor_tilts(rows)
    return dict(
        summary=summ, concentration=conc, sectors=sectors, tilts=tilts,
        flags=risk_flags(summ, conc, sectors, tilts, rows), positions=rows,
    )
