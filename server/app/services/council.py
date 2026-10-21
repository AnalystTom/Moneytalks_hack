"""Council orchestration: the coordinator plans, five specialists research in parallel, the coordinator
verifies and rules, then runs the chat. Design: council/README.md; coordinator rules: services/coordinator.py."""
import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlencode

from app.config import CHAIR, COUNCIL_DIR, MEMBERS, council_version
from app.models import Advice, Analysis, Assignment, Chair, PositionCall, Source, Verdict
from app.services import coordinator, llm, prism, store

log = logging.getLogger(__name__)

RUNS: dict[str, dict] = {}  # run_id -> brief, assignments, verdicts, chair, history; cache in front of the durable store
LENS_QUERIES, NAME_QUERIES, MAX_NAMES, HISTORY_TURNS = 2, 2, 5, 12
QUERIES = {  # stage 1 research playbooks from council/<member>.md, filled with the assignment's focus tickers
    "buffett": ["{0} annual results free cash flow", "{0} valuation vs 10-year average", "{0} competitive moat threats news"],
    "dalio": ["Fed policy rate path latest CPI", "US 10-year yield real yield trend", "equity bond correlation this year", "{0} macro risk"],
    "burry": ["{0} valuation multiple P/E P/S", "{all} short interest insider selling", "{0} latest earnings revenue growth cash burn"],
    "leopold": ["hyperscaler AI capex guidance", "data center power demand grid constraints", "{0} latest results AI revenue", "chip export controls news"],
    "cramer": ["{0} next earnings date expectations", "{all} news catalyst", "{0} analyst upgrades downgrades this month"],
}
PER_NAME = ["{t} stock latest news", "{t} earnings results analyst rating valuation"]  # stage 2, for every name a member checks
NEEDS_SEARCH = re.compile(r"\b(latest|today|news|now|this week|this month|earnings|just|recent)\b", re.I)

CANNED = {  # no-LLM portfolio analysis; numbers are filled from the brief so they always pass verification
    "buffett": ("Own fewer, better businesses and stop trading the rest",
                "Price is what you pay, value is what you get: {top} at {top_w}% of holdings is a bet, not a business plan."),
    "dalio": ("One regime, one bet: this book only works if growth stays hot",
              "The connected brokerage is mostly equities with no bonds, TIPS or gold; a stagflation regime hits every line at once."),
    "burry": ("The biggest winner has become the biggest risk",
              "{top} is {top_w}% of holdings after {top_pnl}%; that is a crowded trade priced for perfection."),
    "leopold": ("The AI build-out is the trendline; own the bottlenecks",
                "AI exposure sits in a few names; compute, power and memory bottlenecks are under-owned."),
    "cramer": ("Are you diversified?! [AIR HORN] No!",
               "Tech is {tech}% of holdings and {worst} is {worst_pnl}%: that's not a portfolio, that's a hope chest!"),
}
CANNED_ADVICE = {
    "buffett": Advice(action="Keep buying a low-cost index fund every month", why="No forecasting needed."),
    "dalio": Advice(action="Add bonds/TIPS/gold at 15-25% of investable assets", why="Balance growth and inflation risk."),
    "burry": Advice(action="Cap any single name at 10% of holdings", why="Concentration after a big run."),
    "leopold": Advice(action="Rotate part of the AI exposure into power and semicap", why="Own the bottleneck, not the crowd."),
    "cramer": Advice(action="Do one hour of homework per stock per week, or own fewer stocks", why="Hope is not a strategy!"),
}


def _etf(p: dict) -> bool:
    return p["ticker"] in coordinator.DIVERSIFIERS or "ETF" in p.get("sector", "")


