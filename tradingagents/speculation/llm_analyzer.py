"""LLM-backed analyzer: converts news events into speculative plays.

Uses the same _llm_factory pattern as playbook_llm.py for provider-agnostic
structured output. Falls back to empty list on any LLM/schema failure.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field
from typing import Literal

from .models import SpeculationEvent, SpeculativePlay

logger = logging.getLogger(__name__)

_MAX_PLAYS = 15
_MAX_EVENTS_IN_PROMPT = 15


class _PlaySchema(BaseModel):
    ticker: str = Field(description="US stock ticker symbol, e.g. 'ARCH', 'BWXT'")
    company_name: str = Field(description="Full company name")
    sector: str = Field(description="Sector, e.g. 'Energy', 'Defense', 'Biotech'")
    direction: Literal["bullish", "bearish"] = Field(description="'bullish' or 'bearish'")
    confidence: Literal["low", "medium", "high"] = Field(description="'low', 'medium', or 'high'")
    reasoning: str = Field(description="≤80 words. Why this event moves this stock.")
    catalyst_type: str = Field(
        description=(
            "One of: 'supply shock', 'demand surge', 'demand decline', "
            "'macro', 'sentiment', 'regulatory', 'M&A', 'earnings'"
        )
    )
    event_headline: str = Field(description="The headline of the triggering news event")


class _AnalysisSchema(BaseModel):
    plays: list[_PlaySchema] = Field(
        description=f"Up to {_MAX_PLAYS} speculative stock plays derived from the news events"
    )


_SYSTEM_PROMPT = """\
You are a professional stock market analyst specializing in event-driven trading.
Given a list of recent news headlines and snippets, identify specific US-listed stocks
that are likely to move significantly up or down as a direct result of those events.

Rules:
- Only name real, currently-traded US stock tickers
- Focus on direct cause-effect: e.g. coal mine explosion → coal producers rally
- Prefer names with clear supply/demand impact over vague macro plays
- Include both bullish AND bearish plays where applicable
- Do not repeat the same ticker more than once
- Skip generic ETFs — name individual stocks
- Confidence: high = very direct causal link; medium = probable; low = speculative
"""


def _build_prompt(events: list[SpeculationEvent]) -> str:
    lines = ["Recent news headlines (analyze for stock market impact):\n"]
    for i, ev in enumerate(events[:_MAX_EVENTS_IN_PROMPT], 1):
        lines.append(f"{i}. [{ev.source}] {ev.headline}")
        if ev.snippet:
            lines.append(f"   {ev.snippet[:200]}")
    lines.append(
        f"\nIdentify up to {_MAX_PLAYS} specific US stocks that will move due to these events. "
        "Today's date context: consider what is most recent and impactful."
    )
    return "\n".join(lines)


def analyze(
    events: list[SpeculationEvent],
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> list[SpeculativePlay]:
    """Run LLM analysis on news events and return speculative plays."""
    if not events:
        return []

    try:
        from tradingagents.scanner._llm_factory import get_llm
        llm = get_llm(provider=provider, model=model)
        structured_llm = llm.with_structured_output(_AnalysisSchema)
    except Exception as exc:
        logger.warning("LLM factory failed: %s", exc)
        return []

    prompt = _build_prompt(events)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        result: _AnalysisSchema = structured_llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
    except Exception as exc:
        logger.warning("LLM speculation analysis failed: %s", exc)
        return []

    plays: list[SpeculativePlay] = []
    event_map = {ev.headline: ev for ev in events}

    for p in result.plays[:_MAX_PLAYS]:
        ticker = (p.ticker or "").strip().upper()
        if not ticker or len(ticker) > 6 or not ticker.isalpha():
            continue

        # Pydantic Literal enforces valid values; these are already validated
        direction = p.direction
        confidence = p.confidence

        triggering_event = event_map.get(p.event_headline, events[0])

        plays.append(SpeculativePlay(
            event=triggering_event,
            ticker=ticker,
            company_name=p.company_name or ticker,
            sector=p.sector or "Unknown",
            direction=direction,
            confidence=confidence,
            reasoning=p.reasoning or "",
            catalyst_type=p.catalyst_type or "macro",
        ))

    return plays
