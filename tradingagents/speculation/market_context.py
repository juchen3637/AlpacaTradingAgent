"""Live market context for the speculation engine.

Fetches macro indicators (FRED) and sector ETF performance (Alpaca) and
returns a compact text block the LLM can use to weight plays against the
current macro regime and sector rotation picture.

Cached for 1 hour — macro data doesn't change tick-by-tick but should
refresh intraday to pick up CPI/Fed releases and sector moves.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE: Optional[tuple[float, str]] = None
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60 * 60  # 1 hour

# Sector ETFs to track for rotation context
_SECTOR_ETFS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq/Tech",
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLC": "Comm Services",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Disc.",
}

# FRED series we care about for the macro regime
_FRED_SERIES = {
    "CPIAUCSL": "CPI (YoY inflation)",
    "FEDFUNDS": "Fed Funds Rate",
    "UNRATE": "Unemployment Rate",
    "T10Y2Y": "10Y-2Y Yield Spread",
}


def _fetch_sector_performance() -> str:
    """Get today's % change for key sector ETFs from Alpaca."""
    lines: list[str] = []
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        from datetime import datetime, timedelta, timezone

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=5)

        for symbol, label in _SECTOR_ETFS.items():
            try:
                df = AlpacaUtils.get_stock_data(
                    symbol, start.isoformat(), end.isoformat(), "1Day"
                )
                if df is None or df.empty or len(df) < 2:
                    continue
                prev_close = float(df["close"].iloc[-2])
                last = float(df["close"].iloc[-1])
                if prev_close <= 0:
                    continue
                chg = (last - prev_close) / prev_close * 100
                arrow = "▲" if chg >= 0 else "▼"
                lines.append(f"  {label} ({symbol}): {arrow}{abs(chg):.2f}%")
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Sector performance fetch failed: %s", exc)

    if not lines:
        return ""
    return "Sector ETF performance (today):\n" + "\n".join(lines)


def _fetch_macro_indicators() -> str:
    """Pull latest values for key FRED series."""
    lines: list[str] = []
    try:
        from tradingagents.dataflows.macro_utils import get_fred_data

        for series_id, label in _FRED_SERIES.items():
            try:
                result = get_fred_data(series_id)
                if isinstance(result, dict) and "error" not in result:
                    observations = result.get("observations", [])
                    if observations:
                        latest = observations[-1]
                        val = latest.get("value", "n/a")
                        date = latest.get("date", "")
                        lines.append(f"  {label}: {val} (as of {date})")
            except Exception:
                pass
    except Exception as exc:
        logger.debug("FRED macro fetch failed: %s", exc)

    if not lines:
        return ""
    return "Macro indicators (FRED):\n" + "\n".join(lines)


def _build_context() -> str:
    """Assemble the full market context block."""
    today = datetime.now().strftime("%B %d, %Y")
    parts: list[str] = [f"Market context as of {today}:"]

    sector_text = _fetch_sector_performance()
    if sector_text:
        parts.append(sector_text)

    macro_text = _fetch_macro_indicators()
    if macro_text:
        parts.append(macro_text)

    parts.append(
        "Structural market themes (standing):\n"
        "  - AI/software infrastructure is the dominant multi-year growth theme\n"
        "  - Large-cap tech (NVDA, MSFT, GOOGL, META) driving index performance\n"
        "  - Rate-sensitive sectors (REITs, utilities) under pressure while rates elevated\n"
        "  - Energy sector volatile on geopolitical and supply/demand swings"
    )

    return "\n\n".join(parts)


def get_market_context() -> str:
    """Return a cached market context block (refreshes every hour)."""
    global _CACHE

    with _CACHE_LOCK:
        now = time.time()
        if _CACHE is not None:
            cached_ts, cached_text = _CACHE
            if now - cached_ts < _CACHE_TTL:
                return cached_text

        logger.info("Speculation: refreshing market context")
        try:
            text = _build_context()
        except Exception as exc:
            logger.warning("Market context build failed: %s", exc)
            text = ""

        _CACHE = (now, text)
        return text
