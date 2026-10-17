import asyncio
import json
import re

import httpx

from app.config import env

BASE_URL = "https://api.nicrron.ai/v1"
DEFAULT_MODEL = "anthropic/claude-opus-5-5"
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 4
_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}  # one per event loop: a semaphore binds to its loop


def enabled() -> bool:
    return bool(env("NICRRON_API_KEY"))


def model() -> str:
    """Claude Opus 5.5 unless NICRRON_MODEL names something other than the router default."""
    name = env("NICRRON_MODEL")
    return DEFAULT_MODEL if name in ("", "nicrron/auto") else name


def _limit() -> asyncio.Semaphore:
    """At most NICRRON_CONCURRENCY calls in flight (default 4): five members in parallel otherwise trip 429s."""
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(int(env("NICRRON_CONCURRENCY", "4") or 4))
    return _slots[loop]


def _wait(r: httpx.Response, attempt: int) -> float:
    try:
        return min(float(r.headers.get("retry-after", "")), 20.0)
    except ValueError:
        return 1.5 * 2**attempt  # 1.5s, 3s, 6s


async def complete_json(system: str, user: str) -> dict:
    """One Nicrron (OpenAI-compatible) chat completion whose reply must be a JSON object.
    Rate limits and server errors are retried with backoff."""
    async with _limit(), httpx.AsyncClient(timeout=90) as client:
        for attempt in range(ATTEMPTS):
            r = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {env('NICRRON_API_KEY')}"},
                json={
                    "model": model(),
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
            )
            if r.status_code not in RETRY_STATUS or attempt == ATTEMPTS - 1:
                break
            await asyncio.sleep(_wait(r, attempt))
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.DOTALL)  # models sometimes wrap JSON in prose or fences
    if not match:
        raise ValueError("Nicrron reply contained no JSON object")
    return json.loads(match.group(0))
