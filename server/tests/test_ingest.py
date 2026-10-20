import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services import council, ingest, llm, profile, store
from tests.conftest import PERSONA, PORTFOLIO, parse_sse, run_council


def test_ingest_csv_summary(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", PORTFOLIO), "persona": ("persona.md", PERSONA)}, data={"plaid": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["brief_id"]
    assert body["summary"] == "$10,000 in VOO, -30%; $4,200 bank cash; 10-year horizon, moderate risk"


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
    """Stand in for the OpenAI call: returns whatever the test puts in `reply`."""
    reply = {}
    monkeypatch.setenv("OPENAI_API_KEY", "k")

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
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert client.post("/api/ingest/text", json={"text": ""}).status_code == 422
    assert client.post("/api/ingest/text", json={"text": "x" * 4001}).status_code == 422


def test_ingest_text_brief_drives_council(client, model, monkeypatch):
    model["value"] = _profile()
    brief_id = client.post("/api/ingest/text", json={"text": SAM}).json()["brief_id"]
    monkeypatch.delenv("OPENAI_API_KEY")
    events = run_council(client, brief_id)[1]
    assert events[-1][0] == "run.done"
    assert "run.error" not in [event for event, _ in events]
    verdicts = [data for event, data in events if event == "member.verdict"]
    assert len(verdicts) == 5
    assert all("unavailable" in v["analysis"] for v in verdicts)
    assert all(v["positions"] == [] for v in verdicts)


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
    monkeypatch.delenv("OPENAI_API_KEY")
    events = run_council(client, response.json()["brief_id"])[1]
    assert events[-1][0] == "run.done"
    ruling = next(data for event, data in events if event == "chair.summary")
    assert ruling["positions"] == []


@pytest.mark.parametrize("cash", [None, 0, 12000])
@pytest.mark.parametrize("valued", [False, True])
def test_ingest_text_preserves_unknown_and_zero_cash(client, model, cash, valued):
    position = {"ticker": "VOO", "shares": None if valued else 10,
                "cost_basis": None if valued else 100, "amount": 8000 if valued else None}
    model["value"] = _profile(name=None, age=None, cash=cash, net_worth=100000,
                              goals=None, horizon=None, risk=None, positions=[position])
    text = ("$8k in VOO" if valued else "10 shares of VOO at $100") + "; net worth $100k"
    if cash is not None:
        text += f"; ${cash} cash"
    response = client.post("/api/ingest/text", json={"text": text})
    assert response.status_code == 200, response.text
    body = response.json()
    brief = ingest.BRIEFS[body["brief_id"]]
    facts = brief["facts"]
    assert brief["account"] == ({"cash": cash} if cash is not None else None)
    assert facts["broker_cash"] == cash
    assert ("cash" in body["missing"]) is (cash is None)
    if cash is None:
        assert not any(line.startswith("Cash:") for line in body["card"]["lines"])
    else:
        assert f"Cash: ${cash:,.0f}" in body["card"]["lines"]
        assert f"${cash:,.0f} cash" in body["summary"]
    if cash is not None and valued:
        assert facts["broker_equity"] == 8000 + cash
        assert facts["broker_cash_pct"] == round(cash / (8000 + cash) * 100, 1)
        assert facts["brokerage_pct_of_net_worth"] == round((8000 + cash) / 100000 * 100, 1)
    else:
        assert {"broker_equity", "broker_cash_pct", "brokerage_pct_of_net_worth"}.isdisjoint(facts)
    persisted = json.loads(store._mem["brief", body["brief_id"]])
    assert persisted["account"] == brief["account"]
    assert persisted["facts"] == facts


@pytest.mark.parametrize("account", [None, {}, {"cash": None}, {"cash": 0}, {"cash": 12000}])
@pytest.mark.parametrize("plaid", [False, True])
def test_ingest_upload_preserves_unknown_cash_with_separate_bank_balances(client, account, plaid):
    portfolio = {"positions": [{"symbol": "VOO", "qty": 1, "avg_entry_price": 6000, "current_price": 8000}],
                 "account": account}
    response = client.post("/api/ingest", files={"portfolio": ("p.json", json.dumps(portfolio)),
                                               "persona": ("p.md", "# Profile\n| **Total Net Worth** | $100,000 |")},
                           data={"plaid": str(plaid).lower()})
    assert response.status_code == 200, response.text
    brief = ingest.BRIEFS[response.json()["brief_id"]]
    facts = brief["facts"]
    cash = account.get("cash") if account else None
    assert facts["broker_cash"] == cash
    assert brief["account"] == account
    if cash is None:
        assert {"broker_equity", "broker_cash_pct", "brokerage_pct_of_net_worth"}.isdisjoint(facts)
        assert brief["summary"] == "$8,000 in VOO, +33%" + ("; $4,200 bank cash" if plaid else "")
    else:
        assert facts["broker_equity"] == 8000 + cash
        assert facts["broker_cash_pct"] == round(cash / (8000 + cash) * 100, 1)
        assert facts["brokerage_pct_of_net_worth"] == round((8000 + cash) / 100000 * 100, 1)
        assert f"${cash + (4200 if plaid else 0):,.0f} cash" in brief["summary"]


def test_zero_equity_has_no_undefined_cash_percentage():
    facts = ingest.facts([{"ticker": "VOO", "shares": 1, "cost_basis": 100}], {"VOO": 0}, 0, 100000)
    assert facts["broker_cash"] == facts["broker_equity"] == facts["brokerage_pct_of_net_worth"] == 0
    assert "broker_cash_pct" not in facts


@pytest.mark.parametrize("failure", ["disabled", "analysis", "advice", "both", "none"])
@pytest.mark.parametrize("roast", [False, True])
def test_missing_performance_fallback_covers_verdict_speech_and_chat(client, model, monkeypatch, failure, roast):
    model["value"] = _profile(name=None, age=None, cash=None, goals=None, horizon=None, risk=None,
                              positions=[{"ticker": "VOO", "shares": None, "cost_basis": None, "amount": 8000}])
    response = client.post("/api/ingest/text", json={"text": "$8k in VOO"})
    assert response.status_code == 200, response.text
    gap = "Current valuation or profit/loss is unavailable; missing prices and cost basis must be supplied before assessing concentration or performance."

    async def complete(system, user, response_format=None):
        if "Stage 1, portfolio analysis." in system:
            if failure in ("analysis", "both"):
                raise ValueError("analysis unavailable")
            return {"headline": "Profile received", "analysis": "This profile includes VOO.",
                    "reasons": ["VOO is supplied by the user."], "names": ["VOO"]}
        if "Stage 3, advice." in system:
            if failure in ("advice", "both"):
                raise ValueError("advice unavailable")
            return {"positions": [{"ticker": "VOO", "signal": "HOLD", "conviction": "low",
                                    "rationale": "Current performance is unavailable."}],
                    "advice": [{"action": "Provide current values", "why": "Performance is unavailable."}]}
        return {}

    async def failed_reply(*args):
        raise ValueError("chat unavailable")

    monkeypatch.setattr(llm, "complete_json", complete)
    monkeypatch.setattr(llm, "complete_reply", failed_reply)
    if failure == "disabled":
        monkeypatch.delenv("OPENAI_API_KEY")
    run_id, events = run_council(client, response.json()["brief_id"], roast=roast)
    assert events[-1][0] == "run.done"
    assert "run.error" not in [event for event, _ in events]
    analyses = [data for event, data in events if event == "member.analysis"]
    verdicts = [data for event, data in events if event == "member.verdict"]
    assert len(analyses) == len(verdicts) == 5
    analysis_fallback = failure in ("disabled", "analysis", "both")
    for analysis in analyses:
        assert analysis["headline"] == (gap if analysis_fallback else "Profile received")
        assert analysis["analysis"] == (gap if analysis_fallback else "This profile includes VOO.")
    advice_fallback = failure in ("disabled", "advice", "both")
    for verdict in verdicts:
        assert verdict["headline"] == (gap if analysis_fallback or advice_fallback else "Profile received")
        if advice_fallback:
            assert verdict["analysis"] == gap
            assert verdict["reasons"] == [gap]
            assert verdict["advice"] == [{"action": gap, "why": gap, "tickers": []}]
            assert verdict["positions"] == []
        else:
            assert verdict["advice"][0]["action"] == "Provide current values"
    member_audio = [data for event, data in events if event == "member.audio" and data["member"] != "chair"]
    assert len(member_audio) == 5
    for audio in member_audio:
        spoken = parse_qs(urlsplit(audio["audio_url"]).query)["text"][0]
        expected = gap + ". " + gap if analysis_fallback or advice_fallback else "Profile received. This profile includes VOO."
        assert spoken == expected + (" HOLD VOO." if not advice_fallback else "")
    ruling = next(data for event, data in events if event == "chair.summary")
    if advice_fallback:
        assert ruling == {
            "positions": [], "dissent": [], "consensus": gap,
            "summary": gap + " Parody council, not financial advice.",
            "actions": [gap + " (Warren, Ray, Michael, Leopold, Jim)"],
            "suggestions": ["Michael, why worry about VOO?", "What should I do with my savings?"],
        }
    else:
        assert len(ruling["positions"]) == 1
        assert ruling["positions"][0]["ticker"] == "VOO"
        assert ruling["positions"][0]["calls"] == {v["member"]: "HOLD" for v in verdicts}
    chair_audio = next(data for event, data in events if event == "member.audio" and data["member"] == "chair")
    assert parse_qs(urlsplit(chair_audio["audio_url"]).query)["text"] == [ruling["summary"]]
    persisted = json.loads(store._mem["run", run_id])
    assert persisted["chair"] == ruling
    assert {m: v["positions"] for m, v in persisted["verdicts"].items()} == {v["member"]: v["positions"] for v in verdicts}
    spoken_history = {h["role"]: h["text"] for h in persisted["history"] if h["role"] != "user"}
    for audio in [*member_audio, chair_audio]:
        assert spoken_history[audio["member"]] == parse_qs(urlsplit(audio["audio_url"]).query)["text"][0]
    for member in ("buffett", "dalio", "burry", "leopold", "cramer"):
        chat_response = client.post("/api/council/chat", json={"run_id": run_id, "text": "Discuss VOO", "to": [member], "roast": roast})
        chat_events = parse_sse(chat_response.text)
        assert chat_events[-1][0] == "run.done"
        replies = [data["text"] for event, data in chat_events if event == "member.reply"]
        assert replies == [gap]
        audio = next(data for event, data in chat_events if event == "member.audio")
        assert parse_qs(urlsplit(audio["audio_url"]).query)["text"] == [gap]

    if advice_fallback:
        council.RUNS.pop(run_id)
        response = client.post("/api/council/chat", json={"run_id": run_id, "text": "Who was most bullish?", "roast": roast})
        chair_events = parse_sse(response.text)
        assert chair_events[-1][0] == "run.done"
        assert next(data["members"] for event, data in chair_events if event == "chat.routed") == ["chair"]
        assert [data["text"] for event, data in chair_events if event == "member.reply"] == [gap]
        audio = next(data for event, data in chair_events if event == "member.audio")
        assert parse_qs(urlsplit(audio["audio_url"]).query)["text"] == [gap]


@pytest.mark.parametrize("roast", [False, True])
def test_complete_demo_keeps_its_canned_verdict_and_chat(client, jordan_brief_id, roast):
    run_id, events = run_council(client, jordan_brief_id, roast=roast)
    assert events[-1][0] == "run.done"
    verdict = next(data for event, data in events if event == "member.verdict" and data["member"] == "burry")
    headline = "I shorted a housing bubble; you built a portfolio-shaped one." if roast else "The biggest winner has become the biggest risk"
    assert verdict["headline"] == headline
    assert verdict["advice"][0]["why"] == "Concentration after a big run."
    audio = next(data for event, data in events if event == "member.audio" and data["member"] == "burry")
    assert parse_qs(urlsplit(audio["audio_url"]).query)["text"][0].startswith(headline)
    response = client.post("/api/council/chat", json={"run_id": run_id, "text": "Discuss PLTR", "to": ["burry"], "roast": roast})
    chat_events = parse_sse(response.text)
    assert chat_events[-1][0] == "run.done"
    reply = next(data["text"] for event, data in chat_events if event == "member.reply")
    assert reply.startswith(headline)


@pytest.mark.parametrize("unknown_value", [False, True])
@pytest.mark.asyncio
async def test_partial_portfolio_fallback_only_votes_with_known_weight_and_performance(client, unknown_value):
    holdings = [{"ticker": "AAPL", "shares": 10, "cost_basis": 150, "amount": None},
                {"ticker": "VOO", "shares": 10 if unknown_value else None, "cost_basis": None,
                 "amount": None if unknown_value else 8000}]
    brief_id, _ = await ingest.build_brief(holdings, "", False, prices={"AAPL": 230})
    run_id, events = run_council(client, brief_id)
    assert events[-1][0] == "run.done"
    verdicts = [data for event, data in events if event == "member.verdict"]
    expected = set() if unknown_value else {"AAPL"}
    assert all({p["ticker"] for p in v["positions"]} == expected for v in verdicts)
    ruling = next(data for event, data in events if event == "chair.summary")
    assert {p["ticker"] for p in ruling["positions"]} == expected
    for audio in (data for event, data in events if event == "member.audio"):
        spoken = parse_qs(urlsplit(audio["audio_url"]).query)["text"][0]
        assert not any(f"{signal} VOO" in spoken for signal in ("BUY", "HOLD", "SELL"))
    response = client.post("/api/council/chat", json={"run_id": run_id, "text": "Who was most bullish?"})
    replies = [data["text"] for event, data in parse_sse(response.text) if event == "member.reply"]
    assert len(replies) == 1
    assert not any(f"{signal} VOO" in replies[0] for signal in ("BUY", "HOLD", "SELL"))
