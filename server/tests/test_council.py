import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import MEMBERS
from tests.conftest import parse_sse, run_council


def names(events):
    return [e for e, _ in events]


def chat(client, run_id, text, **body):
    return parse_sse(client.post("/api/council/chat", json={"run_id": run_id, "text": text, **body}).text)


@pytest.fixture
def kb_results(monkeypatch):
    from app.services import prism

    async def search(agent_id, query, limit=3):
        return [{"doc_name": f"{agent_id}.md", "content": f"KB research: {query}"}]

    mock = AsyncMock(side_effect=search)
    monkeypatch.setenv("COUNCIL_VERSION", "v2")
    monkeypatch.setattr(prism, "kb_search", mock)
    return mock


def test_run_event_order_canned(client, jordan_brief_id):
    r = client.post("/api/council/run", json={"brief_id": jordan_brief_id, "question": "Keep DCA, sell, or move?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    n = names(events)
    assert n[0] == "run.started" and n[-1] == "run.done"
    plans = [d for e, d in events if e == "orchestrator.plan"]
    assert [p["member"] for p in plans] == list(MEMBERS)
    assert all(2 <= len(p["questions"]) <= 3 and 1 <= len(p["focus_tickers"]) <= 4 for p in plans)
    assert max(i for i, e in enumerate(n) if e == "orchestrator.plan") < n.index("member.status")
    assert sorted(d["member"] for e, d in events if e == "member.verdict") == sorted(MEMBERS)
    assert n.count("chair.summary") == 1
    assert n.index("chair.summary") > max(i for i, e in enumerate(n) if e == "member.verdict")
    assert [d["member"] for e, d in events if e == "member.audio"] == [*MEMBERS, "chair"]  # the chair speaks last
    verdict = next(d for e, d in events if e == "member.verdict")
    assert set(verdict) == {"member", "headline", "analysis", "reasons", "names", "positions", "advice", "sources"}
    assert "signal" not in verdict  # no whole-portfolio call: decisions are per name
    assert {p["ticker"] for p in verdict["positions"]} == set(verdict["names"])
    assert all(p["signal"] in ("BUY", "HOLD", "SELL") and p["conviction"] in ("low", "mid", "high") for p in verdict["positions"])
    chair = next(d for e, d in events if e == "chair.summary")
    assert set(chair) == {"consensus", "positions", "dissent", "actions", "summary", "suggestions"}
    assert chair["summary"].endswith("not financial advice.")
    assert 1 <= len(chair["actions"]) <= 4 and 1 <= len(chair["suggestions"]) <= 3


def test_member_stages_analyse_then_research_names_then_decide(client, jordan_brief_id, kb_results):
    _, events = run_council(client, jordan_brief_id)
    burry = [(e, d) for e, d in events if d.get("member") == "burry"]
    statuses = [d["status"] for e, d in burry if e == "member.status"]
    assert statuses[:4] == ["researching", "analysing", "checking names", "deciding"]
    kinds = [e for e, _ in burry]
    analysis = next(d for e, d in burry if e == "member.analysis")
    assert kinds.index("member.analysis") < kinds.index("member.verdict")
    name_sources = [d["ticker"] for e, d in burry if e == "member.source" and d["ticker"]]
    assert set(name_sources) == set(analysis["names"])  # every name was researched before the calls
    assert analysis["names"][:2] == ["PLTR", "SPY"]  # the two biggest holdings are shared by every member


def test_ruling_is_per_name(client, jordan_brief_id):
    _, events = run_council(client, jordan_brief_id)
    rulings = {r["ticker"]: r for r in next(d for e, d in events if e == "chair.summary")["positions"]}
    assert len(rulings["PLTR"]["calls"]) == len(MEMBERS)  # shared name: the whole council voted
    assert rulings["PLTR"]["consensus"] == "3 of 5 say SELL" and rulings["PLTR"]["conviction"] == "mid"
    assert rulings["NVDA"]["signal"] == "HOLD" and rulings["NVDA"]["consensus"].startswith("split")


def test_plan_covers_large_positions(client, jordan_brief_id):
    _, events = run_council(client, jordan_brief_id)
    covered = {t for e, d in events if e == "orchestrator.plan" for t in d["focus_tickers"]}
    assert {"PLTR", "SPY", "NVDA", "TSLA", "AAPL", "MSFT", "SOFI", "AMD"} <= covered  # every position above 5%


def test_run_roast_changes_headline(client, jordan_brief_id):
    def burry_headline(roast):
        _, events = run_council(client, jordan_brief_id, roast=roast)
        return next(d["headline"] for e, d in events if e == "member.verdict" and d["member"] == "burry")

    assert burry_headline(True) != burry_headline(False)


def test_unknown_brief_is_404(client):
    assert client.post("/api/council/run", json={"brief_id": "nope", "question": "q"}).status_code == 404


def test_chat_routes_named_member(client, jordan_brief_id):
    run_id, _ = run_council(client, jordan_brief_id)
    events = chat(client, run_id, "Burry, why sell PLTR?")
    n = names(events)
    assert n[0] == "run.started" and n[-1] == "run.done"
    assert next(d for e, d in events if e == "chat.routed")["members"] == ["burry"]
    assert [d["member"] for e, d in events if e == "member.reply"] == ["burry"]
    assert "chat.closed" in n and "chair.summary" not in n and "member.verdict" not in n


def test_chat_debate_second_member_rebuts(client, jordan_brief_id):
    run_id, _ = run_council(client, jordan_brief_id)
    events = chat(client, run_id, "Burry and Leopold disagree on NVDA. Settle it.")
    replies = [d for e, d in events if e == "member.reply"]
    assert [r["member"] for r in replies] == ["burry", "leopold"]
    assert replies[1]["text"].startswith("Michael, I see NVDA differently")  # SELL vs BUY on NVDA: Leopold rebuts Burry
    close = next(d for e, d in events if e == "chat.closed")
    assert close["text"] and 2 <= len(close["suggestions"]) <= 3


def test_chat_routes_everyone_meta_and_roast(client, jordan_brief_id):
    run_id, _ = run_council(client, jordan_brief_id)
    routed = lambda text: next(d for e, d in chat(client, run_id, text) if e == "chat.routed")["members"]  # noqa: E731
    assert routed("Everyone: I'm retiring in 5 years. Does that change anything?") == list(MEMBERS)
    assert routed("Who was most bullish, and who disagreed?") == ["chair"]
    assert routed("Roast my portfolio.") == list(MEMBERS)
    assert routed("What should I do with my $60k of savings?") == ["dalio", "buffett"]
    assert routed("anything at all") == ["buffett", "dalio"]
    assert chat(client, run_id, "hi", to=["cramer"])[1][1]["members"] == ["cramer"]


def test_chat_remembers_history(client, jordan_brief_id):
    from app.services import council

    run_id, _ = run_council(client, jordan_brief_id)
    chat(client, run_id, "Dalio, what about my 401k?")
    roles = [h["role"] for h in council.RUNS[run_id]["history"]]
    assert roles[0] == "user" and roles[-2:] == ["user", "dalio"]
    assert len(roles) == 1 + len(MEMBERS) + 1 + 2  # question, five verdicts, ruling, then the chat turn


def test_chat_unknown_run_is_404(client):
    assert client.post("/api/council/chat", json={"run_id": "nope", "text": "q"}).status_code == 404


def test_ask_is_chat_with_one_member(client, jordan_brief_id):
    run_id, _ = run_council(client, jordan_brief_id)
    events = parse_sse(client.post("/api/council/ask", json={"run_id": run_id, "member": "dalio", "question": "Why?"}).text)
    assert [d["member"] for e, d in events if e == "member.reply"] == ["dalio"]


def mock_llm(monkeypatch, handler):
    from app.services import llm

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    real = httpx.AsyncClient

    def respond(request):
        reply = handler(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(reply) + "\n```"}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))


