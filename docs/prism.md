# PRISM proofs

Project `6deadd60-9c2a-4ee7-bd40-608c187fa024` (Meta Workspace) at https://prism.blockconvey.com. The judging results below were captured before the council-v0 integration, when each member turn included `anchor.search`, `kb.search` and `grounding.check` spans. The current backend records separate stage traces via `prism.span`, with session id = council `run_id`; it does not emit those historical tool/retrieval steps. Current research behavior is documented in the [council pipeline](../server/council/README.md#3-each-specialist-in-parallel-analyse---research-names---advise).

**The demo in one line:** v1 members invent figures the client file never contained (Cramer: "a $500 monthly plan"); v2 retrieves from each member's Knowledge Base and is told to use only provided figures; the same 18 questions (50 runs each) score 10% grounded on v1 and 64% on v2 in the PRISM evaluator (Buffett), and 61.5% vs 92% on the local check across all four members.

## 1. Knowledge Base

`server/scripts/kb_seed.py` owns the per-agent document set, including Dalio. It uploads research documents from `data/kb/` plus the client files; existing uploads are skipped. From the repository root, with PRISM settings exported in the shell:

```sh
uv run --project server python server/scripts/kb_seed.py
```

| agent | research document (public) | client file |
|---|---|---|
| `council.buffett` | Berkshire Hathaway 2008 shareholder letter (excerpt) | `PERSONA.md`, `portfolio.json` (as `portfolio.txt`) |
| `council.leopold` | *Situational Awareness*, "From GPT-4 to AGI" (excerpt) | same |
| `council.burry` / `council.cramer` / `council.dalio` | Wikipedia biography (CC BY-SA 4.0) | same |

In PRISM: Knowledge Base page, filter by agent. Current retrieval is in `server/app/services/council.py` (`_search` calling `prism.kb_search`), shared by opening lens queries, per-name research and chat questions needing fresh facts. Returned chunks are passed to the specialist as sources. For historical retrieval-span evidence, a "Buffett v2 (KB + grounding rule)" trace for "How much did the S&P 500 fall in 2008, and what did Berkshire's book value do that year?" shows the 2008 letter chunk (book value -9.6%, S&P 500 -37.0%) in `kb.search` and the answer quoting it.

## 2. Root Cause

PRISM Intelligence (Root Cause) clustered the failed traces into **13 clusters over 116 failures** (one paid cluster run, 5 credits; clusters at `GET /api/intelligence/clusters?project_id=...`, dashboard: Intelligence). A failed trace here is one whose `grounding.check` span reported figures that appear in neither the client file nor the retrieved sources. The three largest, all classed by PRISM as **cause: prompt**, severity high, status rising:

| cluster | failures | agent |
|---|---|---|
| `trajectory_rule:agent:burry v1:CORR-001+ROB-001` (Task Completion, Error Handling) | 23 | Burry v1 |
| `trajectory_rule:agent:cramer v1:CORR-001+ROB-001` | 20 | Cramer v1 |
| `trajectory_rule:agent:leopold v1:CORR-001+ROB-001` | 19 | Leopold v1 |

(Further clusters of the same shape cover `council.buffett`, `council.burry`, `Cramer v2` and `Leopold v2`; the two v2 ones come from an early v2 batch whose grounding check compared "20" with "20.0" and flagged correct answers, fixed before the final v2 batch.)

**Why it happens, in one sentence:** v1 told each member to "cite only the provided sources" but gave them none (a stub search and no Knowledge Base), so they filled the gap with plausible-sounding figures that were never in the client file, for example Cramer's "$500 a month" plan. **The fix (v2):** retrieve from the member's Knowledge Base, and tell the member that every figure must appear verbatim in the brief or the sources.


## 3. Evaluator

Evaluator **"Council grounding: every number is in the source"** (`c2be7e00-092a-46b7-bf6a-3c97ac9832cc`, LLM judge, labels `grounded` / `ungrounded`): every number, price, percentage, date and quote in the answer must appear in the client file and question (`{input}`) or the retrieved sources (`{context}`). Manual task `9adecd81-a2f9-49c5-aa3e-c311e3280904`.

Both versions answered the **same 50 questions** (18 distinct, hardest first; `server/scripts/seed_runs.py`), same client brief, same model (`nicrron/auto`):

- **v1** = the backend as on `main` before this work: no Knowledge Base, original persona prompt (`COUNCIL_VERSION=v1`; agent names "<Member> v1 (KB off)").
- **v2** = Knowledge Base retrieval plus a grounding rule in the persona prompt (default; agent names "<Member> v2 (KB + grounding rule)").

**Scores from the PRISM evaluator** (Evaluators Hub, task above, agent filters `Buffett v1 (KB off)` and `Buffett v2 (KB + grounding rule)`; results at `GET /api/eval-results?project_id=...&task_id=9adecd81-a2f9-49c5-aa3e-c311e3280904`), Buffett, same 18 distinct questions in both:

| version | grounded | mean score |
|---|---|---|
| v1 (KB off) | **3 / 29 = 10%** | 23.2 |
| v2 (KB + grounding rule) | **32 / 50 = 64%** | 67.8 |

Only 29 of the 50 v1 traces carry a stored PRISM result: earlier API-triggered runs returned no results and are not re-scored, to stay inside the credit budget. The LLM judge is stricter than the local check below, which is why v2 reads 64% here and 98% locally for the same member.


Local backup evaluator (`server/scripts/score_grounding.py`, a deterministic version of the same rule: every figure in the answer appears in the client file or retrieved sources), all four members, 50 runs each:

| member | v1 (KB off) | v2 (KB + grounding rule) |
|---|---|---|
| Buffett | 34/50 = 68% | 49/50 = 98% |
| Burry | 33/50 = 66% | 46/49 = 94% |
| Cramer | 21/50 = 42% | 41/50 = 82% |
| Leopold | 35/50 = 70% | 47/50 = 94% |
| **all** | **123/200 = 61.5%** | **183/199 = 92%** |

Historical reproduction used `cd server && uv run uvicorn app.main:app --env-file ../.env` (set `COUNCIL_VERSION=v1` for v1), `uv run python scripts/seed_runs.py --runs 50`, then `PYTHONPATH=. uv run python scripts/score_grounding.py "Cramer v1 (KB off)" "Cramer v2 (KB + grounding rule)"`. These commands do not reproduce the reported scores on the current council-v0 pipeline: its model selection, prompts and trace inputs differ. See [server settings](../server/README.md#env-names).

Notes: v1 and v2 were produced by running this branch locally against the live PRISM project, v1 with retrieval and the grounding rule switched off, not by calling the deployed Worker. One Burry v2 trace is missing in PRISM (49 of 50 delivered). Older seed batches without the "(KB off)" / "(KB + grounding rule)" suffix, and agent "Buffett v2 (KB on)", are earlier iterations and not part of the comparison.
