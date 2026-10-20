"""The neutral coordinator's deterministic rules: plan, verify, rule, route (see council/orchestrator.md).

Each function is the no-LLM path and also the guard rail applied to LLM output, so the council
behaves the same shape with or without OPENAI_API_KEY.
"""
import json
import re

from app.config import MEMBERS
from app.models import Analysis, Assignment, Chair, NameRuling, Verdict

NAMES = {
    "buffett": ("buffett", "warren"),
    "dalio": ("dalio", "ray"),
    "burry": ("burry", "michael"),
    "leopold": ("leopold", "aschenbrenner"),
    "cramer": ("cramer", "jim"),
}
DISPLAY = {"buffett": "Warren", "dalio": "Ray", "burry": "Michael", "leopold": "Leopold", "cramer": "Jim", "chair": "The chair"}
AI_TICKERS = {"NVDA", "AMD", "MSFT", "PLTR", "AVGO", "TSM", "GOOGL", "GOOG", "META", "AMZN", "SMCI", "ARM", "MU", "ASML"}
DIVERSIFIERS = {"SPY", "VOO", "VTI", "SCHD", "BND", "AGG", "TLT", "TIP", "GLD", "IAU", "VXUS", "QQQ"}
MAX_SPEAKERS = 3
SHARED = 2  # top holdings every member must call

# --- plan --------------------------------------------------------------------


def _rank(positions: list[dict], pick, limit: int) -> list[str]:
    return [p["ticker"] for p in positions if pick(p)][:limit]


def plan(brief: dict) -> dict[str, Assignment]:
    """One assignment per member: 2-4 focus tickers and 2-3 questions about this user."""
    f = brief["facts"]
    pos = f["positions"]  # sorted by value, largest first
    by_gain = sorted((p for p in pos if p["pnl_pct"] is not None), key=lambda p: -p["pnl_pct"])
    by_loss = sorted((p for p in pos if p["pnl_pct"] is not None), key=lambda p: p["pnl_pct"])
    top = pos[0]
    focus = {
        "dalio": _rank(pos, lambda p: p["ticker"] in DIVERSIFIERS or "ETF" in p.get("sector", ""), 3) or [top["ticker"]],
        "buffett": _rank(pos, lambda p: p.get("sector") in ("Consumer Staples", "Healthcare") or p["ticker"] in ("AAPL", "BRK.B"), 3),
        "burry": [p["ticker"] for p in by_gain if p["weight_pct"] is not None and p["weight_pct"] >= 3][:3],
        "leopold": _rank(pos, lambda p: p["ticker"] in AI_TICKERS, 4),
        "cramer": [p["ticker"] for p in by_loss if p["pnl_pct"] < 0][:3],
    }
    for m in MEMBERS:  # every member gets something to look at
        focus[m] = focus[m] or [p["ticker"] for p in pos[:2]]
    covered = {t for ts in focus.values() for t in ts}
    for p in pos:  # every position above 5% weight is in at least one assignment
        if p["weight_pct"] is not None and p["weight_pct"] > 5 and p["ticker"] not in covered:
            m = min(("burry", "buffett"), key=lambda m: len(focus[m]))
            if len(focus[m]) < 4:
                focus[m].append(p["ticker"])
                covered.add(p["ticker"])
    beta = f.get("portfolio_beta")
    nw = f.get("brokerage_pct_of_net_worth")
    tech = f["sector_mix_pct"].get("Technology")
    worst = by_loss[0] if by_loss else top
    questions = {
        "dalio": [
            f"The connected brokerage is {nw}% of net worth" + (f" at beta {beta}" if beta else "") + "; how does the whole balance sheet do in a stagflation regime?",
            "What diversifiers are missing across all accounts, and how big should they be?",
        ] if nw else [
            "Which economic regime does this portfolio depend on, and what hedges it?",
            "What diversifiers are missing, and how big should they be?",
        ],
        "buffett": [
            f"Which of {', '.join(focus['buffett'])} are durable businesses at a fair price today?",
            "Is the uninvested cash working, and should it be?",
        ],
        "burry": [
            f"{top['ticker']} is {top['weight_pct']}% of holdings at {top['pnl_pct']:+}%; what is priced in?" if top["weight_pct"] is not None and top["pnl_pct"] is not None else f"Valuation or profit/loss for {top['ticker']} is unavailable; what data is needed to assess it?",
            f"What breaks first if the consensus on {', '.join(focus['burry'])} is wrong?",
        ],
        "leopold": [
            f"Is the AI exposure in {', '.join(focus['leopold'])} the bottlenecks, or the crowded names?",
            "Which holdings are exposed to AI disruption, and what is missing from the build-out?",
        ],
        "cramer": [
            f"{worst['ticker']} is {worst['pnl_pct']:+}%; catalyst or dead money?" if worst["pnl_pct"] is not None else f"Profit/loss for {worst['ticker']} is unavailable; what data is needed to assess performance?",
            f"Tech is {tech}% of holdings; is this diversified?" if tech else "Is this diversified across sectors?",
        ],
    }
    shared = [p["ticker"] for p in pos[:SHARED]]
    return {m: Assignment(focus_tickers=focus[m][:4], questions=questions[m][:3], shared_tickers=shared) for m in MEMBERS}


