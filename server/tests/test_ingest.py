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


def test_ingest_rejects_oversize_upload(client):
    big = b"ticker,shares,cost_basis\n" + b"VOO,1,1\n" * 200_000
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", big), "persona": ("persona.md", PERSONA)})
    assert r.status_code == 413