ANALYSIS = {"headline": "h", "analysis": "PLTR is 19.2% of holdings.", "reasons": ["r"], "names": ["COIN", "ZZZZ"]}
ADVICE = {"positions": [{"ticker": "PLTR", "signal": "SELL", "conviction": "high", "rationale": "x"},
                        {"ticker": "SPY", "signal": "SELL", "conviction": "high", "rationale": "x"},
                        {"ticker": "COIN", "signal": "BUY", "conviction": "mid", "rationale": "x"},
                        {"ticker": "GME", "signal": "SELL", "conviction": "mid", "rationale": "not researched"}],
          "advice": [{"action": "Trim PLTR", "tickers": ["PLTR"], "why": "w"}]}
CHAIR = {"consensus": "c", "dissent": [], "actions": ["a"], "summary": "s", "suggestions": ["x"]}


def council_llm(messages, analysis=ANALYSIS, advice=ADVICE):
    system = messages[0]["content"]
    if "Do Job 1" in system:
        return {"burry": {"focus_tickers": ["COIN", "GME"], "questions": ["q1", "q2"]}}  # others fall back to canned
    if "Do Job 3" in system:
        return CHAIR
    return analysis if "Stage 1" in system else advice


def test_run_with_openai_mocked(client, jordan_brief_id, monkeypatch, kb_results):
    mock_llm(monkeypatch, council_llm)
    _, events = run_council(client, jordan_brief_id)
    assert names(events)[-1] == "run.done"
    plan = next(d for e, d in events if e == "orchestrator.plan" and d["member"] == "burry")
    assert plan["focus_tickers"] == ["COIN", "GME"] and plan["shared_tickers"] == ["PLTR", "SPY"]
    analysis = next(d for e, d in events if e == "member.analysis")
    assert analysis["names"] == ["PLTR", "SPY", "COIN"]  # shared first; the unheld ZZZZ is dropped
    calls = {p["ticker"]: p for p in next(d for e, d in events if e == "member.verdict")["positions"]}
    assert set(calls) == {"PLTR", "SPY", "COIN"}  # GME was never researched, so its call is dropped
    assert calls["PLTR"]["conviction"] == "high"  # a quoted source on PLTR backs it
    chair = next(d for e, d in events if e == "chair.summary")
    rulings = {r["ticker"]: r for r in chair["positions"]}
    assert rulings["PLTR"]["signal"] == "SELL" and rulings["PLTR"]["conviction"] == "high"  # 5 of 5, from real calls
    assert chair["summary"].endswith("Parody council, not financial advice.")


