"""Integration test for LongTermPipeline with a fake provider."""

from __future__ import annotations

from typing import Optional

from tradingagents.scanner.longterm_models import (
    LongTermFilters,
    LongTermSnapshot,
)
from tradingagents.scanner.longterm_pipeline import (
    LONGTERM_MAX_RESULTS,
    LongTermPipeline,
)


class _FakeProvider:
    def __init__(self, snapshots: list[LongTermSnapshot]) -> None:
        self._snaps = {s.symbol: s for s in snapshots}

    def build_universe(self, filters: LongTermFilters) -> list[str]:
        if filters.watchlist:
            return list(filters.watchlist)
        return list(self._snaps.keys())

    def fetch_snapshot(self, symbol: str) -> Optional[LongTermSnapshot]:
        return self._snaps.get(symbol.upper())


def _make(symbol: str, score_inputs: dict) -> LongTermSnapshot:
    base = dict(symbol=symbol, last_price=100.0, market_cap_b=1000.0,
                sector="Technology", net_margin_ttm=20.0)
    base.update(score_inputs)
    return LongTermSnapshot(**base)


def test_pipeline_sorts_by_score_desc() -> None:
    snaps = [
        _make("LOW", {"roe_ttm": 5.0, "revenue_growth_3y": 2.0, "pe_forward": 50.0}),
        _make("HIGH", {"roe_ttm": 25.0, "revenue_growth_3y": 18.0, "pe_forward": 12.0,
                       "sma_200": 90.0, "above_sma_200": True, "golden_cross": True}),
        _make("MID", {"roe_ttm": 15.0, "revenue_growth_3y": 10.0, "pe_forward": 25.0}),
    ]
    pipe = LongTermPipeline(_FakeProvider(snaps), max_workers=1)
    out = pipe.run(LongTermFilters(min_market_cap_b=0))
    syms = [r.snapshot.symbol for r in out]
    assert syms == ["HIGH", "MID", "LOW"]


def test_pipeline_caps_at_max_results() -> None:
    snaps = [
        _make(f"T{i:02d}", {"roe_ttm": float(i), "revenue_growth_3y": float(i)})
        for i in range(40)
    ]
    pipe = LongTermPipeline(_FakeProvider(snaps), max_workers=1)
    out = pipe.run(LongTermFilters(min_market_cap_b=0))
    assert len(out) == LONGTERM_MAX_RESULTS


def test_pipeline_drops_filter_failures() -> None:
    snaps = [
        _make("KEEP", {"market_cap_b": 500.0, "net_margin_ttm": 20.0}),
        _make("DROP_SMALL", {"market_cap_b": 5.0, "net_margin_ttm": 20.0}),
        _make("DROP_LOSS", {"market_cap_b": 500.0, "net_margin_ttm": -5.0}),
    ]
    pipe = LongTermPipeline(_FakeProvider(snaps), max_workers=1)
    out = pipe.run(LongTermFilters(min_market_cap_b=100.0, must_be_profitable=True))
    syms = [r.snapshot.symbol for r in out]
    assert syms == ["KEEP"]


def test_pipeline_handles_none_snapshot_gracefully() -> None:
    """Provider returning None for some symbols should not crash."""

    class _PatchyProvider:
        def build_universe(self, _filters):
            return ["A", "B", "C"]
        def fetch_snapshot(self, sym):
            if sym == "B":
                return None
            return _make(sym, {"roe_ttm": 15.0, "revenue_growth_3y": 10.0})

    pipe = LongTermPipeline(_PatchyProvider(), max_workers=1)
    out = pipe.run(LongTermFilters(min_market_cap_b=0))
    assert {r.snapshot.symbol for r in out} == {"A", "C"}


def test_pipeline_watchlist_override() -> None:
    snaps = [_make(s, {"roe_ttm": 20.0, "revenue_growth_3y": 15.0})
             for s in ("AAPL", "MSFT", "NVDA")]
    pipe = LongTermPipeline(_FakeProvider(snaps), max_workers=1)
    out = pipe.run(LongTermFilters(watchlist=("NVDA",), min_market_cap_b=0))
    assert [r.snapshot.symbol for r in out] == ["NVDA"]


def test_pipeline_parallel_fetch_returns_same_results() -> None:
    snaps = [_make(f"T{i:02d}", {"roe_ttm": float(i)}) for i in range(20)]
    seq = LongTermPipeline(_FakeProvider(snaps), max_workers=1).run(
        LongTermFilters(min_market_cap_b=0)
    )
    par = LongTermPipeline(_FakeProvider(snaps), max_workers=4).run(
        LongTermFilters(min_market_cap_b=0)
    )
    # Same set of survivors and same ordering by score.
    assert [r.snapshot.symbol for r in seq] == [r.snapshot.symbol for r in par]
