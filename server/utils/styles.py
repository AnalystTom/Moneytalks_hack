"""Trading-style lenses.

Each lens reads the SAME measured portfolio and reports where the book agrees
or disagrees with the textbook principles of that style. Output is general
education about a trading approach -- not personalised investment advice, not a
buy/sell call, and not a prediction. Every string is derived from the numbers
in analysis.py so the demo is explainable rather than hand-wavy.
"""

DISCLAIMER = ("General educational commentary on how different trading "
              "philosophies read a portfolio's structure. Not investment "
              "advice, not a recommendation to buy or sell any security, and "
              "based on synthetic demo data.")


def _o(verdict, text):
    """verdict: aligned | tension | note"""
    return dict(verdict=verdict, text=text)


def _score(parts):
    """parts: list of (weight, 0..1 satisfaction). Returns 0-100."""
    tw = sum(w for w, _ in parts) or 1.0
    return int(round(sum(w * s for w, s in parts) / tw * 100))


def _clamp01(x):
    return max(0.0, min(1.0, x))


# --- lenses ---------------------------------------------------------------

def passive_index(a):
    s, c, t = a["summary"], a["concentration"], a["tilts"]
    obs = [
        _o("aligned" if t["etf"] >= 40 else "tension",
           f"Index exposure is {t['etf']}% of holdings. A passive allocation is "
           f"usually built the other way round: broad funds as the base, single "
           f"names as the exception."),
        _o("tension" if c["top1"] >= 10 else "aligned",
           f"Largest single position is {c['top1']}%. Pure indexing has no "
           f"single-name bet larger than its weight in the index itself "
           f"(well under 10% for almost everything)."),
        _o("tension" if t["single_name"] >= 60 else "note",
           f"{t['single_name']}% sits in individual stocks, so most of the "
           f"return comes from stock selection rather than market exposure. "
           f"That is the opposite of the passive premise."),
        _o("note",
           f"Effective diversification is about {c['effective_positions']} "
           f"independent positions. A total-market fund is in the thousands."),
        _o("aligned" if abs(s["portfolio_beta"] - 1.0) < 0.2 else "tension",
           f"Portfolio beta {s['portfolio_beta']} vs 1.0 for the market. "
           f"Passive investors generally accept market risk, not a multiple of it."),
    ]
    return _score([
        (3, _clamp01(t["etf"] / 60.0)),
        (3, _clamp01(1 - (c["top1"] - 8) / 20.0)),
        (2, _clamp01(1 - abs(s["portfolio_beta"] - 1.0) / 0.8)),
        (2, _clamp01(c["effective_positions"] / 25.0)),
    ]), obs


def long_term_growth(a):
    s, t, rows = a["summary"], a["tilts"], a["positions"]
    hi_conv = [r for r in rows if r["weight"] >= 10 and r["style"] == "growth"]
    long_held = t["long_term"]
    obs = [
        _o("aligned" if t["growth"] >= 40 else "note",
           f"{t['growth']}% in growth-classified names. Concentration in a few "
           f"compounders is a feature of this style, not a bug -- the usual "
           f"discipline is that conviction must be matched by holding period."),
        _o("aligned" if long_held >= 50 else "tension",
           f"{long_held}% of the book has been held a year or more and "
           f"{t['short_term']}% under 90 days. Growth investing earns its edge "
           f"from time in position; frequent turnover tends to cancel it."),
        _o("note",
           f"Unrealized gain of {s['unrealized_pl_pct']}% overall, with "
           f"{s['winners']} winners against {s['losers']} losers. The classic "
           f"trap in this style is trimming winners early while holding losers "
           f"for the round trip."),
        _o("tension" if t["unprofitable"] >= 5 else "aligned",
           f"{t['unprofitable']}% in companies not yet profitable. Growth and "
           f"speculation look similar in a bull market and very different in a "
           f"drawdown; practitioners usually cap this sleeve explicitly."),
        _o("note",
           f"{len(hi_conv)} position(s) are both >10% weight and growth-classified"
           + (": " + ", ".join(r["symbol"] for r in hi_conv) if hi_conv else "") +
           ". High conviction and high correlation often arrive together."),
    ]
    return _score([
        (3, _clamp01(t["growth"] / 55.0)),
        (3, _clamp01(long_held / 70.0)),
        (2, _clamp01(1 - t["short_term"] / 40.0)),
        (1, _clamp01(1 - t["unprofitable"] / 20.0)),
    ]), obs


