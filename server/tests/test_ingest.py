import json

import pytest

from app.services import ingest, llm, profile
from tests.conftest import PERSONA, PORTFOLIO, run_council


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
    from tests.conftest import DATA

    files = {"portfolio": ("portfolio.json", (DATA / "portfolio.json").read_bytes()), "persona": ("PERSONA.md", (DATA / "PERSONA.md").read_bytes())}
    body = client.post("/api/ingest", files=files).json()
    assert body["summary"] == "$283,741 in PLTR, SPY, NVDA, TSLA +10 more, +23%; $18,431 cash; Jordan Mitchell, 38"
    f = ingest.BRIEFS[body["brief_id"]]["facts"]
    assert f["positions"][0]["ticker"] == "PLTR" and f["positions"][0]["weight_pct"] == 19.2
    assert f["portfolio_beta"] == 1.53 and f["sector_mix_pct"]["Technology"] == 49.0
    assert f["net_worth"] == 787171 and f["brokerage_pct_of_net_worth"] == 38.4


SAM = "I'm Sam, 31. 40 shares of AAPL at $150, $8k in VOO, $12k cash. Goal: house deposit in 5 years, medium risk."


def _profile(**over):
    base = {
        "name": "Sam", "age": 31, "cash": 12000, "net_worth": None, "goals": "house deposit", "horizon": "5 years", "risk": "medium",
        "positions": [
            {"ticker": "AAPL", "shares": 40, "cost_basis": 150, "amount": None},
            {"ticker": "VOO", "shares": None, "cost_basis": None, "amount": 8000},
        ],
    }
    return {**base, **over}


@pytest.fixture
def model(monkeypatch):
    """Stand in for the Nicrron call: returns whatever the test puts in `reply`."""
    reply = {}
    monkeypatch.setenv("NICRRON_API_KEY", "k")

    async def fake(system, user, response_format=None):
        assert response_format["json_schema"]["strict"] is True
        return reply["value"]

    monkeypatch.setattr(llm, "complete_json", fake)
    return reply


def test_ingest_text_builds_brief_from_user_values_only(client, model):
    model["value"] = _profile()
    r = client.post("/api/ingest/text", json={"text": SAM})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == "$17,200 in AAPL, VOO, +23%; $12,000 cash; Sam, 31; not given: cost basis for VOO"
    brief = ingest.BRIEFS[body["brief_id"]]
    pos = {p["ticker"]: p for p in brief["facts"]["positions"]}
    assert pos["AAPL"]["shares"] == 40 and pos["AAPL"]["cost_basis"] == 150
    assert pos["VOO"]["shares"] == 16  # $8k at the quoted $500
    assert brief["account"] == {"cash": 12000}
    assert body["missing"] == ["cost basis for VOO"]
    assert "Not provided by the user" in brief["persona"] and "Sam" in brief["persona"]
    assert body["card"]["title"] == "Sam, 31 — context loaded"
    assert "Goal: house deposit in 5 years" in body["card"]["lines"]
    assert "Not given: cost basis for VOO" in body["card"]["lines"]
    assert "net worth" not in brief["persona"].lower()  # not given, so not written


def test_ingest_text_leaves_missing_fields_missing(client, model):
    model["value"] = _profile(name=None, age=None, cash=None, goals=None, horizon=None, risk=None, positions=[
        {"ticker": "AAPL", "shares": 10, "cost_basis": 100, "amount": None}
    ])
    body = client.post("/api/ingest/text", json={"text": "10 shares of AAPL at $100"}).json()
    assert body["missing"] == ["name", "age", "cash", "goals", "investment horizon", "risk tolerance"]
    assert body["summary"].endswith("not given: " + ", ".join(body["missing"]))
    assert ingest.BRIEFS[body["brief_id"]]["account"] is None
    assert body["card"]["title"] == "Context loaded"


@pytest.mark.parametrize(
    "tweak, text, message",
    [
        ({"cash": 50000}, SAM, "cash (50000) isn't in what you wrote"),
        ({"age": 45}, SAM, "age (45) isn't in what you wrote"),
        ({"positions": []}, SAM, "couldn't find any holdings"),
        ({"positions": [{"ticker": "AAPL", "shares": 400, "cost_basis": 150, "amount": None}]}, SAM, "AAPL shares (400)"),
        ({"positions": [{"ticker": "AAPL", "shares": None, "cost_basis": None, "amount": None}]}, SAM, "How much AAPL"),
        ({"positions": [{"ticker": "ZZZZ", "shares": 5, "cost_basis": None, "amount": None}]}, "5 shares of ZZZZ", "can't price ZZZZ"),
        ({"positions": [{"ticker": "TSLA", "shares": 40, "cost_basis": 150, "amount": None}]}, SAM, "didn't see TSLA"),
        ({"positions": [{"ticker": "not a ticker", "shares": 5, "cost_basis": 1, "amount": None}]}, "5 shares", "doesn't look like a ticker"),
    ],
)
def test_ingest_text_rejects_invented_or_unusable_values(client, model, tweak, text, message):
    model["value"] = _profile(**tweak)
    r = client.post("/api/ingest/text", json={"text": text})
    assert r.status_code == 422 and message in r.json()["detail"]


def test_ingest_text_accepts_suffixed_and_comma_numbers():
    assert {8000, 1_500_000, 1200, 31} <= set(profile._numbers("$8k, 1.5M, 1,200 and 31yo"))
    assert 5 in profile._numbers("5 months")  # "m" in "months" is not a million


def test_ingest_text_unreadable_model_reply_is_a_clear_422(client, model):
    model["value"] = {"surprise": True}
    r = client.post("/api/ingest/text", json={"text": SAM})
    assert r.status_code == 422 and "couldn't read" in r.json()["detail"]


def test_ingest_text_needs_model_and_nonempty_text(client, monkeypatch):
    assert client.post("/api/ingest/text", json={"text": SAM}).status_code == 503
    monkeypatch.setenv("NICRRON_API_KEY", "k")
    assert client.post("/api/ingest/text", json={"text": ""}).status_code == 422
    assert client.post("/api/ingest/text", json={"text": "x" * 4001}).status_code == 422


def test_ingest_text_brief_drives_council(client, model):
    model["value"] = _profile()
    brief_id = client.post("/api/ingest/text", json={"text": SAM}).json()["brief_id"]
    events = run_council(client, brief_id)[1]
    assert events[0][0] == "run.started"


def test_ingest_text_is_traced_to_prism(client, model, monkeypatch):
    spans = []

    async def span(*args, **kw):
        spans.append((args[1], kw.get("ok", True)))

    monkeypatch.setattr(profile.prism, "span", span)
    model["value"] = _profile()
    client.post("/api/ingest/text", json={"text": SAM})
    model["value"] = _profile(positions=[])
    client.post("/api/ingest/text", json={"text": SAM})
    assert spans == [("council.ingest_text", True), ("council.ingest_text", False)]
