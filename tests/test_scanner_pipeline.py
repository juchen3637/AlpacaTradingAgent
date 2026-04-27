"""Integration tests for ScannerPipeline with a mocked DataProvider."""

from __future__ import annotations

from typing import Optional

import pytest

from tradingagents.scanner.models import (
    KeyLevels,
    ScanFilters,
    TickerSnapshot,
)
from tradingagents.scanner.pipeline import ScannerPipeline


class _FakeProvider:
    """Lightweight fake: universe and per-symbol fixtures configured at init."""

    def __init__(
        self,
        universe: list[str],
        snapshots: dict[str, Optional[TickerSnapshot]],
        levels: dict[str, KeyLevels],
    ):
        self._universe = universe
        self._snapshots = snapshots
        self._levels = levels
        self.snapshot_calls: list[str] = []
        self.level_calls: list[str] = []

    def build_universe(self, filters: ScanFilters) -> list[str]:
        return list(self._universe)

    def fetch_snapshot(self, symbol: str) -> Optional[TickerSnapshot]:
        self.snapshot_calls.append(symbol)
        return self._snapshots.get(symbol)

    def fetch_key_levels(self, symbol: str) -> KeyLevels:
        self.level_calls.append(symbol)
        return self._levels.get(symbol, KeyLevels())


def _make_qualifying_snap(symbol: str, **overrides) -> TickerSnapshot:
    base = dict(
        symbol=symbol,
        is_crypto=False,
        last_price=50.0,
        change_pct=3.0,
        premarket_volume=500_000,
        rvol=3.0,
        float_shares=15_000_000_000,
        has_catalyst=False,
        today_volume=None,
        prior_30d_max_volume=None,
        above_sma10=True,
        macd_signal_cross=True,
        vwap_reclaim=False,
        opening_range_high=None,
        minutes_since_open=None,
        levels=KeyLevels(),
    )
    base.update(overrides)
    return TickerSnapshot(**base)


@pytest.mark.integration
def test_pipeline_empty_universe_returns_empty():
    provider = _FakeProvider(universe=[], snapshots={}, levels={})
    pipeline = ScannerPipeline(provider)
    assert pipeline.run(ScanFilters()) == []


@pytest.mark.integration
def test_pipeline_drops_when_snapshot_missing():
    provider = _FakeProvider(universe=["AAA"], snapshots={"AAA": None}, levels={})
    pipeline = ScannerPipeline(provider)
    assert pipeline.run(ScanFilters()) == []
    # No level fetch when snapshot missing
    assert provider.level_calls == []


@pytest.mark.integration
def test_pipeline_drops_when_filters_fail():
    # Price too high
    snap = _make_qualifying_snap("ZZZ", last_price=9999.0)
    provider = _FakeProvider(
        universe=["ZZZ"],
        snapshots={"ZZZ": snap},
        levels={},
    )
    pipeline = ScannerPipeline(provider)
    results = pipeline.run(ScanFilters(price_max=100))
    assert results == []
    # Level enrichment should NOT run for filter failures
    assert provider.level_calls == []


@pytest.mark.integration
def test_pipeline_drops_when_no_strategy_matches():
    # Passes filters but no indicators → no strategy
    snap = _make_qualifying_snap(
        "XYZ", above_sma10=False, macd_signal_cross=False,
    )
    provider = _FakeProvider(
        universe=["XYZ"],
        snapshots={"XYZ": snap},
        levels={"XYZ": KeyLevels()},
    )
    pipeline = ScannerPipeline(provider)
    assert pipeline.run(ScanFilters()) == []


@pytest.mark.integration
def test_pipeline_returns_matched_ticker():
    snap = _make_qualifying_snap("NVDA", rvol=4.0)
    provider = _FakeProvider(
        universe=["NVDA"],
        snapshots={"NVDA": snap},
        levels={"NVDA": KeyLevels()},
    )
    pipeline = ScannerPipeline(provider)
    results = pipeline.run(ScanFilters())
    assert len(results) == 1
    assert results[0].snapshot.symbol == "NVDA"
    assert results[0].strategy_id == "SMA10_MACD"
    assert results[0].strategy_name == "10-SMA + MACD Crossover"


@pytest.mark.integration
def test_pipeline_sorts_by_score_descending():
    # Two qualifying tickers, different RVOLs → higher RVOL first
    snap_a = _make_qualifying_snap("AAA", rvol=3.0, change_pct=1.0)
    snap_b = _make_qualifying_snap("BBB", rvol=10.0, change_pct=10.0, has_catalyst=True)
    provider = _FakeProvider(
        universe=["AAA", "BBB"],
        snapshots={"AAA": snap_a, "BBB": snap_b},
        levels={"AAA": KeyLevels(), "BBB": KeyLevels()},
    )
    pipeline = ScannerPipeline(provider)
    results = pipeline.run(ScanFilters())
    assert len(results) == 2
    assert results[0].snapshot.symbol == "BBB"
    assert results[1].snapshot.symbol == "AAA"
    assert results[0].score > results[1].score


@pytest.mark.integration
def test_pipeline_caps_at_max_results():
    from tradingagents.scanner.constants import MAX_RESULTS

    universe = [f"T{i}" for i in range(MAX_RESULTS + 10)]
    snaps = {
        sym: _make_qualifying_snap(sym, rvol=3.0 + i * 0.01)
        for i, sym in enumerate(universe)
    }
    levels = {sym: KeyLevels() for sym in universe}
    provider = _FakeProvider(universe=universe, snapshots=snaps, levels=levels)

    pipeline = ScannerPipeline(provider)
    results = pipeline.run(ScanFilters())
    assert len(results) == MAX_RESULTS


@pytest.mark.integration
def test_pipeline_level_enrichment_only_for_survivors():
    """Key-level fetch should only run for tickers that pass filters."""
    ok_snap = _make_qualifying_snap("OK", rvol=3.0)
    bad_snap = _make_qualifying_snap("BAD", last_price=0.01)  # fails price band
    provider = _FakeProvider(
        universe=["OK", "BAD"],
        snapshots={"OK": ok_snap, "BAD": bad_snap},
        levels={"OK": KeyLevels(), "BAD": KeyLevels()},
    )
    pipeline = ScannerPipeline(provider)
    pipeline.run(ScanFilters())
    # Both snapshots were fetched …
    assert set(provider.snapshot_calls) == {"OK", "BAD"}
    # … but only the survivor triggered level enrichment
    assert provider.level_calls == ["OK"]
