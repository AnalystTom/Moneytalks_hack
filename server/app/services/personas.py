"""Council members are the files in agents/personas/: adding a member is adding a file."""
from dataclasses import dataclass
from functools import lru_cache

from app.config import AGENTS_DIR


@dataclass(frozen=True)
class Persona:
    member: str  # id used in SSE events and the UI, e.g. "buffett"
    name: str
    role: str
    order: int
    chair: bool
    specialist: str  # Persona column in data/specialist.csv
    voice_names: tuple[str, ...]
    voice_fallback: str
    body: str


def parse(text: str) -> Persona:
    _, front, body = text.split("---\n", 2)
    meta = dict(ln.split(":", 1) for ln in front.strip().splitlines())
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    return Persona(
        member=meta["member"], name=meta["name"], role=meta.get("role", ""), order=int(meta.get("order", 99)),
        chair=meta.get("chair") == "true", specialist=meta.get("specialist", meta["name"]),
        voice_names=tuple(n.strip() for n in meta.get("voice_names", meta["name"]).split(",")),
        voice_fallback=meta.get("voice_fallback", ""), body=body.strip(),
    )


@lru_cache
def load() -> dict[str, Persona]:
    found = sorted((parse(p.read_text()) for p in (AGENTS_DIR / "personas").glob("*.md")), key=lambda p: p.order)
    if sum(p.chair for p in found) != 1:
        raise ValueError("agents/personas needs exactly one persona with `chair: true`")
    return {p.member: p for p in found}


def chair() -> Persona:
    return next(p for p in load().values() if p.chair)


def prompt(name: str) -> str:
    """agents/<name>.md, e.g. orchestrator or skill."""
    return (AGENTS_DIR / f"{name}.md").read_text().strip()