def value_dividend(a):
    s, t, sectors = a["summary"], a["tilts"], a["sectors"]
    defensives = sum(x["weight"] for x in sectors if x["sector"] in
                     ("Consumer Staples", "Healthcare", "Utilities", "Energy",
                      "Dividend ETF"))
    obs = [
        _o("tension" if s["est_yield"] < 2.0 else "aligned",
           f"Estimated portfolio yield is {s['est_yield']}% "
           f"(~${s['est_annual_income']:,.0f}/yr). An income-oriented book "
           f"typically targets a multiple of the market's yield, and here most "
           f"holdings pay little or nothing."),
        _o("tension" if t["value"] < 30 else "aligned",
           f"Only {t['value']}% is in value-classified names versus "
           f"{t['growth']}% growth. On the value lens, that is a bet on "
           f"multiple expansion rather than on cash returns."),
        _o("note",
           f"Defensive sectors (staples, healthcare, utilities, energy, dividend "
           f"funds) total {defensives:.1f}%. This is the sleeve that usually "
           f"cushions a drawdown and funds reinvestment at lower prices."),
        _o("tension" if t["unprofitable"] >= 5 else "aligned",
           f"{t['unprofitable']}% has no current earnings, so there is no "
           f"earnings yield to anchor a valuation on for that slice."),
        _o("note",
           f"Portfolio beta {s['portfolio_beta']}. Value and income portfolios "
           f"usually sit below 1.0, which is where their lower-drawdown "
           f"reputation comes from."),
    ]
    return _score([
        (3, _clamp01(s["est_yield"] / 3.0)),
        (3, _clamp01(t["value"] / 45.0)),
        (2, _clamp01(defensives / 35.0)),
        (2, _clamp01((1.2 - s["portfolio_beta"]) / 0.5)),
    ]), obs


def swing_momentum(a):
    s, t, rows = a["summary"], a["tilts"], a["positions"]
    near_high = [r for r in rows if r["pct_off_high"] is not None
                 and r["pct_off_high"] > -10]
    broken = [r for r in rows if r["pct_off_high"] is not None
              and r["pct_off_high"] < -35]
    broken_txt = ", ".join("{} ({}%)".format(r["symbol"], r["pct_off_high"])
                           for r in broken)
    obs = [
        _o("aligned" if t["high_beta"] >= 40 else "note",
           f"{t['high_beta']}% of the book is in beta >= 1.5 names, which is the "
           f"raw material momentum traders look for -- enough range to make a "
           f"multi-week move worth taking."),
        _o("aligned" if near_high else "tension",
           f"{len(near_high)} position(s) within 10% of their 52-week high"
           + (": " + ", ".join(r["symbol"] for r in near_high) if near_high else "") +
           ". Momentum rules generally keep capital in this group."),
        _o("tension" if broken else "aligned",
           f"{len(broken)} position(s) are more than 35% off their highs"
           + (": " + broken_txt if broken else "") +
           ". A trend-following rulebook would have exited these at a predefined "
           f"stop rather than holding through."),
        _o("tension",
           f"Average holding period skews long: {t['long_term']}% held over a "
           f"year, {t['short_term']}% under 90 days. Swing trading implies the "
           f"inverse distribution."),
        _o("note",
           f"Cash is {s['cash_pct']}% of equity. Active styles depend on dry "
           f"powder to act on setups; a fully invested book has to sell "
           f"something first."),
    ]
    return _score([
        (3, _clamp01(t["short_term"] / 60.0)),
        (2, _clamp01(t["high_beta"] / 50.0)),
        (2, _clamp01(len(near_high) / max(1, len(rows)) * 2.5)),
        (2, _clamp01(1 - len(broken) / max(1, len(rows)) * 3)),
        (1, _clamp01(s["cash_pct"] / 20.0)),
    ]), obs


def day_trading(a):
    s, t, rows = a["summary"], a["tilts"], a["positions"]
    liquid = [r for r in rows if r["cap"] in ("mega", "etf")]
    obs = [
        _o("tension",
           f"This account holds {s['position_count']} overnight positions worth "
           f"${s['market_value']:,.0f}. Day trading as a discipline is defined by "
           f"flat-at-the-close; every one of these carries gap risk the strategy "
           f"is designed to avoid."),
        _o("note",
           f"Cash is {s['cash_pct']}% of equity. Intraday strategies need most of "
           f"the account available as margin, not tied up in held stock."),
        _o("aligned" if len(liquid) >= 4 else "note",
           f"{len(liquid)} holdings are mega-cap or ETF, i.e. the liquid, "
           f"tight-spread instruments intraday traders actually use. The small "
           f"caps in the book would be harder to size into and out of quickly."),
        _o("note",
           "US pattern-day-trader rules require $25,000 minimum equity to place "
           "4+ day trades in 5 business days in a margin account. This is a "
           "mechanical constraint, not a strategy question."),
        _o("note",
           f"Portfolio beta {s['portfolio_beta']} is irrelevant to an intraday "
           f"book but dominant for this one -- a sign the account is positioned "
           f"as an investor's, not a trader's."),
    ]
    return _score([
        (4, _clamp01(s["cash_pct"] / 50.0)),
        (3, _clamp01(t["short_term"] / 80.0)),
        (2, _clamp01(len(liquid) / max(1, len(rows)))),
    ]), obs


