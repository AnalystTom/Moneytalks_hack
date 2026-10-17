"""Run many council runs against a Council server so PRISM has traces to cluster and score.

Local:  cd server && uv run uvicorn app.main:app --port 8000 --env-file ../.env   (COUNCIL_VERSION=v1 for the pre-KB backend)
Seed:   uv run python scripts/seed_runs.py --runs 50 [--base-url https://council.thomasmann2001.workers.dev]
Questions cycle in order, hardest (specific facts the client file does not contain) first, so every version sees the same inputs.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

PERSONA = Path(__file__).resolve().parents[2] / "data" / "PERSONA.md"
PORTFOLIO = b"ticker,shares,cost_basis\nVOO,20,714.29\n"
QUESTIONS = [  # hard: need facts only a source can supply
    "How much did the S&P 500 fall in 2008, and what did Berkshire's book value do that year?",
    "Quote the exact words your best-known investor would use about buying when others are fearful.",
    "What is VOO's closing price today and its trailing P/E? Cite the source.",
    "By how many orders of magnitude per year is AI compute growing, and when is AGI plausible?",
    "What did Berkshire's per-share book value compound at over 44 years?",
    "Which of my holdings carries the most risk, and what percent of my portfolio is it?",
    # ordinary
    "I'm down 30%. Keep dollar-cost averaging, sell, or move somewhere else?",
    "Should I move half my index fund into AI infrastructure stocks?",
    "Is now a good time to put my cash on the sidelines to work?",
    "How should I think about my 10-year horizon after this drawdown?",
    "Am I too concentrated in one position?",
    "Should I sell now and buy back lower?",
    "What would you do with $10,000 of new money today?",
    "Is a recession coming, and should that change my plan?",
    "Should I pay down debt or keep investing?",
    "What is the biggest mistake I could make right now?",
    "Do bonds or gold belong in my portfolio?",
    "How much cash should I keep as an emergency fund?",
]


async def one_run(http: httpx.AsyncClient, brief_id: str, question: str) -> tuple[bool, str]:
    async with http.stream("POST", "/api/council/run", json={"brief_id": brief_id, "question": question}) as r:
        text = "".join([chunk async for chunk in r.aiter_text()])
    errors = [json.loads(b.split("data: ", 1)[1])["message"] for b in text.split("\n\n") if b.startswith("event: run.error")]
    return not errors, errors[0] if errors else ""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=300) as http:
        r = await http.post("/api/ingest", files={"portfolio": ("p.csv", PORTFOLIO), "persona": ("persona.md", PERSONA.read_bytes())}, data={"plaid": "true"})
        r.raise_for_status()
        brief_id = r.json()["brief_id"]
        gate, failed = asyncio.Semaphore(args.concurrency), []

        async def go(i: int) -> None:
            async with gate:
                ok, err = await one_run(http, brief_id, QUESTIONS[i % len(QUESTIONS)])
            print(f"run {i + 1}/{args.runs}", "ok" if ok else f"FAILED: {err[:100]}", flush=True)
            if not ok:
                failed.append(i)

        await asyncio.gather(*(go(i) for i in range(args.runs)))
    print(f"{args.runs} runs, {len(failed)} failed")


if __name__ == "__main__":
    asyncio.run(main())
