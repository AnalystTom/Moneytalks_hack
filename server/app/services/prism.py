import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.config import env

log = logging.getLogger(__name__)


async def span(session_id: str, name: str, span_type: str, input_text: str, output_text: str, ok: bool = True) -> None:
    """Record one trace + span in PRISM; a no-op without PRISMTRACE_API_KEY, never raises."""
    key, project = env("PRISMTRACE_API_KEY"), env("PRISMTRACE_PROJECT_ID")
    if not key or not project:
        return
    host = env("PRISMTRACE_HOST", "https://prism.blockconvey.com")
    now = datetime.now(timezone.utc).isoformat()
    trace_id = str(uuid.uuid4())
    headers = {"X-PRISMtrace-Key": key}
    trace = {
        "trace_id": trace_id, "project_id": project, "session_id": session_id, "agent_id": name,
        "model": env("NICRRON_MODEL", "nicrron/auto"), "input_messages": [{"role": "user", "content": input_text}],
        "output_message": output_text, "latency_ms": 0, "metadata": {"status": "ok" if ok else "error"},
    }
    spans = [{
        "span_id": str(uuid.uuid4()), "name": name, "span_type": span_type, "start_time": now, "end_time": now,
        "duration_ms": 0, "status": "ok" if ok else "error", "input_text": input_text, "output_text": output_text,
    }]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            (await client.post(f"{host}/api/traces", json=trace, headers=headers)).raise_for_status()
            await client.post(
                f"{host}/api/spans/ingest", headers=headers,
                json={"trace_id": trace_id, "project_id": project, "session_id": session_id, "spans": spans},
            )
    except httpx.HTTPError as e:
        log.warning("PRISM delivery failed: %s", e)
