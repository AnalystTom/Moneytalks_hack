import json

import httpx
import pytest

from app.services import ingest, llm, profile, store
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
    assert body["summary"] == "AAPL, VOO: total valuation unavailable, profit/loss unavailable; $12,000 cash; Sam, 31; not given: cost basis for VOO, share count for VOO"
    brief = ingest.BRIEFS[body["brief_id"]]
    pos = {p["ticker"]: p for p in brief["facts"]["positions"]}
    assert pos["AAPL"]["shares"] == 40 and pos["AAPL"]["cost_basis"] == 150
    assert pos["VOO"]["amount"] == pos["VOO"]["value"] == 8000
    assert pos["VOO"]["shares"] is pos["VOO"]["cost_basis"] is None
    assert pos["AAPL"]["price"] is pos["AAPL"]["value"] is None
    assert brief["value"] is brief["pnl_pct"] is None
    assert brief["facts"]["winners"] is brief["facts"]["losers"] is None
    assert all(p["pnl_pct"] is p["weight_pct"] is None for p in pos.values())
    assert brief["account"] == {"cash": 12000}
    assert body["missing"] == ["cost basis for VOO", "share count for VOO"]
    assert "Not provided by the user" in brief["persona"] and "Sam" in brief["persona"]
    assert body["card"]["title"] == "Sam, 31 — context loaded"
    assert "Goal: house deposit in 5 years" in body["card"]["lines"]
    assert "Not given: cost basis for VOO, share count for VOO" in body["card"]["lines"]
    assert "2 holdings — total valuation unavailable" in body["card"]["lines"]
    assert "VOO: share count not given, $8,000.00 reported amount, cost basis not given" in body["card"]["lines"]
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


def test_ingest_text_brief_drives_council(client, model, monkeypatch):
    model["value"] = _profile()
    brief_id = client.post("/api/ingest/text", json={"text": SAM}).json()["brief_id"]
    monkeypatch.delenv("NICRRON_API_KEY")
    events = run_council(client, brief_id)[1]
    assert events[-1][0] == "run.done"
    assert "run.error" not in [event for event, _ in events]
    verdicts = [data for event, data in events if event == "member.verdict"]
    assert len(verdicts) == 5
    assert all("unavailable" in v["analysis"] for v in verdicts)
    assert all("unavailable" in p["rationale"] for v in verdicts for p in v["positions"])


