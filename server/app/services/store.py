"""Briefs and runs as JSON documents that outlive a Worker/Durable Object restart.

On Cloudflare, worker.py binds the D1 database (`bind`); anywhere else (tests, local uvicorn) documents stay in memory.
"""
import json

_db = None  # the D1 binding, set per request by worker.py
_ready = False
_mem: dict[tuple[str, str], str] = {}


def bind(db) -> None:
    global _db
    _db = db  # a fresh proxy every request: keep _ready, the table outlives it


async def _table():
    global _ready
    if not _ready:  # no migration step in deploy.sh, so the table is created on first use
        await _db.prepare("CREATE TABLE IF NOT EXISTS docs (kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (kind, id))").run()
        _ready = True
    return _db


# shortcut: rows never expire, add a created-at column and a periodic delete before real users upload real portfolios.
async def save(kind: str, doc_id: str, doc: dict) -> None:
    body = json.dumps(doc)
    if _db is None:
        _mem[kind, doc_id] = body
        return
    await (await _table()).prepare("INSERT OR REPLACE INTO docs (kind, id, body) VALUES (?, ?, ?)").bind(kind, doc_id, body).run()


async def load(kind: str, doc_id: str) -> dict | None:
    if _db is None:
        body = _mem.get((kind, doc_id))
    else:
        body = await (await _table()).prepare("SELECT body FROM docs WHERE kind = ? AND id = ?").bind(kind, doc_id).first("body")
    return json.loads(body) if body else None
