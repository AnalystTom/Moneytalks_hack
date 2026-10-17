import json

from app.services import ingest, personas, tools
from tests.conftest import PERSONA, PORTFOLIO, parse_sse
from tests.test_agents import fake  # noqa: F401


def test_ingest_csv_summary(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", PORTFOLIO), "persona": ("persona.md", PERSONA)}, data={"plaid": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["brief_id"]
    assert body["summary"] == "Holdings: VOO; Market value and returns unavailable; Bank balances unavailable; 10-year horizon, moderate risk"


def test_ingest_json_without_plaid(client):
    holdings = json.dumps({"holdings": [{"ticker": "aapl", "shares": 1, "cost_basis": 230}]}).encode()
    r = client.post("/api/ingest", files={"portfolio": ("p.json", holdings), "persona": ("persona.md", b"")})
    assert r.json()["summary"] == "Holdings: AAPL; Market value and returns unavailable"


def test_ingest_rejects_bad_portfolio(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", b"ticker\nVOO\n"), "persona": ("persona.md", PERSONA)})
    assert r.status_code == 422


async def test_unavailable_finances_stay_unavailable_through_research(client, fake):
    response = client.post("/api/ingest", files={
        "portfolio": ("p.csv", b"ticker,shares,cost_basis\nVOO,1,714.29\n"),
        "persona": ("p.md", PERSONA),
    }, data={"plaid": "true"})
    assert response.status_code == 200
    brief = ingest.BRIEFS[response.json()["brief_id"]]
    assert brief["holdings"] == [{"ticker": "VOO", "shares": 1, "cost_basis": 714.29}]
    assert {key: brief[key] for key in ("prices", "value", "pnl_pct", "bank")} == {
        "prices": None, "value": None, "pnl_pct": None, "bank": None,
    }
    assert brief["summary"] == "Holdings: VOO; Market value and returns unavailable; Bank balances unavailable; 10-year horizon, moderate risk"
    for args in ({}, {"ticker": "VOO"}):
        data = await tools.call("portfolio_lookup", args, brief, personas.load()["burry"])
        assert data == {"summary": brief["summary"], "account": None, "bank": None, "holdings": brief["holdings"]}
    events = parse_sse(client.post("/api/council/run", json={"brief_id": response.json()["brief_id"], "question": "Can I spend my cash?"}).text)
    assert events[-1][0] == "run.done"
    follow = parse_sse(client.post("/api/council/ask", json={"run_id": events[0][1]["run_id"], "member": "burry", "question": "What about cash?"}).text)
    assert follow[-1][0] == "run.done"
    assert all(brief["summary"] in messages[1]["content"] for _, messages, _ in fake.calls)