def _call(member: str, p: dict) -> tuple[str, str, str]:
    """Canned per-name decision through each lens: (signal, conviction, rationale), numbers from the brief."""
    t, w, pnl, spec = p["ticker"], p["weight_pct"], p["pnl_pct"], p.get("role") == "speculative"
    if member == "buffett":
        if _etf(p):
            return "BUY", "high", f"{t}: a low-cost index is the one thing everybody should keep buying."
        if spec:
            return "SELL", "high", f"{t} at {pnl:+}% is speculation, not a business I can value."
        return "HOLD", "mid", f"{t} is a real business; at {w}% of holdings, hold it and stop checking the price."
    if member == "dalio":
        if _etf(p):
            return "HOLD", "mid", f"{t} is the closest thing here to a diversifier, but it is still equity risk."
        if p.get("beta", 1) >= 1.5:
            return "SELL", "mid", f"{t} has beta {p.get('beta')}; it doubles down on the one regime this book already bets on."
        return "HOLD", "low", f"{t} at {w}% is fine on its own; the problem is what the whole book is missing."
    if member == "burry":
        if pnl >= 50 and w >= 10:
            return "SELL", "high", f"{t} is {w}% of holdings after {pnl:+}%; priced for perfection, and you own too much of it."
        if pnl >= 50:
            return "SELL", "mid", f"{t} is up {pnl:+}%; take the gift before the crowd does."
        return "HOLD", "low", f"{t} at {pnl:+}% is not where the risk is."
    if member == "leopold":
        if t in coordinator.AI_TICKERS:
            return "BUY", "high" if pnl < 0 else "mid", f"{t} sits on the AI build-out; at {pnl:+}% the trendline matters more than the entry."
        return "HOLD", "low", f"{t} is outside the AI thesis; no strong view."
    if spec or pnl <= -25:
        return "SELL", "high" if spec else "mid", f"{t} at {pnl:+}%: [BUZZER] dead money until there's a catalyst!"
    if pnl >= 100:
        return "SELL", "low", f"{t} up {pnl:+}%! Ring the register on some of it! [CASH REGISTER]"
    return "BUY", "low", f"{t}: I like it, but do the homework!"