def merge_plan(canned: dict[str, Assignment], proposed: dict) -> dict[str, Assignment]:
    """Accept an LLM plan member by member; fall back to the canned assignment for anything invalid."""
    out = {}
    for m in MEMBERS:
        try:
            a = Assignment(**{**proposed[m], "shared_tickers": canned[m].shared_tickers})
            out[m] = a if a.focus_tickers and a.questions else canned[m]
        except (KeyError, TypeError, ValueError):
            out[m] = canned[m]
        out[m].focus_tickers, out[m].questions = out[m].focus_tickers[:4], out[m].questions[:3]
    return out


# --- verify ------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?")


def _numbers(text: str) -> list[float]:
    out = []
    for tok in NUMBER.findall(text):
        try:
            out.append(float(tok.replace("$", "").replace(",", "").strip("+%")))  # "-$10,850" -> -10850
        except ValueError:
            pass
    return out


def _supported(n: float, corpus: list[float]) -> bool:
    if abs(n) <= 10 and n == int(n) or 1900 <= n <= 2100:  # counts, list sizes and years are not claims
        return True
    return any(abs(c - n) <= max(0.5, abs(c) * 0.01) for c in corpus)


def _texts(v: Analysis) -> list[str]:
    out = [v.headline, v.analysis, *v.reasons]
    if isinstance(v, Verdict):
        out += [p.rationale for p in v.positions] + [f"{a.action} {a.why}" for a in v.advice]
    return out


def unsupported(v: Analysis, brief: dict, sources: list | None = None) -> list[str]:
    """Numbers in the output that appear neither in the brief nor in the member's own sources."""
    corpus = _numbers(json.dumps(brief["facts"])) + _numbers(brief["persona"])
    corpus += [n for s in (sources if sources is not None else getattr(v, "sources", [])) for n in _numbers(s.quote)]
    corpus += [abs(n) for n in corpus]
    return sorted({tok for t in _texts(v) for tok in NUMBER.findall(t) if not all(_supported(n, corpus) for n in _numbers(tok))})


def strip_unsupported(v: Analysis, bad: list[str]) -> Analysis:
    """Second failure: drop every sentence, reason, call and advice item that carries an unsupported number."""
    hit = lambda t: any(b in t for b in bad)  # noqa: E731
    sentences = re.split(r"(?<=[.!?])\s+", v.analysis)
    update = {
        "analysis": " ".join(s for s in sentences if not hit(s)),
        "reasons": [r for r in v.reasons if not hit(r)] or ["Claims without a source were removed."],
        "headline": v.headline if not hit(v.headline) else "Verdict trimmed to sourced claims",
    }
    if isinstance(v, Verdict):
        update["positions"] = [p for p in v.positions if not hit(p.rationale)]
        update["advice"] = [a for a in v.advice if not hit(f"{a.action} {a.why}")]
    return v.model_copy(update=update)


def check_calls(v: Verdict, held: list[str], names: list[str]) -> Verdict:
    """Calls only on held names the member researched, one per name; `high` needs a quoted source on that name."""
    seen, calls = set(), []
    for p in v.positions:
        t = p.ticker.upper()
        if t in seen or t not in held or t not in names:
            continue
        seen.add(t)
        quoted = any(s.quote and s.ticker == t for s in v.sources)
        calls.append(p.model_copy(update={"ticker": t, "conviction": "mid" if p.conviction == "high" and not quoted else p.conviction}))
    return v.model_copy(update={"positions": calls})


