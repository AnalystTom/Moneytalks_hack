from tests.conftest import parse_sse


def names(events):
    return [e for e, _ in events]


def test_run_event_order_canned(client, brief_id):
    r = client.post("/api/council/run", json={"brief_id": brief_id, "question": "Keep DCA, sell, or move?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    n = names(events)
    assert n[0] == "run.started" and n[-1] == "run.done"
    verdicts = [d["member"] for e, d in events if e == "member.verdict"]
    assert sorted(verdicts) == ["buffett", "burry", "cramer", "leopold"]
    assert verdicts[-1] == "buffett"  # Warren speaks after the other three
    assert n.count("chair.summary") == 1
    assert n.index("chair.summary") > max(i for i, e in enumerate(n) if e == "member.verdict")
    assert sorted(d["member"] for e, d in events if e == "member.audio") == ["buffett", "burry", "cramer", "leopold"]
    verdict = next(d for e, d in events if e == "member.verdict")
    assert set(verdict) >= {"member", "signal", "confidence", "headline", "reasons", "sources", "tickers"}
    chair = next(d for e, d in events if e == "chair.summary")
    assert set(chair) == {"overall_signal", "consensus", "dissent", "summary"}


def test_run_roast_changes_headline(client, brief_id):
    def burry_headline(roast):
        r = client.post("/api/council/run", json={"brief_id": brief_id, "question": "q", "roast": roast})
        return next(d["headline"] for e, d in parse_sse(r.text) if e == "member.verdict" and d["member"] == "burry")

    assert burry_headline(True) != burry_headline(False)


def test_unknown_brief_is_404(client):
    assert client.post("/api/council/run", json={"brief_id": "nope", "question": "q"}).status_code == 404


def test_ask_one_member(client, brief_id):
    run = client.post("/api/council/run", json={"brief_id": brief_id, "question": "q"})
    run_id = parse_sse(run.text)[0][1]["run_id"]
    r = client.post("/api/council/ask", json={"run_id": run_id, "member": "burry", "question": "Why sell?"})
    events = parse_sse(r.text)
    assert names(events)[0] == "run.started" and names(events)[-1] == "run.done"
    assert {d["member"] for e, d in events if "member" in d} == {"burry"}
    assert "chair.summary" not in names(events)
    assert "member.verdict" in names(events) and "member.audio" in names(events)


def test_ask_unknown_run_is_404(client):
    assert client.post("/api/council/ask", json={"run_id": "nope", "member": "burry", "question": "q"}).status_code == 404


def test_run_with_nicrron_mocked(client, brief_id, monkeypatch):
    import json

    import httpx

    from app.services import llm

    monkeypatch.setenv("NICRRON_API_KEY", "test")
    verdict = {"signal": "SELL", "confidence": 0.9, "headline": "h", "reasons": ["r"], "tickers": ["VOO"], "sources": []}
    chair = {"overall_signal": "SELL", "consensus": "c", "dissent": [], "summary": "s"}

    def handler(request):
        system = json.loads(request.content)["messages"][0]["content"]
        reply = chair if "council chair" in system else verdict
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(reply) + "\n```"}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    events = parse_sse(client.post("/api/council/run", json={"brief_id": brief_id, "question": "q"}).text)
    assert names(events)[-1] == "run.done"
    assert next(d for e, d in events if e == "chair.summary")["overall_signal"] == "SELL"
    assert next(d for e, d in events if e == "member.verdict")["headline"] == "h"
