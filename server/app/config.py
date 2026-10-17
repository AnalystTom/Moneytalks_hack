import os
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = SERVER_DIR / "agents"
DATA_DIR = Path(os.environ.get("DATA_DIR") or SERVER_DIR.parent / "data")  # demo inputs: portfolio.json, PERSONA.md, specialist.csv
DEFAULT_MODEL = "anthropic/claude-opus-5-5"  # Claude Opus 5.5 in Nicrron's model list


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def model() -> str:
    """The Nicrron model id. Unset or the router alias `nicrron/auto` means Opus 5.5, which the hackathon build is pinned to."""
    m = env("NICRRON_MODEL")
    return DEFAULT_MODEL if m in ("", "nicrron/auto") else m
