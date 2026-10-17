from tests.conftest import parse_sse
from tests.test_agents import fake  # noqa: F401


def names(events):
    return [e for e, _ in events]


def test_run_event_order(client, brief_id, fake):
    r = client.post("/api/council/run", json={"brief_id": brief_id, "question": "Keep DCA, sell, or move?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    n = names(events)
    assert n[0] == "run.started" and n[-1] == "run.done"
    verdicts = [d["member"] for e, d in events if e == "member.verdict"]
    assert sorted(verdicts) == ["buffett", "burry", "cramer", "dalio", "leopold"]
    assert verdicts[-1] == "buffett"  # Warren speaks after the other four
    assert n.count("chair.summary") == 1
    assert n.index("chair.summary") > max(i for i, e in enumerate(n) if e == "member.verdict")
    assert sorted(d["member"] for e, d in events if e == "member.audio") == ["buffett", "burry", "cramer", "dalio", "leopold"]
    verdict = next(d for e, d in events if e == "member.verdict")
    assert set(verdict) >= {"member", "signal", "confidence", "headline", "reasons", "sources", "tickers"}
    chair = next(d for e, d in events if e == "chair.summary")
    assert set(chair) == {"overall_signal", "consensus", "dissent", "summary"}


def test_run_roast_changes_headline(client, brief_id, fake):
    def burry_headline(roast):
        r = client.post("/api/council/run", json={"brief_id": brief_id, "question": "q", "roast": roast})
        return next(d["headline"] for e, d in parse_sse(r.text) if e == "member.verdict" and d["member"] == "burry")

    assert burry_headline(True) != burry_headline(False)


def test_unknown_brief_is_404(client):
    assert client.post("/api/council/run", json={"brief_id": "nope", "question": "q"}).status_code == 404


def test_ask_one_member(client, brief_id, fake):
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


def test_no_model_key_returns_errors_for_run_and_follow_up(client, brief_id):
    first = parse_sse(client.post("/api/council/run", json={"brief_id": brief_id, "question": "q"}).text)
    run_id = first[0][1]["run_id"]
    follow = parse_sse(client.post("/api/council/ask", json={"run_id": run_id, "member": "burry", "question": "q"}).text)
    for events in (first, follow):
        assert names(events) == ["run.started", "run.error"]
        assert "NICRRON_API_KEY" in events[-1][1]["message"]
    assert client.get("/api/health").json()["llm"] == "unavailable"
