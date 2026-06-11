"""Long-term candidate deep-dive synthesis with web search.

Given a `LongTermScanResult` (the candidate plus its composite score and
fundamentals snapshot), ask a web-search-bound LLM to produce a structured
markdown report covering:

  1. Why this candidate (interpret the score: which metrics drove it)
  2. Business overview (what the company actually does)
  3. Recent catalysts / news (last 90 days, with source citations)
  4. Competitive moat (durable advantages)
  5. Long-term risks (what would invalidate the buy-and-hold thesis)

This is the retrospective companion to `longterm_playbook_llm.py`'s
forward-looking thesis: thesis = "what to do," deep dive = "why."

Anthropic Sonnet is used for its high-quality web_search citations,
mirroring the day-trade catalyst explainer.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from tradingagents.dataflows.cache_utils import with_cache
from tradingagents.default_config import DEFAULT_CONFIG

from .longterm_models import LongTermScanResult, LongTermSnapshot
from .longterm_scoring import (
    WEIGHTS,
    normalize_debt_equity,
    normalize_div_yield,
    normalize_lt_trend,
    normalize_net_margin,
    normalize_pe_inverted,
    normalize_rev_growth,
    normalize_roe,
)

logger = logging.getLogger(__name__)

DEEP_DIVE_PROVIDER = "anthropic"
DEEP_DIVE_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are a long-term equity research analyst writing a deep-dive memo "
    "for a buy-and-hold investor (3–10 year horizon). The user has already "
    "filtered this stock into their candidate list — your job is to explain "
    "WHY it's worth owning, what's happening with it RIGHT NOW, and what "
    "would invalidate the thesis.\n\n"
    "Use web search to surface concrete recent developments (last 90 days): "
    "earnings, product launches, M&A, regulatory actions, management changes. "
    "Cite credible sources inline as [domain](url).\n\n"
    "OUTPUT FORMAT — strict markdown with these exact section headers:\n"
    "## Why this candidate\n"
    "## Business overview\n"
    "## Recent catalysts (last 90 days)\n"
    "## Competitive moat\n"
    "## Long-term risks\n\n"
    "Each section: 2–4 sentences or a tight bullet list. Plain English, "
    "no jargon, no boilerplate disclaimers. Lead with the conclusion in "
    "each section. If web search returns nothing for the catalysts section, "
    "say so explicitly — do not invent."
)


def _fmt(v: Optional[float], suffix: str = "") -> str:
    return "n/a" if v is None else f"{v:,.2f}{suffix}"


def _score_breakdown(snap: LongTermSnapshot) -> str:
    """Render each component's contribution so the LLM can interpret which
    metrics actually drove the score, instead of guessing."""
    rows = [
        ("ROE",         normalize_roe(snap.roe_ttm),                  WEIGHTS["roe"]),
        ("Net margin",  normalize_net_margin(snap.net_margin_ttm),    WEIGHTS["net_margin"]),
        ("Rev 3y CAGR", normalize_rev_growth(snap.revenue_growth_3y), WEIGHTS["rev_growth_3y"]),
        ("Forward P/E", normalize_pe_inverted(snap.pe_forward),       WEIGHTS["pe_forward"]),
        ("LT trend",    normalize_lt_trend(snap),                     WEIGHTS["lt_trend"]),
        ("Debt/Equity", normalize_debt_equity(snap.debt_to_equity),   WEIGHTS["debt_equity"]),
        ("Div yield",   normalize_div_yield(snap.dividend_yield_ttm), WEIGHTS["div_yield"]),
    ]
    lines = []
    for name, normalized, weight in rows:
        if normalized is None:
            lines.append(f"  - {name}: n/a (weight {weight:.2f}, neutral)")
        else:
            contribution = normalized * weight
            lines.append(
                f"  - {name}: norm={normalized:.2f} × weight={weight:.2f} "
                f"= {contribution:.3f}"
            )
    return "\n".join(lines)


def _build_user_prompt(scan_result: LongTermScanResult) -> str:
    snap = scan_result.snapshot
    lines = [
        f"Symbol: {snap.symbol}",
        f"Sector: {snap.sector or 'n/a'}",
        f"Industry: {snap.industry or 'n/a'}",
        f"Last price: ${_fmt(snap.last_price)}",
        f"Market cap: ${_fmt(snap.market_cap_b)}B",
        f"Composite score (0..1, higher=better): {scan_result.score:.3f}",
        "",
        "FUNDAMENTALS (TTM):",
        f"  ROE: {_fmt(snap.roe_ttm, '%')}",
        f"  Net margin: {_fmt(snap.net_margin_ttm, '%')}",
        f"  Revenue 3y CAGR: {_fmt(snap.revenue_growth_3y, '%')}",
        f"  Forward P/E: {_fmt(snap.pe_forward)}",
        f"  Debt/Equity: {_fmt(snap.debt_to_equity)}",
        f"  Dividend yield: {_fmt(snap.dividend_yield_ttm, '%')}",
        "",
        "LONG-TERM TREND:",
        f"  50-SMA: ${_fmt(snap.sma_50)}",
        f"  200-SMA: ${_fmt(snap.sma_200)}",
        f"  Price above 200-SMA: {snap.above_sma_200}",
        f"  Golden cross (50 > 200): {snap.golden_cross}",
        f"  52-week high: ${_fmt(snap.wk52_high)}",
        f"  52-week low: ${_fmt(snap.wk52_low)}",
        f"  1-year return: {_fmt(snap.one_year_return_pct, '%')}",
        "",
        "SCORE BREAKDOWN (interpret this for the user in 'Why this candidate'):",
        _score_breakdown(snap),
        "",
        "Now write the deep-dive memo. Use web search to find recent news. "
        "Cite sources inline.",
    ]
    return "\n".join(lines)


def _get_deep_dive_llm(provider: str, model: str):
    """LLM with the appropriate web-search tool bound."""
    provider = (provider or "anthropic").lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY") or DEFAULT_CONFIG.get("anthropic_api_key")
        ac_kwargs = {"model": model, "api_key": api_key, "timeout": 90}
        if "claude-opus-4" not in model:
            ac_kwargs["temperature"] = 0.3
        llm = ChatAnthropic(**ac_kwargs)
        return llm.bind_tools([{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }])

    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or DEFAULT_CONFIG.get("openai_api_key")
    no_temp = ("o3", "o4-mini", "gpt-5", "gpt-5-mini", "gpt-5-nano")
    kwargs = {"model": model, "openai_api_key": api_key, "timeout": 90,
              "use_responses_api": True}
    if not any(prefix in model for prefix in no_temp):
        kwargs["temperature"] = 0.3
    llm = ChatOpenAI(**kwargs)
    return llm.bind_tools([{"type": "web_search_preview"}])


def _extract_text(content) -> str:
    """Coerce LangChain message content (str | list[dict]) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content) if content is not None else ""