def test_kb_reaches_opening_and_chat_research(client, jordan_brief_id, monkeypatch, kb_results):
    seen = []

    def handler(messages):
        seen.append(messages)
        if "live chat" in messages[0]["content"]:
            return {"text": "The retrieved research supports my view."}
        return council_llm(messages)

    mock_llm(monkeypatch, handler)
    run_id, events = run_council(client, jordan_brief_id)
    assert names(events)[-1] == "run.done"
    for member in MEMBERS:
        doc = f"council.{member}.md"
        verdict = next(d for e, d in events if e == "member.verdict" and d["member"] == member)
        sources = verdict["sources"]
        assert all(s["title"] == doc and s["url"] == f"prism-kb://{doc}" for s in sources)
        assert any(s["ticker"] is None for s in sources)
        assert {s["ticker"] for s in sources if s["ticker"]} == set(verdict["names"])
        for stage in ("Stage 1", "Stage 3"):
            prompts = [m[1]["content"] for m in seen if stage in m[0]["content"] and f"prism-kb://{doc}" in m[1]["content"]]
            assert len(prompts) == 1
            for source in sources:
                if (stage == "Stage 1") == (source["ticker"] is None):
                    assert source["quote"] in prompts[0]

    text = "Burry, what is the latest PLTR news?"
    events = chat(client, run_id, text)
    assert names(events)[-1] == "run.done"
    kb_results.assert_any_await("council.burry", text)
    reply = next(d for e, d in events if e == "member.reply")
    assert any(s["quote"] == f"KB research: {text}" and s["ticker"] == "PLTR" for s in reply["sources"])
    assert f"KB research: {text}" in seen[-1][1]["content"]


def test_v1_skips_kb_retrieval(client, jordan_brief_id, monkeypatch, kb_results):
    monkeypatch.setenv("COUNCIL_VERSION", "v1")
    run_id, events = run_council(client, jordan_brief_id)
    events += chat(client, run_id, "Burry, latest PLTR news?")
    kb_results.assert_not_awaited()
    assert all(not d["sources"] for e, d in events if e in ("member.verdict", "member.reply"))
    assert "member.source" not in names(events)


def test_unconfigured_retrieval_has_no_stub_sources(client, jordan_brief_id, monkeypatch):
    monkeypatch.setenv("COUNCIL_VERSION", "v2")
    monkeypatch.delenv("ANCHOR_API_KEY", raising=False)
    run_id, events = run_council(client, jordan_brief_id)
    events += chat(client, run_id, "Burry, latest PLTR news?")
    assert names(events).count("run.done") == 2
    assert all(not d["sources"] for e, d in events if e in ("member.verdict", "member.reply"))
    assert "member.source" not in names(events)


