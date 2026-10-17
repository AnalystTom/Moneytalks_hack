"""PRISM tracing over plain HTTP: one trace per agent (orchestrator, each worker), session id = council run_id."""
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.config import env, model

log = logging.getLogger(__name__)
LIMIT = 8000  # characters of input/output kept per span


def enabled() -> bool:
    return bool(env("PRISMTRACE_API_KEY") and env("PRISMTRACE_PROJECT_ID"))


def _host() -> str:
    return env("PRISMTRACE_HOST", "https://prism.blockconvey.com").rstrip("/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Span:
    """Times a block (`with trace.span(...) as s:`); set `s.output`, tokens and model inside. An exception marks it failed."""

    def __init__(self, trace: "Trace", name: str, span_type: str, input_text: str, parent: "Span | None"):
        self.trace, self.name, self.type, self.input, self.parent = trace, name, span_type, input_text, parent
        self.id, self.output, self.model, self.tokens_in, self.tokens_out, self.meta = str(uuid.uuid4()), "", None, None, None, {}
        self.error: str | None = None

    def __enter__(self) -> "Span":
        self.start, self.t0 = _now(), time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc:
            self.error = str(exc) or exc_type.__name__
        self.trace.spans.append({
            "span_id": self.id, "parent_span_id": self.parent.id if self.parent else None, "name": self.name,
            "span_type": self.type, "start_time": self.start, "end_time": _now(),
            "duration_ms": round((time.perf_counter() - self.t0) * 1000), "status": "error" if self.error else "ok",
            "error_message": self.error, "input_text": self.input[:LIMIT], "output_text": self.output[:LIMIT],
            "model": self.model, "token_count_input": self.tokens_in, "token_count_output": self.tokens_out, "metadata": self.meta,
        })

    def llm(self, result: dict) -> None:
        """Record a llm.chat result's model and token usage on this span."""
        self.model, usage = result["model"], result["usage"]
        self.tokens_in, self.tokens_out = usage.get("prompt_tokens"), usage.get("completion_tokens")


class Trace:
    def __init__(self, session_id: str, agent_id: str, input_text: str):
        self.session_id, self.agent_id, self.input = session_id, agent_id, input_text
        self.trace_id, self.receipt_id = str(uuid.uuid4()), None
        self.spans: list[dict] = []
        self.t0 = time.perf_counter()

    def span(self, name: str, span_type: str, input_text: str = "", parent: Span | None = None) -> Span:
        return Span(self, name, span_type, input_text, parent)

    async def finish(self, output_text: str, ok: bool = True) -> str | None:
        """Deliver the trace and its spans; returns the trace id, or None when PRISM is off or delivery failed. Never raises."""
        if not enabled():
            return None
        key, project = env("PRISMTRACE_API_KEY"), env("PRISMTRACE_PROJECT_ID")
        tokens = {
            "token_count_input": sum(s["token_count_input"] or 0 for s in self.spans),
            "token_count_output": sum(s["token_count_output"] or 0 for s in self.spans),
        }
        trace = {
            "trace_id": self.trace_id, "project_id": project, "session_id": self.session_id, "agent_id": self.agent_id,
            "model": next((s["model"] for s in self.spans if s["model"]), model()),
            "input_messages": [{"role": "user", "content": self.input[:LIMIT]}], "output_message": output_text[:LIMIT],
            "latency_ms": round((time.perf_counter() - self.t0) * 1000), **tokens,
            "metadata": {"status": "ok" if ok else "error", "environment": "hackathon"},
        }
        try:
            async with httpx.AsyncClient(timeout=30, headers={"X-PRISMtrace-Key": key}) as client:
                r = await client.post(f"{_host()}/api/traces", json=trace)
                r.raise_for_status()
                self.receipt_id = r.json().get("id")
                (await client.post(
                    f"{_host()}/api/spans/ingest",
                    json={"trace_id": self.trace_id, "project_id": project, "session_id": self.session_id, "spans": self.spans},
                )).raise_for_status()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("PRISM delivery failed for %s: %s", self.agent_id, e)
            return None
        return self.trace_id


async def read_back(trace_id: str) -> dict:
    """GET the stored trace and its spans, to prove delivery."""
    async with httpx.AsyncClient(timeout=30, headers={"X-PRISMtrace-Key": env("PRISMTRACE_API_KEY")}) as client:
        trace = await client.get(f"{_host()}/api/traces/{trace_id}")
        spans = await client.get(f"{_host()}/api/spans/{trace_id}")
    return {"trace_status": trace.status_code, "trace": trace.json() if trace.is_success else None,
            "spans_status": spans.status_code, "spans": spans.json() if spans.is_success else None}
