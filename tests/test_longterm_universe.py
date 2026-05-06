"""Unit tests for long-term universe builder."""

from __future__ import annotations

from tradingagents.scanner import longterm_universe
from tradingagents.scanner.longterm_models import LongTermFilters


def test_mega_cap_universe_constant_is_nonempty_and_uppercase() -> None:
    assert len(longterm_universe.MEGA_CAP_UNIVERSE) >= 80
    assert all(s == s.upper() for s in longterm_universe.MEGA_CAP_UNIVERSE)


def test_default_returns_curated_mega_cap_list() -> None:
    out = longterm_universe.build(LongTermFilters())
    assert out == list(longterm_universe.MEGA_CAP_UNIVERSE)


def test_watchlist_overrides_default() -> None:
    out = longterm_universe.build(
        LongTermFilters(watchlist=("nvda", "amd", "googl"))
    )
    assert out == ["NVDA", "AMD", "GOOGL"]


def test_watchlist_dedupes_while_preserving_order() -> None:
    out = longterm_universe.build(
        LongTermFilters(watchlist=("AAPL", "MSFT", "AAPL", "msft", "NVDA"))
    )
    assert out == ["AAPL", "MSFT", "NVDA"]


def test_universe_does_not_mutate_master_tuple() -> None:
    out = longterm_universe.build(LongTermFilters())
    out.append("ZZZZ")
    assert "ZZZZ" not in longterm_universe.MEGA_CAP_UNIVERSE


def test_known_megacaps_in_universe() -> None:
    for s in ("NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMD"):
        assert s in longterm_universe.MEGA_CAP_UNIVERSE
