"""Broad market news scanner for the speculation engine.

Fetches macro/world news using Google News and Finnhub general news.
Results are cached for 30 minutes — news is time-sensitive but not tick-level.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from .models import SpeculationEvent

logger = logging.getLogger(__name__)

_CACHE: Optional[tuple[float, list[SpeculationEvent]]] = None
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 30 * 60  # 30 minutes

_MACRO_QUERIES = [
    # Hard catalysts
    "major accident explosion disaster",
    "supply disruption shortage commodity",
    "IPO announcement merger acquisition",
    "trade war tariff sanctions",
    "natural disaster earthquake hurricane",
    "geopolitical conflict tension war",
    "central bank rate decision Fed",
    "drug approval FDA breakthrough",
    "tech layoffs bankruptcy earnings surprise",
    "energy oil gas pipeline disruption",
    # Macro data releases
    "CPI inflation consumer price index report",
    "PPI producer price index",
    "Federal Reserve interest rates inflation",
    "jobs report unemployment nonfarm payrolls",
    "GDP economic growth recession",
    # Sector trends
    "artificial intelligence AI stocks chips semiconductor",
    "software cloud earnings revenue guidance",
    "AI infrastructure data center hyperscaler",
    "technology sector rotation momentum",
    "biotech pharma clinical trial FDA",
]

# Module-level lazy Finnhub client (not cached on failure — recreated each call
# so a transient import/network error doesn't disable Finnhub for the session).
_finnhub_client_lock = threading.Lock()


def _get_finnhub_client():
    with _finnhub_client_lock:
        try:
            import finnhub
            api_key = os.environ.get("FINNHUB_API_KEY", "")
            if not api_key:
                return None
            return finnhub.Client(api_key=api_key)
        except Exception as exc:
            logger.warning("Could not create Finnhub client: %s", exc)
            return None


def _fetch_google_news(today: str) -> list[SpeculationEvent]:
    events: list[SpeculationEvent] = []
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d")

    for query in _MACRO_QUERIES:
        try:
            from tradingagents.dataflows.googlenews_utils import getNewsData
            results = getNewsData(query, yesterday, today, max_pages=1)
            for r in results[:3]:  # cap per query to avoid rate limits
                events.append(SpeculationEvent(
                    headline=r.get("title", ""),
                    source=r.get("source", "Google News"),
                    published_at=r.get("date", ""),
                    snippet=r.get("snippet", ""),
                ))
        except Exception as exc:
            logger.warning("Google News fetch failed for query '%s': %s", query, exc)

    return events


def _fetch_finnhub_general_news() -> list[SpeculationEvent]:
    events: list[SpeculationEvent] = []
    client = _get_finnhub_client()
    if client is None:
        return events
    try:
        items = client.general_news("general", min_id=0) or []
        for item in items[:20]:
            events.append(SpeculationEvent(
                headline=item.get("headline", ""),
                source=item.get("source", "Finnhub"),
                published_at=str(item.get("datetime", "")),
                snippet=item.get("summary", "")[:300],
            ))
    except Exception as exc:
        logger.warning("Finnhub general news failed: %s", exc)
    return events


def _deduplicate(events: list[SpeculationEvent]) -> list[SpeculationEvent]:
    seen: set[str] = set()
    out: list[SpeculationEvent] = []
    for ev in events:
        key = ev.headline[:60].lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ev)
    return out


def fetch_events(today: Optional[str] = None) -> list[SpeculationEvent]:
    """Fetch broad market news events. Returns cached results within TTL."""
    global _CACHE

    with _CACHE_LOCK:
        now = time.time()
        if _CACHE is not None:
            cached_ts, cached_events = _CACHE
            if now - cached_ts < _CACHE_TTL:
                logger.debug("Speculation news: returning %d cached events", len(cached_events))
                return cached_events

        if today is None:
            today = datetime.now().strftime("%Y-%m-%d")

        logger.info("Speculation news: fetching fresh events for %s", today)
        raw: list[SpeculationEvent] = []
        raw.extend(_fetch_google_news(today))
        raw.extend(_fetch_finnhub_general_news())

        events = _deduplicate(raw)
        events = [e for e in events if e.headline.strip()]

        _CACHE = (now, events)
        logger.info("Speculation news: fetched %d events total", len(events))
        return events
