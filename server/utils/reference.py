"""Static reference data for demo enrichment.

Brokerage position APIs (Alpaca, Tradier, IBKR) return qty / avg entry / market
value and nothing else. Sector, beta, dividend yield, 52-week range and quality
flags normally come from a separate market-data vendor. For the demo we keep a
small hand-written table so the app has zero external dependencies.

ALL NUMBERS BELOW ARE SYNTHETIC DEMO VALUES. They are not market data.
"""

SECURITIES = {
    "NVDA": dict(name="NVIDIA Corp",            sector="Technology",        beta=1.72, div_yield=0.02, cap="mega",  style="growth", wk52_high=212.0, wk52_low=86.4,  profitable=True,  fcf_positive=True),
    "AAPL": dict(name="Apple Inc",              sector="Technology",        beta=1.14, div_yield=0.48, cap="mega",  style="blend",  wk52_high=268.0, wk52_low=169.2, profitable=True,  fcf_positive=True),
    "MSFT": dict(name="Microsoft Corp",         sector="Technology",        beta=0.96, div_yield=0.71, cap="mega",  style="blend",  wk52_high=544.0, wk52_low=385.0, profitable=True,  fcf_positive=True),
    "AMD":  dict(name="Advanced Micro Devices", sector="Technology",        beta=1.88, div_yield=0.00, cap="large", style="growth", wk52_high=227.0, wk52_low=94.5,  profitable=True,  fcf_positive=True),
    "TSLA": dict(name="Tesla Inc",              sector="Consumer Cyclical", beta=2.11, div_yield=0.00, cap="mega",  style="growth", wk52_high=488.0, wk52_low=214.0, profitable=True,  fcf_positive=True),
    "PLTR": dict(name="Palantir Technologies",  sector="Technology",        beta=2.34, div_yield=0.00, cap="large", style="growth", wk52_high=204.0, wk52_low=71.0,  profitable=True,  fcf_positive=True),
    "COIN": dict(name="Coinbase Global",        sector="Financials",        beta=3.02, div_yield=0.00, cap="large", style="growth", wk52_high=412.0, wk52_low=142.0, profitable=True,  fcf_positive=False),
    "SOFI": dict(name="SoFi Technologies",      sector="Financials",        beta=1.95, div_yield=0.00, cap="small", style="growth", wk52_high=32.4,  wk52_low=11.8,  profitable=False, fcf_positive=False),
    "GME":  dict(name="GameStop Corp",          sector="Consumer Cyclical", beta=1.41, div_yield=0.00, cap="small", style="spec",   wk52_high=41.2,  wk52_low=18.6,  profitable=False, fcf_positive=False),
    "KO":   dict(name="Coca-Cola Co",           sector="Consumer Staples",  beta=0.58, div_yield=2.94, cap="mega",  style="value",  wk52_high=78.9,  wk52_low=60.1,  profitable=True,  fcf_positive=True),
    "JNJ":  dict(name="Johnson & Johnson",      sector="Healthcare",        beta=0.52, div_yield=3.02, cap="mega",  style="value",  wk52_high=196.0, wk52_low=145.0, profitable=True,  fcf_positive=True),
    "XOM":  dict(name="Exxon Mobil Corp",       sector="Energy",            beta=0.84, div_yield=3.41, cap="mega",  style="value",  wk52_high=134.0, wk52_low=98.0,  profitable=True,  fcf_positive=True),
    "SPY":  dict(name="SPDR S&P 500 ETF",       sector="Broad Index ETF",   beta=1.00, div_yield=1.18, cap="etf",   style="blend",  wk52_high=742.0, wk52_low=575.0, profitable=True,  fcf_positive=True),
    "SCHD": dict(name="Schwab US Dividend ETF", sector="Dividend ETF",      beta=0.78, div_yield=3.66, cap="etf",   style="value",  wk52_high=29.8,  wk52_low=24.1,  profitable=True,  fcf_positive=True),
}

# Rough S&P 500 sector weights, used only as a "vs. the market" yardstick.
BENCHMARK_SECTOR_WEIGHTS = {
    "Technology": 34.0, "Financials": 13.5, "Consumer Cyclical": 10.5,
    "Healthcare": 9.5, "Communication Services": 9.5, "Industrials": 8.0,
    "Consumer Staples": 5.5, "Energy": 3.5, "Utilities": 2.5,
    "Real Estate": 2.0, "Materials": 2.0,
}

def info(symbol):
    return SECURITIES.get(symbol.upper(), dict(
        name=symbol.upper(), sector="Unclassified", beta=1.0, div_yield=0.0,
        cap="unknown", style="blend", wk52_high=None, wk52_low=None,
        profitable=True, fcf_positive=True,
    ))
