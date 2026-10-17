# Stub: swap for a real quote API (spec: market data TBD).
PRICES = {"VOO": 500.0, "SPY": 550.0, "AAPL": 230.0, "NVDA": 140.0, "CMCSA": 38.0}


async def prices(tickers: list[str], fallback: dict[str, float]) -> dict[str, float]:
    """Latest price per ticker; unknown tickers fall back to the given price (cost basis)."""
    return {t: PRICES.get(t, fallback[t]) for t in tickers}
