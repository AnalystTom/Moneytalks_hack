import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.config import council_version, env

log = logging.getLogger(__name__)


def _auth() -> tuple[str, dict, str] | None:
    key, project = env("PRISMTRACE_API_KEY"), env("PRISMTRACE_PROJECT_ID")
    if not key or not project:
        return None
    return env("PRISMTRACE_HOST", "https://prism.blockconvey.com"), {"X-PRISMtrace-Key": key}, project


async def kb_search(agent_id: str, query: str, limit: int = 3) -> list[dict]:
    """Search the PRISM Knowledge Base documents assigned to `agent_id`; [] without a key or on any failure."""
    if not (auth := _auth()):
        return []
    host, headers, project = auth
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{host}/api/knowledge-base/search", headers=headers,
                json={"project_id": project, "agent_id": agent_id, "query": query, "limit": limit},
            )
            r.raise_for_status()
        return r.json()["results"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("PRISM KB search failed: %s", e)
        return []


async def trace(
    session_id: str, agent_id: str, input_text: str, output_text: str,
    steps: list[tuple[str, str, str, str]], ok: bool = True,
    *, model: str | None = None, span_type: str = "agent",
) -> None:
    """Record one trace with a span per (name, span_type, input, output) step; a no-op without PRISMTRACE_API_KEY, never raises."""
    if not (auth := _auth()):
        return
    host, headers, project = auth
    now = datetime.now(timezone.utc).isoformat()
    trace_id = str(uuid.uuid4())
    status = "ok" if ok else "error"
    body = {
        "trace_id": trace_id, "project_id": project, "session_id": session_id, "agent_id": agent_id,
        "agent_name": f"{agent_id.removeprefix('council.').title()} {council_version()} ({'KB off' if council_version() == 'v1' else 'KB + grounding rule'})" if span_type == "agent" else agent_id,
        "model": model or env("NICRRON_MODEL", "nicrron/auto"), "input_messages": [{"role": "user", "content": input_text}],
        "output_message": output_text, "latency_ms": 0, "metadata": {"status": status, "council_version": council_version()},
    }
    spans = [
        {"span_id": str(uuid.uuid4()), "name": name, "span_type": kind, "start_time": now, "end_time": now,
         "duration_ms": 0, "status": status, "input_text": i, "output_text": o}
        for name, kind, i, o in [(agent_id, span_type, input_text, output_text), *steps]  # PRISM files the first span's I/O on the trace
    ]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            (await client.post(f"{host}/api/traces", json=body, headers=headers)).raise_for_status()
            (await client.post(
                f"{host}/api/spans/ingest", headers=headers,
                json={"trace_id": trace_id, "project_id": project, "session_id": session_id, "spans": spans},
            )).raise_for_status()
    except httpx.HTTPError as e:
        log.warning("PRISM delivery failed: %s", e)


async def span(session_id: str, name: str, span_type: str, input_text: str, output_text: str, ok: bool = True) -> None:
    """One-span trace; the council backend records each stage this way. Never raises."""
    await trace(session_id, name, input_text, output_text, [], ok)
