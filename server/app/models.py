from typing import Literal

from pydantic import BaseModel, Field

Member = str  # a persona id from agents/personas, checked against services.personas at the router
Signal = Literal["BUY", "HOLD", "SELL"]


class Source(BaseModel):
    title: str
    url: str
    quote: str = ""


class Verdict(BaseModel):
    signal: Signal
    confidence: float = Field(ge=0, le=1)
    headline: str
    reasons: list[str]
    sources: list[Source] = []
    tickers: list[str] = []
    line: str = ""  # the short speech-bubble line the member says aloud


class Chair(BaseModel):
    overall_signal: Signal
    consensus: str
    dissent: list[str] = []
    summary: str


class RunRequest(BaseModel):
    brief_id: str
    question: str
    roast: bool = False


class AskRequest(BaseModel):
    run_id: str
    member: Member
    question: str
    roast: bool = False


class SpeakRequest(BaseModel):
    member: Member
    text: str = Field(min_length=1, max_length=2500)
