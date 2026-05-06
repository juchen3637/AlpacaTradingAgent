"""Tests for strategy analysis: sentiment extraction, analyst effectiveness, patterns."""

from __future__ import annotations

import os
import tempfile

import pytest

from tradingagents.analytics.strategy_analysis import (
    analyze_signal_patterns,
    analyze_time_patterns,
    calculate_analyst_effectiveness,
    calculate_streaks,
    extract_analyst_sentiment,
    get_signal_distribution,
)
from tradingagents.analytics.trade_journal import (
    DecisionRecord,
    TradeJournal,
)


# ─── Sentiment extraction ───────────────────────────────────────────────


def test_sentiment_bullish():
    text = "This is a strong buy. Bullish trend, positive momentum, expect upside."
    assert extract_analyst_sentiment(text) == "bullish"


def test_sentiment_bearish():
    text = "Bearish signal — weak fundamentals, sell recommendation, clear downtrend."
    assert extract_analyst_sentiment(text) == "bearish"


def test_sentiment_neutral_mixed():
    text = "Some bullish signs but also bearish concerns. Mixed signals."
    # 1 bullish, 1 bearish → neutral (margin is 0, below threshold of 2)
    assert extract_analyst_sentiment(text) == "neutral"


def test_sentiment_empty_is_neutral():
    assert extract_analyst_sentiment("") == "neutral"
    assert extract_analyst_sentiment(None) == "neutral"


def test_sentiment_requires_margin():
    # Only 1 keyword each side → neutral
    assert extract_analyst_sentiment("bullish but weak") == "neutral"
    # Need at least 2-keyword margin
    assert extract_analyst_sentiment("bullish bullish bullish weak") == "bullish"


# ─── Journal fixtures ───────────────────────────────────────────────────


@pytest.fixture
def journal_with_rich_data():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    j = TradeJournal(db_path=tmp.name)

    def _add(ticker, signal, market, sentiment, news, fundamentals, macro, pnl, timestamp=None):
        did = j.record_decision(DecisionRecord(
            ticker=ticker, trade_date="2026-04-21", signal=signal,
            market_report=market, sentiment_report=sentiment,
            news_report=news, fundamentals_report=fundamentals,
            macro_report=macro,
            selected_analysts=["market", "social", "news", "fundamentals", "macro"],
            timestamp=timestamp or "2026-04-21T14:30:00+00:00",
        ))
        if pnl is not None:
            j.record_outcome(
                decision_id=did, ticker=ticker,
                entry_timestamp=None, entry_price=100.0,
                exit_timestamp="2026-04-22T10:00:00", exit_price=100 + pnl / 10,
                qty=10.0, pnl_dollars=pnl, pnl_percent=pnl / 10,
                hold_duration_hours=24.0,
                exit_reason="take_profit" if pnl > 0 else "stop_loss",
            )

    # Winner: all analysts bullish, BUY signal, positive P&L
    _add("NVDA", "BUY",
         "Strong bullish breakout. Buy signal clear.",
         "Social very bullish. Strong buy momentum.",
         "Positive news bullish fundamentals strong.",
         "Bullish fundamentals strong growth positive.",
         "Macro supportive bullish positive outlook.",
         100.0, timestamp="2026-04-21T14:30:00+00:00")

    # Winner: news bullish, others mixed, BUY signal
    _add("AMD", "BUY",
         "Mixed signals neutral outlook.",
         "Neutral sentiment social.",
         "Bullish positive news strong buy outperform.",
         "Neutral data mixed signals.",
         "Neutral macro stance.",
         50.0, timestamp="2026-04-21T15:00:00+00:00")

    # Loser: macro bullish but stock went down; SELL signal, negative P&L
    _add("TSLA", "SELL",
         "Bearish downtrend clear sell signal.",
         "Bearish sentiment negative social.",
         "Negative news bearish sell.",
         "Weak fundamentals bearish.",
         "Bullish macro strong positive growth.",
         -75.0, timestamp="2026-04-21T09:15:00+00:00")

    # No outcome yet (open position)
    _add("META", "HOLD",
         "Neutral waiting.",
         "Neutral sentiment.",
         "Neutral news.",
         "Neutral data.",
         "Neutral macro.",
         None, timestamp="2026-04-21T10:00:00+00:00")

    yield j
    os.unlink(tmp.name)


