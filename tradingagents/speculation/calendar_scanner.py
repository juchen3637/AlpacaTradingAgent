"""Upcoming corporate events calendar for the speculation engine.

Fetches the broad earnings calendar (next 14 days) and IPO calendar (next 30 days)
from Finnhub and returns a formatted text block for LLM context.
Cached for 1 hour — calendar data changes infrequently.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE: Optional[tuple[float, str]] = None
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60 * 60  # 1 hour

_EARNINGS_LOOKAHEAD_DAYS = 14
_IPO_LOOKAHEAD_DAYS = 30
_MAX_EARNINGS_PER_DAY = 25  # cap to avoid overwhelming the prompt


def _get_client():
    try:
        import finnhub
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if api_key:
            return finnhub.Client(api_key=api_key)
    except Exception as exc:
        logger.warning("Finnhub client unavailable: %s", exc)
    return None


def _earnings_section(client, today: str) -> str:
    end_date = (
        datetime.strptime(today, "%Y-%m-%d") + timedelta(days=_EARNINGS_LOOKAHEAD_DAYS)
    ).strftime("%Y-%m-%d")
    try:
        data = client.earnings_calendar(_from=today, to=end_date, symbol="")
        items = data.get("earningsCalendar") or [] if isinstance(data, dict) else []
    except Exception as exc:
        logger.warning("Finnhub earnings_calendar failed: %s", exc)
        return ""

    if not items:
        return ""

    # Group by date, sort by descending revenue estimate (largest companies first)
    by_date: dict[str, list[dict]] = {}
    for item in items:
        d = item.get("date", "")
        if d:
            by_date.setdefault(d, []).append(item)

    lines = [f"=== UPCOMING EARNINGS REPORTS (next {_EARNINGS_LOOKAHEAD_DAYS} days) ==="]
    for d in sorted(by_date.keys()):
        companies = sorted(by_date[d], key=lambda x: -(x.get("revenueEstimate") or 0))
        lines.append(f"\n{d}:")
        for c in companies[:_MAX_EARNINGS_PER_DAY]:
            sym = c.get("symbol", "")
            if not sym:
                continue
            hour = c.get("hour", "")         # "bmo" | "amc" | "dmh"
            eps_est = c.get("epsEstimate")
            rev_est = c.get("revenueEstimate")
            parts = [f"  {sym}"]
            if hour in ("bmo", "amc", "dmh"):
                label = {"bmo": "pre-market", "amc": "after-hours", "dmh": "during-hours"}.get(hour, hour)
                parts.append(f"({label})")
            if eps_est is not None:
                parts.append(f"EPS est: {eps_est}")
            if rev_est is not None:
                parts.append(f"Rev est: ${rev_est / 1e9:.1f}B")
            lines.append(" ".join(parts))

    return "\n".join(lines)


def _ipo_section(client, today: str) -> str:
    end_date = (
        datetime.strptime(today, "%Y-%m-%d") + timedelta(days=_IPO_LOOKAHEAD_DAYS)
    ).strftime("%Y-%m-%d")
    try:
        data = client.ipo_calendar(_from=today, to=end_date)
        items = data.get("ipoCalendar") or [] if isinstance(data, dict) else []
    except Exception as exc:
        logger.warning("Finnhub ipo_calendar failed: %s", exc)
        return ""

    if not items:
        return ""

    lines = [f"=== UPCOMING IPOs (next {_IPO_LOOKAHEAD_DAYS} days) ==="]
    for item in items[:20]:
        date = item.get("date", "?")
        name = item.get("name", "")
        sym = item.get("symbol", "")
        exchange = item.get("exchange", "")
        price = item.get("price", "")
        shares = item.get("numberOfShares")
        status = item.get("status", "")

        line = f"  {date}: {name}"
        if sym:
            line += f" ({sym})"
        if exchange:
            line += f" on {exchange}"
        if price:
            line += f" @ ${price}"
        if shares:
            line += f", {int(shares):,} shares"
        if status and status != "priced":
            line += f" [{status}]"
        lines.append(line)

    return "\n".join(lines)


def get_calendar_context() -> str:
    """Return upcoming earnings and IPO calendar as a formatted text block.

    Returns empty string if Finnhub key is unavailable. Cached 1 hour.
    """
    global _CACHE

    with _CACHE_LOCK:
        now = time.time()
        if _CACHE is not None:
            cached_ts, cached_text = _CACHE
            if now - cached_ts < _CACHE_TTL:
                return cached_text

        today = datetime.now().strftime("%Y-%m-%d")
        client = _get_client()

        sections: list[str] = []
        if client:
            earnings = _earnings_section(client, today)
            if earnings:
                sections.append(earnings)
            ipos = _ipo_section(client, today)
            if ipos:
                sections.append(ipos)

        result = "\n\n".join(sections)
        _CACHE = (now, result)
        logger.info("Calendar context: %d chars", len(result))
        return result