def balanced_risk(a):
    s, c, t, sectors = a["summary"], a["concentration"], a["tilts"], a["sectors"]
    worst = sectors[0]
    obs = [
        _o("tension" if c["top1"] >= 12 else "aligned",
           f"Top position {c['names'][0]['symbol']} at {c['top1']}% and top three "
           f"at {c['top3']}%. Risk-budgeting frameworks generally cap a single "
           f"name near 5-10% so no one holding can dictate the result."),
        _o("tension" if worst["delta"] and worst["delta"] > 15 else "aligned",
           f"{worst['sector']} is {worst['weight']}% of holdings against a "
           f"{worst['benchmark']}% benchmark weight. Correlated positions inside "
           f"one sector behave like a single larger position during stress."),
        _o("note",
           f"{t['low_beta']}% of the book is in low-beta (<=0.8) names and "
           f"{t['high_beta']}% in high-beta (>=1.5). The barbell shape means "
           f"realised volatility will be driven almost entirely by the second group."),
        _o("note",
           f"No bond, gold, or cash-equivalent sleeve beyond {s['cash_pct']}% "
           f"cash. A balanced mandate usually holds an asset that is expected to "
           f"behave differently from equities, which nothing here does."),
        _o("note",
           f"Rough stress sketch: a 20% equity drawdown applied at beta "
           f"{s['portfolio_beta']} implies roughly "
           f"${s['market_value'] * 0.20 * s['portfolio_beta']:,.0f} of mark-to-market "
           f"movement. Illustrative arithmetic, not a forecast."),
    ]
    return _score([
        (3, _clamp01(1 - (c["top1"] - 6) / 16.0)),
        (3, _clamp01(1 - (worst["delta"] or 0) / 30.0)),
        (2, _clamp01(1 - abs(s["portfolio_beta"] - 1.0) / 0.6)),
        (2, _clamp01(c["effective_positions"] / 20.0)),
    ]), obs


STYLES = [
    dict(id="passive-index", name="Passive Indexer", horizon="Decades",
         tagline="Own the market, minimise cost and decisions.",
         principles=["Broad funds as the core, not the exception",
                     "No single-name bet large enough to matter",
                     "Rebalance on a calendar, not on news",
                     "Accept market risk; do not multiply it"],
         fn=passive_index),
    dict(id="long-term-growth", name="Long-Term Growth", horizon="3-10 years",
         tagline="Concentrate in compounders and hold through volatility.",
         principles=["Conviction must be matched by holding period",
                     "Let winners run; size the losers small",
                     "Separate 'growth' from 'speculation' explicitly",
                     "Revenue durability over near-term multiple"],
         fn=long_term_growth),
    dict(id="value-dividend", name="Value & Dividend Income", horizon="5+ years",
         tagline="Buy cash-generating businesses below intrinsic value.",
         principles=["Pay for earnings and cash flow, not narrative",
                     "Income cushions drawdowns and funds reinvestment",
                     "Prefer sub-1.0 beta and defensive sectors",
                     "Margin of safety over growth rate"],
         fn=value_dividend),
    dict(id="swing-momentum", name="Swing / Momentum Trader",
         horizon="Days to weeks",
         tagline="Ride established trends, cut broken ones mechanically.",
         principles=["Hold strength, exit weakness at a predefined stop",
                     "Range and liquidity matter more than valuation",
                     "Keep cash available to act on setups",
                     "The exit rule is the strategy"],
         fn=swing_momentum),
    dict(id="day-trading", name="Active Day Trader", horizon="Minutes to hours",
         tagline="Flat at the close; no overnight gap risk.",
         principles=["No overnight exposure, by definition",
                     "Liquidity and spread over thesis",
                     "Most of the account available as margin",
                     "PDT rule: $25k minimum for 4+ day trades / 5 days"],
         fn=day_trading),
    dict(id="balanced-risk", name="Risk-Managed Allocator",
         horizon="Open-ended",
         tagline="Budget risk first, returns follow.",
         principles=["Cap single-name and single-sector weights",
                     "Hold something that behaves differently from equities",
                     "Size by volatility contribution, not by conviction",
                     "Stress-test before adding, not after"],
         fn=balanced_risk),
]


def evaluate(a, style_id=None):
    out = []
    for st in STYLES:
        if style_id and st["id"] != style_id:
            continue
        score, obs = st["fn"](a)
        out.append(dict(
            id=st["id"], name=st["name"], horizon=st["horizon"],
            tagline=st["tagline"], principles=st["principles"],
            alignment=score, observations=obs,
            tensions=sum(1 for o in obs if o["verdict"] == "tension"),
            aligned=sum(1 for o in obs if o["verdict"] == "aligned"),
        ))
    out.sort(key=lambda s: -s["alignment"])
    return dict(disclaimer=DISCLAIMER, styles=out)
