"""Council orchestration: the chair assigns research, one worker per persona file runs in parallel with its own context, the chair rules."""
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlencode

from app.models import Chair, Verdict
from app.services import agents, elevenlabs, llm, personas, prism
from app.services.prism import Trace

log = logging.getLogger(__name__)

RUNS: dict[str, dict] = {}  # run_id -> {"brief", "question", "roast", "verdicts"}; in-memory, see ingest.BRIEFS


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def audio_url(member: str, text: str) -> str:
    return "/api/voice/speak?" + urlencode({"member": member, "text": text})


def _context(brief: dict, question: str, roast: bool) -> str:
    style = "ROAST MODE: only the tone changes; tease the client and the members, keep the signal and reasoning honest.\n" if roast else ""
    return f"{style}Client brief: {brief['summary']}\nClient profile: {brief.get('persona') or ''}\nHoldings: {json.dumps(brief['holdings'])}\nClient question: {question}"


async def _assign(orch: Trace, brief: dict, question: str, roast: bool) -> dict[str, str]:
    """The chair's research assignment per member; a failure here only costs the members their personalised brief."""
    ps = personas.load()
    members = [{"member": p.member, "name": p.name, "role": p.role, "lens": p.body[:700]} for p in ps.values()]
    user = f"ASSIGNMENT PHASE\n{_context(brief, question, roast)}\nMembers: {json.dumps(members)}"
    messages = [{"role": "system", "content": personas.prompt("orchestrator")}, {"role": "user", "content": user}]
    with orch.span("orchestrator.assign", "llm", user) as span:
        try:
            result = await llm.chat(messages)
            span.llm(result)
            span.output = result["message"].get("content") or ""
            plan = llm.extract_json(span.output)["assignments"]
            return {m: str(plan[m]) for m in ps if m in plan}
        except (ValueError, KeyError, TypeError) as e:
            log.warning("orchestrator assignment unusable, workers run unbriefed: %s", e)
            span.error = str(e)
            return {}


async def _rule(orch: Trace, brief: dict, question: str, roast: bool, verdicts: dict[str, Verdict]) -> Chair:
    chair = personas.chair()
    system = f"{personas.prompt('orchestrator')}\n\n---\n\n{chair.body}"
    user = f"RULING PHASE\n{_context(brief, question, roast)}\nVerdicts: " + json.dumps({m: v.model_dump(exclude={"sources"}) for m, v in verdicts.items()})
    with orch.span("orchestrator.rule", "llm", user) as span:
        try:
            result = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
            span.llm(result)
            span.output = result["message"].get("content") or ""
            ruling = Chair(**llm.extract_json(span.output))
            if not ruling.consensus.strip() or not ruling.summary.strip():
                raise ValueError("the chair returned blank ruling text")
            return ruling
        except (ValueError, TypeError, KeyError) as e:
            raise ValueError("Council ruling unavailable: the chair returned an unusable response") from e


async def _member(persona, run_id: str, brief: dict, question: str, roast: bool, assignment: str, emit, orch: Trace,
                  earlier: str = "", hold: asyncio.Event | None = None) -> tuple[Verdict, str | None]:
    """One worker end to end: its own PRISM trace, its status/source events, then its verdict (after `hold`, for the chair)."""
    trace = Trace(run_id, persona.member, assignment or question)
    with orch.span(f"worker.{persona.member}", "agent", assignment or question) as span:
        try:
            if not llm.enabled():
                raise ValueError("Council unavailable: NICRRON_API_KEY is not configured")
            for attempt in (1, 2):
                try:
                    verdict = await agents.run(persona, brief, question, roast, assignment, trace, emit, earlier)
                    break
                except (llm.httpx.HTTPError, ValueError) as e:
                    log.warning("worker %s attempt %d failed: %s", persona.member, attempt, e)
                    if attempt == 2:
                        raise
            span.output = verdict.headline
        except BaseException as e:
            await trace.finish(str(e), ok=False)
            raise
        trace_id = await trace.finish(verdict.headline)
        span.meta = {"trace_id": trace_id}
    if hold:
        await hold.wait()
    await emit("member.verdict", {"member": persona.member, **verdict.model_dump()})
    return verdict, trace_id


async def _tts(member: str, text: str, orch: Trace) -> None:
    """Synthesise ahead of the `speaking` beat so the browser's audio fetch is a cache hit; a failure leaves the URL to 503 on its own."""
    if not elevenlabs.enabled():
        return
    with orch.span(f"tool.elevenlabs.speak.{member}", "tool", text) as span:
        try:
            span.output = f"{len(await elevenlabs.speak(member, text))} bytes of audio/mpeg"
        except elevenlabs.VoiceError as e:
            log.warning("speech for %s failed: %s", member, e)
            span.error = str(e)