@pytest.mark.parametrize("failure", [None, "validation", "schema", "provider"])
def test_ingest_text_is_traced_to_prism_without_personal_data(client, model, monkeypatch, failure):
    requests = []

    def capture(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    original = httpx.AsyncClient
    monkeypatch.setattr(profile.prism, "_auth", lambda: ("https://trace.test", {}, "project"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(capture)))
    model["value"] = _profile(positions=[]) if failure == "validation" else {"surprise": True} if failure == "schema" else _profile()
    if failure == "provider":
        async def fail(*args):
            raise httpx.ConnectError(SAM)
        monkeypatch.setattr(llm, "complete_json", fail)
    response = client.post("/api/ingest/text", json={"text": SAM})
    assert response.status_code == (502 if failure == "provider" else 422 if failure else 200)
    assert [path for path, _ in requests] == ["/api/traces", "/api/spans/ingest"]
    trace, spans = [body for _, body in requests]
    assert trace["input_messages"] == [{"role": "user", "content": ""}]
    metadata = json.loads(trace["output_message"])
    assert set(metadata) == {"model", "latency_ms", "success", "field_count", "position_field_count"}
    assert metadata["model"] == trace["model"] == llm.model()
    assert metadata["latency_ms"] >= 0
    assert metadata["success"] is (failure is None)
    assert metadata["field_count"] == (0 if failure in ("schema", "provider") else 7)
    assert metadata["position_field_count"] == (5 if failure is None else 0)
    assert len(spans["spans"]) == 1
    span = spans["spans"][0]
    assert span["input_text"] == ""
    assert json.loads(span["output_text"]) == metadata
    assert span["status"] == ("error" if failure else "ok")


@pytest.mark.parametrize("ticker, shares, amount", [("VOO", None, 8000), ("ZZZZ", None, 8000), ("ZZZZ", 5, None)])
def test_ingest_text_accepts_unpriced_positions_without_inventing_figures(client, model, ticker, shares, amount):
    model["value"] = _profile(name=None, age=None, cash=None, goals=None, horizon=None, risk=None,
                              positions=[{"ticker": ticker, "shares": shares, "cost_basis": None, "amount": amount}])
    text = f"${amount} in {ticker}" if amount else f"{shares} shares of {ticker}"
    response = client.post("/api/ingest/text", json={"text": text})
    assert response.status_code == 200, response.text
    body = response.json()
    brief = ingest.BRIEFS.pop(body["brief_id"])
    position = brief["facts"]["positions"][0]
    assert position["shares"] == shares
    assert position["amount"] == position["value"] == amount
    assert position["price"] is position["cost_basis"] is position["pnl_pct"] is None
    assert position["weight_pct"] == (100 if amount else None)
    assert brief["facts"]["unrealized_pl"] is brief["pnl_pct"] is None
    assert "profit/loss unavailable" in body["summary"]
    if amount:
        assert f"${amount:,.0f} across 1 holdings" in body["card"]["lines"]
    else:
        assert "1 holdings — total valuation unavailable" in body["card"]["lines"]
    assert json.loads(store._mem["brief", body["brief_id"]]) == brief


@pytest.mark.parametrize("net_worth", [None, 123456.78, 0])
def test_ingest_text_uses_explicit_net_worth_not_goal_text(client, model, net_worth):
    model["value"] = _profile(name=None, age=None, cash=None, goals="net worth of $1m", horizon=None, risk=None,
                              net_worth=net_worth, positions=[{"ticker": "AAPL", "shares": None, "cost_basis": None, "amount": 8000}])
    text = "$8k in AAPL; goal: net worth of $1m" + (f"; current net worth ${net_worth}" if net_worth is not None else "")
    body = client.post("/api/ingest/text", json={"text": text}).json()
    facts = ingest.BRIEFS[body["brief_id"]]["facts"]
    assert facts.get("net_worth") == net_worth
    if net_worth:
        assert facts["brokerage_pct_of_net_worth"] == round(8000 / net_worth * 100, 1)
    else:
        assert "brokerage_pct_of_net_worth" not in facts


@pytest.mark.parametrize("lots, text, shares, amount, basis", [
    ([{"ticker": "aapl", "shares": 10, "cost_basis": 100, "amount": None},
      {"ticker": "AAPL", "shares": 20, "cost_basis": 200, "amount": None}],
     "10 shares of AAPL at $100 in one account; 20 shares of AAPL at $200 in another", 30, None, 5000 / 30),
    ([{"ticker": "VOO", "shares": None, "cost_basis": None, "amount": 8000},
      {"ticker": "VOO", "shares": None, "cost_basis": None, "amount": 4000}],
     "$8k in VOO in one account; $4k in VOO in another", None, 12000, None),
    ([{"ticker": "AAPL", "shares": 10, "cost_basis": 100, "amount": None},
      {"ticker": "AAPL", "shares": 20, "cost_basis": None, "amount": None}],
     "10 shares of AAPL at $100 in one account; 20 shares of AAPL in another", 30, None, None),
    ([{"ticker": "AAPL", "shares": 10, "cost_basis": 100, "amount": None},
      {"ticker": "AAPL", "shares": None, "cost_basis": None, "amount": 8000}],
     "10 shares of AAPL at $100 in one account; $8k in AAPL in another", None, None, None),
])
def test_ingest_text_consolidates_lots_without_losing_unknowns(client, model, monkeypatch, lots, text, shares, amount, basis):
    model["value"] = _profile(name=None, age=None, cash=None, goals=None, horizon=None, risk=None, positions=lots)
    response = client.post("/api/ingest/text", json={"text": text})
    assert response.status_code == 200, response.text
    brief = ingest.BRIEFS[response.json()["brief_id"]]
    assert len(brief["holdings"]) == len(brief["facts"]["positions"]) == 1
    position = brief["facts"]["positions"][0]
    assert position["shares"] == shares
    assert position["amount"] == position["value"] == amount
    assert position["cost_basis"] == (pytest.approx(basis) if basis is not None else None)
    assert position["weight_pct"] == (100 if amount else None)
    assert position["lots"] == [{**lot, "ticker": lot["ticker"].upper()} for lot in lots]
    if basis is not None:
        assert position["cost"] == 5000
    monkeypatch.delenv("NICRRON_API_KEY")
    events = run_council(client, response.json()["brief_id"])[1]
    assert events[-1][0] == "run.done"
    ruling = next(data for event, data in events if event == "chair.summary")
    assert len(ruling["positions"]) == 1
