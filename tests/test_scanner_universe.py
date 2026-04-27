"""Tests for the scanner universe builder (watchlist / most-active / crypto)."""

from __future__ import annotations

import pytest

from tradingagents.scanner.models import ScanFilters
from tradingagents.scanner.universe import build


@pytest.mark.unit
def test_watchlist_universe_returns_exact_symbols():
    filters = ScanFilters(universe_kind="watchlist", watchlist=("AAPL", "NVDA", "TSLA"))
    assert build(filters) == ["AAPL", "NVDA", "TSLA"]


@pytest.mark.unit
def test_watchlist_empty():
    filters = ScanFilters(universe_kind="watchlist", watchlist=())
    assert build(filters) == []


@pytest.mark.unit
def test_crypto_universe_has_btc_eth():
    filters = ScanFilters(universe_kind="crypto")
    symbols = build(filters)
    assert "BTC/USD" in symbols
    assert "ETH/USD" in symbols
    assert all("/" in s for s in symbols)


@pytest.mark.unit
def test_crypto_universe_dedups_extras():
    filters = ScanFilters(universe_kind="crypto", watchlist=("BTC/USD", "LUNA/USD"))
    symbols = build(filters)
    assert symbols.count("BTC/USD") == 1
    assert "LUNA/USD" in symbols


@pytest.mark.unit
def test_most_active_injects_watchlist_at_end():
    filters = ScanFilters(universe_kind="most_active", watchlist=("TSLA", "NVDA"))
    # Fake fetcher returns a fixed list; TSLA is already in it (should dedup),
    # NVDA is not (should be appended).
    symbols = build(filters, most_actives_fetcher=lambda n: ["AAPL", "TSLA", "AMD"])
    assert symbols == ["AAPL", "TSLA", "AMD", "NVDA"]


@pytest.mark.unit
def test_most_active_empty_fetch_still_returns_watchlist():
    filters = ScanFilters(universe_kind="most_active", watchlist=("NVDA",))
    symbols = build(filters, most_actives_fetcher=lambda n: [])
    assert symbols == ["NVDA"]
