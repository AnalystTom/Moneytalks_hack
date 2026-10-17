"""Anchor web search. Offered to the workers only when ANCHOR_API_KEY is set."""
import json
import re

import httpx

from app.config import env
from app.models import Source

URL = "https://api.anchorbrowser.io/v1/tools/perform-web-task"


def enabled() -> bool:
    return bool(env("ANCHOR_API_KEY"))


async def search(query: str) -> list[Source]:
    # shortcut: Anchor has no search endpoint we could confirm, so this asks its web-task agent for results; swap if a search API turns up
    prompt = (
        f"Search the web for: {query}. Reply with only a JSON array of up to 4 objects "
        '{"title": str, "url": str, "quote": a sentence copied verbatim from that page}.'
    )
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(URL, headers={"anchor-api-key": env("ANCHOR_API_KEY")}, json={"prompt": prompt})
    r.raise_for_status()
    match = re.search(r"\[.*\]", r.text.replace('\\"', '"'), re.DOTALL) or re.search(r"\[.*\]", r.text, re.DOTALL)
    rows = json.loads(match.group(0)) if match else []
    return [Source(title=str(x["title"]), url=str(x["url"]), quote=str(x.get("quote", ""))) for x in rows if x.get("url")]
