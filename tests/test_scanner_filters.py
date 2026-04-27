"""Unit tests for scanner filter predicates."""

from __future__ import annotations

import pytest

from tradingagents.scanner.filters import (
    apply_filters,
    passes_catalyst,
    passes_float,
    passes_premarket_volume,
    passes_price_band,
    passes_rvol,
)
from tradingagents.scanner.models import KeyLevels, ScanFilters, TickerSnapshot


def _snap(**overrides) -> TickerSnapshot:
    base = dict(
        symbol="AAPL",
        is_crypto=False,
        last_price=150.0,
        change_pct=2.0,
        premarket_volume=500_000,
        rvol=3.0,
        float_shares=10_000_000_000,  # 10B = AAPL-ish
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


# ─── price band ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_price_band_inside_passes():
    assert passes_price_band(_snap(last_price=50.0), ScanFilters(price_min=10, price_max=100))


@pytest.mark.unit
def test_price_band_below_min_fails():
    assert not passes_price_band(_snap(last_price=5.0), ScanFilters(price_min=10, price_max=100))


@pytest.mark.unit
def test_price_band_above_max_fails():
    assert not passes_price_band(_snap(last_price=200.0), ScanFilters(price_min=10, price_max=100))


# ─── rvol ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_rvol_none_fails():
    assert not passes_rvol(_snap(rvol=None), ScanFilters(min_rvol=2.0))


@pytest.mark.unit
def test_rvol_below_min_fails():
    assert not passes_rvol(_snap(rvol=1.5), ScanFilters(min_rvol=2.0))


@pytest.mark.unit
def test_rvol_at_min_passes():
    assert passes_rvol(_snap(rvol=2.0), ScanFilters(min_rvol=2.0))


# ─── premarket volume ──────────────────────────────────────────────────

@pytest.mark.unit
def test_premarket_crypto_always_passes():
    # Crypto has no premarket session.
    snap = _snap(symbol="BTC/USD", is_crypto=True, premarket_volume=None)
    assert passes_premarket_volume(snap, ScanFilters(min_premarket_volume=1_000_000))


@pytest.mark.unit
def test_premarket_stock_none_fails():
    assert not passes_premarket_volume(
        _snap(premarket_volume=None), ScanFilters(min_premarket_volume=100_000)
    )


@pytest.mark.unit
def test_premarket_stock_below_min_fails():
    assert not passes_premarket_volume(
        _snap(premarket_volume=50_000), ScanFilters(min_premarket_volume=100_000)
    )


@pytest.mark.unit
def test_premarket_threshold_zero_skips_filter_for_missing_data():
    # Threshold <= 0 means "ignore this filter" so missing premarket data passes.
    assert passes_premarket_volume(
        _snap(premarket_volume=None), ScanFilters(min_premarket_volume=0)
    )


@pytest.mark.unit
def test_premarket_default_threshold_is_zero_and_passes_none():
    # Default ScanFilters has min_premarket_volume=0 → premarket is optional.
    assert passes_premarket_volume(_snap(premarket_volume=None), ScanFilters())


# ─── float ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_float_no_filter_always_passes():
    assert passes_float(_snap(float_shares=None), ScanFilters(max_float_millions=None))


@pytest.mark.unit
def test_float_missing_with_filter_fails():
    assert not passes_float(
        _snap(float_shares=None), ScanFilters(max_float_millions=20.0)
    )


@pytest.mark.unit
def test_float_under_cap_passes():
    # 15M shares under 20M cap
    assert passes_float(
        _snap(float_shares=15_000_000), ScanFilters(max_float_millions=20.0)
    )


@pytest.mark.unit
def test_float_over_cap_fails():
    assert not passes_float(
        _snap(float_shares=25_000_000), ScanFilters(max_float_millions=20.0)
    )


# ─── catalyst ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_catalyst_not_required_passes():
    assert passes_catalyst(_snap(has_catalyst=False), ScanFilters(catalyst_only=False))


@pytest.mark.unit
def test_catalyst_required_without_fails():
    assert not passes_catalyst(_snap(has_catalyst=False), ScanFilters(catalyst_only=True))


@pytest.mark.unit
def test_catalyst_required_with_passes():
    assert passes_catalyst(_snap(has_catalyst=True), ScanFilters(catalyst_only=True))


# ─── apply_filters (short-circuit composition) ─────────────────────────

@pytest.mark.unit
def test_apply_filters_all_pass():
    snap = _snap(
        last_price=50, rvol=3.0, premarket_volume=500_000,
        float_shares=10_000_000, has_catalyst=True,
    )
    filters = ScanFilters(
        price_min=1, price_max=100, min_rvol=2.0, min_premarket_volume=100_000,
        max_float_millions=20.0, catalyst_only=True,
    )
    assert apply_filters(snap, filters)


@pytest.mark.unit
def test_apply_filters_short_circuits_on_first_failure():
    # Price fails — nothing else matters.
    snap = _snap(last_price=0.5)
    assert not apply_filters(snap, ScanFilters(price_min=1.0))
