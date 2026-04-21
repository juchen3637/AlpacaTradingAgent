"""Tests for the SQLite-backed trade journal."""

from __future__ import annotations

import os
import tempfile

import pytest

from tradingagents.analytics.trade_journal import (
    DecisionRecord,
    TradeJournal,
    TradeRecord,
    build_decision_from_state,
)


@pytest.fixture
def journal():
    """Temp SQLite journal, cleaned up after each test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    j = TradeJournal(db_path=tmp.name)
    yield j
    os.unlink(tmp.name)


def _decision(ticker="NVDA", signal="BUY", **overrides) -> DecisionRecord:
    defaults = dict(
        ticker=ticker,
        trade_date="2026-04-21",
        signal=signal,
        market_report="market",
        sentiment_report="sentiment",
        news_report="news",
        fundamentals_report="fundamentals",
        macro_report="macro",
        bull_summary="bull",
        bear_summary="bear",
        judge_decision="judge",
        trader_plan="trader",
        risk_debate_summary="risk",
        final_decision="final",
        position_size_dollars=5000.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=[110.0, 115.0],
        selected_analysts=["market", "news"],
        research_depth="shallow",
        llm_provider="anthropic",
        quick_llm="sonnet",
        deep_llm="opus",
        execution_time_seconds=30.0,
        allow_shorts=False,
    )
    defaults.update(overrides)
    return DecisionRecord(**defaults)


def test_record_and_retrieve_decision(journal):
    did = journal.record_decision(_decision())
    assert did > 0

    fetched = journal.get_decision_by_id(did)
    assert fetched is not None
    assert fetched["ticker"] == "NVDA"
    assert fetched["signal"] == "BUY"
    assert fetched["take_profit"] == [110.0, 115.0]
    assert fetched["selected_analysts"] == ["market", "news"]
    assert fetched["allow_shorts"] is False


def test_filter_decisions_by_ticker(journal):
    journal.record_decision(_decision(ticker="NVDA"))
    journal.record_decision(_decision(ticker="AMD"))
    journal.record_decision(_decision(ticker="NVDA", signal="SELL"))

    nvda = journal.get_decisions(ticker="NVDA")
    amd = journal.get_decisions(ticker="AMD")

    assert len(nvda) == 2
    assert len(amd) == 1
    assert all(d["ticker"] == "NVDA" for d in nvda)


def test_filter_decisions_by_signal(journal):
    journal.record_decision(_decision(signal="BUY"))
    journal.record_decision(_decision(signal="SELL"))
    journal.record_decision(_decision(signal="BUY"))

    buys = journal.get_decisions(signal="BUY")
    sells = journal.get_decisions(signal="SELL")

    assert len(buys) == 2
    assert len(sells) == 1


def test_record_trade_linked_to_decision(journal):
    did = journal.record_decision(_decision())
    tid = journal.record_trade(TradeRecord(
        decision_id=did,
        ticker="NVDA",
        side="buy",
        qty=50.0,
        filled_price=100.0,
        order_type="market",
        alpaca_order_id="xyz",
        status="filled",
    ))
    assert tid > 0

    trades = journal.get_trades_for_decision(did)
    assert len(trades) == 1
    assert trades[0]["alpaca_order_id"] == "xyz"
    assert trades[0]["qty"] == 50.0


def test_record_outcome(journal):
    did = journal.record_decision(_decision())
    oid = journal.record_outcome(
        decision_id=did,
        ticker="NVDA",
        entry_timestamp="2026-04-21T10:00:00",
        entry_price=100.0,
        exit_timestamp="2026-04-22T10:00:00",
        exit_price=105.0,
        qty=50.0,
        pnl_dollars=250.0,
        pnl_percent=5.0,
        hold_duration_hours=24.0,
        exit_reason="take_profit",
    )
    assert oid > 0

    outcomes = journal.get_outcomes_for_decision(did)
    assert len(outcomes) == 1
    assert outcomes[0]["pnl_dollars"] == 250.0
    assert outcomes[0]["exit_reason"] == "take_profit"


def test_all_tickers_deduplicates(journal):
    journal.record_decision(_decision(ticker="NVDA"))
    journal.record_decision(_decision(ticker="AMD"))
    journal.record_decision(_decision(ticker="NVDA"))

    tickers = journal.get_all_tickers()
    assert sorted(tickers) == ["AMD", "NVDA"]


def test_count_decisions(journal):
    assert journal.count_decisions() == 0
    journal.record_decision(_decision(ticker="NVDA"))
    journal.record_decision(_decision(ticker="AMD"))
    assert journal.count_decisions() == 2
    assert journal.count_decisions(ticker="NVDA") == 1


def test_decisions_with_outcomes_joins_children(journal):
    did = journal.record_decision(_decision())
    journal.record_trade(TradeRecord(
        decision_id=did, ticker="NVDA", side="buy", qty=1.0,
        filled_price=100.0, order_type="market",
    ))
    journal.record_outcome(
        decision_id=did, ticker="NVDA",
        entry_timestamp=None, entry_price=100.0,
        exit_timestamp="2026-04-22T10:00:00", exit_price=110.0,
        qty=1.0, pnl_dollars=10.0, pnl_percent=10.0,
        hold_duration_hours=24.0, exit_reason="take_profit",
    )

    decisions = journal.get_decisions_with_outcomes()
    assert len(decisions) == 1
    assert len(decisions[0]["trades"]) == 1
    assert len(decisions[0]["outcomes"]) == 1


def test_build_decision_from_state_extracts_all_fields():
    state = {
        "market_report": "m",
        "sentiment_report": "s",
        "news_report": "n",
        "fundamentals_report": "f",
        "macro_report": "ma",
        "investment_debate_state": {
            "bull_history": "bull wins",
            "bear_history": "bear loses",
            "judge_decision": "go long",
        },
        "risk_debate_state": {
            "judge_decision": "approved",
        },
        "trader_investment_plan": "plan",
        "final_trade_decision": "BUY",
        "approved_trading_prices": {
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "targets": [110, 115],
        },
    }
    rec = build_decision_from_state(
        ticker="NVDA",
        trade_date="2026-04-21",
        final_state=state,
        signal="BUY",
        config={
            "research_depth": "shallow",
            "llm_provider": "anthropic",
            "quick_think_llm": "sonnet",
            "deep_think_llm": "opus",
        },
        selected_analysts=["market"],
        position_size_dollars=1000.0,
        execution_time_seconds=10.0,
        allow_shorts=False,
    )
    assert rec.market_report == "m"
    assert rec.bull_summary == "bull wins"
    assert rec.bear_summary == "bear loses"
    assert rec.judge_decision == "go long"
    assert rec.risk_debate_summary == "approved"
    assert rec.entry_price == 100.0
    assert rec.stop_loss == 95.0
    assert rec.take_profit == [110.0, 115.0]


def test_build_decision_handles_missing_state_fields():
    # Empty state should not raise; everything falls back to None/empty
    rec = build_decision_from_state(
        ticker="NVDA",
        trade_date="2026-04-21",
        final_state={},
        signal=None,
        config={},
        selected_analysts=[],
        position_size_dollars=None,
        execution_time_seconds=None,
        allow_shorts=False,
    )
    assert rec.market_report is None
    assert rec.entry_price is None
    assert rec.take_profit == []


def test_decision_records_are_immutable():
    rec = _decision()
    with pytest.raises(Exception):
        rec.ticker = "AMD"  # frozen dataclass
