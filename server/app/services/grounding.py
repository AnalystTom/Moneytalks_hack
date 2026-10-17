"""The "every number is in the source" check: figures in an answer that appear in neither the client file nor the sources."""
import re

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def figures(text: str) -> set[float]:
    return {float(m.rstrip(",.").replace(",", "")) for m in NUMBER.findall(text)}  # 20 == 20.0


def ungrounded(answer: str, *allowed: str) -> list[float]:
    """Sorted figures in `answer` that no `allowed` text contains."""
    known = figures(" ".join(allowed))
    return sorted(figures(answer) - known)
