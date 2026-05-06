"""Unit tests for long-term playbook LLM."""

from __future__ import annotations

import pytest

from tradingagents.scanner.longterm_models import (
    LONGTERM_STRATEGY_ID,
    LongTermPlaybook,
    LongTermScanResult,
    LongTermSnapshot,
)
from tradingagents.scanner.longterm_playbook_llm import (
    _fallback_playbook,
    _format_user_prompt,
    _LongTermPlaybookSchema,
    generate_longterm_playbook,
)


def _scan_result(symbol="NVDA") -> LongTermScanResult:
    snap = LongTermSnapshot(
        symbol=symbol, last_price=500.0, market_cap_b=1200.0,
        sector="Technology", industry="Semiconductors",
        roe_ttm=30.0, net_margin_ttm=40.0, revenue_growth_3y=25.0,
        pe_forward=35.0, debt_to_equity=0.4, dividend_yield_ttm=0.02,
        sma_50=480.0, sma_200=420.0, above_sma_200=True,
        golden_cross=True, wk52_high=520.0, wk52_low=380.0,
        one_year_return_pct=30.0,
    )
    return LongTermScanResult(snapshot=snap, score=0.85)


# ── Schema validation ──────────────────────────────────────────────────

def test_schema_rejects_negative_entry_zone() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(
            thesis="x" * 50, key_drivers=["a", "b"], key_risks=["a", "b"],
            entry_zone_low=-1.0, entry_zone_high=10.0, dca_weeks=4,
            hold_horizon_years=3, target_price_3y=20.0, conviction="medium",
            conviction_reason="x",
        )


def test_schema_rejects_excessive_dca_weeks() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(
            thesis="x", key_drivers=["a", "b"], key_risks=["a", "b"],
            entry_zone_low=1.0, entry_zone_high=10.0, dca_weeks=99,
            hold_horizon_years=3, target_price_3y=20.0, conviction="medium",
            conviction_reason="x",
        )


def test_schema_swaps_inverted_entry_zone() -> None:
    """LLM hallucination with low > high should be auto-swapped, not rejected."""
    schema = _LongTermPlaybookSchema(
        thesis="x", key_drivers=["a", "b"], key_risks=["a", "b"],
        entry_zone_low=510.0, entry_zone_high=460.0,  # inverted
        dca_weeks=8, hold_horizon_years=5,
        target_price_3y=750.0, conviction="medium", conviction_reason="x",
        entry_price=510.0, stop_loss=400.0,
        profit_target_1=600.0, profit_target_2=750.0,
        position_size_pct=0.08, order_type="Buy Limit",
    )
    assert schema.entry_zone_low == 460.0
    assert schema.entry_zone_high == 510.0


def test_schema_rejects_invalid_conviction() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(
            thesis="x", key_drivers=["a", "b"], key_risks=["a", "b"],
            entry_zone_low=460.0, entry_zone_high=510.0,
            dca_weeks=8, hold_horizon_years=5,
            target_price_3y=750.0, conviction="extremely-high",
            conviction_reason="x",
        )


def test_schema_accepts_valid_payload() -> None:
    schema = _LongTermPlaybookSchema(
        thesis="NVDA dominates AI accelerators with 30% ROE and 40% margins.",
        key_drivers=["Hyperscaler capex", "CUDA moat", "Margin expansion"],
        key_risks=["Cyclical demand", "Competition from AMD"],
        entry_zone_low=460.0, entry_zone_high=510.0,
        dca_weeks=8, hold_horizon_years=5,
        target_price_3y=750.0, conviction="high",
        conviction_reason="ROE 30%, margin 40%, growth 25% all top-decile.",
        entry_price=510.0, stop_loss=400.0,
        profit_target_1=600.0, profit_target_2=750.0,
        position_size_pct=0.08, order_type="Buy Limit",
    )
    assert schema.dca_weeks == 8
    assert schema.entry_price == 510.0


# ── Bracket cross-field validation ─────────────────────────────────────

def _bracket_kwargs(**overrides):
    """Helper: a valid bracket payload with overridable fields."""
    base = dict(
        thesis="x", key_drivers=["a", "b"], key_risks=["a", "b"],
        entry_zone_low=460.0, entry_zone_high=510.0,
        dca_weeks=8, hold_horizon_years=5,
        target_price_3y=750.0, conviction="high",
        conviction_reason="x",
        entry_price=510.0, stop_loss=400.0,
        profit_target_1=600.0, profit_target_2=750.0,
        position_size_pct=0.08, order_type="Buy Limit",
    )
    base.update(overrides)
    return base


