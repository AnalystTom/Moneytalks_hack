# Position Analyst — hackathon demo

Paper-trading account → position analysis → portfolio read through six
trading-style lenses. Runs on **Python 3.9+ stdlib only**. No `pip install`,
no API key, no signup.

```bash
python3 server.py          # dashboard at http://localhost:8787
python3 demo.py            # same analysis in the terminal
python3 demo.py value-dividend   # one style lens
```

## Which brokerage API to connect to

| Platform | Signup to first API call | Paper/fake account | Notes |
|---|---|---|---|
| **Alpaca** | ~2 min, email only | Yes, `paper-api.alpaca.markets`, $100k virtual, no KYC | Two header keys, plain REST+JSON. **Best choice for a hackathon.** |
| **Tradier** | ~10 min | Yes, sandbox | OAuth, delayed sandbox quotes |
| **SnapTrade / Plaid Investments** | Hours–days | No | Aggregators to read *real* user accounts; needs an approved app |
| **Interactive Brokers** | Days | Yes | Requires a local gateway process; heaviest option |
| **Robinhood / Webull** | — | No | No public API. Unofficial wrappers break and violate ToS. Don't demo on these. |

Go with **Alpaca paper**. The one catch: nobody wants to open a brokerage
account at a hackathon kiosk, and a fresh paper account has **zero positions**,
so there is nothing to analyse on stage. Hence this repo ships a mock broker
that speaks Alpaca's shapes, pre-seeded with a deliberately messy portfolio.

## Switching to the real Alpaca paper account

[`broker.py`](broker.py) has two classes with an identical method surface:

```bash
export BROKER=alpaca
export APCA_API_KEY_ID=...        # from alpaca.markets > Paper Trading > API keys
export APCA_API_SECRET_KEY=...
python3 server.py
```

Nothing else changes — `analysis.py`, `styles.py`, the API and the dashboard all
read the same normalised position dicts. Keys stay in the environment; they are
never written to disk or sent anywhere but Alpaca.

To get positions into a real paper account first:

```bash
curl -X POST https://paper-api.alpaca.markets/v2/orders \
  -H "APCA-API-KEY-ID: $APCA_API_KEY_ID" \
  -H "APCA-API-SECRET-KEY: $APCA_API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"NVDA","qty":"120","side":"buy","type":"market","time_in_force":"day"}'
```

## The seeded account

`PA3K9QDEMO01` — ~$302k equity, 14 positions, $18.4k cash. Built to be
**interestingly flawed** so the analysis has something to say:

- PLTR at ~19% of holdings — single-name concentration
- Technology ~49% vs ~34% benchmark — sector overweight
- Portfolio beta ~1.53 — high-beta book
- SOFI −36%, GME −43%, AMD −27% — losers held far past any stop
- 0.8% yield, 6% cash — nothing defensive, no dry powder

Mock prices drift ±0.8% on a sine + seeded jitter, so the dashboard looks live
and refreshes every 6s.

## Layout

| File | Role |
|---|---|
| [broker.py](broker.py) | `MockBroker` / `AlpacaBroker`, same interface |
| [reference.py](reference.py) | sector, beta, yield, 52wk range (synthetic) |
| [analysis.py](analysis.py) | measurement only — weights, HHI, exposures, flags |
| [styles.py](styles.py) | six style lenses + fit scoring |
| [server.py](server.py) | stdlib HTTP API + dashboard |
| [demo.py](demo.py) | terminal walkthrough |
| [static/index.html](static/index.html) | dashboard UI |

`analysis.py` measures, `styles.py` interprets. Keeping them apart is what makes
every sentence on screen traceable to a number.

## API

```
GET  /api/portfolio        account + enriched positions
GET  /api/analysis         summary, concentration, sectors, tilts, flags
GET  /api/styles           all six lenses, scored and sorted by fit
GET  /api/styles/<id>      passive-index | long-term-growth | value-dividend
                           swing-momentum | day-trading | balanced-risk
GET  /api/orders           recent orders
POST /api/orders           {"symbol":"NVDA","qty":10,"side":"buy"}
```

## How the style lenses work

Six philosophies read the *same* measured portfolio and report where it agrees
or disagrees with their own textbook principles. Each observation is tagged
`aligned` / `tension` / `note` and every string is interpolated from a computed
number, so nothing is hand-waved. A 0–100 "structural fit" is a weighted sum of
satisfaction terms — the demo-friendly bit is that one portfolio scores 72 as
long-term growth and 24 as day trading, from identical inputs.

**Scope:** this describes portfolio *structure* against named trading
philosophies. It is general education, not investment advice, not a buy/sell
recommendation, and not a prediction — and it runs on synthetic data. The
disclaimer is surfaced in the UI and in `/api/styles` rather than buried here;
if you extend this past a demo, keep it that way.
