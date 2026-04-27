"""
tradingagents/analytics/performance.py - Performance metric calculations.

Two data sources:
- Equity-curve metrics (Sharpe, max drawdown) compute from the Alpaca
  portfolio history time series.
- Trade-level metrics (win rate, profit factor, per-ticker stats, avg hold)
  compute from the SQLite trade journal's `outcomes` table.

All functions return None / empty dicts when insufficient data exists — they
never raise on empty input.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from .trade_journal import TradeJournal, get_journal

logger = logging.getLogger(__name__)

# Trading days per year for annualization
_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class DrawdownResult:
    """Peak-to-trough decline result."""
    max_drawdown_dollars: float
    max_drawdown_percent: float
    peak_value: float
    trough_value: float
    peak_index: int
    trough_index: int


# ---- Equity-curve metrics (from Alpaca portfolio history) --------------

def calculate_max_drawdown(equity_curve: Sequence[float]) -> DrawdownResult | None:
    """Compute the maximum peak-to-trough decline in an equity curve.

    Returns None if fewer than 2 data points or all equal.
    """
    if not equity_curve or len(equity_curve) < 2:
        return None

    peak = equity_curve[0]
    peak_idx = 0
    max_dd_dollars = 0.0
    max_dd_percent = 0.0
    trough_idx = 0
    result_peak_idx = 0
    result_peak = peak

    for i, value in enumerate(equity_curve):
        if value > peak:
            peak = value
            peak_idx = i
        dd_dollars = peak - value
        dd_percent = (dd_dollars / peak * 100) if peak > 0 else 0.0
        if dd_dollars > max_dd_dollars:
            max_dd_dollars = dd_dollars
            max_dd_percent = dd_percent
            trough_idx = i
            result_peak_idx = peak_idx
            result_peak = peak

    if max_dd_dollars <= 0:
        return None

    return DrawdownResult(
        max_drawdown_dollars=max_dd_dollars,
        max_drawdown_percent=max_dd_percent,
        peak_value=result_peak,
        trough_value=equity_curve[trough_idx],
        peak_index=result_peak_idx,
        trough_index=trough_idx,
    )


def calculate_sharpe_ratio(
    equity_curve: Sequence[float],
    *,
    risk_free_rate: float = 0.05,
    periods_per_year: int = _TRADING_DAYS_PER_YEAR,
) -> float | None:
    """Annualized Sharpe ratio from an equity time series.

    Interprets each curve step as one period (default 1 trading day).
    Returns None if fewer than 2 usable returns or stdev is zero.
    """
    if not equity_curve or len(equity_curve) < 2:
        return None

    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        curr = equity_curve[i]
        if prev <= 0:
            continue
        returns.append((curr - prev) / prev)

    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    stdev = math.sqrt(variance)

    if stdev == 0:
        return None

    # Annualize: mean * N, stdev * sqrt(N)
    annualized_return = mean * periods_per_year
    annualized_vol = stdev * math.sqrt(periods_per_year)

    return (annualized_return - risk_free_rate) / annualized_vol


# ---- Trade-level metrics (from journal outcomes) ------------------------

def _fetch_outcomes(
    journal: TradeJournal | None,
    *,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch outcomes joined with their parent decisions (for ticker filter)."""
    j = journal or get_journal()
    decisions = j.get_decisions_with_outcomes(ticker=ticker, limit=5000)
    outcomes: list[dict[str, Any]] = []
    for d in decisions:
        for o in d.get("outcomes", []) or []:
            outcomes.append(o)
    return outcomes


def calculate_win_rate(
    journal: TradeJournal | None = None,
    *,
    ticker: str | None = None,
) -> float | None:
    """Return % of outcomes with positive P&L, or None if no outcomes."""
    outcomes = _fetch_outcomes(journal, ticker=ticker)
    if not outcomes:
        return None
    wins = sum(1 for o in outcomes if (o.get("pnl_dollars") or 0) > 0)
    return wins / len(outcomes) * 100


def calculate_total_pnl(
    journal: TradeJournal | None = None,
    *,
    ticker: str | None = None,
) -> float:
    """Sum of realized P&L across all closed trades."""
    outcomes = _fetch_outcomes(journal, ticker=ticker)
    return sum((o.get("pnl_dollars") or 0) for o in outcomes)


def calculate_profit_factor(
    journal: TradeJournal | None = None,
    *,
    ticker: str | None = None,
) -> float | None:
    """Gross profit / gross loss. Returns None if no losses or no outcomes."""
    outcomes = _fetch_outcomes(journal, ticker=ticker)
    if not outcomes:
        return None
    gross_profit = sum(o["pnl_dollars"] for o in outcomes
                       if (o.get("pnl_dollars") or 0) > 0)
    gross_loss = abs(sum(o["pnl_dollars"] for o in outcomes
                         if (o.get("pnl_dollars") or 0) < 0))
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def calculate_avg_hold_duration(
    journal: TradeJournal | None = None,
    *,
    ticker: str | None = None,
) -> float | None:
    """Average hold duration in hours across all outcomes. None if no data."""
    outcomes = _fetch_outcomes(journal, ticker=ticker)
    durations = [o["hold_duration_hours"] for o in outcomes
                 if o.get("hold_duration_hours") is not None]
    if not durations:
        return None
    return sum(durations) / len(durations)


def calculate_per_ticker_stats(
    journal: TradeJournal | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-ticker aggregates: trade count, win rate, avg P&L, total P&L."""
    j = journal or get_journal()
    tickers = j.get_all_tickers()
    stats: dict[str, dict[str, Any]] = {}

    for t in tickers:
        outcomes = _fetch_outcomes(j, ticker=t)
        if not outcomes:
            stats[t] = {
                "trade_count": 0,
                "win_rate": None,
                "avg_pnl": None,
                "total_pnl": 0.0,
            }
            continue
        pnls = [o.get("pnl_dollars") or 0 for o in outcomes]
        wins = sum(1 for p in pnls if p > 0)
        stats[t] = {
            "trade_count": len(outcomes),
            "win_rate": wins / len(outcomes) * 100,
            "avg_pnl": sum(pnls) / len(pnls),
            "total_pnl": sum(pnls),
        }

    return stats


# ---- Convenience: all metrics in one call ------------------------------

def calculate_all_metrics(
    *,
    equity_curve: Sequence[float] | None = None,
    risk_free_rate: float = 0.05,
    journal: TradeJournal | None = None,
) -> dict[str, Any]:
    """Bundle all metrics into a single dict for UI consumption."""
    dd = calculate_max_drawdown(equity_curve) if equity_curve else None
    sharpe = (calculate_sharpe_ratio(equity_curve, risk_free_rate=risk_free_rate)
              if equity_curve else None)

    return {
        "sharpe_ratio": sharpe,
        "max_drawdown": dd,
        "win_rate": calculate_win_rate(journal),
        "total_pnl": calculate_total_pnl(journal),
        "profit_factor": calculate_profit_factor(journal),
        "avg_hold_hours": calculate_avg_hold_duration(journal),
        "per_ticker": calculate_per_ticker_stats(journal),
    }
