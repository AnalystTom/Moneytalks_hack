import json
import re
import time

import httpx

from app.config import env, model

BASE_URL = "https://api.nicrron.ai/v1"


def enabled() -> bool:
    return bool(env("NICRRON_API_KEY"))


async def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 4096) -> dict:
    """One Nicrron (OpenAI-compatible) chat completion: {"message", "model", "usage", "latency_ms"}."""
    body = {"model": model(), "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=180) as client:
        for attempt in (1, 2):  # one retry for transient gateway errors
            r = await client.post(f"{BASE_URL}/chat/completions", headers={"Authorization": f"Bearer {env('NICRRON_API_KEY')}"}, json=body)
            if r.status_code < 500 and r.status_code != 429 or attempt == 2:
                break
    r.raise_for_status()
    data = r.json()
    return {
        "message": data["choices"][0]["message"], "model": data.get("model") or body["model"],
        "usage": data.get("usage") or {}, "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)  # models sometimes wrap JSON in prose or fences
    if not match:
        raise ValueError("model reply contained no JSON object")
    return json.loads(match.group(0))
