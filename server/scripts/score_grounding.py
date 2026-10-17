"""Local backup evaluator: re-score PRISM traces with "every number is in the client file or the sources".

Usage (env as for the server): uv run python scripts/score_grounding.py "Buffett v1 (KB off)" "Buffett v2 (KB on)" ...
Prints, per agent_name, grounded/total and the share of traces whose every figure was found.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.services.grounding import ungrounded

HOST = os.environ.get("PRISMTRACE_HOST", "https://prism.blockconvey.com")
PROJECT = os.environ["PRISMTRACE_PROJECT_ID"]
http = httpx.Client(base_url=HOST, headers={"X-PRISMtrace-Key": os.environ["PRISMTRACE_API_KEY"]}, timeout=60)


def trace_ids(agent_name: str) -> list[str]:
    ids, page = [], 1
    while True:
        rows = http.get("/api/traces", params={"project_id": PROJECT, "page": page, "page_size": 50}).json()["traces"]
        ids += [t["id"] for t in rows if t.get("agent_name") == agent_name]
        if len(rows) < 50:
            return ids
        page += 1


def grounded(trace_id: str) -> bool:
    t = http.get(f"/api/traces/{trace_id}").json()
    sources = " ".join(s["output_text"] or "" for s in t["db_spans"] if s["span_type"] in ("tool", "retrieval"))
    return not ungrounded(t["output_message"], t["input_messages"][0]["content"], sources)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(grounded, trace_ids(name)))
        print(f"{name}: {sum(results)}/{len(results)} grounded = {sum(results) / max(len(results), 1):.0%}")
