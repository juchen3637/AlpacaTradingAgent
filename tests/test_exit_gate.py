"""Tests for the bracket-first exit gate.

The exit gate prevents the scheduled re-analysis loop from prematurely
liquidating a fresh position before its bracket TP/SL has had a chance to fire.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.utils.exit_gate import (
    ExitDecision,
    evaluate_exit_gate,
)


DEFAULT_CFG = {
    "respect_brackets_when_held": True,
    "position_age_min_hold_hours": 4,
    "exit_conviction_threshold": 0.75,
    "exit_adverse_move_pct": 2.0,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_neutral_position_is_pass_through():
    """No position held → gate is a no-op; signal flows untouched."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="NEUTRAL",
        signal="SELL",
        avg_entry=0.0,
        current_price=0.0,
        position_opened_at=None,
        conviction=0.9,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "keep"
    assert "no position" in decision.reason.lower()


def test_buy_or_hold_signals_are_pass_through():
    """Gate only engages when the new signal would close the position."""
    for signal in ("BUY", "HOLD", "LONG"):
        decision = evaluate_exit_gate(
            symbol="NVDA",
            current_position="LONG",
            signal=signal,
            avg_entry=100.0,
            current_price=100.5,
            position_opened_at=_now() - timedelta(minutes=30),
            conviction=0.4,
            thesis_break=False,
            config=DEFAULT_CFG,
        )
        assert decision.action == "keep", f"signal={signal} should not trigger gate"


def test_young_position_low_conviction_respects_bracket():
    """1h old + conviction 0.6 + price near entry → respect bracket."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(hours=1),
        conviction=0.6,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "respect_bracket"
    assert "min-hold" in decision.reason or "conviction" in decision.reason


def test_old_position_high_conviction_closes():
    """5h old (past min-hold) + conviction 0.85 → close."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(hours=5),
        conviction=0.85,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "close"


def test_old_position_low_conviction_still_respects():
    """5h old but conviction 0.5 — past min-hold but conviction insufficient."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(hours=5),
        conviction=0.5,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "respect_bracket"


def test_adverse_move_overrides_min_hold_long():
    """Long position down 3% vs entry → close even if young + low conviction."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=96.5,  # -3.5% adverse
        position_opened_at=_now() - timedelta(minutes=20),
        conviction=0.3,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "close"
    assert "adverse" in decision.reason.lower()


def test_adverse_move_overrides_min_hold_short():
    """Short position up 3% vs entry → close even if young."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="SHORT",
        signal="BUY",
        avg_entry=100.0,
        current_price=103.5,  # +3.5% against short
        position_opened_at=_now() - timedelta(minutes=20),
        conviction=0.3,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "close"


def test_thesis_break_overrides_min_hold():
    """Explicit thesis break → close regardless of age/conviction."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(minutes=10),
        conviction=0.3,
        thesis_break=True,
        config=DEFAULT_CFG,
    )
    assert decision.action == "close"
    assert "thesis" in decision.reason.lower()


def test_unknown_position_age_respects_bracket_when_held():
    """If position_opened_at is None and respect-flag on, default to respect."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=None,
        conviction=0.6,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "respect_bracket"


def test_unknown_age_with_high_conviction_closes():
    """Unknown age but conviction clears threshold → close (manual position case)."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=None,
        conviction=0.9,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "close"


def test_recent_fill_within_5min_always_respects():
    """Position opened in the last 5 minutes — likely the bracket fill itself.
    Always respect, even if conviction is high."""
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(minutes=2),
        conviction=0.95,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "respect_bracket"
    assert "recent" in decision.reason.lower()


def test_respect_flag_disabled_passes_through():
    """When respect_brackets_when_held=False, gate is bypassed."""
    cfg = {**DEFAULT_CFG, "respect_brackets_when_held": False}
    decision = evaluate_exit_gate(
        symbol="NVDA",
        current_position="LONG",
        signal="SELL",
        avg_entry=100.0,
        current_price=100.5,
        position_opened_at=_now() - timedelta(minutes=30),
        conviction=0.3,
        thesis_break=False,
        config=cfg,
    )
    assert decision.action == "keep"


def test_crypto_symbol_skips_bracket_logic():
    """Crypto bracket orders behave differently in alpaca_utils — skip the gate."""
    decision = evaluate_exit_gate(
        symbol="BTC/USD",
        current_position="LONG",
        signal="SELL",
        avg_entry=50000.0,
        current_price=50100.0,
        position_opened_at=_now() - timedelta(minutes=30),
        conviction=0.3,
        thesis_break=False,
        config=DEFAULT_CFG,
    )
    assert decision.action == "keep"
    assert "crypto" in decision.reason.lower()


def test_exit_decision_is_immutable():
    """ExitDecision is a frozen dataclass."""
    decision = ExitDecision(action="keep", reason="ok")
    with pytest.raises(Exception):
        decision.action = "close"  # type: ignore[misc]


def test_invalid_action_rejected():
    """ExitDecision constructor rejects unknown action strings."""
    with pytest.raises(ValueError):
        ExitDecision(action="explode", reason="nope")
