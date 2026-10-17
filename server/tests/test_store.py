import sqlite3

import pytest

from app.services import council, ingest, store
from tests.conftest import run_council
from tests.test_council import chat


class FakeD1:
    """The slice of the D1 binding the store uses (prepare/bind/run/first), backed by sqlite."""

    def __init__(self):
        self.sql = sqlite3.connect(":memory:", check_same_thread=False)

    def prepare(self, query):
        return FakeStatement(self.sql, query)


class FakeStatement:
    def __init__(self, sql, query, args=()):
        self.sql, self.query, self.args = sql, query, args

    def bind(self, *args):
        return FakeStatement(self.sql, self.query, args)

    async def run(self):
        self.sql.execute(self.query, self.args)

    async def first(self, column):
        row = self.sql.execute(self.query, self.args).fetchone()
        return row[0] if row else None


def restart():
    """A new Durable Object instance: the in-memory caches are gone, only the durable store survives."""
    ingest.BRIEFS.clear()
    council.RUNS.clear()


@pytest.fixture(params=["memory", "d1"])
def durable(request):
    store._ready = False  # each fake database starts without the table
    store.bind(FakeD1() if request.param == "d1" else None)
    yield
    store.bind(None)


def test_run_survives_restart_between_ingest_and_run(durable, client, brief_id):
    restart()
    r = client.post("/api/council/run", json={"brief_id": brief_id, "question": "q"})
    assert r.status_code == 200 and "run.done" in r.text


def test_chat_survives_restart_after_the_run(durable, client, jordan_brief_id):
    run_id, _ = run_council(client, jordan_brief_id)
    restart()
    events = chat(client, run_id, "@burry why are you bearish on PLTR?")
    assert [e for e, _ in events][-1] == "run.done"
    assert [d["member"] for e, d in events if e == "member.reply"] == ["burry"]
    # the turn is persisted too: a second restart keeps the follow-up in the history
    restart()
    chat(client, run_id, "And a third general question?")
    roles = [h["role"] for h in council.RUNS[run_id]["history"]]
    assert roles.count("user") == 3
    assert council.RUNS[run_id]["verdicts"]["burry"].positions  # models, not dicts, after reload


def test_unknown_ids_are_still_404(durable, client):
    assert client.post("/api/council/run", json={"brief_id": "nope", "question": "q"}).status_code == 404
    assert client.post("/api/council/chat", json={"run_id": "nope", "text": "q"}).status_code == 404
