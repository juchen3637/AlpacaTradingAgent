"""Tests for the performance metrics engine."""

from __future__ import annotations

import math
import os
import tempfile

import pytest

from tradingagents.analytics.performance import (
    DrawdownResult,
    calculate_all_metrics,
    calculate_avg_hold_duration,
    calculate_max_drawdown,
    calculate_per_ticker_stats,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_total_pnl,
    calculate_win_rate,
)
from tradingagents.analytics.trade_journal import (
    DecisionRecord,
    TradeJournal,
)


# ─── Equity-curve metrics ───────────────────────────────────────────────


def test_max_drawdown_basic():
    # Peak 150 → trough 80 → partial recovery
    curve = [100, 120, 150, 130, 110, 80, 100]
    result = calculate_max_drawdown(curve)
    assert result is not None
    assert result.max_drawdown_dollars == pytest.approx(70.0)
    assert result.max_drawdown_percent == pytest.approx(70 / 150 * 100)
    assert result.peak_value == 150
    assert result.trough_value == 80


def test_max_drawdown_monotonic_up_returns_none():
    curve = [100, 110, 120, 130]
    assert calculate_max_drawdown(curve) is None


def test_max_drawdown_empty_and_short():
    assert calculate_max_drawdown([]) is None
    assert calculate_max_drawdown([100]) is None


def test_max_drawdown_flat_returns_none():
    assert calculate_max_drawdown([100, 100, 100]) is None


def test_sharpe_ratio_positive_trend():
    # Steady 0.1% daily gain → very high Sharpe (low volatility, positive return)
    curve = [100 * (1.001 ** i) for i in range(100)]
    sharpe = calculate_sharpe_ratio(curve, risk_free_rate=0.0)
    assert sharpe is not None
    assert sharpe > 10  # Extremely high since no volatility


def test_sharpe_ratio_flat_returns_none():
    # No variation → stdev 0 → None
    curve = [100] * 10
    assert calculate_sharpe_ratio(curve) is None


def test_sharpe_ratio_short_returns_none():
    assert calculate_sharpe_ratio([]) is None
    assert calculate_sharpe_ratio([100]) is None
    assert calculate_sharpe_ratio([100, 101]) is None  # need ≥2 returns, this gives 1


def test_sharpe_ratio_mixed_returns():
    # Small random walk — just verify it returns a finite number
    curve = [100, 101, 100, 102, 101, 103, 102, 104, 103, 105]
    sharpe = calculate_sharpe_ratio(curve, risk_free_rate=0.0)
    assert sharpe is not None
    assert math.isfinite(sharpe)


# ─── Journal-based metrics ──────────────────────────────────────────────


@pytest.fixture
def journal_with_outcomes():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    j = TradeJournal(db_path=tmp.name)

    def _add(ticker, signal, pnl, hold_hours=24.0):
        did = j.record_decision(DecisionRecord(
            ticker=ticker, trade_date="2026-04-21", signal=signal,
            selected_analysts=[],
        ))
        j.record_outcome(
            decision_id=did, ticker=ticker,
            entry_timestamp="2026-04-20T10:00:00",
            entry_price=100.0,
            exit_timestamp="2026-04-21T10:00:00",
            exit_price=100.0 + pnl / 10,
            qty=10.0,
            pnl_dollars=pnl,
            pnl_percent=pnl / 1000 * 100,
            hold_duration_hours=hold_hours,
            exit_reason="take_profit" if pnl > 0 else "stop_loss",
        )

    # 3 wins, 2 losses
    _add("NVDA", "BUY", 100.0, 24.0)
    _add("NVDA", "BUY", 200.0, 12.0)
    _add("NVDA", "SELL", -50.0, 48.0)
    _add("AMD", "BUY", 75.0, 36.0)
    _add("AMD", "BUY", -100.0, 6.0)

    yield j
    os.unlink(tmp.name)


def test_win_rate(journal_with_outcomes):
    # 3 wins out of 5 = 60%
    assert calculate_win_rate(journal_with_outcomes) == pytest.approx(60.0)


