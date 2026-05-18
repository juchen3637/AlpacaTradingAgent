"""Tests for the per-ticker re-analysis gate.

Skips re-analyzing a ticker when nothing material has changed since the last
run — saves API cost on the dominant case (holding through a quiet hour).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from webui.utils.reanalysis_gate import should_reanalyze


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeState:
    """Minimal stand-in for app_state with the two new fields."""

    def __init__(self):
        self.last_analysis_at: dict[str, datetime] = {}
        self.last_analysis_price: dict[str, float] = {}


DEFAULT_CFG = {
    "per_ticker_cooldown_hours": 4,
    "min_price_move_pct_for_reanalysis": 0.0,
    "require_fresh_news_for_reanalysis": False,
}


def test_first_analysis_always_runs():
    """No prior record → never skip."""
    state = _FakeState()
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=500.0) is True


def test_within_cooldown_blocks():
    """Inside cooldown window with no price-move escape → skip."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=500.5) is False


def test_after_cooldown_runs():
    """Past cooldown window → always run."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=5)
    state.last_analysis_price["NVDA"] = 500.0
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=500.5) is True


def test_price_move_escape_within_cooldown():
    """Inside cooldown but price moved past threshold → run anyway."""
    cfg = {**DEFAULT_CFG, "min_price_move_pct_for_reanalysis": 1.0}
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    # 2% move > 1% threshold
    assert should_reanalyze("NVDA", cfg, state, current_price=510.0) is True


def test_price_move_below_threshold_still_blocks():
    """Inside cooldown, price moved less than threshold → still skip."""
    cfg = {**DEFAULT_CFG, "min_price_move_pct_for_reanalysis": 2.0}
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    # 0.5% move < 2% threshold
    assert should_reanalyze("NVDA", cfg, state, current_price=502.5) is False


def test_zero_threshold_means_no_price_escape():
    """Default threshold 0 → no price-move escape, cooldown alone gates."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    # Even a 50% move wouldn't unlock when threshold is 0 (interpreted as "off")
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=750.0) is False


def test_zero_cooldown_disables_gate():
    """Cooldown of 0 hours → never blocks."""
    cfg = {**DEFAULT_CFG, "per_ticker_cooldown_hours": 0}
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(seconds=5)
    state.last_analysis_price["NVDA"] = 500.0
    assert should_reanalyze("NVDA", cfg, state, current_price=500.5) is True


def test_unknown_current_price_runs_safely():
    """If current_price unavailable, default to running (safe-fail)."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    cfg = {**DEFAULT_CFG, "min_price_move_pct_for_reanalysis": 1.0}
    assert should_reanalyze("NVDA", cfg, state, current_price=None) is True


def test_per_symbol_isolation():
    """Cooldown for one symbol doesn't affect another."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = _now() - timedelta(hours=1)
    state.last_analysis_price["NVDA"] = 500.0
    # MSFT has no record → must run
    assert should_reanalyze("MSFT", DEFAULT_CFG, state, current_price=400.0) is True
    # NVDA is gated
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=500.5) is False


def test_naive_datetime_is_treated_as_utc():
    """Robustness: naive datetime in state is interpreted as UTC."""
    state = _FakeState()
    state.last_analysis_at["NVDA"] = (_now() - timedelta(hours=5)).replace(tzinfo=None)
    state.last_analysis_price["NVDA"] = 500.0
    assert should_reanalyze("NVDA", DEFAULT_CFG, state, current_price=500.5) is True
