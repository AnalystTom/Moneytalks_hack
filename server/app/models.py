from typing import Literal

from pydantic import BaseModel, Field

Member = Literal["buffett", "dalio", "burry", "leopold", "cramer"]
Speaker = Literal["buffett", "dalio", "burry", "leopold", "cramer", "chair"]
Signal = Literal["BUY", "HOLD", "SELL"]
Conviction = Literal["low", "mid", "high"]


class Source(BaseModel):
    title: str
    url: str
    quote: str = ""
    ticker: str | None = None  # set when the search was about one held name


class Analysis(BaseModel):
    """Stage 1: the member's read of the whole portfolio. No buy/sell call here."""
    headline: str
    analysis: str  # 2-4 sentences, in character
    reasons: list[str]  # 2-3 observations
    names: list[str] = []  # held tickers the member wants to research before deciding


class PositionCall(BaseModel):
    """Stage 3: a decision on one held name, made after researching it."""
    ticker: str
    signal: Signal
    conviction: Conviction
    rationale: str


class Advice(BaseModel):
    action: str  # portfolio-level: what to do, not just what is wrong
    tickers: list[str] = []
    why: str = ""


class Verdict(Analysis):
    positions: list[PositionCall] = []
    advice: list[Advice] = []
    sources: list[Source] = []


class NameRuling(BaseModel):
    ticker: str
    calls: dict[str, Signal]  # member -> signal
    signal: Signal
    conviction: Conviction
    consensus: str


class Chair(BaseModel):
    consensus: str
    positions: list[NameRuling] = []
    dissent: list[str] = []
    actions: list[str] = []
    summary: str
    suggestions: list[str] = []


class Assignment(BaseModel):
    focus_tickers: list[str]  # names chosen for this member's lens
    questions: list[str]
    shared_tickers: list[str] = []  # the biggest holdings: every member calls these, so the council can vote on them


class RunRequest(BaseModel):
    brief_id: str
    question: str
    roast: bool = False


class ChatRequest(BaseModel):
    run_id: str
    text: str = Field(min_length=1, max_length=2000)
    to: list[Member] = []  # empty: the coordinator routes
    roast: bool = False


class AskRequest(BaseModel):  # kept for older clients; same as chat with to=[member]
    run_id: str
    member: Member
    question: str
    roast: bool = False


class SpeakRequest(BaseModel):
    member: Speaker
    text: str = Field(min_length=1, max_length=2500)
