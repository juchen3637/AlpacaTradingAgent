"""
tradingagents/analytics - Trade journaling, performance metrics, and strategy analysis.
"""

from .performance import (
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
from .strategy_analysis import (
    analyze_signal_patterns,
    analyze_time_patterns,
    calculate_analyst_effectiveness,
    calculate_streaks,
    extract_analyst_sentiment,
    get_signal_distribution,
)
from .backfill import BackfillReport, backfill_from_alpaca
from .trade_journal import TradeJournal, get_journal

__all__ = [
    "TradeJournal",
    "get_journal",
    "BackfillReport",
    "backfill_from_alpaca",
    "DrawdownResult",
    "calculate_all_metrics",
    "calculate_avg_hold_duration",
    "calculate_max_drawdown",
    "calculate_per_ticker_stats",
    "calculate_profit_factor",
    "calculate_sharpe_ratio",
    "calculate_total_pnl",
    "calculate_win_rate",
    "analyze_signal_patterns",
    "analyze_time_patterns",
    "calculate_analyst_effectiveness",
    "calculate_streaks",
    "extract_analyst_sentiment",
    "get_signal_distribution",
]
