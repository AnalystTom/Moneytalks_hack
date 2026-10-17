import asyncio
import json

import httpx
import pytest

from app.services import council, elevenlabs, llm, personas, prism, tools
from tests.conftest import parse_sse

VERDICT = {"signal": "SELL", "confidence": 0.9, "headline": "h", "reasons": ["r"], "tickers": ["VOO"], "sources": [{"title": "portfolio_lookup", "url": "", "quote": "VOO"}], "line": "say this"}
CHAIR = {"overall_signal": "HOLD", "consensus": "c", "dissent": ["burry: SELL"], "summary": "Warren rules."}
TOOL_CALLS = [
    {"id": f"call-{n}", "type": "function", "function": {"name": n, "arguments": a}}
    for n, a in [("portfolio_lookup", "{}"), ("persona_profile", "{}"), ("specialist_row", "{}")]
]


class FakeLLM:
    """Stands in for Nicrron: assignment -> chair JSON, workers call tools once then answer, ruling -> chair JSON."""

    def __init__(self, verdict=None, replies=None):
        self.calls: list[tuple[str, list[dict], list | None]] = []
        self.verdict = verdict or VERDICT
        self.replies = replies  # optional per-worker scripted replies (list of message dicts), consumed in order

    async def chat(self, messages, tools=None, max_tokens=4096):
        system = messages[0]["content"]
        self.calls.append((system, [dict(m) for m in messages], tools))
        if "ASSIGNMENT PHASE" in messages[1]["content"]:
            who = json.loads(messages[1]["content"].split("Members: ")[1])
            reply = {"assignments": {m["member"]: f"look at X for {m['member']}" for m in who}}
        elif "RULING PHASE" in messages[1]["content"]:
            reply = CHAIR
        elif not any(m["role"] == "tool" for m in messages):
            return self._result({"role": "assistant", "content": None, "tool_calls": TOOL_CALLS})
        else:
            reply = {**self.verdict, "headline": "roasted"} if "ROAST MODE" in messages[1]["content"] else self.verdict
        return self._result({"role": "assistant", "content": "```json\n" + json.dumps(reply) + "\n```"})

    @staticmethod
    def _result(message):
        return {"message": message, "model": "anthropic/claude-opus-5-5", "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "latency_ms": 1}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("NICRRON_API_KEY", "test")
    f = FakeLLM()
    monkeypatch.setattr(llm, "chat", f.chat)
    return f


def run(client, brief_id, **kw):
    return parse_sse(client.post("/api/council/run", json={"brief_id": brief_id, "question": "q", **kw}).text)


def test_fan_out_gives_each_worker_its_own_context(client, brief_id, fake):
    events = run(client, brief_id)
    assert events[-1][0] == "run.done"
    verdicts = [d["member"] for e, d in events if e == "member.verdict"]
    assert sorted(verdicts) == ["buffett", "burry", "cramer", "dalio", "leopold"] and verdicts[-1] == "buffett"
    workers = [(s, m) for s, m, t in fake.calls if "RULING PHASE" not in m[1]["content"] and "ASSIGNMENT PHASE" not in m[1]["content"]]
    assert len(workers) == 10  # 5 workers x (tool round + answer)
    for name in ("Warren Buffett", "Michael Burry", "Jim Cramer", "Leopold Aschenbrenner", "Ray Dalio"):
        mine = [s for s, _ in workers if s.startswith(f"# {name}")]
        assert len(mine) == 2
        others = [n for n in ("Warren Buffett", "Michael Burry", "Jim Cramer", "Leopold Aschenbrenner", "Ray Dalio") if n != name]
        assert not any(f"# {o}" in mine[0] for o in others)  # no persona sees another's prompt
    assert any("look at X for burry" in m[1]["content"] for _, m in workers)  # the chair's assignment reached the worker
    assert all("portfolio_lookup" in s for s, _ in workers)  # skill.md is part of every worker's prompt
    chair = next(d for e, d in events if e == "chair.summary")
    assert chair == CHAIR


def test_worker_output_reaches_the_ui_contract(client, brief_id, fake):
    verdict = next(d for e, d in run(client, brief_id) if e == "member.verdict")
    assert set(verdict) >= {"member", "signal", "confidence", "headline", "reasons", "sources", "tickers", "line"}
    assert verdict["line"] == "say this"


def test_roast_changes_tone_only(client, brief_id, fake):
    run(client, brief_id, roast=True)
    assert all("ROAST MODE" in m[1]["content"] for s, m, t in fake.calls if "ASSIGNMENT PHASE" not in m[1]["content"] and m[0]["role"] == "system" and "RULING" not in m[1]["content"])


def test_invalid_worker_reply_is_repaired_once(client, brief_id, monkeypatch, fake):
    seen = {"n": 0}
    real = fake.chat

    async def flaky(messages, tools=None, max_tokens=4096):
        if "# Michael Burry" in messages[0]["content"] and any(m["role"] == "tool" for m in messages) and seen["n"] == 0:
            seen["n"] += 1
            return fake._result({"role": "assistant", "content": '{"signal": "MAYBE"}'})
        return await real(messages, tools, max_tokens)

    monkeypatch.setattr(llm, "chat", flaky)
    events = run(client, brief_id)
    assert seen["n"] == 1 and events[-1][0] == "run.done"


def test_worker_failing_twice_fails_the_run(client, brief_id, monkeypatch, fake):
    real = fake.chat

    async def broken(messages, tools=None, max_tokens=4096):
        if "# Jim Cramer" in messages[0]["content"]:
            raise ValueError("boom")
        return await real(messages, tools, max_tokens)

    monkeypatch.setattr(llm, "chat", broken)
    assert run(client, brief_id)[-1][0] == "run.error"


def test_five_personas_ship(client, brief_id, fake):
    events = run(client, brief_id)
    assert sorted(d["member"] for e, d in events if e == "member.verdict") == ["buffett", "burry", "cramer", "dalio", "leopold"]


def test_sources_not_returned_by_a_tool_are_dropped(client, brief_id, monkeypatch):
    monkeypatch.setenv("NICRRON_API_KEY", "test")
    monkeypatch.setenv("ANCHOR_API_KEY", "a")
    from app.models import Source
    from app.services import anchor

    async def search(query):
        return [Source(title="Real", url="https://real.example.org/a", quote="q")]

    monkeypatch.setattr(anchor, "search", search)
    answer = {**VERDICT, "sources": [
        {"title": "Real", "url": "https://real.example.org/a", "quote": "q"},
        {"title": "Made up", "url": "https://invented.example.org/z", "quote": "q"},
        {"title": "Portfolio", "url": "", "quote": "VOO 100%"},
        {"title": "Real", "url": "https://real.example.org/a", "quote": "$100"},
        {"title": "Invented title", "url": "https://real.example.org/a", "quote": "q"},
    ]}
    f = FakeLLM(verdict=answer)
    real = f.chat
    search_call = [{"id": "s1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "VOO"}'}}]

    async def chat(messages, tools=None, max_tokens=4096):
        if tools:
            assert "web_search" in [t["function"]["name"] for t in tools]
        if "Research assignment" in messages[1]["content"] and not any(m["role"] == "tool" for m in messages):
            return f._result({"role": "assistant", "content": None, "tool_calls": search_call})
        return await real(messages, tools, max_tokens)

    monkeypatch.setattr(llm, "chat", chat)
    events = run(client, brief_id)
    v = next(d for e, d in events if e == "member.verdict")
    assert [s["url"] for s in v["sources"]] == ["https://real.example.org/a"]
    assert any(e == "member.source" and d["url"] == "https://real.example.org/a" for e, d in events)


async def test_tool_dispatch(monkeypatch):
    brief = {"summary": "s", "holdings": [{"ticker": "PLTR", "shares": 300, "cost_basis": 68.9}, {"ticker": "ZZZZ", "shares": 1, "cost_basis": 1}], "persona": "# Alex", "bank": None}
    burry = personas.load()["burry"]
    whole = await tools.call("portfolio_lookup", {}, brief, burry)
    pltr = next(h for h in whole["holdings"] if h["ticker"] == "PLTR")
    assert pltr == brief["holdings"][0] and whole["account"] is None
    assert (await tools.call("portfolio_lookup", {"ticker": "pltr"}, brief, burry))["holdings"][0]["ticker"] == "PLTR"
    assert "error" in await tools.call("portfolio_lookup", {"ticker": "NOPE"}, brief, burry)
    assert (await tools.call("persona_profile", {}, brief, burry)) == {"profile": "# Alex"}
    assert (await tools.call("specialist_row", {}, brief, burry))["Persona"] == "Michael Burry"
    assert (await tools.call("specialist_row", {"persona": "jim cramer"}, brief, burry))["Persona"] == "Jim Cramer"
    assert "error" in await tools.call("nope", {}, brief, burry)
    assert "error" in await tools.call("web_search", {"query": "x"}, brief, burry)  # not offered without ANCHOR_API_KEY


def test_web_search_is_only_offered_with_anchor(monkeypatch):
    names = lambda: [t["function"]["name"] for t in tools.specs()]  # noqa: E731
    assert names() == ["portfolio_lookup", "persona_profile", "specialist_row"]
    monkeypatch.setenv("ANCHOR_API_KEY", "a")
    assert names()[-1] == "web_search"


def test_prism_gets_a_trace_per_agent_with_run_id_as_session(client, brief_id, fake, monkeypatch):
    for k, v in {"PRISMTRACE_API_KEY": "k", "PRISMTRACE_PROJECT_ID": "p", "PRISMTRACE_HOST": "https://prism.test"}.items():
        monkeypatch.setenv(k, v)
    traces, spans = [], []

    def handler(request):
        assert request.headers["X-PRISMtrace-Key"] == "k"
        body = json.loads(request.content)
        (traces if request.url.path == "/api/traces" else spans).append(body)
        return httpx.Response(200, json={"id": "receipt"})

    real = httpx.AsyncClient
    monkeypatch.setattr(prism.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    events = run(client, brief_id)
    run_id = events[0][1]["run_id"]
    done = events[-1][1]
    assert sorted(t["agent_id"] for t in traces) == ["buffett", "burry", "cramer", "dalio", "leopold", "orchestrator"]
    assert {t["session_id"] for t in traces} == {run_id} and {s["session_id"] for s in spans} == {run_id}
    assert done["trace_id"] in {t["trace_id"] for t in traces} and set(done["traces"]) == {"buffett", "burry", "cramer", "dalio", "leopold"}
    names = [s["name"] for b in spans for s in b["spans"]]
    assert {"worker.burry", "tool.portfolio_lookup", "tool.persona_profile", "tool.specialist_row", "orchestrator.assign", "orchestrator.rule"} <= set(names)
    assert names.count("tool.portfolio_lookup") == 5  # one tool span per call, per worker
    assert all(t["model"] == "anthropic/claude-opus-5-5" for t in traces)


def test_default_model_is_opus_5_5(monkeypatch):
    from app.config import model

    assert model() == "anthropic/claude-opus-5-5"
    monkeypatch.setenv("NICRRON_MODEL", "nicrron/auto")
    assert model() == "anthropic/claude-opus-5-5"
    monkeypatch.setenv("NICRRON_MODEL", "anthropic/claude-sonnet-5-5")
    assert model() == "anthropic/claude-sonnet-5-5"


async def test_voice_matches_name_then_falls_back(monkeypatch, caplog):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    voices = [{"voice_id": "v-bill", "name": "Bill - Wise"}, {"voice_id": "v-warren", "name": "Warren Buffett (clone)"}, {"voice_id": "v-x", "name": "Brian - Deep"}]

    def handler(request):
        return httpx.Response(200, json={"voices": voices})

    real = httpx.AsyncClient
    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    async with elevenlabs.httpx.AsyncClient() as c:
        assert await elevenlabs.voice_for(c, "k", "buffett") == "v-warren"  # matched by name
        with caplog.at_level("WARNING"):
            assert await elevenlabs.voice_for(c, "k", "burry") == "v-x"  # fallback voice named in the persona file
        assert "fallback" in caplog.text
        monkeypatch.setenv("ELEVENLABS_VOICE_CRAMER", "v-env")
        assert await elevenlabs.voice_for(c, "k", "cramer") == "v-env"  # env override wins


def test_follow_up_asks_one_worker_with_its_earlier_verdict(client, brief_id, fake):
    first = run(client, brief_id)
    run_id = first[0][1]["run_id"]
    fake.calls.clear()
    events = parse_sse(client.post("/api/council/ask", json={"run_id": run_id, "member": "burry", "question": "Why sell?"}).text)
    assert events[-1][0] == "run.done" and {d["member"] for e, d in events if "member" in d} == {"burry"}
    assert {s.split("\n")[0] for s, _, _ in fake.calls} == {"# Michael Burry"}  # only Burry's context ran
    assert "What you said earlier" in fake.calls[0][1][1]["content"]
    assert client.post("/api/council/ask", json={"run_id": run_id, "member": "nobody", "question": "q"}).status_code == 422


async def test_audio_cache_is_bounded(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_BURRY", "v")
    monkeypatch.setattr(elevenlabs, "CACHE_LINES", 3)
    real = httpx.AsyncClient
    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"mp3")), **kw))
    for n in range(10):
        await elevenlabs.speak("burry", f"line {n}")
    assert len(elevenlabs._audio) == 3


async def test_uploaded_account_and_profile_never_inherit_demo_data():
    persona = personas.load()["burry"]
    brief = {"summary": "one share", "holdings": [{"ticker": "PLTR", "shares": 1, "cost_basis": 10}], "persona": ""}
    for args in ({}, {"ticker": "pltr"}):
        result = await tools.call("portfolio_lookup", args, brief, persona)
        assert result == {"summary": "one share", "holdings": brief["holdings"], "account": None, "bank": None}
    assert await tools.call("persona_profile", {}, brief, persona) == {"profile": ""}
    brief["persona"] = "constraints\n" * 1000
    assert await tools.call("persona_profile", {}, brief, persona) == {"profile": brief["persona"]}


@pytest.mark.parametrize("who", ["a", "", "cramer", "Burry"])
async def test_specialist_rejects_partial_or_empty_names(who):
    assert "error" in await tools.call("specialist_row", {"persona": who}, {}, personas.load()["burry"])


@pytest.mark.parametrize("source", [
    {"title": "portfolio_lookup", "url": "", "quote": "VOO 100%"},
    {"title": "Invented", "url": "", "quote": "VOO"},
    {"title": "portfolio_lookup", "url": "", "quote": ""},
])
def test_unsupported_local_citations_cannot_produce_verdicts(client, brief_id, monkeypatch, source):
    monkeypatch.setenv("NICRRON_API_KEY", "test")
    f = FakeLLM(verdict={**VERDICT, "sources": [source]})
    monkeypatch.setattr(llm, "chat", f.chat)
    events = run(client, brief_id)
    assert events[-1][0] == "run.error"
    assert not any(e == "member.verdict" for e, _ in events)


def test_worker_must_research_before_returning_verdict(client, brief_id, fake, monkeypatch):
    real = fake.chat

    async def no_research(messages, tools=None, max_tokens=4096):
        if tools:
            return fake._result({"role": "assistant", "content": json.dumps(VERDICT)})
        return await real(messages, tools, max_tokens)

    monkeypatch.setattr(llm, "chat", no_research)
    events = run(client, brief_id)
    assert events[-1][0] == "run.error"
    assert not any(e == "member.verdict" for e, _ in events)


def test_both_chair_calls_receive_full_uploaded_profile_and_holdings(client, fake):
    profile = "# Client\n" + "Long horizon. " * 100 + "\nNeed all this money next month."
    holdings = [{"ticker": "PLTR", "shares": 17, "cost_basis": 68.9}, {"ticker": "VOO", "shares": 1, "cost_basis": 10}]
    response = client.post("/api/ingest", files={
        "portfolio": ("p.json", json.dumps(holdings).encode()),
        "persona": ("p.md", profile.encode()),
    })
    question = "How many PLTR shares should I trim?"
    events = parse_sse(client.post("/api/council/run", json={"brief_id": response.json()["brief_id"], "question": question}).text)
    assert events[-1][0] == "run.done"
    chair_calls = [messages for _, messages, specs in fake.calls if specs is None]
    assert len(chair_calls) == 2
    for messages in chair_calls:
        prompt = messages[1]["content"]
        assert profile in prompt and question in prompt
        assert prompt.count("\nHoldings: ") == 1
        assert json.loads(prompt.split("\nHoldings: ")[1].split("\nClient question: ")[0]) == holdings


@pytest.mark.parametrize("content", [
    "not JSON", "{", "{}",
    json.dumps({**CHAIR, "overall_signal": "MAYBE"}),
    json.dumps({**CHAIR, "consensus": ""}),
    json.dumps({**CHAIR, "summary": "   "}),
])
def test_unusable_chair_ruling_returns_error(client, brief_id, fake, monkeypatch, content):
    real = fake.chat

    async def malformed(messages, tools=None, max_tokens=4096):
        if "RULING PHASE" in messages[1]["content"]:
            return fake._result({"role": "assistant", "content": content})
        return await real(messages, tools, max_tokens)

    monkeypatch.setattr(llm, "chat", malformed)
    events = run(client, brief_id)
    assert sum(e == "member.verdict" for e, _ in events) == 5
    assert events[-1] == ("run.error", {"message": "Council ruling unavailable: the chair returned an unusable response"})
    assert not any(e in ("chair.summary", "member.audio", "run.done") for e, _ in events)


@pytest.mark.parametrize("nested,encoded", [(False, False), (False, True), (True, False), (True, True)])
async def test_anchor_decodes_result_without_corrupting_escapes(monkeypatch, nested, encoded):
    from app.services import anchor

    rows = [{"title": "Report", "url": "https://issuer.test/report", "quote": 'The CEO said "growth"\nC:\\reports\\new — [10]'}]
    result = json.dumps(rows) if encoded else rows
    envelope = {"data": {"result": {"result": result} if nested else result}}
    real = httpx.AsyncClient
    monkeypatch.setattr(anchor.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=envelope)), **kw))
    assert [s.model_dump() for s in await anchor.search("earnings")] == rows


