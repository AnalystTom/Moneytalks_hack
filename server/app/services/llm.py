import json
import re

import httpx

from app.config import env

BASE_URL = "https://api.nicrron.ai/v1"


def enabled() -> bool:
    return bool(env("NICRRON_API_KEY"))


async def complete_json(system: str, user: str) -> dict:
    """One Nicrron (OpenAI-compatible) chat completion whose reply must be a JSON object."""
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {env('NICRRON_API_KEY')}"},
            json={
                "model": env("NICRRON_MODEL", "nicrron/auto"),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.DOTALL)  # models sometimes wrap JSON in prose or fences
    if not match:
        raise ValueError("Nicrron reply contained no JSON object")
    return json.loads(match.group(0))