@with_cache(cache_category="longterm_deep_dive", max_age_hours=24)
def _deep_dive_cached(symbol: str, provider: str, model: str,
                      cache_key: str, prompt: str) -> str:
    """Cached LLM call. `cache_key` participates in the cache hash."""
    del cache_key
    try:
        llm = _get_deep_dive_llm(provider=provider, model=model)
        msg = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        text = _extract_text(getattr(msg, "content", msg))
        return text.strip()
    except Exception as exc:
        logger.warning("longterm deep-dive failed for %s (%s): %s",
                       symbol, provider, exc)
        return ""


def generate_deep_dive(
    scan_result: LongTermScanResult,
    provider: str = DEEP_DIVE_PROVIDER,
    model: str = DEEP_DIVE_MODEL,
    cache_key: Optional[str] = None,
) -> str:
    """Generate a long-term deep-dive markdown memo for one candidate.

    Returns markdown on success, or an empty string on failure (UI degrades
    gracefully). Cached for 24h on (symbol, provider, model, date-bucket).
    """
    if not scan_result or not scan_result.snapshot or not scan_result.snapshot.symbol:
        return ""
    symbol = scan_result.snapshot.symbol
    prompt = _build_user_prompt(scan_result)
    if cache_key is None:
        # Daily bucket — long-term context doesn't change hour-to-hour.
        cache_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _deep_dive_cached(symbol, provider, model, cache_key, prompt)
