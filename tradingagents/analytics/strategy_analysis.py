"""
tradingagents/analytics/strategy_analysis.py - Agent effectiveness and pattern analysis.

Two categories of insight:
- **Analyst effectiveness**: extracts sentiment (bullish/bearish/neutral) from each
  analyst's free-text report, then correlates that sentiment with trade outcomes
  to answer "which analysts are contributing to winning trades?".
- **Signal / timing patterns**: distribution of signals, per-ticker performance,
  time-of-day decision patterns, win/loss streaks.

Sentiment extraction is deliberately simple keyword counting — it's a heuristic
that gives directional signal without needing an LLM call. Can be upgraded later.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .trade_journal import TradeJournal, get_journal

# Analyst report fields on each decision row
_ANALYST_FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "macro": "macro_report",
}

# Keyword banks — counted case-insensitively with word-boundary regex
_BULLISH_KEYWORDS = (
    "bullish", "buy", "long", "strong buy", "overweight", "outperform",
    "accumulate", "upside", "positive", "strong", "growth", "breakout",
    "uptrend", "rally", "momentum",
)
_BEARISH_KEYWORDS = (
    "bearish", "sell", "short", "strong sell", "underweight", "underperform",
    "distribute", "downside", "negative", "weak", "decline", "breakdown",
    "downtrend", "crash", "drop",
)

# Normalized signal → direction, for correlation with sentiment
_BUY_SIGNALS = {"BUY", "LONG"}
_SELL_SIGNALS = {"SELL", "SHORT"}
_NEUTRAL_SIGNALS = {"HOLD", "NEUTRAL"}


# ─── Sentiment extraction ───────────────────────────────────────────────


def _count_keywords(text: str, keywords: tuple[str, ...]) -> int:
    """Case-insensitive word-boundary count of any keyword occurrence."""
    if not text:
        return 0
    pattern = r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


def extract_analyst_sentiment(report_text: str | None) -> str:
    """Classify a report as 'bullish', 'bearish', or 'neutral'.

    Uses keyword counts; ties / empty text → 'neutral'. Margin threshold of 1
    prevents a single mention from flipping the classification.
    """
    if not report_text:
        return "neutral"
    bullish = _count_keywords(report_text, _BULLISH_KEYWORDS)
    bearish = _count_keywords(report_text, _BEARISH_KEYWORDS)
    if bullish - bearish >= 2:
        return "bullish"
    if bearish - bullish >= 2:
        return "bearish"
    return "neutral"


def _sentiment_matches_signal(sentiment: str, signal: str | None) -> bool | None:
    """True if sentiment aligns with signal direction. None if unclear."""
    if not signal:
        return None
    sig = signal.upper().strip()
    if sig in _BUY_SIGNALS:
        if sentiment == "bullish":
            return True
        if sentiment == "bearish":
            return False
        return None
    if sig in _SELL_SIGNALS:
        if sentiment == "bearish":
            return True
        if sentiment == "bullish":
            return False
        return None
    # Neutral signal — no clear direction to check
    return None


# ─── Analyst effectiveness ──────────────────────────────────────────────


def calculate_analyst_effectiveness(
    journal: TradeJournal | None = None,
) -> dict[str, dict[str, Any]]:
    """For each analyst, count times they aligned with the final signal,
    and cross-reference with trade outcomes (if available).

    Returns {
        analyst: {
            "total_decisions": int,
            "bullish": int,
            "bearish": int,
            "neutral": int,
            "aligned_with_signal": int,     # sentiment matches direction
            "contra_signal": int,           # sentiment opposes direction
            "aligned_with_winner": int,     # aligned + outcome positive
            "aligned_with_loser": int,      # aligned + outcome negative
            "influence_score": float | None,  # % of aligned+win out of aligned+outcome
        }
    }
    """
    j = journal or get_journal()
    # Exclude backfilled decisions — they have no agent reports, which would
    # skew the radar toward "all neutral".
    decisions = j.get_decisions_with_outcomes(exclude_source="backfill", limit=5000)

    stats: dict[str, dict[str, Any]] = {
        name: {
            "total_decisions": 0,
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "aligned_with_signal": 0,
            "contra_signal": 0,
            "aligned_with_winner": 0,
            "aligned_with_loser": 0,
            "influence_score": None,
        }
        for name in _ANALYST_FIELDS
    }

    for d in decisions:
        signal = d.get("signal")
        outcomes = d.get("outcomes") or []
        decision_pnl = sum(o.get("pnl_dollars") or 0 for o in outcomes) if outcomes else None

        for analyst_name, field in _ANALYST_FIELDS.items():
            report = d.get(field)
            if not report:
                continue
            sentiment = extract_analyst_sentiment(report)
            s = stats[analyst_name]
            s["total_decisions"] += 1
            s[sentiment] += 1

            alignment = _sentiment_matches_signal(sentiment, signal)
            if alignment is True:
                s["aligned_with_signal"] += 1
                if decision_pnl is not None:
                    if decision_pnl > 0:
                        s["aligned_with_winner"] += 1
                    elif decision_pnl < 0:
                        s["aligned_with_loser"] += 1
            elif alignment is False:
                s["contra_signal"] += 1

    # Compute influence score: of the times this analyst aligned with the signal
    # AND we have a P&L, what % were winners?
    for name, s in stats.items():
        total_with_outcome = s["aligned_with_winner"] + s["aligned_with_loser"]
        if total_with_outcome > 0:
            s["influence_score"] = s["aligned_with_winner"] / total_with_outcome * 100
        else:
            s["influence_score"] = None

    return stats


# ─── Signal / timing patterns ───────────────────────────────────────────


def get_signal_distribution(
    journal: TradeJournal | None = None,
    *,
    ticker: str | None = None,
) -> dict[str, int]:
    """Count of decisions per signal type."""
    j = journal or get_journal()
    decisions = j.get_decisions(ticker=ticker, limit=5000)
    counter: Counter[str] = Counter()
    for d in decisions:
        sig = (d.get("signal") or "UNKNOWN").upper().strip()
        counter[sig] += 1
    return dict(counter)


def analyze_signal_patterns(
    journal: TradeJournal | None = None,
) -> dict[str, dict[str, Any]]:
    """For each (ticker, signal) pair, compute win rate and count.

    Returns {
        ticker: {
            signal: {
                "count": int,
                "outcomes_count": int,
                "win_rate": float | None,
                "total_pnl": float,
            }
        }
    }
    """
    j = journal or get_journal()
    decisions = j.get_decisions_with_outcomes(limit=5000)

    nested: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {
            "count": 0,
            "outcomes_count": 0,
            "wins": 0,
            "total_pnl": 0.0,
        })
    )

    for d in decisions:
        ticker = d.get("ticker") or "UNKNOWN"
        signal = (d.get("signal") or "UNKNOWN").upper().strip()
        bucket = nested[ticker][signal]
        bucket["count"] += 1
        for o in d.get("outcomes") or []:
            pnl = o.get("pnl_dollars") or 0
            bucket["outcomes_count"] += 1
            bucket["total_pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1

    # Finalize: compute win_rate, drop intermediate 'wins' counter
    result: dict[str, dict[str, Any]] = {}
    for ticker, signals in nested.items():
        result[ticker] = {}
        for signal, b in signals.items():
            win_rate = (b["wins"] / b["outcomes_count"] * 100
                        if b["outcomes_count"] > 0 else None)
            result[ticker][signal] = {
                "count": b["count"],
                "outcomes_count": b["outcomes_count"],
                "win_rate": win_rate,
                "total_pnl": b["total_pnl"],
            }
    return result


def analyze_time_patterns(
    journal: TradeJournal | None = None,
) -> dict[int, dict[str, Any]]:
    """Decisions grouped by hour-of-day (0-23).

    Returns { hour: { 'count': int, 'outcomes_count': int, 'win_rate': float | None } }
    """
    j = journal or get_journal()
    decisions = j.get_decisions_with_outcomes(limit=5000)

    hour_buckets: dict[int, dict[str, Any]] = {
        h: {"count": 0, "outcomes_count": 0, "wins": 0}
        for h in range(24)
    }

    for d in decisions:
        ts = d.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        h = dt.hour
        hour_buckets[h]["count"] += 1
        for o in d.get("outcomes") or []:
            pnl = o.get("pnl_dollars") or 0
            hour_buckets[h]["outcomes_count"] += 1
            if pnl > 0:
                hour_buckets[h]["wins"] += 1

    out: dict[int, dict[str, Any]] = {}
    for h, b in hour_buckets.items():
        win_rate = (b["wins"] / b["outcomes_count"] * 100
                    if b["outcomes_count"] > 0 else None)
        out[h] = {
            "count": b["count"],
            "outcomes_count": b["outcomes_count"],
            "win_rate": win_rate,
        }
    return out


def calculate_streaks(
    journal: TradeJournal | None = None,
) -> dict[str, Any]:
    """Compute the longest win/loss streaks and current streak.

    Returns {
        'longest_win': int,
        'longest_loss': int,
        'current_streak': int,       # positive for wins, negative for losses
        'streak_timeline': [+1, -1, +1, +1, -1, ...]  # oldest→newest
    }
    """
    j = journal or get_journal()
    # Exclude backfilled decisions — the "current streak" should reflect the
    # live agent's performance, not historical Alpaca fills.
    decisions = j.get_decisions_with_outcomes(exclude_source="backfill", limit=5000)

    # Sort by timestamp ascending for chronological streaks
    dated = [d for d in decisions if d.get("timestamp")]
    dated.sort(key=lambda d: d["timestamp"])

    timeline: list[int] = []
    for d in dated:
        for o in d.get("outcomes") or []:
            pnl = o.get("pnl_dollars") or 0
            if pnl > 0:
                timeline.append(1)
            elif pnl < 0:
                timeline.append(-1)

    if not timeline:
        return {
            "longest_win": 0,
            "longest_loss": 0,
            "current_streak": 0,
            "streak_timeline": [],
        }

    longest_win = 0
    longest_loss = 0
    cur_win = 0
    cur_loss = 0
    for v in timeline:
        if v > 0:
            cur_win += 1
            cur_loss = 0
            longest_win = max(longest_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            longest_loss = max(longest_loss, cur_loss)

    # Current streak sign based on the trailing run
    if timeline[-1] > 0:
        current = cur_win
    else:
        current = -cur_loss

    return {
        "longest_win": longest_win,
        "longest_loss": longest_loss,
        "current_streak": current,
        "streak_timeline": timeline,
    }