# ─── Analyst effectiveness ──────────────────────────────────────────────


def test_analyst_effectiveness_counts_decisions(journal_with_rich_data):
    eff = calculate_analyst_effectiveness(journal_with_rich_data)
    # All 5 analysts wrote for all 4 decisions
    for name in ("market", "social", "news", "fundamentals", "macro"):
        assert eff[name]["total_decisions"] == 4


def test_analyst_effectiveness_sentiment_distribution(journal_with_rich_data):
    eff = calculate_analyst_effectiveness(journal_with_rich_data)
    # market: 1 bullish (NVDA), 1 bearish (TSLA), 2 neutral (AMD, META)
    assert eff["market"]["bullish"] == 1
    assert eff["market"]["bearish"] == 1
    assert eff["market"]["neutral"] == 2


def test_analyst_effectiveness_alignment(journal_with_rich_data):
    eff = calculate_analyst_effectiveness(journal_with_rich_data)
    # Market analyst: bullish on NVDA (BUY signal) = aligned, bearish on TSLA (SELL) = aligned
    assert eff["market"]["aligned_with_signal"] == 2


def test_analyst_effectiveness_influence_score(journal_with_rich_data):
    eff = calculate_analyst_effectiveness(journal_with_rich_data)
    # Market analyst aligned: NVDA (+100), TSLA (-75) — 1 win out of 2 with outcome = 50%
    assert eff["market"]["influence_score"] == pytest.approx(50.0)

    # News analyst aligned: NVDA bullish+BUY (+100), AMD bullish+BUY (+50), TSLA bearish+SELL (-75)
    # 2 wins / 3 with outcome = 66.67%
    assert eff["news"]["influence_score"] == pytest.approx(2 / 3 * 100)

    # Macro: bullish on NVDA (BUY, +100) = aligned+winner; bullish on TSLA (SELL, -75) = contra
    # AMD and META macro are neutral → no alignment. So only 1 aligned, 1 winner.
    assert eff["macro"]["aligned_with_winner"] == 1
    assert eff["macro"]["aligned_with_loser"] == 0
    assert eff["macro"]["influence_score"] == pytest.approx(100.0)


def test_analyst_effectiveness_contra_signal(journal_with_rich_data):
    eff = calculate_analyst_effectiveness(journal_with_rich_data)
    # Macro was bullish on TSLA but signal was SELL → contra
    assert eff["macro"]["contra_signal"] >= 1


def test_analyst_effectiveness_empty_journal_returns_none_influence():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        eff = calculate_analyst_effectiveness(j)
        for name in ("market", "social", "news", "fundamentals", "macro"):
            assert eff[name]["total_decisions"] == 0
            assert eff[name]["influence_score"] is None
    finally:
        os.unlink(tmp.name)


# ─── Signal distribution ────────────────────────────────────────────────


def test_signal_distribution(journal_with_rich_data):
    dist = get_signal_distribution(journal_with_rich_data)
    assert dist["BUY"] == 2
    assert dist["SELL"] == 1
    assert dist["HOLD"] == 1


def test_signal_distribution_filtered_by_ticker(journal_with_rich_data):
    dist = get_signal_distribution(journal_with_rich_data, ticker="NVDA")
    assert dist == {"BUY": 1}


# ─── Signal pattern analysis ────────────────────────────────────────────


def test_signal_patterns_structure(journal_with_rich_data):
    patterns = analyze_signal_patterns(journal_with_rich_data)
    assert "NVDA" in patterns
    assert "BUY" in patterns["NVDA"]
    assert patterns["NVDA"]["BUY"]["count"] == 1
    assert patterns["NVDA"]["BUY"]["win_rate"] == pytest.approx(100.0)
    assert patterns["NVDA"]["BUY"]["total_pnl"] == pytest.approx(100.0)


def test_signal_patterns_hold_has_no_outcomes(journal_with_rich_data):
    patterns = analyze_signal_patterns(journal_with_rich_data)
    meta_hold = patterns["META"]["HOLD"]
    assert meta_hold["count"] == 1
    assert meta_hold["outcomes_count"] == 0
    assert meta_hold["win_rate"] is None


