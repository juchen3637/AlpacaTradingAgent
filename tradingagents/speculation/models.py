"""Data models for the speculation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SpeculationEvent:
    headline: str
    source: str
    published_at: str  # raw date string from news source
    snippet: str


@dataclass(frozen=True)
class SpeculativePlay:
    event: SpeculationEvent
    ticker: str
    company_name: str
    sector: str
    direction: Literal["bullish", "bearish"]
    confidence: Literal["low", "medium", "high"]
    reasoning: str
    catalyst_type: str  # e.g. "supply shock", "demand surge", "macro", "sentiment"
