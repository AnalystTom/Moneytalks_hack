# PRISM proofs

Project `6deadd60-9c2a-4ee7-bd40-608c187fa024` (Meta Workspace) at https://prism.blockconvey.com. Council members are PRISM agents `council.<member>`; every member turn is one trace (session id = council `run_id`) with spans `council.<member>` (agent), `anchor.search` (tool), `kb.search` (retrieval) and `grounding.check`.

**The demo in one line:** v1 members invent figures the client file never contained (Cramer: "a $500 monthly plan"); v2 retrieves from each member's Knowledge Base and is told to use only provided figures; the same 50 questions score 61% grounded on v1 and 92% on v2.

## 1. Knowledge Base

15 documents (+ `dalio` for the pending fifth seat), three per member, assigned per agent by `server/scripts/kb_seed.py`:

| agent | research document (public) | client file |
|---|---|---|
| `council.buffett` | Berkshire Hathaway 2008 shareholder letter (excerpt) | `PERSONA.md`, `portfolio.json` (as `portfolio.txt`) |
| `council.leopold` | *Situational Awareness*, "From GPT-4 to AGI" (excerpt) | same |
| `council.burry` / `council.cramer` / `council.dalio` | Wikipedia biography (CC BY-SA 4.0) | same |

Sources live in `data/kb/`. In PRISM: Knowledge Base page, filter by agent. The retrieval is in the persona worker (`server/app/services/council.py`, `prism.kb_search`): each v2 trace has a `kb.search` retrieval span whose output is the chunks it pulled, and those chunks are passed to the member as sources. Example: any "Buffett v2 (KB + grounding rule)" trace for "How much did the S&P 500 fall in 2008, and what did Berkshire's book value do that year?" shows the 2008 letter chunk (book value -9.6%, S&P 500 -37.0%) in `kb.search` and the answer quoting it.

## 2. Root Cause

PENDING_RCA

## 3. Evaluator

Evaluator **"Council grounding: every number is in the source"** (`c2be7e00-092a-46b7-bf6a-3c97ac9832cc`, LLM judge, labels `grounded` / `ungrounded`): every number, price, percentage, date and quote in the answer must appear in the client file and question (`{input}`) or the retrieved sources (`{context}`). Manual task `9adecd81-a2f9-49c5-aa3e-c311e3280904`.

Both versions answered the **same 50 questions** (18 distinct, hardest first; `server/scripts/seed_runs.py`), same client brief, same model (`nicrron/auto`):

- **v1** = the backend as on `main` before this work: no Knowledge Base, original persona prompt (`COUNCIL_VERSION=v1`; agent names "<Member> v1 (KB off)").
- **v2** = Knowledge Base retrieval plus a grounding rule in the persona prompt (default; agent names "<Member> v2 (KB + grounding rule)").

PRISM_EVAL

Local backup evaluator (`server/scripts/score_grounding.py`, a deterministic version of the same rule: every figure in the answer appears in the client file or retrieved sources), all four members, 50 runs each:

| member | v1 (KB off) | v2 (KB + grounding rule) |
|---|---|---|
| Buffett | 34/50 = 68% | 49/50 = 98% |
| Burry | 33/50 = 66% | 46/49 = 94% |
| Cramer | 21/50 = 42% | 41/50 = 82% |
| Leopold | 35/50 = 70% | 47/50 = 94% |
| **all** | **123/200 = 61.5%** | **183/199 = 92%** |

Reproduce: `cd server && uv run uvicorn app.main:app --env-file ../.env` (set `COUNCIL_VERSION=v1` for v1), `uv run python scripts/seed_runs.py --runs 50`, then `PYTHONPATH=. uv run python scripts/score_grounding.py "Cramer v1 (KB off)" "Cramer v2 (KB + grounding rule)"`.

Notes: v1 and v2 were produced by running this branch locally against the live PRISM project, v1 with retrieval and the grounding rule switched off, not by calling the deployed Worker. One Burry v2 trace is missing in PRISM (49 of 50 delivered). Older seed batches without the "(KB off)" / "(KB + grounding rule)" suffix, and agent "Buffett v2 (KB on)", are earlier iterations and not part of the comparison.
