import os
from pathlib import Path

MEMBERS = ("buffett", "cramer", "burry", "leopold")
COUNCIL_DIR = Path(__file__).resolve().parent.parent / "council"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def voice_id(member: str) -> str:
    return env(f"ELEVENLABS_VOICE_{member.upper()}") or env("ELEVENLABS_VOICE_ID")


def council_version() -> str:
    """"v1" turns PRISM Knowledge Base retrieval off (the pre-KB backend); anything else is "v2"."""
    return "v1" if env("COUNCIL_VERSION") == "v1" else "v2"
