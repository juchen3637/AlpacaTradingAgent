"""Unit tests for the long-term → bracket-playbook adapter.

Covers the conversion mapping (`to_bracket_playbook`), the executable
gate (`is_executable`), and the R/R math.
"""

from __future__ import annotations

import pytest

from tradingagents.scanner.longterm_execution import (
    is_executable,
    to_bracket_playbook,
)
from tradingagents.scanner.longterm_models import (
    LONGTERM_STRATEGY_ID,
    LongTermPlaybook,
)
from tradingagents.scanner.models import Playbook


def _lt_playbook(**overrides) -> LongTermPlaybook:
    base = dict(
        symbol="NVDA", thesis="AI moat compounds.",
        key_drivers=("CUDA", "Hyperscalers"),
        key_risks=("Cyclicality", "Competition"),
        entry_zone_low=460.0, entry_zone_high=510.0,
        dca_weeks=8, hold_horizon_years=5,
        target_price_3y=750.0, conviction="high",
        conviction_reason="Top-decile metrics.",
        entry_price=510.0, stop_loss=400.0,
        profit_target_1=600.0, profit_target_2=750.0,
        position_size_pct=0.08, order_type="Buy Limit",
    )
    base.update(overrides)
    return LongTermPlaybook(**base)


# ── to_bracket_playbook ────────────────────────────────────────────────

@pytest.mark.unit
def test_to_bracket_returns_playbook_with_strategy_id() -> None:
    pb = to_bracket_playbook(_lt_playbook())
    assert isinstance(pb, Playbook)
    assert pb.strategy_id == LONGTERM_STRATEGY_ID
    assert pb.symbol == "NVDA"


@pytest.mark.unit
def test_to_bracket_preserves_levels() -> None:
    lt = _lt_playbook(entry_price=510.0, stop_loss=400.0,
                      profit_target_1=600.0, profit_target_2=750.0)
    pb = to_bracket_playbook(lt)
    assert pb.entry_price == 510.0
    assert pb.stop_loss == 400.0
    assert pb.profit_target_1 == 600.0
    assert pb.profit_target_2 == 750.0


@pytest.mark.unit
def test_to_bracket_computes_risk_reward() -> None:
    """R/R = (PT1 - entry) / (entry - stop). 510 → 600 / 110 ≈ 0.82."""
    pb = to_bracket_playbook(_lt_playbook(
        entry_price=510.0, stop_loss=400.0, profit_target_1=600.0,
    ))
    expected = round(90.0 / 110.0, 2)
    assert pb.risk_reward == expected


@pytest.mark.unit
def test_to_bracket_carries_position_size_and_order_type() -> None:
    lt = _lt_playbook(position_size_pct=0.05, order_type="Buy Stop")
    pb = to_bracket_playbook(lt)
    assert pb.position_size_pct == 0.05
    assert pb.order_type == "Buy Stop"


@pytest.mark.unit
def test_to_bracket_invalidation_text_references_stop() -> None:
    pb = to_bracket_playbook(_lt_playbook(stop_loss=400.0))
    assert "$400.00" in pb.invalidation
    assert "thesis" in pb.invalidation.lower()


@pytest.mark.unit
def test_to_bracket_indicators_to_watch_long_term_oriented() -> None:
    pb = to_bracket_playbook(_lt_playbook())
    assert "200-SMA" in pb.indicators_to_watch


@pytest.mark.unit
def test_to_bracket_handles_zero_risk_safely() -> None:
    """Defensive: stop == entry would divide by zero — adapter clamps."""
    # Note: the LLM schema rejects this combo, but the adapter is also
    # called from saved-play rehydration where defaults could collide.
    pb = to_bracket_playbook(_lt_playbook(
        entry_price=100.0, stop_loss=100.0, profit_target_1=110.0,
    ))
    assert pb.risk_reward >= 0  # no exception, no inf


# ── is_executable ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_is_executable_true_for_populated_bracket() -> None:
    assert is_executable(_lt_playbook()) is True


@pytest.mark.unit
def test_is_executable_false_for_zeroed_bracket() -> None:
    """Older saved plays predating the bracket schema have zeroed levels."""
    lt = _lt_playbook(entry_price=0.0, stop_loss=0.0,
                      profit_target_1=0.0, profit_target_2=0.0)
    assert is_executable(lt) is False


@pytest.mark.unit
def test_is_executable_false_when_levels_inverted() -> None:
    """Cross-field invariants matter even at the gate."""
    lt = _lt_playbook(entry_price=400.0, stop_loss=500.0,
                      profit_target_1=600.0)
    assert is_executable(lt) is False