def test_win_rate_filtered_by_ticker(journal_with_outcomes):
    # NVDA: 2 wins out of 3
    assert calculate_win_rate(journal_with_outcomes, ticker="NVDA") == pytest.approx(2 / 3 * 100)
    # AMD: 1 win out of 2
    assert calculate_win_rate(journal_with_outcomes, ticker="AMD") == pytest.approx(50.0)


def test_win_rate_empty_returns_none():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        assert calculate_win_rate(j) is None
    finally:
        os.unlink(tmp.name)


def test_total_pnl(journal_with_outcomes):
    # 100 + 200 - 50 + 75 - 100 = 225
    assert calculate_total_pnl(journal_with_outcomes) == pytest.approx(225.0)


def test_total_pnl_filtered(journal_with_outcomes):
    # NVDA: 100 + 200 - 50 = 250
    assert calculate_total_pnl(journal_with_outcomes, ticker="NVDA") == pytest.approx(250.0)


def test_profit_factor(journal_with_outcomes):
    # gross profit = 100 + 200 + 75 = 375
    # gross loss = 50 + 100 = 150
    # factor = 375 / 150 = 2.5
    assert calculate_profit_factor(journal_with_outcomes) == pytest.approx(2.5)


def test_profit_factor_no_losses_returns_none():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        j = TradeJournal(db_path=tmp.name)
        did = j.record_decision(DecisionRecord(
            ticker="NVDA", trade_date="2026-04-21", signal="BUY",
            selected_analysts=[],
        ))
        j.record_outcome(
            decision_id=did, ticker="NVDA",
            entry_timestamp=None, entry_price=100.0,
            exit_timestamp="2026-04-22", exit_price=110.0, qty=1.0,
            pnl_dollars=10.0, pnl_percent=10.0,
            hold_duration_hours=24.0, exit_reason="take_profit",
        )
        assert calculate_profit_factor(j) is None
    finally:
        os.unlink(tmp.name)


def test_avg_hold_duration(journal_with_outcomes):
    # (24 + 12 + 48 + 36 + 6) / 5 = 25.2
    assert calculate_avg_hold_duration(journal_with_outcomes) == pytest.approx(25.2)


def test_per_ticker_stats(journal_with_outcomes):
    stats = calculate_per_ticker_stats(journal_with_outcomes)
    assert set(stats.keys()) == {"NVDA", "AMD"}

    nvda = stats["NVDA"]
    assert nvda["trade_count"] == 3
    assert nvda["win_rate"] == pytest.approx(2 / 3 * 100)
    assert nvda["total_pnl"] == pytest.approx(250.0)
    assert nvda["avg_pnl"] == pytest.approx(250 / 3)

    amd = stats["AMD"]
    assert amd["trade_count"] == 2
    assert amd["win_rate"] == pytest.approx(50.0)
    assert amd["total_pnl"] == pytest.approx(-25.0)


def test_calculate_all_metrics_bundles_everything(journal_with_outcomes):
    curve = [100, 120, 150, 130, 110, 80, 100]
    all_metrics = calculate_all_metrics(
        equity_curve=curve,
        risk_free_rate=0.0,
        journal=journal_with_outcomes,
    )
    assert isinstance(all_metrics["max_drawdown"], DrawdownResult)
    assert all_metrics["sharpe_ratio"] is not None
    assert all_metrics["win_rate"] == pytest.approx(60.0)
    assert all_metrics["total_pnl"] == pytest.approx(225.0)
    assert all_metrics["profit_factor"] == pytest.approx(2.5)
    assert all_metrics["avg_hold_hours"] == pytest.approx(25.2)
    assert "NVDA" in all_metrics["per_ticker"]


def test_calculate_all_metrics_no_equity_curve(journal_with_outcomes):
    result = calculate_all_metrics(
        equity_curve=None,
        journal=journal_with_outcomes,
    )
    assert result["max_drawdown"] is None
    assert result["sharpe_ratio"] is None
    # Journal-based metrics still populated
    assert result["win_rate"] == pytest.approx(60.0)
