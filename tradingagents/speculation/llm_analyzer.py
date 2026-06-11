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
You are a professional stock market analyst specializing in event-driven and catalyst-driven trading.
Given recent news headlines, current market context (macro, sector performance), and an upcoming
corporate events calendar (earnings, IPOs), identify specific US-listed stocks likely to move.

Rules — News & Macro:
- Only name real, currently-traded US stock tickers
- Focus on direct cause-effect: coal mine explosion → coal producers rally
- Weight signals against the current macro regime: elevated CPI = rate-sensitive headwinds;
  AI/tech dominant = catalyst plays in that sector carry higher follow-through probability
- Account for sector momentum: bullish catalyst in a hot sector carries more conviction
- Include both bullish AND bearish plays where applicable
- Do not repeat the same ticker more than once
- Skip generic ETFs — name individual stocks
- Confidence: high = direct causal link aligned with macro/sector tailwind;
  medium = probable but macro is neutral; low = speculative or macro headwind

Rules — Upcoming Earnings:
- Stocks typically drift toward consensus expectations (implied move) in the 3-7 days before
  earnings; identify pre-earnings positioning plays where the macro/sector backdrop supports
  the direction
- Consider SECTOR SYMPATHY: when a large-cap reports (e.g. NVDA), peers in the same supply
  chain or sector (AMD, AVGO, INTC) will gap sympathetically — especially if guidance mentions
  industry demand or pricing
- If a stock recently had a positive catalyst AND is reporting soon, the pre-earnings drift is
  more reliable; if the sector is under distribution, fade the move post-earnings
- "bmo" = before market open (you know before the day starts); "amc" = after hours

Rules — Upcoming IPOs:
- A major IPO in a sector can act as a sentiment barometer: an oversubscribed AI IPO lifts
  the sector; a weak/pulled IPO signals risk-off in that sector
- Identify existing publicly-traded comps that will move on IPO performance
- Lock-up expiration for recent IPOs (typically 180 days post-IPO) is a supply overhang;
  if a recent IPO lock-up is expiring soon, it's a bearish signal for that stock and sometimes
  its closest competitors
- Consider whether the IPO takes capital from existing sector comps (rotation risk)

Due Diligence:
- Cross-reference: if a company has earnings next week AND a bullish news catalyst today,
  that's a higher-conviction play than news alone
- Be skeptical of plays where the catalyst is stale (> 3 days old) unless the market hasn't
  priced it yet
- Flag if a play is ONLY justified by calendar timing (no news confirmation) — set confidence
  to 'low' in that case
"""


def _build_prompt(
    events: list[SpeculationEvent],
    market_context: str = "",
    calendar_context: str = "",
) -> str:
    lines = []

    if market_context:
        lines.append("=== CURRENT MARKET CONTEXT ===")
        lines.append(market_context)
        lines.append("")

    if calendar_context:
        lines.append("=== UPCOMING CORPORATE EVENTS CALENDAR ===")
        lines.append(calendar_context)
        lines.append("")

    lines.append("=== RECENT NEWS HEADLINES ===")
    lines.append("Analyze these for stock market impact, weighted against the context above:\n")
    for i, ev in enumerate(events[:_MAX_EVENTS_IN_PROMPT], 1):
        lines.append(f"{i}. [{ev.source}] {ev.headline}")
        if ev.snippet:
            lines.append(f"   {ev.snippet[:200]}")
    lines.append(
        f"\nIdentify up to {_MAX_PLAYS} specific US stocks that will move due to these events, "
        "the upcoming earnings/IPO calendar, and the macro context above. "
        "Include pre-earnings positioning plays and IPO sector-comp moves where conviction is high."
    )
    return "\n".join(lines)


def analyze(
    events: list[SpeculationEvent],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    market_context: str = "",
    calendar_context: str = "",
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

    prompt = _build_prompt(events, market_context=market_context, calendar_context=calendar_context)

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
