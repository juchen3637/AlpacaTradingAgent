"""Orchestrator for the speculation engine."""

from __future__ import annotations

import logging
from typing import Optional

from .models import SpeculativePlay
from .news_scanner import fetch_events
from .llm_analyzer import analyze
from .market_context import get_market_context
from .calendar_scanner import get_calendar_context

logger = logging.getLogger(__name__)

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


class SpeculationEngine:
    def run(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        today: Optional[str] = None,
    ) -> list[SpeculativePlay]:
        """Fetch news events, run LLM analysis, return ranked unique plays."""
        events = fetch_events(today=today)
        if not events:
            logger.info("Speculation engine: no events found")
            return []

        market_context = get_market_context()
        calendar_context = get_calendar_context()
        plays = analyze(
            events,
            provider=provider,
            model=model,
            market_context=market_context,
            calendar_context=calendar_context,
        )

        # Deduplicate by ticker — keep highest-confidence entry
        seen: dict[str, SpeculativePlay] = {}
        for play in plays:
            existing = seen.get(play.ticker)
            if existing is None or (
                _CONFIDENCE_ORDER.get(play.confidence, 99) < _CONFIDENCE_ORDER.get(existing.confidence, 99)
            ):
                seen[play.ticker] = play

        ranked = sorted(seen.values(), key=lambda p: _CONFIDENCE_ORDER.get(p.confidence, 99))
        logger.info("Speculation engine: returning %d plays", len(ranked))
        return ranked
