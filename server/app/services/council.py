"""Council orchestration: Warren hands out the research, the other three run in parallel, then Warren rules."""
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from app.config import COUNCIL_DIR, MEMBERS
from app.models import Chair, Source, Verdict
from app.services import anchor, llm, prism
from app.services.store import put

log = logging.getLogger(__name__)

RUNS: dict[str, dict] = {}  # run_id -> {"brief", "question", "roast"}; in-memory, see ingest.BRIEFS
LINES: dict[str, tuple[str, str]] = {}  # line_id -> (member, text) behind member.audio URLs
PARALLEL = [m for m in MEMBERS if m != "buffett"]

CANNED = {
    "buffett": ("HOLD", 0.7, "Keep owning the index and keep buying", "Hold the index fund; down 30% is a price, not a loss."),
    "cramer": ("BUY", 0.6, "The trend is your friend, keep buying", "Keep dollar-cost averaging; momentum turns."),
    "burry": ("SELL", 0.55, "Everything is priced for perfection", "Trim hard; valuations assume nothing goes wrong."),
    "leopold": ("BUY", 0.65, "The AI build-out is the trendline", "Tilt toward AI infrastructure."),
}
CANNED_ROAST = {
    "buffett": "Down 30% in an index fund? Even my nap schedule is more active.",
    "cramer": "BOOYAH, you bought the top! Sound effect: sad trombone!",
    "burry": "I shorted a housing bubble; you built a portfolio-shaped one.",
    "leopold": "You're down 30% while the compute curve goes vertical. Bold.",
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def audio_url(member: str, text: str) -> str:
    """Park the server-written line under an opaque id so the audio URL can't be used to voice arbitrary text."""
    line_id = uuid.uuid4().hex
    put(LINES, line_id, (member, text))
    return f"/api/voice/line/{line_id}"


def _persona(member: str) -> str:
    return (COUNCIL_DIR / f"{member}.md").read_text()


def _context(brief: dict, question: str, roast: bool) -> str:
    style = "Roast the user's portfolio mercilessly but stay in character and keep it comedic. " if roast else ""
    return f"{style}Client brief: {brief['summary']}\nPersona profile:\n{brief['persona']}\nHoldings: {json.dumps(brief['holdings'])}\nQuestion: {question}"


async def _verdict(member: str, brief: dict, question: str, roast: bool, sources: list[Source]) -> Verdict:
    if not llm.enabled():
        signal, conf, headline, reason = CANNED[member]
        if roast:
            headline = CANNED_ROAST[member]
        return Verdict(
            signal=signal, confidence=conf, headline=headline, sources=sources, tickers=[h["ticker"] for h in brief["holdings"]],
            reasons=[reason, f"Canned answer to: {question[:80]}", "Set NICRRON_API_KEY for live research."],
        )
    system = (
        f"You are this council member:\n{_persona(member)}\n"
        'Reply with only a JSON object: {"signal":"BUY|HOLD|SELL","confidence":0-1,"headline":str,"reasons":[2-3 str],'
        '"tickers":[str],"sources":[{"title","url","quote"}]}. Cite ONLY the provided sources; never invent a number or quote.'
    )
    user = _context(brief, question, roast) + f"\nSources: {json.dumps([s.model_dump() for s in sources])}"
    return Verdict(**await llm.complete_json(system, user))


async def _chair(brief: dict, question: str, roast: bool, verdicts: dict[str, Verdict]) -> Chair:
    if not llm.enabled():
        signals = [v.signal for v in verdicts.values()]
        overall = max(set(signals), key=signals.count)
        dissent = [f"{m}: {v.signal}" for m, v in verdicts.items() if v.signal != overall]
        text = "Order, order. " + ("The council roasts you equally. " if roast else "") + f"Overall: {overall}."
        return Chair(overall_signal=overall, consensus=f"{signals.count(overall)} of {len(signals)} say {overall}", dissent=dissent, summary=text)
    system = (
        f"You are the council chair:\n{_persona('buffett')}\n"
        'Reply with only a JSON object: {"overall_signal":"BUY|HOLD|SELL","consensus":str,"dissent":[str],"summary":str}. '
        "summary is spoken aloud by you in 3-4 sentences."
    )
    user = _context(brief, question, roast) + "\nVerdicts: " + json.dumps({m: v.model_dump() for m, v in verdicts.items()})
    return Chair(**await llm.complete_json(system, user))


async def _member(member: str, run_id: str, brief: dict, question: str, roast: bool, emit) -> Verdict:
    """Research -> think -> verdict -> speak, emitting events through `emit`."""
    await emit("member.status", {"member": member, "status": "researching"})
    sources = await anchor.search(member, question)
    for s in sources:
        await emit("member.source", {"member": member, "title": s.title, "url": s.url})
    await emit("member.status", {"member": member, "status": "thinking"})
    verdict = await _verdict(member, brief, question, roast, sources)
    await prism.span(run_id, f"council.{member}", "agent", question, verdict.headline)
    await emit("member.verdict", {"member": member, **verdict.model_dump()})
    return verdict


async def _speak(member: str, text: str, emit) -> None:
    await emit("member.status", {"member": member, "status": "speaking"})
    await emit("member.audio", {"member": member, "audio_url": audio_url(member, text)})
    await emit("member.status", {"member": member, "status": "done"})


def _line(v: Verdict) -> str:
    return f"{v.headline}. " + " ".join(v.reasons[:2])


async def _stream(body, run_id: str) -> AsyncIterator[str]:
    """Run `body(emit)` as a task and yield its events as SSE; failures become run.error."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put(sse(event, data))

    async def main() -> None:
        try:
            await body(emit)
            await emit("run.done", {"run_id": run_id})
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


def start_run(brief: dict, question: str, roast: bool) -> tuple[str, AsyncIterator[str]]:
    run_id = uuid.uuid4().hex
    put(RUNS, run_id, {"brief": brief, "question": question, "roast": roast})

    async def body(emit) -> None:
        verdicts = dict(zip(PARALLEL, await asyncio.gather(*(_member(m, run_id, brief, question, roast, emit) for m in PARALLEL))))
        verdicts["buffett"] = await _member("buffett", run_id, brief, question, roast, emit)
        chair = await _chair(brief, question, roast, verdicts)
        await emit("chair.summary", chair.model_dump())
        for m in PARALLEL:
            await _speak(m, _line(verdicts[m]), emit)
        await _speak("buffett", chair.summary, emit)

    return run_id, _stream(body, run_id)


def ask(run: dict, run_id: str, member: str, question: str, roast: bool) -> AsyncIterator[str]:
    async def body(emit) -> None:
        verdict = await _member(member, run_id, run["brief"], question, roast, emit)
        await _speak(member, _line(verdict), emit)

    return _stream(body, run_id)
