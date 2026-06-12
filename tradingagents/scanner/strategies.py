"""Rule-based strategy matcher.

Given a fully-enriched TickerSnapshot, return the single best-fit strategy
id from the seven in `constants.STRATEGY_NAMES`, or None if nothing matches.
Order matters: most specific / highest-conviction conditions are checked first.
"""

from __future__ import annotations

from typing import Optional

from .constants import (
    ATH_BREAKOUT,
    BREAKDOWN,
    LOW_FLOAT_HVD,
    LOW_FLOAT_L2,
    ORB,
    PDH_REJECTION,
    SMA10_MACD,
    SPY_0DTE_FADE,
    STRATEGY_NAMES,
    VWAP_FADE,
    VWAP_RECLAIM,
)
from .models import TickerSnapshot


def _near_ath(snap: TickerSnapshot, pct: float = 1.0) -> bool:
    ath = snap.levels.ath or snap.levels.wk52_high
    if ath is None or ath <= 0:
        return False
    return abs((ath - snap.last_price) / ath) * 100 <= pct


def _near_level(price: float, level: Optional[float], pct: float = 0.3) -> bool:
    if level is None or level <= 0:
        return False
    return abs((price - level) / level) * 100 <= pct


def match_strategy(snap: TickerSnapshot) -> Optional[str]:
    price = snap.last_price
    lv = snap.levels

    # SPY/QQQ-only: PDH/PDL fade (highest specificity)
    if snap.symbol.upper() in {"SPY", "QQQ"}:
        if _near_level(price, lv.pdh) or _near_level(price, lv.pdl):
            return SPY_0DTE_FADE

    # ATH breakout: near ATH + strong RVOL + above VWAP
    if (
        _near_ath(snap, 1.0)
        and snap.rvol is not None
        and snap.rvol > 2.0
        and lv.vwap is not None
        and price > lv.vwap
    ):
        return ATH_BREAKOUT

    # Low-float highest-volume day
    if (
        snap.float_shares is not None
        and snap.float_shares < 20_000_000
        and snap.today_volume is not None
        and snap.prior_30d_max_volume is not None
        and snap.today_volume > snap.prior_30d_max_volume
    ):
        return LOW_FLOAT_HVD

    # Low-float L2 momentum (price band + RVOL)
    if (
        snap.float_shares is not None
        and snap.float_shares < 20_000_000
        and 0.75 <= price <= 10.0
        and snap.rvol is not None
        and snap.rvol > 5.0
    ):
        return LOW_FLOAT_L2

    # VWAP reclaim (boolean computed upstream)
    if snap.vwap_reclaim:
        return VWAP_RECLAIM

    # Opening Range Breakout (first 30 min after open)
    if (
        snap.minutes_since_open is not None
        and 0 < snap.minutes_since_open <= 30
        and snap.opening_range_high is not None
        and price > snap.opening_range_high
    ):
        return ORB

    # 10-SMA + MACD trend continuation
    if snap.above_sma10 and snap.macd_signal_cross:
        return SMA10_MACD

    # ── Short strategies ──────────────────────────────────────────────

    # PDH rejection: price near PDH but trending down (negative change)
    if (
        _near_level(price, lv.pdh, pct=0.5)
        and snap.change_pct < -1.0
        and snap.rvol is not None
        and snap.rvol > 1.5
    ):
        return PDH_REJECTION

    # VWAP fade: price crossed back below VWAP after being above it
    if snap.vwap_rejection and snap.rvol is not None and snap.rvol > 1.5:
        return VWAP_FADE

    # PDL breakdown: price near or below PDL with volume confirmation
    if (
        lv.pdl is not None
        and price <= lv.pdl * 1.003
        and snap.change_pct < -2.0
        and snap.rvol is not None
        and snap.rvol > 2.0
    ):
        return BREAKDOWN

    return None


def get_strategy_name(strategy_id: str) -> str:
    return STRATEGY_NAMES.get(strategy_id, strategy_id)
