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
def test_non_empty_watchlist_overrides_crypto_universe():
    """Filling the watchlist scans only those symbols, even with crypto universe selected."""
    filters = ScanFilters(universe_kind="crypto", watchlist=("BTC/USD", "LUNA/USD"))
    assert build(filters) == ["BTC/USD", "LUNA/USD"]


@pytest.mark.unit
def test_non_empty_watchlist_overrides_most_active():
    """Filling the watchlist short-circuits the most-actives fetch."""
    filters = ScanFilters(universe_kind="most_active", watchlist=("TSLA", "NVDA"))

    def _should_not_run(_n):
        raise AssertionError("most-actives fetcher should not be called when watchlist is non-empty")

    assert build(filters, most_actives_fetcher=_should_not_run) == ["TSLA", "NVDA"]


@pytest.mark.unit
def test_empty_watchlist_falls_back_to_most_active():
    """Empty watchlist → use the most-actives universe."""
    filters = ScanFilters(universe_kind="most_active", watchlist=())
    symbols = build(filters, most_actives_fetcher=lambda n: ["AAPL", "TSLA", "AMD"])
    assert symbols == ["AAPL", "TSLA", "AMD"]


@pytest.mark.unit
def test_empty_watchlist_falls_back_to_crypto():
    filters = ScanFilters(universe_kind="crypto", watchlist=())
    symbols = build(filters)
    assert "BTC/USD" in symbols
    assert "ETH/USD" in symbols