# ─── Time patterns ──────────────────────────────────────────────────────


def test_time_patterns_counts_by_hour(journal_with_rich_data):
    patterns = analyze_time_patterns(journal_with_rich_data)
    # Hours used: 14 (NVDA), 15 (AMD), 9 (TSLA), 10 (META)
    assert patterns[14]["count"] == 1
    assert patterns[15]["count"] == 1
    assert patterns[9]["count"] == 1
    assert patterns[10]["count"] == 1
    # Hour 3 (unused) should be 0
    assert patterns[3]["count"] == 0


def test_time_patterns_win_rate_per_hour(journal_with_rich_data):
    patterns = analyze_time_patterns(journal_with_rich_data)
    # Hour 14 has NVDA (+100) = 100% win rate
    assert patterns[14]["win_rate"] == pytest.approx(100.0)
    # Hour 9 has TSLA (-75) = 0% win rate
    assert patterns[9]["win_rate"] == pytest.approx(0.0)
    # Hour 10 has META with no outcome → None
    assert patterns[10]["win_rate"] is None


# ─── Streaks ────────────────────────────────────────────────────────────


def test_streaks_empty_returns_zeros():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        s = calculate_streaks(j)
        assert s["longest_win"] == 0
        assert s["longest_loss"] == 0
        assert s["current_streak"] == 0
        assert s["streak_timeline"] == []
    finally:
        os.unlink(tmp.name)


def test_streaks_mixed(journal_with_rich_data):
    # Chronological (by timestamp): TSLA 09:15 (-75), META 10:00 (no outcome → skipped),
    # NVDA 14:30 (+100), AMD 15:00 (+50)
    # Timeline: [-1, +1, +1]
    s = calculate_streaks(journal_with_rich_data)
    assert s["streak_timeline"] == [-1, 1, 1]
    assert s["longest_win"] == 2
    assert s["longest_loss"] == 1
    assert s["current_streak"] == 2


def test_streaks_all_wins():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        for i, pnl in enumerate([50, 75, 100]):
            did = j.record_decision(DecisionRecord(
                ticker="NVDA", trade_date="2026-04-21", signal="BUY",
                selected_analysts=[],
                timestamp=f"2026-04-21T{10+i:02d}:00:00+00:00",
            ))
            j.record_outcome(
                decision_id=did, ticker="NVDA",
                entry_timestamp=None, entry_price=100.0,
                exit_timestamp=f"2026-04-22T{10+i:02d}:00:00", exit_price=110,
                qty=1.0, pnl_dollars=pnl, pnl_percent=10.0,
                hold_duration_hours=24.0, exit_reason="take_profit",
            )
        s = calculate_streaks(j)
        assert s["longest_win"] == 3
        assert s["longest_loss"] == 0
        assert s["current_streak"] == 3
    finally:
        os.unlink(tmp.name)


# ─── Source filter (Analysis tab Scanner-only view) ─────────────────────


def test_get_decisions_filters_by_source():
    """Journal source filter cleanly separates scanner / agent / backfill."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        j.record_decision(DecisionRecord(
            ticker="NVDA", trade_date="2026-04-30", signal="BUY",
            source="agent", selected_analysts=[],
        ))
        j.record_decision(DecisionRecord(
            ticker="AMD", trade_date="2026-04-30", signal="BUY",
            source="scanner", source_order_id="scanner:ATH_BREAKOUT:abc1234567",
            selected_analysts=[],
        ))
        j.record_decision(DecisionRecord(
            ticker="TSLA", trade_date="2026-04-30", signal="SELL",
            source="backfill", source_order_id="alpaca-historical-1",
            selected_analysts=[],
        ))

        scanner_only = j.get_decisions(source="scanner")
        assert len(scanner_only) == 1
        assert scanner_only[0]["ticker"] == "AMD"
        assert scanner_only[0]["source_order_id"].startswith("scanner:")

        agent_only = j.get_decisions(source="agent")
        assert len(agent_only) == 1
        assert agent_only[0]["ticker"] == "NVDA"

        all_decisions = j.get_decisions()
        assert len(all_decisions) == 3
    finally:
        os.unlink(tmp.name)
