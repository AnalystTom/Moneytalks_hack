import os
from pathlib import Path

MEMBERS = ("buffett", "dalio", "burry", "leopold", "cramer")
CHAIR = "chair"  # the neutral coordinator; speaks but is not one of the five
SPEAKERS = (*MEMBERS, CHAIR)
COUNCIL_DIR = Path(__file__).resolve().parent.parent / "council"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # repo-root .env (gitignored); see .env.example


def load_env_file(path: Path = ENV_FILE) -> None:
    """KEY=value lines into os.environ; variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


load_env_file()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def voice_id(member: str) -> str:
    return env(f"ELEVENLABS_VOICE_{member.upper()}")
