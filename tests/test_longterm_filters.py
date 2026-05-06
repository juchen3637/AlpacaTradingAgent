"""Unit tests for long-term filter predicates."""

from __future__ import annotations

from tradingagents.scanner.longterm_filters import (
    apply_longterm_filters,
    passes_catalyst_only,
    passes_max_pe,
    passes_min_market_cap,
    passes_profitability,
    passes_sector_exclusion,
)
from tradingagents.scanner.longterm_models import LongTermFilters, LongTermSnapshot


def _snap(**overrides) -> LongTermSnapshot:
    base = dict(symbol="NVDA", last_price=500.0, market_cap_b=1000.0,
                sector="Technology", net_margin_ttm=20.0, pe_forward=30.0)
    base.update(overrides)
    return LongTermSnapshot(**base)


# ── min_market_cap ──────────────────────────────────────────────────────

def test_min_market_cap_passes_when_above_threshold() -> None:
    assert passes_min_market_cap(_snap(market_cap_b=1000.0),
                                 LongTermFilters(min_market_cap_b=100.0)) is True


def test_min_market_cap_fails_when_below_threshold() -> None:
    assert passes_min_market_cap(_snap(market_cap_b=50.0),
                                 LongTermFilters(min_market_cap_b=100.0)) is False


def test_min_market_cap_zero_threshold_disables_filter() -> None:
    assert passes_min_market_cap(_snap(market_cap_b=None),
                                 LongTermFilters(min_market_cap_b=0.0)) is True


def test_min_market_cap_missing_data_fails() -> None:
    assert passes_min_market_cap(_snap(market_cap_b=None),
                                 LongTermFilters(min_market_cap_b=100.0)) is False


# ── profitability ───────────────────────────────────────────────────────

def test_profitability_passes_when_positive() -> None:
    assert passes_profitability(_snap(net_margin_ttm=15.0),
                                LongTermFilters(must_be_profitable=True)) is True


def test_profitability_fails_when_negative() -> None:
    assert passes_profitability(_snap(net_margin_ttm=-5.0),
                                LongTermFilters(must_be_profitable=True)) is False


def test_profitability_missing_data_fails_closed_when_required() -> None:
    assert passes_profitability(_snap(net_margin_ttm=None),
                                LongTermFilters(must_be_profitable=True)) is False


def test_profitability_disabled_passes_anything() -> None:
    assert passes_profitability(_snap(net_margin_ttm=-50.0),
                                LongTermFilters(must_be_profitable=False)) is True


# ── max_pe ──────────────────────────────────────────────────────────────

def test_max_pe_passes_when_below_cap() -> None:
    assert passes_max_pe(_snap(pe_forward=25.0),
                        LongTermFilters(max_pe=40.0)) is True


def test_max_pe_fails_when_above_cap() -> None:
    assert passes_max_pe(_snap(pe_forward=60.0),
                        LongTermFilters(max_pe=40.0)) is False


def test_max_pe_no_cap_passes_anything() -> None:
    assert passes_max_pe(_snap(pe_forward=200.0),
                        LongTermFilters(max_pe=None)) is True


def test_max_pe_negative_or_zero_falls_through() -> None:
    # Companies with no/negative earnings shouldn't be auto-rejected here —
    # other filters (profitability) handle that case.
    assert passes_max_pe(_snap(pe_forward=-5.0),
                        LongTermFilters(max_pe=40.0)) is True
    assert passes_max_pe(_snap(pe_forward=None),
                        LongTermFilters(max_pe=40.0)) is True


# ── sector exclusion ────────────────────────────────────────────────────

def test_sector_exclusion_filters_named_sector() -> None:
    assert passes_sector_exclusion(
        _snap(sector="Energy"),
        LongTermFilters(excluded_sectors=("Energy",)),
    ) is False


def test_sector_exclusion_substring_match_consumer() -> None:
    """Token 'Consumer' should match both Consumer Discretionary and Consumer Staples."""
    for sector in ("Consumer Discretionary", "Consumer Staples"):
        assert passes_sector_exclusion(
            _snap(sector=sector),
            LongTermFilters(excluded_sectors=("Consumer",)),
        ) is False


def test_sector_exclusion_case_insensitive() -> None:
    assert passes_sector_exclusion(
        _snap(sector="ENERGY"),
        LongTermFilters(excluded_sectors=("energy",)),
    ) is False


def test_sector_exclusion_passes_other_sectors() -> None:
    assert passes_sector_exclusion(
        _snap(sector="Technology"),
        LongTermFilters(excluded_sectors=("Energy",)),
    ) is True


def test_sector_exclusion_unknown_sector_passes() -> None:
    assert passes_sector_exclusion(
        _snap(sector=None),
        LongTermFilters(excluded_sectors=("Energy",)),
    ) is True


def test_sector_exclusion_empty_list_passes_all() -> None:
    assert passes_sector_exclusion(
        _snap(sector="Energy"),
        LongTermFilters(excluded_sectors=()),
    ) is True


# ── apply_longterm_filters (composite) ──────────────────────────────────

def test_apply_filters_short_circuits_correctly() -> None:
    snap = _snap(market_cap_b=50.0)  # fails first filter
    assert apply_longterm_filters(snap, LongTermFilters(min_market_cap_b=100.0)) is False


def test_apply_filters_passes_when_all_pass() -> None:
    assert apply_longterm_filters(
        _snap(),
        LongTermFilters(min_market_cap_b=100.0, must_be_profitable=True, max_pe=40.0),
    ) is True


def test_apply_filters_excluded_sector_blocks() -> None:
    snap = _snap(sector="Energy")
    assert apply_longterm_filters(
        snap,
        LongTermFilters(excluded_sectors=("Energy",)),
    ) is False


# ── catalyst_only ──────────────────────────────────────────────────────


def test_catalyst_only_off_passes_regardless() -> None:
    """Default — catalyst_only off — never blocks anything."""
    snap = _snap(has_catalyst=False)
    assert passes_catalyst_only(snap, LongTermFilters(catalyst_only=False)) is True


def test_catalyst_only_on_blocks_when_no_catalyst() -> None:
    snap = _snap(has_catalyst=False)
    assert passes_catalyst_only(snap, LongTermFilters(catalyst_only=True)) is False


def test_catalyst_only_on_passes_when_catalyst_present() -> None:
    snap = _snap(has_catalyst=True)
    assert passes_catalyst_only(snap, LongTermFilters(catalyst_only=True)) is True


def test_apply_filters_includes_catalyst_check() -> None:
    """Composition: a snapshot that passes everything else should still be
    rejected when catalyst_only is on and has_catalyst is False."""
    snap = _snap(market_cap_b=1000.0, net_margin_ttm=20.0, pe_forward=30.0,
                 has_catalyst=False)
    assert apply_longterm_filters(
        snap, LongTermFilters(catalyst_only=True, min_market_cap_b=100.0),
    ) is False
