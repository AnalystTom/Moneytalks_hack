import pytest
from fastapi.testclient import TestClient

from app.main import app

KEYS = ["NICRRON_API_KEY", "PRISMTRACE_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL"] + [
    f"ELEVENLABS_VOICE_{m}" for m in ("BUFFETT", "CRAMER", "BURRY", "LEOPOLD")
]
PORTFOLIO = b"ticker,shares,cost_basis\nVOO,20,714.29\n"
PERSONA = b"# Alex\n10-year horizon, moderate risk\n"


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


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        events.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events
