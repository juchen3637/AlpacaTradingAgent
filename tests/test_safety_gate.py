"""Tests for tradingagents/safety_gate.py"""

from __future__ import annotations

import pytest

from tradingagents.safety_gate import GateResult, check_order

_BASE_ACCOUNT = {
    "equity": 10_000.0,
    "last_equity": 10_000.0,
    "buying_power": 20_000.0,
    "cash": 10_000.0,
}

_BASE_CONFIG = {
    "max_daily_loss_pct": 5.0,
    "max_open_positions": 10,
    "max_position_pct_of_buying_power": 30,
    "max_risk_pct_per_trade": 3,
    "min_position_size": 100,
}


def _check(**kwargs):
    defaults = dict(
        symbol="NVDA",
        signal="BUY",
        proposed_size_dollars=1000.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=[110.0],
        account_info=_BASE_ACCOUNT,
        open_positions_count=0,
        config=_BASE_CONFIG,
    )
    defaults.update(kwargs)
    return check_order(**defaults)


# ── Neutral/sell signals always pass ─────────────────────────────────────────

@pytest.mark.parametrize("signal", ["SELL", "HOLD", "NEUTRAL"])
def test_closing_signals_always_pass(signal):
    result = _check(signal=signal)
    assert result.passed


# ── Daily loss kill switch ────────────────────────────────────────────────────

def test_daily_loss_kill_switch_blocks_when_exceeded():
    account = {**_BASE_ACCOUNT, "equity": 9_400.0, "last_equity": 10_000.0}
    result = _check(account_info=account)
    assert not result.passed
    assert "DAILY LOSS" in result.reason


def test_daily_loss_kill_switch_allows_when_under():
    account = {**_BASE_ACCOUNT, "equity": 9_600.0, "last_equity": 10_000.0}
    result = _check(account_info=account)
    assert result.passed


def test_daily_loss_disabled_when_zero():
    account = {**_BASE_ACCOUNT, "equity": 5_000.0, "last_equity": 10_000.0}
    cfg = {**_BASE_CONFIG, "max_daily_loss_pct": 0}
    result = _check(account_info=account, config=cfg)
    assert result.passed


# ── Max open positions ────────────────────────────────────────────────────────

def test_max_positions_blocks_when_at_limit():
    result = _check(open_positions_count=10)
    assert not result.passed
    assert "MAX POSITIONS" in result.reason


def test_max_positions_allows_when_under():
    result = _check(open_positions_count=9)
    assert result.passed


def test_max_positions_disabled_when_zero():
    cfg = {**_BASE_CONFIG, "max_open_positions": 0}
    result = _check(open_positions_count=9999, config=cfg)
    assert result.passed


# ── Position size clamping ────────────────────────────────────────────────────

def test_size_clamped_to_buying_power_pct():
    # 30% of $20k buying_power = $6000; proposing $8000 → should be clamped
    result = _check(proposed_size_dollars=8_000.0)
    assert result.passed
    assert result.adjusted_size is not None
    assert result.adjusted_size == pytest.approx(6_000.0)


def test_size_not_clamped_when_within_limit():
    result = _check(proposed_size_dollars=1_000.0)
    assert result.passed
    assert result.adjusted_size is None


# ── Risk per trade capping ────────────────────────────────────────────────────

def test_risk_cap_clamps_size():
    # entry=100, stop=90 → risk/share=$10 → 3% of $10k = $300 max risk → 30 shares max → $3000 size
    result = _check(
        proposed_size_dollars=8_000.0,
        entry_price=100.0,
        stop_loss=90.0,
    )
    assert result.passed
    # adjusted_size should be ≤ $3000 (risk cap) and ≤ $6000 (bp cap)
    assert result.adjusted_size is not None
    assert result.adjusted_size <= 3_000.0 + 1  # tolerance


# ── Price sanity ──────────────────────────────────────────────────────────────

def test_stop_above_entry_long_is_rejected():
    result = _check(signal="BUY", entry_price=100.0, stop_loss=105.0, take_profit=[110.0])
    assert not result.passed
    assert "PRICE INVALID" in result.reason


def test_stop_below_entry_short_is_rejected():
    result = _check(signal="SHORT", entry_price=100.0, stop_loss=95.0, take_profit=[90.0])
    assert not result.passed
    assert "PRICE INVALID" in result.reason


def test_target_below_entry_long_is_rejected():
    result = _check(signal="BUY", entry_price=100.0, stop_loss=95.0, take_profit=[90.0])
    assert not result.passed
    assert "PRICE INVALID" in result.reason


def test_stop_too_far_is_rejected():
    # 50% stop = exceeds 40% max deviation
    result = _check(signal="BUY", entry_price=100.0, stop_loss=50.0, take_profit=[120.0])
    assert not result.passed
    assert "PRICE INVALID" in result.reason


def test_valid_long_trade_passes():
    result = _check(
        signal="BUY",
        entry_price=100.0,
        stop_loss=97.0,
        take_profit=[106.0],
        proposed_size_dollars=500.0,
    )
    assert result.passed


def test_valid_short_trade_passes():
    result = _check(
        signal="SHORT",
        entry_price=100.0,
        stop_loss=103.0,
        take_profit=[94.0],
        proposed_size_dollars=500.0,
    )
    assert result.passed


# ── Min position size ─────────────────────────────────────────────────────────

def test_below_min_size_rejected():
    result = _check(proposed_size_dollars=50.0)
    assert not result.passed
    assert "BELOW MIN" in result.reason


# ── No prices → gate still checks account limits ─────────────────────────────

def test_no_prices_provided_still_checks_account():
    result = _check(entry_price=None, stop_loss=None, take_profit=None, proposed_size_dollars=1_000.0)
    assert result.passed