# --- rule --------------------------------------------------------------------


def rule_names(verdicts: dict[str, Verdict], brief: dict) -> list[NameRuling]:
    """Per held name, from the members' calls:
    unanimous 3+ -> high; unanimous 2 -> mid (high if both high); one caller -> their conviction, capped at mid;
    a clear majority -> mid at 3+ callers, else low; a tie -> HOLD, low, "split"."""
    weight = {p["ticker"]: p["weight_pct"] for p in brief["facts"]["positions"]}
    calls: dict[str, dict[str, tuple[str, str]]] = {}
    for m, v in verdicts.items():
        for p in v.positions:
            calls.setdefault(p.ticker, {})[m] = (p.signal, p.conviction)
    order = ["low", "mid", "high"]
    out = []
    for t, c in calls.items():
        signals = [s for s, _ in c.values()]
        counts = {s: signals.count(s) for s in set(signals)}
        top = max(counts.values())
        leaders = [s for s, n in counts.items() if n == top]
        n = len(signals)
        if len(leaders) > 1:
            signal, conviction = "HOLD", "low"
            consensus = "split: " + ", ".join(f"{DISPLAY[m]} {s}" for m, (s, _) in c.items())
        else:
            signal = leaders[0]
            if n == 1:
                conviction = min(next(iter(c.values()))[1], "mid", key=order.index)
            elif top == n:
                conviction = "high" if n >= 3 or all(cv == "high" for _, cv in c.values()) else "mid"
            else:
                conviction = "mid" if n >= 3 else "low"
            consensus = f"{top} of {n} say {signal}"
        out.append(NameRuling(ticker=t, calls={m: s for m, (s, _) in c.items()}, signal=signal, conviction=conviction, consensus=consensus))
    return sorted(out, key=lambda r: (-order.index(r.conviction), r.signal == "HOLD", -len(r.calls), -(weight.get(r.ticker) or 0)))


def rule(verdicts: dict[str, Verdict], brief: dict, roast: bool) -> Chair:
    names = rule_names(verdicts, brief)
    strongest = names[0] if names else None
    return Chair(
        consensus=f"The council made calls on {len(names)} names" + (f"; strongest: {strongest.signal} {strongest.ticker} ({strongest.consensus})" if strongest else ""),
        positions=names,
        dissent=dissent(names),
        actions=merge_actions(verdicts, names),
        summary=("Order. The council has roasted you thoroughly. " if roast else "Order. ")
        + (f"Strongest call: {strongest.signal} {strongest.ticker}, {strongest.consensus}. " if strongest else "")
        + (f"Split on {', '.join(r.ticker for r in names if r.consensus.startswith('split'))}. " if any(r.consensus.startswith("split") for r in names) else "")
        + "Parody council, not financial advice.",
        suggestions=suggestions(verdicts, brief, names),
    )


def cap_chair(chair: Chair, verdicts: dict[str, Verdict], brief: dict) -> Chair:
    """Guard an LLM ruling: per-name rulings always come from the members' actual calls."""
    chair = chair.model_copy(update={"positions": rule_names(verdicts, brief)})
    if not chair.summary.rstrip().endswith("not financial advice."):
        chair = chair.model_copy(update={"summary": chair.summary.rstrip() + " Parody council, not financial advice."})
    return chair


def dissent(names: list[NameRuling]) -> list[str]:
    out = []
    for r in names:
        if r.consensus.startswith("split"):
            out.append(f"{r.ticker} {r.consensus}")
        elif against := [f"{DISPLAY[m]} {s}" for m, s in r.calls.items() if s != r.signal]:
            out.append(f"{r.ticker}: {', '.join(against)} against {r.consensus}")
    return out


