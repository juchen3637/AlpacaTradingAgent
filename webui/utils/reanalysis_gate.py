"""Per-ticker re-analysis gate.

The scheduler runs every market hour. For tickers we already analyzed recently
where nothing material has changed, the rerun is wasted spend. This gate blocks
re-analysis when:

  - The last successful analysis happened within ``per_ticker_cooldown_hours``
  - AND the price hasn't moved by ``min_price_move_pct_for_reanalysis`` (when
    > 0; otherwise the price-move escape is disabled)

A ticker with no prior record always runs (no first-analysis blockade).
A safe-fail policy: any ambiguity (missing price, missing config) → run.

Concurrency: the ``app_state.last_analysis_at`` and ``last_analysis_price``
dicts are touched from multiple threads (market-hour loop + parallel-batch
worker threads + Dash callbacks). Both reads and writes hold
``app_state.reanalysis_lock`` — declared in webui/utils/state.py.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Fallback lock used only by tests that pass a bare object as ``app_state``.
# Production code always provides ``app_state.reanalysis_lock``.
_FALLBACK_LOCK = threading.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@contextmanager
def _state_lock(app_state: Any):
    lock = getattr(app_state, "reanalysis_lock", None) or _FALLBACK_LOCK
    with lock:
        yield


def should_reanalyze(
    symbol: str,
    config: dict,
    app_state: Any,
    current_price: Optional[float] = None,
) -> bool:
    """Decide whether the scheduler should re-analyze ``symbol`` this cycle.

    Args:
        symbol: Ticker symbol.
        config: Project config dict; reads ``per_ticker_cooldown_hours``,
            ``min_price_move_pct_for_reanalysis``.
        app_state: Object exposing ``last_analysis_at: dict[str, datetime]``,
            ``last_analysis_price: dict[str, float]``, and
            ``reanalysis_lock: threading.Lock``.
        current_price: Latest known price. ``None`` defaults to "run" (safe-fail).

    Returns:
        True if the ticker should be re-analyzed this cycle, False to skip.
    """
    cooldown_hours = float(config.get("per_ticker_cooldown_hours", 0) or 0)
    if cooldown_hours <= 0:
        return True

    with _state_lock(app_state):
        last_at = getattr(app_state, "last_analysis_at", {}).get(symbol)
        last_price = getattr(app_state, "last_analysis_price", {}).get(symbol)

    if last_at is None:
        return True

    last_at = _ensure_utc(last_at)
    age = _now_utc() - last_at
    cooldown = timedelta(hours=cooldown_hours)
    if age >= cooldown:
        return True

    # Inside cooldown — check the price-move escape hatch.
    move_threshold = float(config.get("min_price_move_pct_for_reanalysis", 0) or 0)
    if move_threshold <= 0:
        return False  # No escape, skip.

    if current_price is None or current_price <= 0:
        # Can't measure the move → safe-fail to running.
        return True

    if not last_price or last_price <= 0:
        return True

    move_pct = abs(current_price - last_price) / last_price * 100.0
    return move_pct >= move_threshold


def record_analysis(
    symbol: str,
    app_state: Any,
    price: Optional[float] = None,
    when: Optional[datetime] = None,
) -> None:
    """Stamp the timestamp + price for ``symbol`` after a successful analysis.

    Holds ``app_state.reanalysis_lock`` while updating both dicts so
    concurrent readers see a consistent (timestamp, price) pair.
    """
    ts = _ensure_utc(when or _now_utc())
    with _state_lock(app_state):
        if not hasattr(app_state, "last_analysis_at"):
            app_state.last_analysis_at = {}
        if not hasattr(app_state, "last_analysis_price"):
            app_state.last_analysis_price = {}
        app_state.last_analysis_at[symbol] = ts
        if price is not None and price > 0:
            app_state.last_analysis_price[symbol] = float(price)
