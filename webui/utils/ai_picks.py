"""AI Picked Stocks — speculation-driven ticker discovery for analysis runs.

Mirrors the _SpeculationState pattern from speculation_state.py. Discovery is
gated to hours 9, 12, 15 EST in market-hour mode; other hourly runs reuse the
cached tickers.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tradingagents.speculation.models import SpeculativePlay

logger = logging.getLogger(__name__)

_DISCOVERY_HOURS = frozenset({9, 12, 15})
_MAX_TOTAL_TICKERS = 25
_MAX_AI_PICKS = 10
_ALLOWED_CONFIDENCE = frozenset({"high", "medium"})


def _is_tradeable(ticker: str) -> bool:
    """Return True only if Alpaca knows this ticker as an active, tradeable asset."""
    try:
        from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client
        client = get_alpaca_trading_client()
        asset = client.get_asset(ticker)
        return bool(asset and getattr(asset, "tradable", False) and getattr(asset, "status", "") == "active")
    except Exception:
        return False


def merge_tickers(
    manual: list[str], ai: list[str], max_total: int = _MAX_TOTAL_TICKERS
) -> list[str]:
    """Merge manual + AI tickers, deduped, manual first, capped at max_total."""
    seen: set[str] = set()
    merged: list[str] = []
    for ticker in list(manual) + list(ai):
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        merged.append(ticker)
        if len(merged) >= max_total:
            break
    return merged


def discover_ai_tickers(
    provider: Optional[str],
    model: Optional[str],
    manual_tickers: list[str],
    max_picks: int = _MAX_AI_PICKS,
) -> tuple[list[str], list[str], list[SpeculativePlay]]:
    """Run the speculation engine and return (merged_symbols, ai_only_symbols, plays).

    The third element is the list of SpeculativePlay objects for all AI-only
    tickers that made it into the merged list, preserving the original play data
    so callers can push rich results to the Speculation tab.

    Falls back to (manual_tickers, [], []) on any engine failure so analysis
    always proceeds.
    """
    from tradingagents.speculation.engine import SpeculationEngine

    try:
        plays = SpeculationEngine().run(provider=provider, model=model)
    except Exception as exc:
        logger.warning("Speculation discovery failed: %s", exc)
        return list(manual_tickers), [], []

    manual_set = {t.upper() for t in manual_tickers}
    ai_only: list[str] = []
    ai_plays: list = []
    for play in plays:
        ticker = play.ticker.upper()
        if play.confidence not in _ALLOWED_CONFIDENCE:
            continue
        if "/" in ticker or ticker in manual_set or ticker in ai_only:
            continue
        if not _is_tradeable(ticker):
            logger.info("Skipping %s — not an active tradeable asset on Alpaca", ticker)
            continue
        ai_only.append(ticker)
        ai_plays.append(play)
        if len(ai_only) >= max_picks:
            break

    merged = merge_tickers(list(manual_tickers), ai_only)
    # Keep only plays for tickers that survived the merge cap
    merged_set = set(merged)
    ai_only = [t for t in ai_only if t in merged_set]
    ai_plays = [p for p in ai_plays if p.ticker.upper() in merged_set]
    return merged, ai_only, ai_plays


def publish_plays_to_speculation_state(plays: list[SpeculativePlay], source: str) -> None:
    """Push SpeculativePlay objects to SPECULATION_STATE for UI display.

    Uses the atomic set_plays_and_stop_scanning so the polling callback
    cannot observe a state where plays are set but scanning is still True.
    """
    from webui.utils.speculation_state import SPECULATION_STATE
    SPECULATION_STATE.set_plays_and_stop_scanning(plays, source=source)


class _AIPicksState:
    """Thread-safe cache of AI-discovered tickers shared across loop iterations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickers: list[str] = []
        self._last_hour: Optional[int] = None
        self._last_date: Optional[str] = None

    def set_tickers(self, tickers: list[str], hour: int, date: str) -> None:
        with self._lock:
            self._tickers = list(tickers)
            self._last_hour = hour
            self._last_date = date

    def get_tickers(self) -> list[str]:
        with self._lock:
            return list(self._tickers)

    def should_rediscover(self, now: datetime) -> bool:
        """True when discovery should run: never ran before, or a 9/12/15 EST
        slot we haven't covered yet (same-day different slot, or a new day)."""
        with self._lock:
            if self._last_date is None:
                return True
            if now.hour not in _DISCOVERY_HOURS:
                return False
            if self._last_date != now.date().isoformat():
                return True
            return now.hour != self._last_hour

    def reset(self) -> None:
        with self._lock:
            self._tickers = []
            self._last_hour = None
            self._last_date = None


AI_PICKS_STATE = _AIPicksState()
