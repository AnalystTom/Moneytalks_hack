import json

from tests.conftest import PERSONA, PORTFOLIO


def test_ingest_csv_summary(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", PORTFOLIO), "persona": ("persona.md", PERSONA)}, data={"plaid": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["brief_id"]
    assert body["summary"] == "$10,000 in VOO, -30%; $4,200 cash; 10-year horizon, moderate risk"


def test_ingest_json_without_plaid(client):
    holdings = json.dumps({"holdings": [{"ticker": "aapl", "shares": 1, "cost_basis": 230}]}).encode()
    r = client.post("/api/ingest", files={"portfolio": ("p.json", holdings), "persona": ("persona.md", b"")})
    assert r.json()["summary"] == "$230 in AAPL, +0%"


def test_ingest_rejects_bad_portfolio(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", b"ticker\nVOO\n"), "persona": ("persona.md", PERSONA)})
    assert r.status_code == 422


def test_ingest_broker_snapshot_and_persona(client):
    from app.services import ingest
    from tests.conftest import DATA

    files = {"portfolio": ("portfolio.json", (DATA / "portfolio.json").read_bytes()), "persona": ("PERSONA.md", (DATA / "PERSONA.md").read_bytes())}
    body = client.post("/api/ingest", files=files).json()
    assert body["summary"] == "$283,741 in PLTR, SPY, NVDA, TSLA +10 more, +23%; $18,431 cash; Jordan Mitchell, 38"
    f = ingest.BRIEFS[body["brief_id"]]["facts"]
    assert f["positions"][0]["ticker"] == "PLTR" and f["positions"][0]["weight_pct"] == 19.2
    assert f["portfolio_beta"] == 1.53 and f["sector_mix_pct"]["Technology"] == 49.0
    assert f["net_worth"] == 787171 and f["brokerage_pct_of_net_worth"] == 38.4