@pytest.mark.parametrize("rows", [None, {}, [{"title": 1, "url": "https://issuer.test", "quote": "q"}], [{"title": "t", "url": "javascript:alert(1)", "quote": "q"}], [{"title": "t", "url": "https://issuer.test", "quote": ""}]])
async def test_anchor_rejects_malformed_sources(monkeypatch, rows):
    from app.services import anchor

    real = httpx.AsyncClient
    monkeypatch.setattr(anchor.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"data": {"result": {"result": rows}}})), **kw))
    with pytest.raises(ValueError):
        await anchor.search("earnings")


@pytest.mark.parametrize("follow_up", [False, True])
async def test_cancellation_awaits_owned_speech_before_finishing_trace(fake, monkeypatch, follow_up):
    brief = {"summary": "s", "holdings": [{"ticker": "VOO", "shares": 1, "cost_basis": 10}], "persona": ""}
    started = asyncio.Event()
    stopped = set()
    active = set()
    finished = []

    async def speak(member, text):
        active.add(member)
        if follow_up:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(member)

    async def rule(*args):
        while len(active) < 4:
            await asyncio.sleep(0)
        started.set()
        await asyncio.Event().wait()

    async def finish(self, output_text, ok=True):
        if self.agent_id in ("orchestrator", "ask-burry"):
            assert stopped == active and active
            finished.append(ok)

    monkeypatch.setattr(elevenlabs, "enabled", lambda: True)
    monkeypatch.setattr(elevenlabs, "speak", speak)
    monkeypatch.setattr(council, "_rule", rule)
    monkeypatch.setattr(prism.Trace, "finish", finish)
    if follow_up:
        stream = council.ask({"brief": brief, "verdicts": {}}, "ask-test", "burry", "q", False)
    else:
        _, stream = council.start_run(brief, "q", False)

    async def consume():
        async for _ in stream:
            pass

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), 2)
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    assert stopped == active and finished == [False]
