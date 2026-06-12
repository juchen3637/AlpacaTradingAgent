"""Tests for tradingagents/llm_cost.py and eval-loop journal wiring."""

from __future__ import annotations

import threading

import pytest

from tradingagents.llm_cost import (
    _price_for,
    add_usage,
    get_thread_cost,
    pop_thread_cost,
    reset_thread_cost,
)


def test_price_prefix_matching_prefers_longest():
    # gpt-5-mini-2025-08-07 must match gpt-5-mini, not gpt-5
    assert _price_for("gpt-5-mini-2025-08-07") == (0.25, 2.0)
    assert _price_for("gpt-5.2-2025-12-11") == (15.0, 60.0)
    assert _price_for("claude-sonnet-4-6") == (3.0, 15.0)


def test_unknown_model_uses_fallback():
    assert _price_for("some-future-model") == (3.0, 15.0)


def test_accumulation_and_reset():
    reset_thread_cost()
    add_usage("gpt-4o-mini", 1_000_000, 1_000_000)  # $0.15 + $0.60
    assert get_thread_cost() == pytest.approx(0.75)
    add_usage("gpt-4o-mini", 1_000_000, 0)
    assert get_thread_cost() == pytest.approx(0.90)
    reset_thread_cost()
    assert get_thread_cost() == 0.0


def test_pop_clears_bucket():
    reset_thread_cost()
    add_usage("gpt-4o-mini", 1_000_000, 0)
    assert pop_thread_cost() == pytest.approx(0.15)
    assert get_thread_cost() == 0.0


def test_thread_isolation():
    reset_thread_cost()
    add_usage("gpt-4o-mini", 1_000_000, 0)
    other_cost = []

    def _other():
        reset_thread_cost()
        add_usage("gpt-4o-mini", 2_000_000, 0)
        other_cost.append(get_thread_cost())

    t = threading.Thread(target=_other)
    t.start()
    t.join()

    assert other_cost[0] == pytest.approx(0.30)
    assert get_thread_cost() == pytest.approx(0.15)


# ── Journal eval wiring ───────────────────────────────────────────────────────

def test_journal_eval_fields_roundtrip(tmp_path):
    from tradingagents.analytics.trade_journal import DecisionRecord, TradeJournal

    journal = TradeJournal(db_path=tmp_path / "test.db")
    decision_id = journal.record_decision(
        DecisionRecord(
            ticker="NVDA",
            trade_date="2026-06-11",
            signal="BUY",
            conviction=0.82,
            llm_cost_estimate=0.45,
        )
    )
    row = journal.get_decision_by_id(decision_id)
    assert row["conviction"] == pytest.approx(0.82)
    assert row["llm_cost_estimate"] == pytest.approx(0.45)
    assert row["gate_rejection_reason"] is None

    journal.update_decision_gate_result(decision_id, "MAX POSITIONS: at limit")
    row = journal.get_decision_by_id(decision_id)
    assert row["gate_rejection_reason"] == "MAX POSITIONS: at limit"


def test_eval_report_basic(tmp_path):
    from tradingagents.analytics.trade_journal import DecisionRecord, TradeJournal

    journal = TradeJournal(db_path=tmp_path / "test.db")

    d1 = journal.record_decision(
        DecisionRecord(ticker="NVDA", trade_date="2026-06-11", signal="BUY",
                       conviction=0.85, llm_cost_estimate=0.50)
    )
    d2 = journal.record_decision(
        DecisionRecord(ticker="AMD", trade_date="2026-06-11", signal="BUY",
                       conviction=0.55, llm_cost_estimate=0.30)
    )
    journal.record_outcome(
        decision_id=d1, ticker="NVDA", entry_timestamp=None, entry_price=100.0,
        exit_timestamp="2026-06-11T20:00:00+00:00", exit_price=110.0, qty=10,
        pnl_dollars=100.0, pnl_percent=10.0, hold_duration_hours=5.0, exit_reason="target",
    )
    journal.record_outcome(
        decision_id=d2, ticker="AMD", entry_timestamp=None, entry_price=100.0,
        exit_timestamp="2026-06-11T20:00:00+00:00", exit_price=95.0, qty=10,
        pnl_dollars=-50.0, pnl_percent=-5.0, hold_duration_hours=3.0, exit_reason="stop",
    )

    report = journal.get_eval_report(days=30, min_trades=2)
    assert report["total_decisions"] == 2
    assert report["closed_trades"] == 2
    assert report["win_rate"] == pytest.approx(0.5)
    assert report["total_pnl_dollars"] == pytest.approx(50.0)
    assert report["total_llm_cost"] == pytest.approx(0.80)
    assert report["conviction_calibration"]["high_conviction_win_rate"] == pytest.approx(1.0)
    assert report["conviction_calibration"]["low_conviction_win_rate"] == pytest.approx(0.0)
    assert report["note"] == ""


def test_eval_report_warns_on_insufficient_data(tmp_path):
    from tradingagents.analytics.trade_journal import TradeJournal

    journal = TradeJournal(db_path=tmp_path / "test.db")
    report = journal.get_eval_report(days=30, min_trades=5)
    assert report["closed_trades"] == 0
    assert "Keep paper-trading" in report["note"]
