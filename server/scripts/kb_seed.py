"""Upload each council member's PRISM Knowledge Base: one research doc plus the client file (PERSONA.md, portfolio).

Run from the repo root: uv run --project server python server/scripts/kb_seed.py [--env .env]
Reads PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID / PRISMTRACE_HOST from the environment; skips documents already uploaded.
"""
import json
import os
import sys
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parents[2] / "data"
MEMBERS = ("buffett", "cramer", "burry", "leopold", "dalio")


def client_files(member: str) -> dict[str, str]:
    # KB accepts .txt/.md/.pdf, so the JSON snapshot goes up as text; the header keeps the content hash unique per agent,
    # because PRISM dedupes identical files and a document belongs to one agent only
    head = f"Client file for council.{member}\n\n"
    return {"PERSONA.md": head + (DATA / "PERSONA.md").read_text(), "portfolio.txt": head + (DATA / "portfolio.json").read_text()}


def main() -> None:
    host = os.environ.get("PRISMTRACE_HOST", "https://prism.blockconvey.com")
    project = os.environ["PRISMTRACE_PROJECT_ID"]
    headers = {"X-PRISMtrace-Key": os.environ["PRISMTRACE_API_KEY"]}
    with httpx.Client(base_url=host, headers=headers, timeout=120) as http:
        existing = {(d["agent_id"], d["name"]) for d in http.get("/api/knowledge-base/documents", params={"project_id": project}).json()["documents"]}
        for member in MEMBERS:
            agent = f"council.{member}"
            docs = {p.name: p.read_text() for p in (DATA / "kb").glob(f"{member}-*.md")} | client_files(member)
            for name, text in docs.items():
                if (agent, name) in existing:
                    continue
                r = http.post(
                    "/api/knowledge-base/documents",
                    data={"project_id": project, "agent_id": agent, "description": f"{member} knowledge: {name}"},
                    files={"file": (name, text.encode(), "text/markdown")},
                )
                r.raise_for_status()
                print(agent, name, json.dumps(r.json())[:120])


if __name__ == "__main__":
    main()
