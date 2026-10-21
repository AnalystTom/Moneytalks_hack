from app.models import PositionCall, Verdict
from app.services import coordinator

BRIEF = {"facts": {"positions": [{"ticker": t, "weight_pct": w} for t, w in [("AAA", 30), ("BBB", 20), ("CCC", 10)]]}}


def verdict(*calls):
    return Verdict(headline="h", analysis="a", reasons=["r"],
                   positions=[PositionCall(ticker=t, signal=s, conviction=c, rationale="x") for t, s, c in calls])


def rulings(**members):
    return {r.ticker: r for r in coordinator.rule_names({m: verdict(*c) for m, c in members.items()}, BRIEF)}


def test_unanimous_three_is_high_and_two_is_mid_unless_both_high():
    r = rulings(buffett=[("AAA", "SELL", "low"), ("BBB", "BUY", "high")], burry=[("AAA", "SELL", "mid"), ("BBB", "BUY", "high")],
                dalio=[("AAA", "SELL", "low"), ("CCC", "HOLD", "mid")], cramer=[("CCC", "HOLD", "low")])
    assert (r["AAA"].signal, r["AAA"].conviction) == ("SELL", "high")
    assert r["BBB"].conviction == "high" and r["CCC"].conviction == "mid"


def test_lone_call_keeps_conviction_capped_at_mid():
    r = rulings(burry=[("AAA", "SELL", "high"), ("BBB", "SELL", "low")])
    assert r["AAA"].conviction == "mid" and r["BBB"].conviction == "low"


def test_tie_is_a_split_hold_and_majority_needs_three_callers_for_mid():
    r = rulings(burry=[("AAA", "SELL", "high"), ("BBB", "SELL", "high")], leopold=[("AAA", "BUY", "high"), ("BBB", "SELL", "high")],
                cramer=[("BBB", "BUY", "low")])
    assert (r["AAA"].signal, r["AAA"].conviction) == ("HOLD", "low") and r["AAA"].consensus.startswith("split")
    assert (r["BBB"].signal, r["BBB"].conviction, r["BBB"].consensus) == ("SELL", "mid", "2 of 3 say SELL")


def test_check_calls_keeps_researched_held_names_and_needs_a_quote_for_high():
    from app.models import Source

    v = verdict(("AAA", "BUY", "high"), ("aaa", "SELL", "low"), ("BBB", "SELL", "high"), ("ZZZ", "BUY", "mid"), ("CCC", "BUY", "mid"),
                ("", "BUY", "high"), ("  ", "SELL", "low"))
    v = v.model_copy(update={"sources": [Source(title="t", url="u", quote="q", ticker="AAA")]})
    out = coordinator.check_calls(v, held=["AAA", "BBB", "CCC", "", "  "], names=["AAA", "BBB", "", "  "])
    assert [(p.ticker, p.conviction) for p in out.positions] == [("AAA", "high"), ("BBB", "mid")]
    assert {r.ticker for r in coordinator.rule_names({"buffett": v}, BRIEF)} == {"AAA", "BBB", "CCC"}


def test_route():
    route = lambda text: coordinator.route(text, [], {}, ["KO", "NVDA"])[0]  # noqa: E731
    assert route("@cramer what now?") == ["cramer"]
    assert route("Is KO a bubble?") == ["burry", "buffett"]  # no BUY call on file: a non-AI name gets Warren
    assert route("NVDA thoughts?") == ["burry", "leopold"]
    assert route("Should I worry about inflation?") == ["dalio", "buffett"]
    assert coordinator.route("Hello there", [], {}, ["", "  ", "NVDA"]) == (["buffett", "dalio"], "general question", False)


def test_numbers_parse_signed_dollars_and_tags_are_stripped():
    from app.services import llm

    assert coordinator._numbers("drag of -$10,850 and +$1,234.5") == [-10850.0, 1234.5]
    assert llm.strip_tags("<chair>The floor is yours.</chair>") == "The floor is yours."
