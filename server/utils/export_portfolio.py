#!/usr/bin/env python3
"""Write the dashboard's portfolio view (same shape as GET /api/portfolio)
to ../user_data/portfolio.json.

    python3 export_portfolio.py                 # mock broker, base prices
    BROKER=alpaca python3 export_portfolio.py   # real Alpaca paper account
"""

import json
import os
from datetime import datetime, timezone

import analysis
import broker as broker_mod

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "user_data", "portfolio.json")


def main():
    b = broker_mod.get_broker()
    if isinstance(b, broker_mod.MockBroker):
        b = broker_mod.MockBroker(drift=False)  # stable prices for a fixture
    acct = b.get_account()
    a = analysis.analyze(acct, b.get_positions())
    data = dict(
        exported_at=datetime.now(timezone.utc).isoformat(),
        broker=dict(name=b.name, label=b.label),
        account=acct,
        positions=a["positions"],
        summary=a["summary"],
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.write("\n")
    print(f"wrote {os.path.normpath(OUT)} ({len(data['positions'])} positions)")


if __name__ == "__main__":
    main()
