#!/usr/bin/env python3
"""Terminal walkthrough -- same engine as the web demo, no browser needed.

    python3 demo.py                    # full run
    python3 demo.py swing-momentum     # one style lens
"""

import sys

import analysis
import broker as broker_mod
import styles

C = dict(dim="\033[2m", b="\033[1m", g="\033[32m", r="\033[31m",
         y="\033[33m", c="\033[36m", off="\033[0m")


def rule(title):
    print(f"\n{C['b']}{C['c']}{title}{C['off']}")
    print(C["dim"] + "-" * 78 + C["off"])


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    b = broker_mod.get_broker()
    acct = b.get_account()
    a = analysis.analyze(acct, b.get_positions())
    s, c = a["summary"], a["concentration"]

    rule("1. ACCOUNT  (" + b.label + ")")
    print(f"  {acct['account_number']}   status {acct['status']}   "
          f"opened {str(acct['created_at'])[:10]}")
    print(f"  Equity {C['b']}${s['equity']:,.2f}{C['off']}   "
          f"cash ${s['cash']:,.2f} ({s['cash_pct']}%)   "
          f"buying power ${acct['buying_power']:,.2f}")

    rule("2. POSITIONS")
    print(f"  {'SYM':<6}{'QTY':>7}{'ENTRY':>10}{'LAST':>10}{'VALUE':>12}"
          f"{'P/L':>12}{'%':>9}{'WT':>7}{'HELD':>7}  ROLE")
    for p in a["positions"]:
        col = C["g"] if p["unrealized_pl"] > 0 else C["r"]
        held = f"{p['days_held']}d" if p["days_held"] is not None else "-"
        print(f"  {p['symbol']:<6}{p['qty']:>7.0f}{p['avg_entry_price']:>10,.2f}"
              f"{p['current_price']:>10,.2f}{p['market_value']:>12,.0f}"
              f"{col}{p['unrealized_pl']:>12,.0f}{p['pnl_pct']:>8.1f}%{C['off']}"
              f"{p['weight']:>6.1f}%{held:>7}  {p['role']}")
    plc = C["g"] if s["unrealized_pl"] > 0 else C["r"]
    print(f"  {'':<6}{'':>7}{'':>10}{'':>10}{s['market_value']:>12,.0f}"
          f"{plc}{s['unrealized_pl']:>12,.0f}{s['unrealized_pl_pct']:>8.1f}%{C['off']}")

    rule("3. STRUCTURE")
    print(f"  Beta {s['portfolio_beta']}   est. yield {s['est_yield']}% "
          f"(${s['est_annual_income']:,.0f}/yr)   "
          f"{s['winners']} winners / {s['losers']} losers")
    print(f"  Top 1/3/5 weight: {c['top1']}% / {c['top3']}% / {c['top5']}%   "
          f"HHI {c['hhi']}   effective positions {c['effective_positions']}")
    print(f"  {C['dim']}Sectors:{C['off']} " + "   ".join(
        f"{x['sector']} {x['weight']}%"
        + (f" ({x['delta']:+.0f} vs mkt)" if x["delta"] is not None else "")
        for x in a["sectors"][:5]))

    rule("4. RISK OBSERVATIONS")
    for f in a["flags"]:
        col = {"high": C["r"], "medium": C["y"], "low": C["dim"]}[f["level"]]
        print(f"  {col}[{f['level'].upper():<6}]{C['off']} {f['title']}")
        print(f"           {C['dim']}{f['detail']}{C['off']}")

    res = styles.evaluate(a, want)
    if not res["styles"]:
        print(f"\n  unknown style '{want}'. options: "
              + ", ".join(x["id"] for x in styles.STYLES))
        return 1

    rule("5. TRADING-STYLE LENSES")
    print(f"  {C['dim']}{res['disclaimer']}{C['off']}\n")
    for st in res["styles"]:
        bar = "#" * round(st["alignment"] / 5)
        col = (C["g"] if st["alignment"] >= 60 else
               C["y"] if st["alignment"] >= 40 else C["r"])
        print(f"  {st['name']:<26}{col}{st['alignment']:>4}{C['off']} "
              f"{C['dim']}{bar}{C['off']}")
    print()
    for st in res["styles"]:
        print(f"\n  {C['b']}{st['name']}{C['off']} {C['dim']}· {st['horizon']} "
              f"· fit {st['alignment']}/100{C['off']}")
        print(f"  {C['dim']}{st['tagline']}{C['off']}")
        for o in st["observations"]:
            col = {"aligned": C["g"], "tension": C["y"], "note": C["dim"]}[o["verdict"]]
            text = o["text"]
            # wrap at ~72 cols
            line, out = "", []
            for w in text.split():
                if len(line) + len(w) > 72:
                    out.append(line); line = w
                else:
                    line = (line + " " + w).strip()
            out.append(line)
            print(f"    {col}{o['verdict']:<8}{C['off']}{out[0]}")
            for extra in out[1:]:
                print(f"            {extra}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
