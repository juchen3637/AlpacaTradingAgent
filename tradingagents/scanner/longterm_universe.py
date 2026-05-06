"""Long-term candidate universe builder.

Resolution order:
1. If `filters.watchlist` is non-empty, return exactly those symbols.
2. Otherwise return the curated mega-cap list (S&P 100 ≈ 100 tickers).

The S&P 100 is refreshed manually at year-end. Source:
https://en.wikipedia.org/wiki/S%26P_100
TODO: refresh annually.
"""

from __future__ import annotations

from .longterm_models import LongTermFilters

# Curated mega-cap universe (S&P 100 constituents, sorted alphabetically).
# Frozen tuple so callers can't mutate it.
MEGA_CAP_UNIVERSE: tuple[str, ...] = (
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK.B", "C",
    "CAT", "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS",
    "CVX", "DE", "DHR", "DIS", "DUK", "EMR", "F", "FDX", "GD", "GE",
    "GILD", "GM", "GOOG", "GOOGL", "GS", "HD", "HON", "IBM", "INTC", "INTU",
    "ISRG", "JNJ", "JPM", "KHC", "KO", "LIN", "LLY", "LMT", "LOW", "MA",
    "MCD", "MDLZ", "MDT", "MET", "META", "MMM", "MO", "MRK", "MS", "MSFT",
    "NEE", "NFLX", "NKE", "NOW", "NVDA", "ORCL", "PEP", "PFE", "PG", "PLTR",
    "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT",
    "TMO", "TMUS", "TSLA", "TXN", "UNH", "UNP", "UPS", "USB", "V", "VZ",
    "WFC", "WMT", "XOM",
)


def build(filters: LongTermFilters) -> list[str]:
    """Resolve LongTermFilters → concrete ticker list."""
    if filters.watchlist:
        # De-dupe while preserving user-typed order.
        seen: set[str] = set()
        out: list[str] = []
        for s in filters.watchlist:
            up = s.upper()
            if up not in seen:
                seen.add(up)
                out.append(up)
        return out

    return list(MEGA_CAP_UNIVERSE)
