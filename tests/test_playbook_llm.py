"""Unit tests for the AI playbook layer.

We never call a real LLM — the ChatOpenAI instance is injected via the `llm`
kwarg so we can mock `with_structured_output(...).invoke(...)`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.scanner.models import (
    KeyLevels,
    ScanResult,
    TickerSnapshot,
)
from tradingagents.scanner.playbook_llm import (
    _PlaybookSchema,
    _fallback_playbook,
    generate_playbook,
)


def _snap(**overrides) -> TickerSnapshot:
    base = dict(
        symbol="NVDA",
        is_crypto=False,
        last_price=1000.0,
        change_pct=3.0,
        rvol=3.5,
        float_shares=24_000_000_000,
        today_volume=50_000_000,
        prior_30d_max_volume=40_000_000,
        above_sma10=True,
        macd_signal_cross=False,
        vwap_reclaim=False,
        levels=KeyLevels(pdh=995, pdl=980, vwap=990, ath=1010),
    )
    base.update(overrides)
    return TickerSnapshot(**base)


def _result() -> ScanResult:
    return ScanResult(
        snapshot=_snap(),
        strategy_id="ATH_BREAKOUT",
        strategy_name="ATH Breakout",
        score=0.8,
    )


def _build_mock_llm(payload: _PlaybookSchema):
    """Mock ChatOpenAI: with_structured_output(schema).invoke(msgs) returns payload."""
    structured = MagicMock()
    structured.invoke.return_value = payload
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ─── happy path ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_generate_playbook_happy_path():
    payload = _PlaybookSchema(
        thesis="Near ATH with volume.",
        entry_trigger="Break $1005 with vol",
        stop_loss=995.0,
        profit_target_1=1015.0,
        profit_target_2=1025.0,
        risk_reward=2.0,
        position_size_pct=0.08,
        indicators_to_watch=["VWAP", "MACD"],
        invalidation="Close below VWAP.",
        confidence="high",
    )
    llm = _build_mock_llm(payload)
    pb = generate_playbook(_result(), llm=llm)
    assert pb.symbol == "NVDA"
    assert pb.strategy_id == "ATH_BREAKOUT"
    assert pb.stop_loss == 995.0
    assert pb.profit_target_1 == 1015.0
    assert pb.confidence == "high"
    assert pb.indicators_to_watch == ("VWAP", "MACD")


@pytest.mark.unit
def test_generate_playbook_normalizes_confidence_case():
    payload = _PlaybookSchema(
        thesis="t", entry_trigger="e", stop_loss=1, profit_target_1=2,
        profit_target_2=3, risk_reward=1, position_size_pct=0.1,
        indicators_to_watch=[], invalidation="inv", confidence="HIGH",
    )
    pb = generate_playbook(_result(), llm=_build_mock_llm(payload))
    assert pb.confidence == "high"


# ─── failure → fallback ─────────────────────────────────────────────────

@pytest.mark.unit
def test_generate_playbook_llm_none_returns_fallback():
    llm = _build_mock_llm(None)  # invoke returns None
    pb = generate_playbook(_result(), llm=llm)
    assert pb.confidence == "low"
    assert pb.symbol == "NVDA"
    assert pb.strategy_id == "ATH_BREAKOUT"


@pytest.mark.unit
def test_generate_playbook_llm_exception_returns_fallback():
    llm = MagicMock()
    llm.with_structured_output.side_effect = RuntimeError("boom")
    pb = generate_playbook(_result(), llm=llm)
    assert pb.symbol == "NVDA"
    # Fallback always uses low confidence + 1% stop / 2% & 4% targets
    snap = _result().snapshot
    assert pb.stop_loss == round(snap.last_price * 0.99, 2)
    assert pb.profit_target_1 == round(snap.last_price * 1.02, 2)
    assert pb.confidence == "low"


@pytest.mark.unit
def test_fallback_playbook_risk_reward_positive():
    pb = _fallback_playbook(_result())
    assert pb.risk_reward > 0
    assert pb.position_size_pct == 0.05


# ─── provider/model overrides ───────────────────────────────────────────

def _ok_payload() -> _PlaybookSchema:
    return _PlaybookSchema(
        thesis="t", entry_trigger="e", stop_loss=1.0, profit_target_1=2.0,
        profit_target_2=3.0, risk_reward=2.0, position_size_pct=0.05,
        indicators_to_watch=[], invalidation="inv", confidence="medium",
    )


@pytest.mark.unit
def test_generate_playbook_forwards_provider_and_model_to_get_llm():
    llm = _build_mock_llm(_ok_payload())
    with patch(
        "tradingagents.scanner.playbook_llm._get_llm", return_value=llm
    ) as mock_get_llm:
        generate_playbook(_result(), provider="openai", model="gpt-5")
    mock_get_llm.assert_called_once_with(provider="openai", model="gpt-5")


@pytest.mark.unit
def test_generate_playbook_routes_to_anthropic_when_provider_specified():
    llm = _build_mock_llm(_ok_payload())
    with patch(
        "tradingagents.scanner.playbook_llm._get_llm", return_value=llm
    ) as mock_get_llm:
        generate_playbook(_result(), provider="anthropic", model="claude-sonnet-4-6")
    mock_get_llm.assert_called_once_with(
        provider="anthropic", model="claude-sonnet-4-6"
    )


@pytest.mark.unit
def test_generate_playbook_falls_back_to_config_when_no_override():
    llm = _build_mock_llm(_ok_payload())
    with patch(
        "tradingagents.scanner.playbook_llm._get_llm", return_value=llm
    ) as mock_get_llm:
        generate_playbook(_result())
    mock_get_llm.assert_called_once_with(provider=None, model=None)
