import asyncio
import json
import re

import httpx

from app.config import env

BASE_URL = "https://api.nicrron.ai/v1"
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 4
_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}  # one per event loop: a semaphore binds to its loop


def enabled() -> bool:
    return bool(env("NICRRON_API_KEY"))


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


async def complete_text(system: str, user: str) -> str:
    """One Nicrron (OpenAI-compatible) chat completion; rate limits and server errors are retried with backoff."""
    async with _limit(), httpx.AsyncClient(timeout=90) as client:
        for attempt in range(ATTEMPTS):
            r = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {env('NICRRON_API_KEY')}"},
                json={
                    "model": env("NICRRON_MODEL", "nicrron/auto"),
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "max_tokens": 1500,  # bounds spend per call; a verdict JSON fits well inside it
                },
            )
            if r.status_code not in RETRY_STATUS or attempt == ATTEMPTS - 1:
                break
            await asyncio.sleep(_wait(r, attempt))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


async def complete_json(system: str, user: str) -> dict:
    """A completion whose reply must be a JSON object."""
    text = await complete_text(system, user)
    match = re.search(r"\{.*\}", text, re.DOTALL)  # models sometimes wrap JSON in prose or fences
    if not match:
        raise ValueError("Nicrron reply contained no JSON object")
    return json.loads(match.group(0))


VOICE_TAG = re.compile(r"</?(?:chair|buffett|dalio|burry|leopold|cramer)>", re.I)  # v1 voice-mode markup, not for text chat


def strip_tags(text: str) -> str:
    return VOICE_TAG.sub("", text).strip()


async def complete_reply(system: str, user: str) -> str:
    """A spoken/chat line: the "text" field when the model answers in JSON, else its prose as-is."""
    text = strip_tags(await complete_text(system, user))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return strip_tags(str(json.loads(match.group(0)).get("text", "")))
        except (ValueError, AttributeError):
            pass
    return re.sub(r"^```\w*\s*|\s*```$", "", text).strip()
