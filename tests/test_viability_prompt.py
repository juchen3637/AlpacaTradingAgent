"""Snapshot test for the viability re-analysis prompt.

The prompt sent to the LLM is the contract — silent drift here changes
verdict behavior in production. This test pins the prompt to a golden
fixture; on intentional changes, regenerate the fixture by running with
WRITE_GOLDEN=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tradingagents.scanner.models import Playbook
from tradingagents.scanner.viability import build_viability_user_prompt


GOLDEN = Path(__file__).parent / "golden" / "viability_prompt_v1.txt"


def _fixed_playbook() -> Playbook:
    return Playbook(
        symbol="NVDA",
        strategy_id="ATH_BREAKOUT",
        thesis="Breakout above ATH on heavy volume confirms continuation.",
        entry_trigger="Buy stop above 920.50 with confirming volume.",
        entry_price=920.50,
        order_type="Buy Stop",
        stop_loss=905.00,
        profit_target_1=940.00,
        profit_target_2=960.00,
        risk_reward=2.6,
        position_size_pct=0.05,
        indicators_to_watch=("VWAP", "RVOL", "PDH"),
        invalidation="Loss of VWAP on heavy volume.",
        confidence="high",
        qualification_reason=(
            "Within 0.4% of ATH and RVOL is 3.1x with a fresh earnings catalyst."
        ),
        confidence_reason=(
            "Three confluent signals aligned — catalyst, RVOL, and ATH proximity."
        ),
    )


def _fixed_inputs() -> dict:
    return dict(
        playbook=_fixed_playbook(),
        scan_row={
            "symbol": "NVDA",
            "last_price": 920.55,
            "rvol": 3.1,
            "catalyst": "Earnings 2026-05-07",
        },
        current_snapshot={
            "current_price": 935.20,
            "change_since_save_pct": 1.59,
            "today_change_pct": 2.40,
            "current_rvol": 2.4,
        },
        news=[
            {"headline": "NVIDIA tops Q1 estimates, raises guidance",
             "source": "Reuters"},
            {"headline": "Analysts bump NVDA price target to $1000",
             "source": "Bloomberg"},
        ],
        catalyst_now="Earnings beat — guidance raised",
        position={
            "side": "long",
            "qty": 100,
            "avg_entry_price": 920.50,
            "unrealized_pl": 1470.00,
            "unrealized_plpc": 0.0160,
        },
        unfilled_orders=[],
    )


@pytest.mark.unit
def test_viability_prompt_matches_golden():
    prompt = build_viability_user_prompt(**_fixed_inputs())
    if os.environ.get("WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(prompt, encoding="utf-8")
    assert GOLDEN.exists(), (
        f"Golden fixture missing: {GOLDEN}. Re-run with WRITE_GOLDEN=1 "
        "to generate it."
    )
    expected = GOLDEN.read_text(encoding="utf-8")
    assert prompt == expected, (
        "Viability prompt drifted from golden. If intentional, regenerate with "
        "WRITE_GOLDEN=1 pytest tests/test_viability_prompt.py"
    )


@pytest.mark.unit
def test_viability_prompt_handles_missing_position_and_news():
    inputs = _fixed_inputs()
    inputs["position"] = None
    inputs["news"] = []
    inputs["unfilled_orders"] = []
    prompt = build_viability_user_prompt(**inputs)
    assert "Position: none" in prompt
    assert "(no recent news)" in prompt
    assert "Unfilled orders: none" in prompt


@pytest.mark.unit
def test_viability_prompt_handles_unfilled_orders():
    inputs = _fixed_inputs()
    inputs["position"] = None
    inputs["unfilled_orders"] = [{
        "side": "buy",
        "qty": 100,
        "order_type": "stop",
        "limit_price": None,
        "stop_price": 920.50,
        "status": "accepted",
    }]
    prompt = build_viability_user_prompt(**inputs)
    assert "Unfilled order: BUY" in prompt
    assert "stop=920.50" in prompt