def merge_actions(verdicts: dict[str, Verdict], names: list[NameRuling], limit: int = 4) -> list[str]:
    """Top per-name rulings (not low), then portfolio advice merged by tickers or wording, credited to every member."""
    out = [f"{r.signal} {r.ticker} ({', '.join(DISPLAY[m] for m, s in r.calls.items() if s == r.signal)}; {r.conviction})"
           for r in names if r.conviction != "low"][:2]
    merged: dict[tuple, tuple[str, list[str]]] = {}
    for m, v in verdicts.items():
        for a in v.advice:
            key = tuple(sorted(a.tickers)) or (a.action.lower(),)
            text, who = merged.get(key, (a.action, []))
            merged[key] = (text, who if DISPLAY[m] in who else who + [DISPLAY[m]])
    out += [f"{text} ({', '.join(who)})" for text, who in sorted(merged.values(), key=lambda tw: -len(tw[1]))]
    return out[:limit]


def suggestions(verdicts: dict[str, Verdict], brief: dict, names: list[NameRuling] | None = None) -> list[str]:
    """2-3 follow-ups for the chat chips, filled from the rulings and the brief."""
    names = names if names is not None else rule_names(verdicts, brief)
    out = []
    split = next((r for r in names if r.consensus.startswith("split")), None) or next((r for r in names if len(set(r.calls.values())) > 1), None)
    if split:
        by = lambda sig: next((m for m, s in split.calls.items() if s == sig), None)  # noqa: E731
        a = by("SELL") or list(split.calls)[0]
        b = by("BUY") if by("BUY") and by("BUY") != a else next(m for m, s in split.calls.items() if s != split.calls[a])
        out.append(f"{DISPLAY[a]} and {DISPLAY[b]} split on {split.ticker}. Settle it.")
    top = brief["facts"]["positions"][0]["ticker"]
    out.append(f"Michael, why worry about {top}?")
    out.append("What should I do with my savings?")
    return out[:3]


# --- route -------------------------------------------------------------------

EVERYONE = re.compile(r"\b(everyone|everybody|whole council|all of you|all five|council)\b", re.I)
META = re.compile(r"\b(summari[sz]e|recap|who (?:was|is|were) (?:most|the)|who disagreed|so far)\b", re.I)
ROAST = re.compile(r"\broast\b", re.I)
LENS = [
    (re.compile(r"\b(sav(e|ings)|cash|bonds?|inflation|rates?|retire\w*|401k|ira|macro|recession|hedge)\b", re.I), ["dalio", "buffett"]),
    (re.compile(r"\b(ai|chips?|compute|semis?|data ?cent(er|re)s?|gpu)\b", re.I), ["leopold"]),
    (re.compile(r"\b(bubble|overvalued|crash|short|downside|risk)\b", re.I), ["burry"]),
    (re.compile(r"\b(earnings|catalyst|trade|trading|meme|momentum)\b", re.I), ["cramer"]),
    (re.compile(r"\b(dividends?|value|moat|long[- ]term|index)\b", re.I), ["buffett"]),
]


def mentioned(text: str) -> list[str]:
    """Members named or @-mentioned, in order of appearance."""
    hits = []
    for m, words in NAMES.items():
        pos = [x.start() for w in (m, *words) for x in re.finditer(rf"(?<![\w])@?{w}\b", text, re.I)]
        if pos:
            hits.append((min(pos), m))
    return [m for _, m in sorted(hits)]


def route(text: str, to: list[str], verdicts: dict[str, Verdict], holdings: list[str]) -> tuple[list[str], str, bool]:
    """(speakers, reason, roast) for one chat turn. `chair` alone means the coordinator answers itself."""
    if to:
        return list(dict.fromkeys(to)), "addressed directly", False
    if ROAST.search(text):
        return list(MEMBERS), "roast requested", True
    if META.search(text):
        return ["chair"], "about the conversation", False
    named = mentioned(text)
    if EVERYONE.search(text) and not named:
        return list(MEMBERS), "the whole council", False
    if named:
        return named[:MAX_SPEAKERS], "named in the question", False
    tickers = [t for t in holdings if re.search(rf"\b{re.escape(t)}\b", text, re.I)]
    if tickers:
        t = tickers[0]
        bull = next((m for m, v in verdicts.items() if m != "burry" and any(p.ticker == t and p.signal == "BUY" for p in v.positions)), None)
        bull = bull or ("leopold" if t in AI_TICKERS else "buffett")
        return ["burry", bull], f"a single holding ({t}): the bear and a bull", False
    for pattern, members in LENS:
        if pattern.search(text):
            return members, "best lens for the question", False
    return ["buffett", "dalio"], "general question", False
