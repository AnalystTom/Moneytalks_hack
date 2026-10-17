import json
import shutil

import httpx
import pytest

from app.config import AGENTS_DIR
from app.services import council, elevenlabs, llm, personas, prism, tools
from tests.conftest import parse_sse

VERDICT = {"signal": "SELL", "confidence": 0.9, "headline": "h", "reasons": ["r"], "tickers": ["VOO"], "sources": [], "line": "say this"}
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
            reply = self.verdict
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
    assert sorted(verdicts) == ["buffett", "burry", "cramer", "leopold"] and verdicts[-1] == "buffett"
    workers = [(s, m) for s, m, t in fake.calls if "RULING PHASE" not in m[1]["content"] and "ASSIGNMENT PHASE" not in m[1]["content"]]
    assert len(workers) == 8  # 4 workers x (tool round + answer)
    for name in ("Warren Buffett", "Michael Burry", "Jim Cramer", "Leopold Aschenbrenner"):
        mine = [s for s, _ in workers if s.startswith(f"# {name}")]
        assert len(mine) == 2
        others = [n for n in ("Warren Buffett", "Michael Burry", "Jim Cramer", "Leopold Aschenbrenner") if n != name]
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


def test_a_fifth_persona_is_just_a_file(client, brief_id, fake, monkeypatch, tmp_path):
    shutil.copytree(AGENTS_DIR, tmp_path / "agents")
    (tmp_path / "agents" / "personas" / "dalio.md").write_text(
        "---\nmember: dalio\nname: Ray Dalio\nrole: Macro\norder: 4\nspecialist: Ray Dalio\n---\n# Ray Dalio\nBalance risk across regimes.\n"
    )
    monkeypatch.setattr("app.services.personas.AGENTS_DIR", tmp_path / "agents")
    personas.load.cache_clear()
    try:
        events = run(client, brief_id)
    finally:
        monkeypatch.undo()
        personas.load.cache_clear()
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
    assert [s["url"] for s in v["sources"]] == ["https://real.example.org/a", ""]
    assert any(e == "member.source" and d["url"] == "https://real.example.org/a" for e, d in events)


async def test_tool_dispatch(monkeypatch):
    brief = {"summary": "s", "holdings": [{"ticker": "PLTR", "shares": 300, "cost_basis": 68.9}, {"ticker": "ZZZZ", "shares": 1, "cost_basis": 1}], "persona": "# Alex", "bank": None}
    burry = personas.load()["burry"]
    whole = await tools.call("portfolio_lookup", {}, brief, burry)
    pltr = next(h for h in whole["holdings"] if h["ticker"] == "PLTR")
    assert pltr["sector"] == "Technology" and "portfolio_beta" in whole["account"]
    assert (await tools.call("portfolio_lookup", {"ticker": "pltr"}, brief, burry))["holdings"][0]["ticker"] == "PLTR"
    assert "error" in await tools.call("portfolio_lookup", {"ticker": "NOPE"}, brief, burry)
    assert (await tools.call("persona_profile", {}, brief, burry)) == {"profile": "# Alex"}
    assert (await tools.call("specialist_row", {}, brief, burry))["Persona"] == "Michael Burry"
    assert (await tools.call("specialist_row", {"persona": "cramer"}, brief, burry))["Persona"] == "Jim Cramer"
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
    assert sorted(t["agent_id"] for t in traces) == ["buffett", "burry", "cramer", "leopold", "orchestrator"]
    assert {t["session_id"] for t in traces} == {run_id} and {s["session_id"] for s in spans} == {run_id}
    assert done["trace_id"] in {t["trace_id"] for t in traces} and set(done["traces"]) == {"buffett", "burry", "cramer", "leopold"}
    names = [s["name"] for b in spans for s in b["spans"]]
    assert {"worker.burry", "tool.portfolio_lookup", "tool.persona_profile", "tool.specialist_row", "orchestrator.assign", "orchestrator.rule"} <= set(names)
    assert names.count("tool.portfolio_lookup") == 4  # one tool span per call, per worker
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
