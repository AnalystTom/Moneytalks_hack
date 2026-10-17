"""Broker abstraction with two interchangeable backends.

MockBroker   - a fake account seeded in-process. Zero signup, works offline,
               speaks the same shapes as Alpaca's /v2/account and /v2/positions.
AlpacaBroker - real Alpaca *paper* trading. Same methods, same field names.

Swap by setting BROKER=alpaca plus APCA_API_KEY_ID / APCA_API_SECRET_KEY.
Nothing else in the app changes -- that's the whole point of this file.
"""

import json
import math
import os
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# --- seed portfolio -------------------------------------------------------
# qty, avg entry price, a baseline "last" price, and when the lot was opened.
# Deliberately messy: a huge winner, a deep loser, an overweight sector, one
# meme position, and a couple of day-old trades.
SEED_POSITIONS = [
    # symbol,  qty,   avg_entry,  base_price, days_held
    ("NVDA",   120,     94.20,      198.40,   412),
    ("AAPL",    85,    191.55,      259.10,   298),
    ("MSFT",    40,    402.10,      511.75,   355),
    ("AMD",    150,    168.40,      121.90,   132),
    ("TSLA",    55,    331.80,      402.60,    76),
    ("PLTR",   300,     68.90,      181.25,   221),
    ("COIN",    22,    338.00,      246.70,    58),
    ("SOFI",  1400,     21.60,       13.85,   164),
    ("GME",    250,     34.10,       19.40,   503),
    ("KO",     160,     62.40,       74.85,   690),
    ("JNJ",     70,    152.30,      188.20,   640),
    ("XOM",     90,    109.70,      127.40,   211),
    ("SPY",     65,    598.20,      728.90,   455),
    ("SCHD",   310,     26.05,       28.95,   380),
]

SEED_CASH = 18_430.55
ACCOUNT_NUMBER = "PA3K9QDEMO01"


class MockBroker:
    """Deterministic fake brokerage. Prices wiggle so the demo looks alive."""

    name = "mock"
    label = "Mock Broker (local, synthetic data)"

    def __init__(self, seed=1337, drift=True):
        self._seed = seed
        self._drift = drift
        self._t0 = time.time()
        self._cash = SEED_CASH
        self._orders = []
        self._positions = []
        now = datetime.now(timezone.utc)
        for sym, qty, entry, base, days in SEED_POSITIONS:
            self._positions.append(dict(
                symbol=sym, qty=float(qty), avg_entry_price=float(entry),
                _base_price=float(base),
                opened_at=(now - timedelta(days=days)).isoformat(),
            ))

    # price wiggle: a stable per-symbol phase plus a slow sine, +/- ~0.8%
    def _price(self, sym, base):
        if not self._drift:
            return base
        phase = (sum(ord(c) for c in sym) % 97) / 97.0 * math.tau
        t = (time.time() - self._t0) / 9.0
        rng = random.Random(f"{sym}:{int(time.time() // 6)}:{self._seed}")
        wiggle = math.sin(t + phase) * 0.005 + rng.uniform(-0.003, 0.003)
        return round(base * (1 + wiggle), 2)

    def get_positions(self):
        out = []
        for p in self._positions:
            px = self._price(p["symbol"], p["_base_price"])
            qty, entry = p["qty"], p["avg_entry_price"]
            mv, cost = px * qty, entry * qty
            out.append(dict(
                symbol=p["symbol"], qty=qty, side="long",
                avg_entry_price=entry, current_price=px,
                market_value=round(mv, 2), cost_basis=round(cost, 2),
                unrealized_pl=round(mv - cost, 2),
                unrealized_plpc=(mv - cost) / cost if cost else 0.0,
                asset_class="us_equity", opened_at=p["opened_at"],
            ))
        return out

    def get_account(self):
        equity = self._cash + sum(p["market_value"] for p in self.get_positions())
        return dict(
            account_number=ACCOUNT_NUMBER, status="ACTIVE", currency="USD",
            cash=round(self._cash, 2), equity=round(equity, 2),
            buying_power=round(self._cash * 2, 2), pattern_day_trader=False,
            created_at="2024-02-11T14:03:22Z",
        )

    def place_order(self, symbol, qty, side):
        symbol, qty = symbol.upper(), float(qty)
        pos = next((p for p in self._positions if p["symbol"] == symbol), None)
        px = self._price(symbol, pos["_base_price"]) if pos else 100.0
        if side == "buy":
            if px * qty > self._cash:
                raise ValueError("insufficient cash in demo account")
            self._cash -= px * qty
            if pos:
                total = pos["qty"] + qty
                pos["avg_entry_price"] = (
                    pos["avg_entry_price"] * pos["qty"] + px * qty) / total
                pos["qty"] = total
            else:
                self._positions.append(dict(
                    symbol=symbol, qty=qty, avg_entry_price=px, _base_price=px,
                    opened_at=datetime.now(timezone.utc).isoformat()))
        else:
            if not pos or pos["qty"] < qty:
                raise ValueError(f"not enough {symbol} to sell")
            pos["qty"] -= qty
            self._cash += px * qty
            if pos["qty"] <= 0:
                self._positions.remove(pos)
        order = dict(id=f"demo-{len(self._orders)+1:04d}", symbol=symbol, qty=qty,
                     side=side, type="market", status="filled", filled_avg_price=px,
                     submitted_at=datetime.now(timezone.utc).isoformat())
        self._orders.insert(0, order)
        return order

    def get_orders(self):
        return self._orders[:25]


