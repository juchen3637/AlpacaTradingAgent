"""Candidate ticker universe builders.

Three universes supported:
- "watchlist": exact symbols the user provides in ScanFilters.watchlist
- "most_active": Alpaca ScreenerClient.get_most_actives top N
- "crypto": small hard-coded crypto universe (Phase 4 expands this)
"""

from __future__ import annotations

import logging
from typing import Optional

from .constants import DEFAULT_CRYPTO_UNIVERSE_LIMIT, DEFAULT_MOST_ACTIVE_LIMIT
from .models import ScanFilters

logger = logging.getLogger(__name__)

_CRYPTO_DEFAULT_UNIVERSE = (
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
    "LINK/USD", "MATIC/USD", "ADA/USD", "DOT/USD", "LTC/USD",
)


def _fetch_most_actives(limit: int = DEFAULT_MOST_ACTIVE_LIMIT) -> list[str]:
    """Fetch most-active US stocks via Alpaca ScreenerClient.

    Returns an empty list on any failure — the caller can fall back to watchlist.
    """
    try:
        from alpaca.data.historical.screener import ScreenerClient
        from alpaca.data.requests import MostActivesRequest

        from tradingagents.dataflows.config import get_api_key

        api_key = get_api_key("alpaca_api_key", "ALPACA_API_KEY")
        api_secret = get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
        if not api_key or not api_secret:
            logger.warning("Alpaca credentials missing — most-actives universe empty")
            return []

        client = ScreenerClient(api_key, api_secret)
        req = MostActivesRequest(top=limit)
        resp = client.get_most_actives(req)
        return [m.symbol for m in resp.most_actives]
    except Exception as exc:
        logger.warning("Failed to fetch most-actives from Alpaca: %s", exc)
        return []


def build(
    filters: ScanFilters,
    most_actives_fetcher: Optional[callable] = None,
) -> list[str]:
    """Resolve ScanFilters → concrete ticker list.

    `most_actives_fetcher` is injectable for tests.
    """
    fetcher = most_actives_fetcher or _fetch_most_actives

    if filters.universe_kind == "watchlist":
        return list(filters.watchlist)

    if filters.universe_kind == "crypto":
        base = list(_CRYPTO_DEFAULT_UNIVERSE[:DEFAULT_CRYPTO_UNIVERSE_LIMIT])
        # Dedup with user watchlist additions
        extras = [s for s in filters.watchlist if s not in base]
        return base + extras

    # default: most_active + watchlist, dedup
    symbols = fetcher(DEFAULT_MOST_ACTIVE_LIMIT)
    seen = set(symbols)
    for sym in filters.watchlist:
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)
    return symbols
