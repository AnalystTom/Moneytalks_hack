from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

KEYS = ["OPENAI_API_KEY", "PRISMTRACE_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL"] + [
    f"ELEVENLABS_VOICE_{m}" for m in ("BUFFETT", "DALIO", "BURRY", "LEOPOLD", "CRAMER", "CHAIR")
]
PORTFOLIO = b"ticker,shares,cost_basis\nVOO,20,714.29\n"
PERSONA = b"# Alex\n10-year horizon, moderate risk\n"
DATA = Path(__file__).resolve().parents[2] / "data"  # demo user Jordan: data/portfolio.json + data/PERSONA.md


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def brief_id(client):
    r = client.post("/api/ingest", files={"portfolio": ("p.csv", PORTFOLIO), "persona": ("persona.md", PERSONA)}, data={"plaid": "true"})
    return r.json()["brief_id"]


@pytest.fixture
def jordan_brief_id(client):
    files = {"portfolio": ("portfolio.json", (DATA / "portfolio.json").read_bytes()), "persona": ("PERSONA.md", (DATA / "PERSONA.md").read_bytes())}
    r = client.post("/api/ingest", files=files)
    assert r.status_code == 200, r.text
    return r.json()["brief_id"]


def run_council(client, brief_id, **body):
    """Opening run; returns (run_id, events)."""
    events = parse_sse(client.post("/api/council/run", json={"brief_id": brief_id, "question": "q", **body}).text)
    return events[0][1]["run_id"], events


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        events.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events