class AlpacaBroker:
    """Real Alpaca paper trading. Identical method surface to MockBroker."""

    name = "alpaca"
    label = "Alpaca Paper Trading (live API)"

    def __init__(self, key=None, secret=None, base=None):
        self.key = key or os.environ.get("APCA_API_KEY_ID")
        self.secret = secret or os.environ.get("APCA_API_SECRET_KEY")
        self.base = (base or os.environ.get(
            "APCA_API_BASE_URL", "https://paper-api.alpaca.markets")).rstrip("/")
        if not (self.key and self.secret):
            raise RuntimeError(
                "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY for BROKER=alpaca")

    def _req(self, path, method="GET", body=None):
        url = f"{self.base}/v2{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Alpaca {e.code}: {e.read().decode()[:300]}")

    def get_positions(self):
        out = []
        for p in self._req("/positions") or []:
            cost = float(p["cost_basis"])
            out.append(dict(
                symbol=p["symbol"], qty=float(p["qty"]), side=p["side"],
                avg_entry_price=float(p["avg_entry_price"]),
                current_price=float(p["current_price"]),
                market_value=float(p["market_value"]), cost_basis=cost,
                unrealized_pl=float(p["unrealized_pl"]),
                unrealized_plpc=float(p["unrealized_plpc"]),
                asset_class=p.get("asset_class", "us_equity"),
                # Alpaca's positions endpoint has no lot-open date; you would
                # derive it from /v2/account/activities if you need holding period.
                opened_at=None,
            ))
        return out

    def get_account(self):
        a = self._req("/account")
        return dict(
            account_number=a["account_number"], status=a["status"],
            currency=a["currency"], cash=float(a["cash"]),
            equity=float(a["equity"]), buying_power=float(a["buying_power"]),
            pattern_day_trader=a.get("pattern_day_trader", False),
            created_at=a.get("created_at"),
        )

    def place_order(self, symbol, qty, side):
        return self._req("/orders", "POST", dict(
            symbol=symbol.upper(), qty=str(qty), side=side,
            type="market", time_in_force="day"))

    def get_orders(self):
        return self._req("/orders?status=all&limit=25") or []


def get_broker():
    if os.environ.get("BROKER", "mock").lower() == "alpaca":
        return AlpacaBroker()
    return MockBroker()
