"""Unit tests for long-term scoring."""

from __future__ import annotations

import math

import pytest

from tradingagents.scanner.longterm_models import LongTermSnapshot
from tradingagents.scanner.longterm_scoring import (
    WEIGHTS,
    normalize_debt_equity,
    normalize_div_yield,
    normalize_lt_trend,
    normalize_net_margin,
    normalize_pe_inverted,
    normalize_rev_growth,
    normalize_roe,
    score_longterm,
)


def _snap(**overrides) -> LongTermSnapshot:
    base = dict(symbol="X", last_price=100.0)
    base.update(overrides)
    return LongTermSnapshot(**base)


# ── Invariant: weights sum to 1.0 ──────────────────────────────────────

def test_weights_sum_to_one() -> None:
    assert math.isclose(sum(WEIGHTS.values()), 1.0, abs_tol=1e-9)


# ── Per-metric normalizers ─────────────────────────────────────────────

def test_normalize_roe() -> None:
    assert normalize_roe(0.0) == 0.0
    assert normalize_roe(25.0) == 1.0
    assert normalize_roe(50.0) == 1.0  # winsorized
    assert normalize_roe(-5.0) == 0.0
    assert normalize_roe(None) is None
    assert math.isclose(normalize_roe(12.5), 0.5)


def test_normalize_net_margin() -> None:
    assert normalize_net_margin(0.0) == 0.0
    assert normalize_net_margin(30.0) == 1.0
    assert normalize_net_margin(60.0) == 1.0
    assert normalize_net_margin(-10.0) == 0.0
    assert normalize_net_margin(None) is None


def test_normalize_rev_growth() -> None:
    assert normalize_rev_growth(0.0) == 0.0
    assert normalize_rev_growth(20.0) == 1.0
    assert normalize_rev_growth(-5.0) == 0.0
    assert normalize_rev_growth(40.0) == 1.0
    assert normalize_rev_growth(None) is None


def test_normalize_pe_inverted() -> None:
    assert normalize_pe_inverted(10.0) == 1.0
    assert normalize_pe_inverted(50.0) == 0.0
    assert normalize_pe_inverted(30.0) == 0.5
    assert normalize_pe_inverted(60.0) == 0.0  # winsorized
    assert normalize_pe_inverted(5.0) == 1.0   # below floor — best score
    assert normalize_pe_inverted(0.0) == 0.0   # zero → unprofitable
    assert normalize_pe_inverted(-10.0) == 0.0
    assert normalize_pe_inverted(None) is None


def test_normalize_lt_trend() -> None:
    assert normalize_lt_trend(_snap(sma_200=100.0, above_sma_200=True,
                                     golden_cross=True)) == 1.0
    assert normalize_lt_trend(_snap(sma_200=100.0, above_sma_200=True,
                                     golden_cross=False)) == 0.5
    assert normalize_lt_trend(_snap(sma_200=100.0, above_sma_200=False,
                                     golden_cross=False)) == 0.0
    assert normalize_lt_trend(_snap()) is None  # no trend data


def test_normalize_debt_equity() -> None:
    assert normalize_debt_equity(0.0) == 1.0
    assert normalize_debt_equity(2.0) == 0.0
    assert normalize_debt_equity(1.0) == 0.5
    assert normalize_debt_equity(3.0) == 0.0  # winsorized
    assert normalize_debt_equity(-1.0) == 0.0  # negative equity
    assert normalize_debt_equity(None) is None


def test_normalize_div_yield() -> None:
    assert normalize_div_yield(0.0) == 0.0
    assert normalize_div_yield(4.0) == 1.0
    assert normalize_div_yield(8.0) == 1.0  # winsorized
    assert normalize_div_yield(None) is None


# ── Composite score_longterm ────────────────────────────────────────────

def test_score_perfect_inputs_returns_one() -> None:
    snap = _snap(
        roe_ttm=30.0, net_margin_ttm=40.0, revenue_growth_3y=25.0,
        pe_forward=10.0, sma_200=100.0, above_sma_200=True,
        golden_cross=True, debt_to_equity=0.0, dividend_yield_ttm=4.0,
    )
    assert score_longterm(snap) == pytest.approx(1.0, abs=1e-6)


def test_score_worst_inputs_returns_zero() -> None:
    snap = _snap(
        roe_ttm=-10.0, net_margin_ttm=-10.0, revenue_growth_3y=-10.0,
        pe_forward=100.0, sma_200=100.0, above_sma_200=False,
        golden_cross=False, debt_to_equity=5.0, dividend_yield_ttm=0.0,
    )
    assert score_longterm(snap) == pytest.approx(0.0, abs=1e-6)


def test_score_missing_metrics_neutral() -> None:
    """All None → score is sum(weights × 0.5) = 0.5."""
    snap = _snap()
    assert score_longterm(snap) == pytest.approx(0.5, abs=1e-6)


def test_score_partial_missing_does_not_crash() -> None:
    """Single missing field flows through neutral weighting."""
    snap = _snap(
        roe_ttm=20.0, net_margin_ttm=None, revenue_growth_3y=15.0,
        pe_forward=20.0,
    )
    s = score_longterm(snap)
    assert 0.0 <= s <= 1.0


def test_score_monotonicity_roe() -> None:
    """Improving any single input should never decrease composite."""
    base = _snap(roe_ttm=10.0)
    better = _snap(roe_ttm=20.0)
    assert score_longterm(better) >= score_longterm(base)


def test_score_monotonicity_pe() -> None:
    """Lower P/E (better) should score higher."""
    high_pe = _snap(pe_forward=40.0)
    low_pe = _snap(pe_forward=15.0)
    assert score_longterm(low_pe) >= score_longterm(high_pe)


def test_score_clamped_to_unit() -> None:
    """Even with extreme values, score stays in [0, 1]."""
    snap = _snap(
        roe_ttm=1e9, net_margin_ttm=1e9, revenue_growth_3y=1e9,
        pe_forward=1.0, debt_to_equity=-1e9, dividend_yield_ttm=1e9,
        sma_200=100.0, above_sma_200=True, golden_cross=True,
    )
    s = score_longterm(snap)
    assert 0.0 <= s <= 1.0
