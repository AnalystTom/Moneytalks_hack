# Stub: swap for Anchor web search (needs ANCHOR_API_KEY).
from app.models import Source


async def search(member: str, query: str) -> list[Source]:
    return [
        Source(
            title=f"Placeholder search result for {member}",
            url="https://example.com/anchor-stub",
            quote=f"Stub result for: {query[:80]}",
        )
    ]
