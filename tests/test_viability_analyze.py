"""Tests for analyze_viability with a mocked LLM client."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents.scanner.models import Playbook
from tradingagents.scanner.viability import (
    ViabilityVerdict,
    _VerdictSchema,
    analyze_viability,
)
from webui.utils.saved_plays import SavedPlaysStore


def _mk_playbook() -> Playbook:
    return Playbook(
        symbol="NVDA",
        strategy_id="ATH_BREAKOUT",
        thesis="Breakout thesis.",
        entry_trigger="Buy stop above 920.50",
        entry_price=920.50,
        order_type="Buy Stop",
        stop_loss=905.00,
        profit_target_1=940.00,
        profit_target_2=960.00,
        risk_reward=2.6,
        position_size_pct=0.05,
        indicators_to_watch=("VWAP", "RVOL"),
        invalidation="Loss of VWAP.",
        confidence="high",
        qualification_reason="ATH 0.4%, RVOL 3.1x.",
        confidence_reason="Three signals aligned.",
    )


class _StubStructured:
    """Mimics LangChain's structured-output runnable: invoke() returns a pydantic obj."""

    def __init__(self, payload: dict):
        self._payload = payload

    def invoke(self, _messages):
        return _VerdictSchema(**self._payload)


class _StubLLM:
    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, _schema):
        return _StubStructured(self._payload)


def _good_payload() -> dict:
    return {
        "status": "still_viable",
        "confidence": "high",
        "reasoning": "Thesis intact: price above entry, RVOL holding.",
        "recommended_action": "hold",
        "key_changes": ["Up 1.6% since save", "RVOL 2.4 (down from 3.1)"],
        "news_signals": ["NVDA beat earnings"],
    }


@pytest.mark.unit
def test_analyze_viability_returns_typed_verdict():
    verdict = analyze_viability(
        playbook=_mk_playbook(),
        scan_row={"last_price": 920.55, "rvol": 3.1},
        current_snapshot={"current_price": 935.20, "change_since_save_pct": 1.59,
                          "today_change_pct": 2.4, "current_rvol": 2.4},
        news=[{"headline": "NVDA beat", "source": "Reuters"}],
        catalyst_now="Earnings beat",
        position={"qty": 100, "avg_entry_price": 920.50,
                  "unrealized_pl": 1470, "unrealized_plpc": 0.016, "side": "long"},
        unfilled_orders=[],
        provider="openai",
        model="gpt-5-mini",
        llm=_StubLLM(_good_payload()),
    )
    assert isinstance(verdict, ViabilityVerdict)
    assert verdict.status == "still_viable"
    assert verdict.recommended_action == "hold"
    assert verdict.confidence == "high"
    assert "Thesis intact" in verdict.reasoning
    assert verdict.key_changes == ("Up 1.6% since save", "RVOL 2.4 (down from 3.1)")
    assert verdict.news_signals == ("NVDA beat earnings",)
    assert verdict.snapshot["current_price"] == 935.20
    assert verdict.snapshot["position_qty"] == 100
    assert verdict.model == "gpt-5-mini"
    assert verdict.analyzed_at  # non-empty timestamp


@pytest.mark.unit
def test_analyze_viability_normalizes_unknown_status():
    """Out-of-domain status values must clamp to 'invalidated'."""
    bad = _good_payload()
    bad["status"] = "looks_great"  # not in the allowed set
    verdict = analyze_viability(
        playbook=_mk_playbook(),
        scan_row={}, current_snapshot={}, news=[],
        catalyst_now=None, position=None, unfilled_orders=[],
        llm=_StubLLM(bad),
    )
    assert verdict.status == "invalidated"


@pytest.mark.unit
def test_analyze_viability_normalizes_unknown_action():
    bad = _good_payload()
    bad["recommended_action"] = "go_long_again"
    verdict = analyze_viability(
        playbook=_mk_playbook(),
        scan_row={}, current_snapshot={}, news=[],
        catalyst_now=None, position=None, unfilled_orders=[],
        llm=_StubLLM(bad),
    )
    assert verdict.recommended_action == "hold"


@pytest.mark.unit
def test_analyze_viability_returns_invalidated_on_llm_failure():
    class _ExplodingLLM:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            raise RuntimeError("rate limited")

    verdict = analyze_viability(
        playbook=_mk_playbook(),
        scan_row={}, current_snapshot={}, news=[],
        catalyst_now=None, position=None, unfilled_orders=[],
        provider="openai", model="gpt-5-mini",
        llm=_ExplodingLLM(),
    )
    assert verdict.status == "invalidated"
    assert "rate limited" in verdict.reasoning


@pytest.mark.unit
def test_verdict_to_dict_round_trips_through_set_verdict(tmp_path: Path):
    """End-to-end: stub LLM → ViabilityVerdict → SAVED_PLAYS.set_verdict → reload."""
    store = SavedPlaysStore(path=tmp_path / "saved_plays" / "index.json")
    e = store.save(symbol="NVDA", strategy_id="ATH_BREAKOUT",
                   strategy_name="ATH Breakout",
                   model="gpt-5-mini", provider="openai",
                   playbook=_mk_playbook(), scan_row={"last_price": 920.55})

    verdict = analyze_viability(
        playbook=_mk_playbook(),
        scan_row={"last_price": 920.55},
        current_snapshot={"current_price": 935.20},
        news=[], catalyst_now=None, position=None, unfilled_orders=[],
        provider="openai", model="gpt-5-mini",
        llm=_StubLLM(_good_payload()),
    )
    assert store.set_verdict(e["id"], verdict.to_dict()) is True

    loaded = store.load(e["id"])
    assert loaded["verdict"]["status"] == "still_viable"
    assert loaded["verdict"]["recommended_action"] == "hold"
    assert loaded["verdict"]["snapshot"]["current_price"] == 935.20