CANNED_ROAST = {
    "buffett": "I've held Coca-Cola longer than you've held a single opinion.",
    "dalio": "Your all-weather strategy is: hope it's sunny.",
    "burry": "I shorted a housing bubble; you built a portfolio-shaped one.",
    "leopold": "You own the AI hype and none of the AI bottlenecks. Bold.",
    "cramer": "BOOYAH! [SAD TROMBONE] You bought every top on my show!",
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def audio_url(member: str, text: str) -> str:
    return "/api/voice/speak?" + urlencode({"member": member, "text": text[:2500]})


def _persona(member: str) -> str:
    text = (COUNCIL_DIR / f"{'orchestrator' if member == CHAIR else member}.md").read_text()
    return text.split("**v1 voice mode only:**")[0]  # text chat: leave out the voice-tag format


def _brief_text(brief: dict) -> str:
    return f"Client brief: {brief['summary']}\nPersona profile:\n{brief['persona']}\nPortfolio facts (pre-computed, use these numbers): {json.dumps(brief['facts'])}"


def _roast(roast: bool) -> str:
    return "ROAST MODE: roast the user's portfolio mercilessly, stay in character, keep it comedic, still no invented facts.\n" if roast else ""


def _performance_gap(f: dict) -> str | None:
    if not f["positions"]:
        return "No holdings were provided; positions, concentration and performance cannot be assessed from the user's notes alone."
    if any(p["weight_pct"] is None or p["pnl_pct"] is None for p in f["positions"]):
        return "Current valuation or profit/loss is unavailable; missing prices and cost basis must be supplied before assessing concentration or performance."


def _fill(text: str, f: dict) -> str:
    if gap := _performance_gap(f):
        return gap
    pos = f["positions"]
    worst = min(pos, key=lambda p: p["pnl_pct"])
    return text.format(
        top=pos[0]["ticker"], top_w=pos[0]["weight_pct"], top_pnl=f"{pos[0]['pnl_pct']:+}",
        tech=f["sector_mix_pct"].get("Technology", 0), worst=worst["ticker"], worst_pnl=f"{worst['pnl_pct']:+}",
    )


def _held(brief: dict) -> list[str]:
    return [p["ticker"] for p in brief["facts"]["positions"]]


def _names(picked: list[str], a: Assignment) -> list[str]:
    """Names to research and call: the shared biggest holdings first, then the member's own picks."""
    return list(dict.fromkeys([*a.shared_tickers, *picked]))[:MAX_NAMES]


def _sources_json(sources: list[Source]) -> str:
    return json.dumps([s.model_dump(exclude_none=True) for s in sources])


# --- opening run -------------------------------------------------------------


async def _plan(run_id: str, brief: dict) -> dict[str, Assignment]:
    canned = coordinator.plan(brief)
    if not llm.enabled() or not brief["facts"]["positions"]:
        return canned
    system = (
        f"{_persona(CHAIR)}\nDo Job 1 only. Reply with only a JSON object keyed by member id "
        f"({', '.join(MEMBERS)}), each {{\"focus_tickers\":[2-4 tickers from the brief],\"questions\":[2-3 str]}}."
    )
    try:
        plan = coordinator.merge_plan(canned, await llm.complete_json(system, _brief_text(brief)))
    except (ValueError, KeyError) as e:  # a bad plan must not sink the run
        log.warning("plan fell back to canned: %s", e)
        plan = canned
    await prism.span(run_id, "council.plan", "agent", brief["summary"], json.dumps({m: a.model_dump() for m, a in plan.items()}))
    return plan


async def _search(member: str, queries: list[str], emit, ticker: str | None = None, limit: int = 2) -> list[Source]:
    found: dict[tuple[str, str], Source] = {}
    results = [] if council_version() == "v1" else await asyncio.gather(*(prism.kb_search(f"council.{member}", q) for q in queries))
    for chunks in results:
        for r in chunks:
            s = Source(title=r["doc_name"], url=f"prism-kb://{r['doc_name']}", quote=r["content"][:1200], ticker=ticker)
            found.setdefault((s.url, s.quote), s)
    out = list(found.values())[:limit]
    for s in out:
        await emit("member.source", {"member": member, "title": s.title, "url": s.url, "ticker": ticker})
    return out


async def _llm_checked(build, system: str, user: str, run_id: str, stage: str, brief: dict, sources: list[Source]):
    """One structured LLM call, verified (Job 2): unsupported numbers get one retry, then are stripped."""
    out = build(await llm.complete_json(system, user))
    if bad := coordinator.unsupported(out, brief, sources):
        await prism.span(run_id, f"verify.{stage}", "evaluator", out.model_dump_json(), f"unsupported: {bad}", ok=False)
        retry = user + f"\nYour previous answer used numbers found in neither the brief nor the sources: {bad}. Remove or correct them."
        out = build(await llm.complete_json(system, retry))
        if bad := coordinator.unsupported(out, brief, sources):
            out = coordinator.strip_unsupported(out, bad)
    return out


ANALYSIS_SCHEMA = (
    'Stage 1, portfolio analysis. Do NOT give buy/hold/sell calls yet. Reply with only a JSON object: {"headline":str,'
    '"analysis":"2-4 sentences in character about the whole portfolio and balance sheet","reasons":[2-3 observations],'
    f'"names":[2-{MAX_NAMES - 2} held tickers you want to research before deciding on them]}}. '
    "The assignment's shared_tickers are always researched and called too. "
    "Use ONLY numbers from the brief or the sources; never invent a number or quote."
)
ADVICE_SCHEMA = (
    "Stage 3, advice. You researched each name below. Reply with only a JSON object: "
    '{"positions":[one per researched name {"ticker":str,"signal":"BUY|HOLD|SELL","conviction":"low|mid|high","rationale":"1-2 sentences"}],'
    '"advice":[1-3 portfolio-level {"action":str,"tickers":[str],"why":str}]}. '
    "Conviction: high = your lens applies squarely and that name's sources clearly support the call; mid = sound but mixed; "
    "low = thin evidence. Every advice item says what to do. Use ONLY numbers from the brief or the sources."
)


async def _analyse(member: str, run_id: str, brief: dict, a: Assignment, roast: bool, sources: list[Source]) -> Analysis:
    f = brief["facts"]
    headline, text = CANNED[member]
    canned = Analysis(headline=_fill(CANNED_ROAST[member] if roast else headline, f), analysis=_fill(text, f),
                      reasons=[_fill(text, f), f"Assignment: {a.questions[0]}"], names=_names(a.focus_tickers, a))
    if not llm.enabled():
        return canned
    system = f"You are this council member:\n{_persona(member)}\n{ANALYSIS_SCHEMA}"
    user = _roast(roast) + _brief_text(brief) + f"\nYour assignment: {a.model_dump_json()}\nSources: {_sources_json(sources)}"
    try:
        out = await _llm_checked(Analysis.model_validate, system, user, run_id, f"{member}.analysis", brief, sources)
    except Exception as e:  # one member's bad reply must not sink the run: canned analysis, failure traced for PRISM
        log.warning("%s analysis fell back to canned: %s", member, e)
        await prism.span(run_id, f"council.{member}.analysis", "agent", json.dumps(a.questions), f"{type(e).__name__}: {e}", ok=False)
        return canned
    held = _held(brief)
    picked = [t for t in dict.fromkeys(n.upper() for n in out.names) if t in held]
    return out.model_copy(update={"names": _names(picked or a.focus_tickers, a)})


async def _advise(member: str, run_id: str, brief: dict, an: Analysis, roast: bool, research: dict[str, list[Source]], sources: list[Source]) -> Verdict:
    pos = {p["ticker"]: p for p in brief["facts"]["positions"]}
    gap = _performance_gap(brief["facts"])
    fallback = an.model_copy(update={"headline": gap, "analysis": gap, "reasons": [gap]}) if gap else an
    canned = Verdict(**fallback.model_dump(), sources=sources,
                     advice=[Advice(action=gap, why=gap) if gap else CANNED_ADVICE[member]], positions=[
        PositionCall(ticker=t, **dict(zip(("signal", "conviction", "rationale"), _call(member, pos[t]))))
        for t in an.names if pos[t]["weight_pct"] is not None and pos[t]["pnl_pct"] is not None
    ])
    if llm.enabled():
        system = f"You are this council member:\n{_persona(member)}\n{ADVICE_SCHEMA}"
        user = (
            _roast(roast) + _brief_text(brief) + f"\nYour portfolio analysis: {an.model_dump_json()}"
            + "".join(f"\nResearch on {t}: {_sources_json(s)}" for t, s in research.items())
        )
        stage1 = an.model_dump()  # headline/analysis/reasons/names stay as verified in stage 1

        def calls(raw: dict) -> Verdict:
            return Verdict(**stage1, sources=sources, positions=raw.get("positions", []), advice=raw.get("advice", []))

        try:
            canned = await _llm_checked(calls, system, user, run_id, f"{member}.advice", brief, sources)
        except Exception as e:
            log.warning("%s advice fell back to canned: %s", member, e)
            await prism.span(run_id, f"council.{member}.advice", "agent", json.dumps(an.names), f"{type(e).__name__}: {e}", ok=False)
    return coordinator.check_calls(canned, list(pos), an.names)


async def _member(member: str, run_id: str, brief: dict, a: Assignment, roast: bool, emit) -> Verdict:
    """Stage 1 analyse the portfolio -> stage 2 research each name -> stage 3 per-name calls + advice."""
    await emit("member.status", {"member": member, "status": "researching"})
    lens = []
    if a.focus_tickers:
        first, every = a.focus_tickers[0], " ".join(a.focus_tickers)
        lens = await _search(member, [q.format(first, all=every) for q in QUERIES[member]][:LENS_QUERIES], emit)
    await emit("member.status", {"member": member, "status": "analysing"})
    an = await _analyse(member, run_id, brief, a, roast, lens)
    await emit("member.analysis", {"member": member, **an.model_dump()})
    await emit("member.status", {"member": member, "status": "checking names"})
    found = await asyncio.gather(*(_search(member, [q.format(t=t) for q in PER_NAME][:NAME_QUERIES], emit, ticker=t) for t in an.names))
    research = dict(zip(an.names, found))
    await emit("member.status", {"member": member, "status": "deciding"})
    verdict = await _advise(member, run_id, brief, an, roast, research, lens + [s for ss in found for s in ss])
    await prism.span(run_id, f"council.{member}", "agent", json.dumps(a.questions), verdict.model_dump_json())
    await emit("member.verdict", {"member": member, **verdict.model_dump()})
    return verdict


async def _rule(run_id: str, brief: dict, roast: bool, verdicts: dict[str, Verdict]) -> Chair:
    canned = coordinator.rule(verdicts, brief, roast)
    if not canned.positions and (gap := _performance_gap(brief["facts"])):
        return canned.model_copy(update={"consensus": gap, "summary": gap + " Parody council, not financial advice."})
    if not llm.enabled():
        return canned
    system = (
        f"{_persona(CHAIR)}\nDo Job 3 only. Per-name rulings are computed for you: {json.dumps([r.model_dump() for r in canned.positions])}. "
        'Reply with only a JSON object: {"consensus":str,"dissent":[str],"actions":[max 4 str],"summary":str,"suggestions":[2-3 str]}.'
    )
    user = _roast(roast) + _brief_text(brief) + "\nVerdicts: " + json.dumps({m: v.model_dump() for m, v in verdicts.items()})
    try:
        chair = coordinator.cap_chair(Chair(**await llm.complete_json(system, user)), verdicts, brief)
    except Exception as e:
        log.warning("ruling fell back to canned: %s", e)
        chair = canned
    await prism.span(run_id, "council.chair", "agent", "ruling", chair.summary)
    return chair


async def _speak(member: str, text: str, emit) -> None:
    await emit("member.status", {"member": member, "status": "speaking"})
    await emit("member.audio", {"member": member, "audio_url": audio_url(member, text)})
    await emit("member.status", {"member": member, "status": "done"})


def _line(v: Verdict) -> str:
    calls = " ".join(f"{p.signal} {p.ticker}." for p in v.positions[:3])
    return f"{v.headline}. {v.analysis or ' '.join(v.reasons[:2])} {calls}".strip()


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


def _dump(run: dict) -> dict:
    models = lambda d: {k: v.model_dump() for k, v in d.items()}  # noqa: E731
    return {**run, "assignments": models(run["assignments"]), "verdicts": models(run["verdicts"]),
            "sources": {m: [s.model_dump() for s in ss] for m, ss in run["sources"].items()},
            "chair": run["chair"] and run["chair"].model_dump()}


def _load(doc: dict) -> dict:
    models = lambda cls, d: {k: cls(**v) for k, v in d.items()}  # noqa: E731
    return {**doc, "assignments": models(Assignment, doc["assignments"]), "verdicts": models(Verdict, doc["verdicts"]),
            "sources": {m: [Source(**s) for s in ss] for m, ss in doc["sources"].items()},
            "chair": doc["chair"] and Chair(**doc["chair"])}


async def save_run(run_id: str) -> None:
    """Persist a run after the opening and after each chat turn so a restarted server can still answer follow-ups."""
    try:
        await store.save("run", run_id, _dump(RUNS[run_id]))
    except Exception:  # the live stream is unaffected; only a later follow-up after a restart would miss the run
        log.exception("could not persist run %s", run_id)


async def get_run(run_id: str) -> dict | None:
    if run_id not in RUNS and (doc := await store.load("run", run_id)):
        RUNS[run_id] = _load(doc)
    return RUNS.get(run_id)


def start_run(brief: dict, question: str, roast: bool) -> tuple[str, AsyncIterator[str]]:
    run_id = uuid.uuid4().hex
    run = RUNS[run_id] = {"brief": brief, "question": question, "roast": roast, "assignments": {}, "verdicts": {},
                          "sources": {}, "chair": None, "history": [{"role": "user", "text": question}]}

    async def body(emit) -> None:
        plan = run["assignments"] = await _plan(run_id, brief)
        for m, a in plan.items():
            await emit("orchestrator.plan", {"member": m, **a.model_dump()})
        results = await asyncio.gather(*(_member(m, run_id, brief, plan[m], roast, emit) for m in MEMBERS))
        verdicts = run["verdicts"] = dict(zip(MEMBERS, results))
        run["sources"] = {m: v.sources for m, v in verdicts.items()}
        chair = run["chair"] = await _rule(run_id, brief, roast, verdicts)
        await emit("chair.summary", chair.model_dump())
        for m in MEMBERS:
            await _speak(m, _line(verdicts[m]), emit)
        await _speak(CHAIR, chair.summary, emit)
        run["history"] += [{"role": m, "text": _line(v)} for m, v in verdicts.items()]
        run["history"].append({"role": CHAIR, "text": chair.summary})
        await save_run(run_id)

    return run_id, _stream(body, run_id)


# --- chat --------------------------------------------------------------------

REPLY_RULES = (
    "You are in a live chat with the user after the council's opening verdicts. Reply in character, 2-4 sentences "
    "(about 40-90 words). You may address another member who already spoke this turn by name, at most one rebuttal; "
    "otherwise answer the user. Use only numbers from the brief, your verdict or your sources. "
    'Reply with only a JSON object: {"text":str}.'
)


def _history(run: dict) -> str:
    lines = [f"{h['role']}: {h['text']}" for h in run["history"][-HISTORY_TURNS:]]
    return "Conversation so far:\n" + "\n".join(lines)


def _asked(text: str, run: dict) -> list[str]:
    return [t for t in _held(run["brief"]) if re.search(rf"\b{re.escape(t)}\b", text, re.I)]


def _canned_reply(member: str, run: dict, text: str, said: list[tuple[str, str]], roast: bool) -> str:
    if gap := _performance_gap(run["brief"]["facts"]):
        return gap
    v = run["verdicts"].get(member)
    if roast:
        return CANNED_ROAST[member]
    if not v:
        return "I need to look into that."
    asked = _asked(text, run)
    call = next((p for p in v.positions if p.ticker in asked), None) or (v.positions[0] if v.positions else None)
    line = f"{v.headline}. " + (f"{call.signal} {call.ticker} ({call.conviction}): {call.rationale}" if call else (v.advice[0].action + "." if v.advice else v.reasons[0]))
    if said and call:
        prev, _ = said[-1]
        theirs = next((p for p in run["verdicts"][prev].positions if p.ticker == call.ticker), None) if prev in run["verdicts"] else None
        if theirs and theirs.signal != call.signal:
            return f"{coordinator.DISPLAY[prev]}, I see {call.ticker} differently. {line}"
    return line


async def _reply(member: str, run_id: str, run: dict, text: str, said: list[tuple[str, str]], roast: bool, emit) -> str:
    sources = run["sources"].get(member, [])
    if NEEDS_SEARCH.search(text):  # the question needs new facts: one fresh search on top of the run's sources
        await emit("member.status", {"member": member, "status": "researching"})
        ticker = (_asked(text, run) or [None])[0]
        sources = (await _search(member, [text[:200]], emit, ticker=ticker)) + sources
        run["sources"][member] = sources[:12]
    await emit("member.status", {"member": member, "status": "thinking"})
    if not llm.enabled():
        return _canned_reply(member, run, text, said, roast)
    v = run["verdicts"].get(member)
    system = f"You are this council member:\n{_persona(member)}\n{REPLY_RULES}"
    user = (
        _roast(roast) + _brief_text(run["brief"]) + f"\nYour opening verdict: {v.model_dump_json() if v else 'none'}"
        + f"\nYour sources: {json.dumps([s.model_dump() for s in sources])}\n{_history(run)}"
        + "".join(f"\n{m} (this turn): {t}" for m, t in said) + f"\nUser: {text}"
    )
    return await llm.complete_reply(system, user) or "I'll pass on that one."


async def _close(run_id: str, run: dict, text: str, said: list[tuple[str, str]], reason: str) -> dict:
    """The coordinator hands the floor back: one line + 2-3 follow-up chips."""
    speakers = [m for m, _ in said if m != CHAIR]
    if not speakers:
        return {"text": "", "suggestions": coordinator.suggestions(run["verdicts"], run["brief"])}
    last = speakers[-1] if speakers else "buffett"
    others = [m for m in MEMBERS if m not in speakers]
    chips = [f"{coordinator.DISPLAY[last]}, what would change your mind?"]
    if others:
        chips.append(f"{coordinator.DISPLAY[others[0]]}, do you agree with {coordinator.DISPLAY[last]}?")
    chips.append("Who was most bullish, and who disagreed?")
    if reason == "the whole council":
        line = "Noted for the record. Earlier verdicts may shift with that; ask any member to revisit theirs."
    elif len(speakers) > 1:
        line = f"{len(speakers)} views on the table. Your call: who do you want to hear more from?"
    else:
        line = ""
    if llm.enabled() and len(speakers) > 1:
        system = f"{_persona(CHAIR)}\nClose this chat turn. Reply with only a JSON object: {{\"text\":one line,\"suggestions\":[2-3 str]}}."
        user = _history(run) + "".join(f"\n{m}: {t}" for m, t in said) + f"\nUser asked: {text}"
        try:
            out = await llm.complete_json(system, user)
            line, chips = llm.strip_tags(str(out.get("text") or line)), [llm.strip_tags(str(s)) for s in out.get("suggestions") or chips][:3]
        except Exception as e:  # keep the canned close line and chips
            log.warning("chat close fell back to canned: %s", e)
    return {"text": line, "suggestions": chips[:3]}


async def _chair_answer(run: dict, text: str) -> str:
    if not llm.enabled() or not run["chair"]:
        return _canned_chair(run)
    system = f"{_persona(CHAIR)}\nAnswer the user's question about the conversation in 1-3 sentences. Reply with only a JSON object: {{\"text\":str}}."
    return await llm.complete_reply(system, _history(run) + f"\nUser: {text}")


def _canned_chair(run: dict) -> str:
    chair: Chair | None = run["chair"]
    verdicts = run["verdicts"]
    if not any(v.positions for v in verdicts.values()) and (gap := _performance_gap(run["brief"]["facts"])):
        return gap
    count = lambda sig: {m: sum(p.signal == sig for p in v.positions) for m, v in verdicts.items()}  # noqa: E731
    most = lambda sig: max(count(sig).items(), key=lambda mc: mc[1], default=(None, 0))  # noqa: E731
    (bull, nb), (bear, ns) = most("BUY"), most("SELL")
    return (f"{chair.consensus if chair else 'No ruling yet'}. Most bullish: {coordinator.DISPLAY[bull] + f' ({nb} BUY calls)' if nb else 'nobody'}. "
            f"Most bearish: {coordinator.DISPLAY[bear] + f' ({ns} SELL calls)' if ns else 'nobody'}.")


def chat(run: dict, run_id: str, text: str, to: list[str], roast: bool) -> AsyncIterator[str]:
    async def body(emit) -> None:
        holdings = [h["ticker"] for h in run["brief"]["holdings"]]
        speakers, reason, routed_roast = coordinator.route(text, to, run["verdicts"], holdings)
        turn_roast = roast or routed_roast
        await emit("chat.routed", {"members": speakers, "reason": reason})
        await prism.span(run_id, "council.route", "agent", text, f"{speakers}: {reason}")
        run["history"].append({"role": "user", "text": text})
        said: list[tuple[str, str]] = []
        for m in speakers:
            try:
                reply = await _chair_answer(run, text) if m == CHAIR else await _reply(m, run_id, run, text, said, turn_roast, emit)
            except Exception as e:  # one speaker's failure must not end the turn: canned line, failure traced for PRISM
                log.warning("chat reply from %s fell back to canned: %s", m, e)
                await prism.span(run_id, f"chat.{m}", "agent", text, f"{type(e).__name__}: {e}", ok=False)
                reply = _canned_chair(run) if m == CHAIR else _canned_reply(m, run, text, said, turn_roast)
            said.append((m, reply))
            run["history"].append({"role": m, "text": reply})
            sources = [] if m == CHAIR else [s.model_dump() for s in run["sources"].get(m, [])]
            await emit("member.reply", {"member": m, "text": reply, "sources": sources})
            await prism.span(run_id, f"chat.{m}", "agent", text, reply)
            await _speak(m, reply, emit)
        close = await _close(run_id, run, text, said, reason)
        if close["text"]:
            run["history"].append({"role": CHAIR, "text": close["text"]})
        await save_run(run_id)
        await emit("chat.closed", close)

    return _stream(body, run_id)
