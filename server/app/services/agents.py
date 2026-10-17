"""One worker: a persona with its own context, running the tool loop and returning a structured verdict."""
import asyncio
import json
import logging

from pydantic import ValidationError

from app.models import Source, Verdict
from app.services import llm, personas, tools
from app.services.prism import Trace

log = logging.getLogger(__name__)
MAX_STEPS = 6  # model turns before the worker is forced to answer without tools
OUTPUT_CONTRACT = (
    "Reply, when your research is done, with only a JSON object: "
    '{"signal":"BUY|HOLD|SELL","confidence":0-1,"headline":"one line","reasons":["2-3 short reasons"],'
    '"tickers":["symbols you rule on"],"sources":[{"title","url","quote"}],'
    '"line":"your speech-bubble line, at most 25 words, in your own voice"}. '
    "Cite only what your tools returned: web sources with their real URL and a quote the page contained; "
    "for data from the portfolio, profile or specialist sheet use the tool name as title, an empty url, and an exact excerpt of the returned JSON as quote. "
    "Never invent a number, quote or URL."
)


def system_prompt(persona: personas.Persona) -> str:
    return f"{persona.body}\n\n---\n\n{personas.prompt('skill')}\n\n---\n\n{OUTPUT_CONTRACT}"


def task_prompt(brief: dict, question: str, roast: bool, assignment: str, earlier: str = "") -> str:
    parts = [f"Client brief: {brief['summary']}", f"Client question: {question}"]
    if assignment:
        parts.append(f"Research assignment from the chair: {assignment}")
    if earlier:
        parts.append(f"What you said earlier in this run (stay consistent unless the new question changes it): {earlier}")
    if roast:
        parts.append("ROAST MODE: roast the client's portfolio mercilessly in your own voice, comedic but in character. Only the tone changes; the signal and reasoning stay honest.")
    parts.append("Use your tools to research before you rule.")
    return "\n".join(parts)


def _clean(verdict: Verdict, evidence: list[Source]) -> Verdict:
    verdict.sources = [s for s in verdict.sources if s.quote.strip() and any(
        s.title == e.title and s.url == e.url and s.quote in e.quote for e in evidence
    )]
    if not verdict.sources:
        raise ValueError("A verdict must cite evidence returned by a successful tool call")
    return verdict


async def run(persona: personas.Persona, brief: dict, question: str, roast: bool, assignment: str, trace: Trace, emit, earlier: str = "") -> Verdict:
    """Research -> verdict for one persona. Events go through `emit`; every LLM and tool call is a PRISM span."""
    messages = [
        {"role": "system", "content": system_prompt(persona)},
        {"role": "user", "content": task_prompt(brief, question, roast, assignment, earlier)},
    ]
    evidence: list[Source] = []
    with trace.span(f"worker.{persona.member}", "agent", messages[1]["content"]) as root:
        await emit("member.status", {"member": persona.member, "status": "researching"})
        for step in range(MAX_STEPS + 2):
            if step == MAX_STEPS:  # Anthropic rejects tool history without tools, so keep offering them but ask for the answer
                messages.append({"role": "user", "content": "Research budget used. Reply now with only the JSON verdict."})
            with trace.span("llm.chat", "llm", str(messages[-1].get("content"))[:4000], root) as span:
                result = await llm.chat(messages, tools.specs())
                span.llm(result)
                reply = result["message"]
                span.output = reply.get("content") or json.dumps(reply.get("tool_calls"))
            messages.append({k: v for k, v in reply.items() if k in ("role", "content", "tool_calls") and v is not None})
            if calls := reply.get("tool_calls"):
                if step >= MAX_STEPS:
                    raise ValueError(f"{persona.member} kept calling tools past its research budget")
                await asyncio.gather(*(_tool(c, persona, brief, trace, root, messages, evidence, emit) for c in calls))
                await emit("member.status", {"member": persona.member, "status": "thinking"})
                continue
            try:
                verdict = _clean(Verdict(**llm.extract_json(reply.get("content") or "")), evidence)
            except (ValueError, ValidationError) as e:
                if step >= MAX_STEPS + 1:
                    raise ValueError(f"{persona.member} returned no valid verdict: {e}") from e
                messages.append({"role": "user", "content": f"That reply was not a valid verdict ({str(e)[:300]}). {OUTPUT_CONTRACT}"})
                continue
            root.output = verdict.headline
            return verdict
    raise ValueError(f"{persona.member} did not finish")


async def _tool(call: dict, persona, brief: dict, trace: Trace, root, messages: list, evidence: list[Source], emit) -> None:
    name = call["function"]["name"]
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except ValueError:
        args = {}
    with trace.span(f"tool.{name}", "tool", json.dumps(args), root) as span:
        result = await tools.call(name, args, brief, persona)
        span.output = json.dumps(result)
        if "error" in result:
            span.error = str(result["error"])
    content = json.dumps(result, ensure_ascii=False)
    if "error" not in result:
        if name == "web_search":
            evidence.extend(Source(**r) for r in result.get("results", []))
        else:
            evidence.append(Source(title=name, url="", quote=content))
    for r in result.get("results", []):
        await emit("member.source", {"member": persona.member, "title": r["title"], "url": r["url"]})
    messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