def test_schema_rejects_stop_above_entry() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(**_bracket_kwargs(stop_loss=520.0))


def test_schema_rejects_pt1_below_entry() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(**_bracket_kwargs(profit_target_1=500.0))


def test_schema_rejects_pt2_below_pt1() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(**_bracket_kwargs(profit_target_2=550.0))


def test_schema_rejects_oversized_position() -> None:
    """position_size_pct capped at 0.10 — long-term plays shouldn't lever up."""
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(**_bracket_kwargs(position_size_pct=0.20))


def test_schema_rejects_invalid_order_type() -> None:
    with pytest.raises(Exception):
        _LongTermPlaybookSchema(**_bracket_kwargs(order_type="Sell Stop"))


# ── Fallback path ──────────────────────────────────────────────────────

def test_fallback_returns_deterministic_playbook() -> None:
    pb = _fallback_playbook(_scan_result())
    assert isinstance(pb, LongTermPlaybook)
    assert pb.symbol == "NVDA"
    assert pb.conviction == "low"
    assert pb.entry_zone_low < pb.entry_zone_high
    assert pb.target_price_3y > pb.entry_zone_high
    assert len(pb.key_drivers) >= 2
    assert len(pb.key_risks) >= 2
    # Bracket fields must be populated by the fallback so the UI's Execute
    # button isn't gated to "regenerate" on the fallback path.
    assert pb.entry_price > 0
    assert pb.stop_loss > 0 and pb.stop_loss < pb.entry_price
    assert pb.profit_target_1 > pb.entry_price
    assert pb.profit_target_2 >= pb.profit_target_1
    assert 0 < pb.position_size_pct <= 0.10
    assert pb.order_type in {"Buy Limit", "Buy Stop"}


def test_generate_falls_back_on_llm_exception() -> None:
    class _BoomLLM:
        def with_structured_output(self, _schema):
            return self
        def invoke(self, _messages):
            raise RuntimeError("simulated network failure")

    pb = generate_longterm_playbook(_scan_result(), llm=_BoomLLM())
    assert pb.conviction == "low"
    assert "fallback" in pb.thesis.lower()


def test_generate_uses_llm_when_provided() -> None:
    class _StubLLM:
        def with_structured_output(self, _schema):
            return self
        def invoke(self, _messages):
            return _LongTermPlaybookSchema(
                thesis="NVDA AI moat compounds at 25% CAGR.",
                key_drivers=["Capex", "Software", "Margins"],
                key_risks=["Cyclicality", "Competition"],
                entry_zone_low=460.0, entry_zone_high=510.0,
                dca_weeks=8, hold_horizon_years=5,
                target_price_3y=750.0, conviction="HIGH",
                conviction_reason="Top-decile ROE/margin/growth.",
                entry_price=510.0, stop_loss=400.0,
                profit_target_1=600.0, profit_target_2=750.0,
                position_size_pct=0.08, order_type="Buy Limit",
            )

    pb = generate_longterm_playbook(_scan_result(), llm=_StubLLM())
    assert pb.symbol == "NVDA"
    assert pb.conviction == "high"  # normalized lowercase
    assert pb.dca_weeks == 8
    assert pb.target_price_3y == 750.0
    assert pb.entry_price == 510.0
    assert pb.stop_loss == 400.0
    assert pb.position_size_pct == 0.08
    assert pb.order_type == "Buy Limit"


# ── Prompt formatting ──────────────────────────────────────────────────

def test_user_prompt_contains_key_fields() -> None:
    snap = _scan_result().snapshot
    prompt = _format_user_prompt(snap)
    assert "NVDA" in prompt
    assert "Technology" in prompt
    assert "1,200.00B" in prompt or "$1,200.00B" in prompt
    assert "ROE" in prompt
    assert "200-SMA" in prompt
    assert "Golden cross" in prompt


def test_user_prompt_handles_missing_fields() -> None:
    snap = LongTermSnapshot(symbol="X", last_price=10.0)
    prompt = _format_user_prompt(snap)
    assert "n/a" in prompt
    # Should not crash on None values.
    assert "X" in prompt


# ── Strategy id constant ───────────────────────────────────────────────

def test_strategy_id_constant() -> None:
    assert LONGTERM_STRATEGY_ID == "LONGTERM_HOLD"
