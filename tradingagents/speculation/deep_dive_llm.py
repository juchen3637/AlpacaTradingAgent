"""Speculation deep-dive: web-search LLM report for a single speculation signal.

Follows the same pattern as scanner_deep_dive.py but tuned for
event-driven speculation (macro/news catalyst) rather than intraday
technical signals. Caches for 2 hours — short enough to pick up breaking
developments, long enough to avoid hammering the search API.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from tradingagents.dataflows.cache_utils import with_cache
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

DEEP_DIVE_PROVIDER = "anthropic"
DEEP_DIVE_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are an event-driven equity research analyst writing a deep-dive report "
    "for a retail trader considering a speculation play. Your job is to explain "
    "WHY the news catalyst should move this stock, cite multiple credible recent "
    "sources, and give an honest bear case.\n\n"
    "Use web search to find the last 72 hours of coverage on this ticker and the "
    "catalyst event. Cite sources inline as [Source Name](url).\n\n"
    "OUTPUT FORMAT — strict markdown with these exact section headers:\n"
    "## Thesis\n"
    "## Supporting Evidence\n"
    "## Bull Case\n"
    "## Bear Case\n"
    "## Key Risks\n\n"
    "Each section: 3–5 sentences or a tight bullet list. Plain English, "
    "no boilerplate disclaimers. Lead with the conclusion. "
    "Cite at least 2 distinct sources across the report. "
    "If you find no relevant coverage for a section, say so explicitly — do not invent."
)


def _build_prompt(
    ticker: str,
    company_name: str,
    direction: str,
    catalyst_type: str,
    reasoning: str,
    event_headline: str,
    event_source: str,
) -> str:
    lines = [
        f"Ticker: {ticker} ({company_name})",
        f"Direction: {direction.upper()}",
        f"Catalyst type: {catalyst_type}",
        f"Triggering headline: {event_headline}",
        f"Source: {event_source}",
        "",
        "Initial analysis:",
        reasoning,
        "",
        "Search for recent news about this ticker and the catalyst event. "
        "Write the deep-dive memo with cited sources. "
        "Focus on concrete recent developments in the last 72 hours.",
    ]
    return "\n".join(lines)


def _get_deep_dive_llm(provider: str, model: str):
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


@with_cache(cache_category="spec_deep_dive", max_age_hours=2)
def _deep_dive_cached(
    ticker: str,
    direction: str,
    provider: str,
    model: str,
    cache_key: str,
    prompt: str,
) -> str:
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
        logger.warning("Speculation deep-dive failed for %s (%s): %s", ticker, provider, exc)
        return ""


def generate_deep_dive(
    ticker: str,
    company_name: str,
    direction: str,
    catalyst_type: str,
    reasoning: str,
    event_headline: str,
    event_source: str,
    provider: str = DEEP_DIVE_PROVIDER,
    model: str = DEEP_DIVE_MODEL,
    cache_key: Optional[str] = None,
) -> str:
    """Generate a deep-dive markdown report for a speculation signal.

    Returns markdown on success, empty string on failure.
    Cached for 2 hours.
    """
    if not ticker:
        return ""
    prompt = _build_prompt(
        ticker, company_name, direction, catalyst_type,
        reasoning, event_headline, event_source,
    )
    if cache_key is None:
        dt = datetime.now(timezone.utc)
        cache_key = f"{dt.strftime('%Y-%m-%d')}-{dt.hour // 2}"
    return _deep_dive_cached(ticker, direction, provider, model, cache_key, prompt)