def test_invented_number_is_retried_then_stripped(client, jordan_brief_id, monkeypatch):
    retries = []

    def handler(messages):
        if "Stage 1" in messages[0]["content"]:
            retries.append("previous answer used numbers" in messages[1]["content"])
            return {**ANALYSIS, "analysis": "PLTR is 19.2% of holdings. It will fall 87.3% by spring."}
        return council_llm(messages)

    mock_llm(monkeypatch, handler)
    _, events = run_council(client, jordan_brief_id)
    assert all(d["analysis"] == "PLTR is 19.2% of holdings." for e, d in events if e == "member.verdict")
    assert retries.count(True) == len(MEMBERS)  # exactly one retry per member


def test_bad_llm_output_falls_back_to_canned(client, jordan_brief_id, monkeypatch):
    mock_llm(monkeypatch, lambda m: council_llm(m, analysis={"oops": 1}, advice={"positions": [{"ticker": "PLTR", "signal": "MAYBE"}]}))
    _, events = run_council(client, jordan_brief_id)
    assert names(events)[-1] == "run.done"
    verdicts = [d for e, d in events if e == "member.verdict"]
    assert len(verdicts) == len(MEMBERS) and all(v["positions"] for v in verdicts)


def test_chat_with_openai_mocked(client, jordan_brief_id, monkeypatch):
    run_id, _ = run_council(client, jordan_brief_id)
    seen = []

    def handler(messages):
        seen.append(messages[1]["content"])
        if "Close this chat turn" in messages[0]["content"]:
            return {"text": "Your call.", "suggestions": ["a", "b"]}
        return {"text": "Michael, the capex is real."}

    mock_llm(monkeypatch, handler)
    events = chat(client, run_id, "Burry and Leopold, settle NVDA")
    assert [d["text"] for e, d in events if e == "member.reply"] == ["Michael, the capex is real."] * 2
    assert next(d for e, d in events if e == "chat.closed") == {"text": "Your call.", "suggestions": ["a", "b"]}
    assert "burry (this turn): Michael, the capex is real." in seen[1]  # the second speaker sees the first


def test_demo_page_and_data(client):
    assert "Council demo" in client.get("/demo").text
    assert client.get("/demo/data/portfolio.json").json()["account"]["account_number"]
    assert client.get("/demo/data/spec.md").status_code == 404  # only the two demo files are served


def test_root_redirects_to_demo(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/demo"


def test_llm_retries_rate_limits(monkeypatch):
    import asyncio

    from app.services import llm

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    waits, real_sleep = [], asyncio.sleep
    monkeypatch.setattr(llm.asyncio, "sleep", lambda s: waits.append(s) or real_sleep(0))
    replies = iter([httpx.Response(429), httpx.Response(503, headers={"retry-after": "1"}),
                    httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})])
    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: next(replies)), **kw))
    assert asyncio.run(llm.complete_json("s", "u")) == {"ok": 1}
    assert waits == [1.5, 1.0]  # backoff, then the server's Retry-After


def test_chat_survives_prose_and_failed_replies(client, jordan_brief_id, monkeypatch):
    run_id, _ = run_council(client, jordan_brief_id)
    calls = iter([None, RuntimeError("upstream down")])  # first speaker: prose reply; second: the call fails

    def respond(request):
        if "Close this chat turn" in json.loads(request.content)["messages"][0]["content"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": "no json here"}}]})
        err = next(calls)
        if err:
            raise err
        return httpx.Response(200, json={"choices": [{"message": {"content": "AMD has no catalyst. SELL it!"}}]})

    from app.services import llm

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    events = chat(client, run_id, "AMD is split: Leopold says hold, Jim says sell. Settle it.")
    assert names(events)[-1] == "run.done"
    replies = [d for e, d in events if e == "member.reply"]
    assert [r["member"] for r in replies] == ["leopold", "cramer"]
    assert replies[0]["text"] == "AMD has no catalyst. SELL it!"  # prose accepted as the reply
    assert replies[1]["text"]  # canned fallback instead of a dead turn
    assert next(d for e, d in events if e == "chat.closed")["suggestions"]
