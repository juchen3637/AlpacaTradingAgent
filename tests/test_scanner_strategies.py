"""Unit tests for the strategy matcher."""

from __future__ import annotations

import pytest

from tradingagents.scanner.constants import (
    ATH_BREAKOUT,
    LOW_FLOAT_HVD,
    LOW_FLOAT_L2,
    ORB,
    SMA10_MACD,
    SPY_0DTE_FADE,
    VWAP_RECLAIM,
)
from tradingagents.scanner.models import KeyLevels, TickerSnapshot
from tradingagents.scanner.strategies import get_strategy_name, match_strategy


def _snap(**overrides) -> TickerSnapshot:
    base = dict(
        symbol="AAPL",
        is_crypto=False,
        last_price=100.0,
        change_pct=1.0,
        premarket_volume=None,
        rvol=None,
        float_shares=None,
        has_catalyst=False,
        today_volume=None,
        prior_30d_max_volume=None,
        above_sma10=False,
        macd_signal_cross=False,
        vwap_reclaim=False,
        opening_range_high=None,
        minutes_since_open=None,
        levels=KeyLevels(),
    )
    base.update(overrides)
    return TickerSnapshot(**base)


@pytest.mark.unit
def test_no_match_returns_none():
    assert match_strategy(_snap()) is None


@pytest.mark.unit
def test_spy_fade_near_pdh():
    snap = _snap(symbol="SPY", last_price=500.0, levels=KeyLevels(pdh=500.5))
    assert match_strategy(snap) == SPY_0DTE_FADE


@pytest.mark.unit
def test_spy_fade_near_pdl():
    snap = _snap(symbol="QQQ", last_price=400.0, levels=KeyLevels(pdl=400.8))
    assert match_strategy(snap) == SPY_0DTE_FADE


@pytest.mark.unit
def test_spy_far_from_levels_falls_through():
    # SPY but price far from both levels → no 0DTE fade match
    snap = _snap(symbol="SPY", last_price=500.0, levels=KeyLevels(pdh=520, pdl=480))
    assert match_strategy(snap) != SPY_0DTE_FADE


@pytest.mark.unit
def test_ath_breakout_match():
    snap = _snap(
        symbol="NVDA", last_price=999.5, rvol=3.5,
        levels=KeyLevels(ath=1000, vwap=995),
    )
    assert match_strategy(snap) == ATH_BREAKOUT


@pytest.mark.unit
def test_ath_breakout_needs_above_vwap():
    snap = _snap(
        symbol="NVDA", last_price=999.5, rvol=3.5,
        levels=KeyLevels(ath=1000, vwap=1000),  # below vwap
    )
    assert match_strategy(snap) != ATH_BREAKOUT


@pytest.mark.unit
def test_ath_breakout_needs_high_rvol():
    snap = _snap(
        symbol="NVDA", last_price=999.5, rvol=1.5,
        levels=KeyLevels(ath=1000, vwap=995),
    )
    assert match_strategy(snap) != ATH_BREAKOUT


@pytest.mark.unit
def test_low_float_hvd_match():
    snap = _snap(
        symbol="ATER", last_price=4.0,
        float_shares=15_000_000,
        today_volume=10_000_000,
        prior_30d_max_volume=8_000_000,
    )
    assert match_strategy(snap) == LOW_FLOAT_HVD


@pytest.mark.unit
def test_low_float_l2_match():
    snap = _snap(
        symbol="XYZ", last_price=5.0,
        float_shares=10_000_000, rvol=6.0,
    )
    assert match_strategy(snap) == LOW_FLOAT_L2


@pytest.mark.unit
def test_low_float_l2_price_out_of_band():
    snap = _snap(
        symbol="XYZ", last_price=15.0,  # above $10
        float_shares=10_000_000, rvol=6.0,
    )
    assert match_strategy(snap) != LOW_FLOAT_L2


@pytest.mark.unit
def test_vwap_reclaim_match():
    snap = _snap(vwap_reclaim=True)
    assert match_strategy(snap) == VWAP_RECLAIM


@pytest.mark.unit
def test_orb_match_first_30_min():
    snap = _snap(
        last_price=105.0,
        opening_range_high=104.0,
        minutes_since_open=15,
    )
    assert match_strategy(snap) == ORB


@pytest.mark.unit
def test_orb_expires_after_30_min():
    snap = _snap(
        last_price=105.0,
        opening_range_high=104.0,
        minutes_since_open=45,
    )
    assert match_strategy(snap) != ORB


@pytest.mark.unit
def test_sma10_macd_match():
    snap = _snap(above_sma10=True, macd_signal_cross=True)
    assert match_strategy(snap) == SMA10_MACD


@pytest.mark.unit
def test_precedence_ath_beats_sma10():
    """ATH_BREAKOUT should match before SMA10_MACD when both conditions hold."""
    snap = _snap(
        symbol="NVDA", last_price=999.0, rvol=3.0,
        above_sma10=True, macd_signal_cross=True,
        levels=KeyLevels(ath=1000, vwap=995),
    )
    assert match_strategy(snap) == ATH_BREAKOUT


@pytest.mark.unit
def test_get_strategy_name_known():
    assert get_strategy_name(ATH_BREAKOUT) == "ATH Breakout"


@pytest.mark.unit
def test_get_strategy_name_unknown_falls_back_to_id():
    assert get_strategy_name("UNKNOWN") == "UNKNOWN"