async def _speak(member: str, text: str, speech: asyncio.Task, emit) -> None:
    await emit("member.status", {"member": member, "status": "speaking"})
    await speech
    await emit("member.audio", {"member": member, "audio_url": audio_url(member, text)})
    await emit("member.status", {"member": member, "status": "done"})


def _line(v: Verdict) -> str:
    return v.line or f"{v.headline}. " + " ".join(v.reasons[:2])


def _earlier(v: Verdict) -> str:
    return f"{v.headline}. " + " ".join(v.reasons)


async def _stream(body, run_id: str) -> AsyncIterator[str]:
    """Run `body(emit)` as a task and yield its events as SSE; failures become run.error."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put(sse(event, data))

    async def main() -> None:
        try:
            await emit("run.done", {"run_id": run_id, **await body(emit)})
        except Exception as e:  # surface any failure to the client instead of dropping the stream
            log.exception("council run %s failed", run_id)
            await emit("run.error", {"message": str(e) or type(e).__name__})
        await queue.put(None)

    task = asyncio.create_task(main())
    await emit("run.started", {"run_id": run_id})
    try:
        while (item := await queue.get()) is not None:
            yield item
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def start_run(brief: dict, question: str, roast: bool) -> tuple[str, AsyncIterator[str]]:
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"brief": brief, "question": question, "roast": roast, "verdicts": {}}

    async def body(emit) -> dict:
        ps = personas.load()
        chair = personas.chair()
        orch = Trace(run_id, "orchestrator", _context(brief, question, roast))
        speech: dict[str, asyncio.Task] = {}
        tasks: list[asyncio.Task] = []
        try:
            if not llm.enabled():
                raise ValueError("Council unavailable: NICRRON_API_KEY is not configured")
            assignments = await _assign(orch, brief, question, roast)
            chair_may_speak = asyncio.Event()  # Warren's verdict lands after the other members'
            tasks = [
                asyncio.create_task(_member(p, run_id, brief, question, roast, assignments.get(p.member, ""), emit, orch,
                                            hold=chair_may_speak if p.chair else None))
                for p in ps.values()
            ]
            others = [t for t, p in zip(tasks, ps.values()) if not p.chair]
            await asyncio.gather(*others)
            chair_may_speak.set()
            results = dict(zip(ps, await asyncio.gather(*tasks)))
            verdicts = {m: v for m, (v, _) in results.items()}
            traces = {m: t for m, (_, t) in results.items() if t}
            RUNS[run_id]["verdicts"] = verdicts
            for m, v in verdicts.items():
                if m != chair.member:  # the chair speaks the ruling, not his verdict line
                    speech[m] = asyncio.create_task(_tts(m, _line(v), orch))
            ruling = await _rule(orch, brief, question, roast, verdicts)
            await emit("chair.summary", ruling.model_dump())
            speech["chair"] = asyncio.create_task(_tts(chair.member, ruling.summary, orch))
            for m in ps:
                if m != chair.member:
                    await _speak(m, _line(verdicts[m]), speech[m], emit)
            await _speak(chair.member, ruling.summary, speech["chair"], emit)
        except BaseException as e:
            owned = [*tasks, *speech.values()]
            for t in owned:
                t.cancel()
            await asyncio.gather(*owned, return_exceptions=True)
            await orch.finish(str(e) or type(e).__name__, ok=False)
            raise
        trace_id = await orch.finish(f"{ruling.overall_signal}: {ruling.consensus}")
        return {"trace_id": trace_id, "traces": traces}

    return run_id, _stream(body, run_id)


def ask(run: dict, run_id: str, member: str, question: str, roast: bool) -> AsyncIterator[str]:
    async def body(emit) -> dict:
        persona = personas.load()[member]
        orch = Trace(run_id, f"ask-{member}", question)
        speech = None
        try:
            prior = run["verdicts"].get(member)
            verdict, trace_id = await _member(persona, run_id, run["brief"], question, roast, "", emit, orch, _earlier(prior) if prior else "")
            speech = asyncio.create_task(_tts(member, _line(verdict), orch))
            await _speak(member, _line(verdict), speech, emit)
        except BaseException as e:
            if speech is not None:
                speech.cancel()
                await asyncio.gather(speech, return_exceptions=True)
            await orch.finish(str(e) or type(e).__name__, ok=False)
            raise
        await orch.finish(verdict.headline)
        return {"trace_id": trace_id}

    return _stream(body, run_id)
