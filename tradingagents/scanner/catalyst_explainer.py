"""LLM-backed catalyst narrative synthesis with web search.

Given a `CatalystFacts` object (the structured signal detected from Finnhub),
ask the user-selected LLM provider to explain *why* the stock is moving,
using its native web-search tool. Returns a markdown narrative string.

Provider tools used:
  - OpenAI: `web_search_preview` via the Responses API.
  - Anthropic: `web_search_20250305` via the Messages API.

On any failure, returns an empty string so the UI can degrade gracefully to
the structured Finnhub card alone.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from tradingagents.dataflows.cache_utils import with_cache
from tradingagents.default_config import DEFAULT_CONFIG

from .models import CatalystFacts

logger = logging.getLogger(__name__)

# Anthropic's web_search tool returns the best citation-rich narratives for
# this use case, so the explainer is pinned to Sonnet regardless of the LLM
# the user selected for playbook generation.
EXPLAINER_PROVIDER = "anthropic"
EXPLAINER_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are an equity research assistant. Given a stock ticker and a structured "
    "catalyst signal (earnings, M&A, FDA, management change, insider activity, "
    "filing, corporate action, or news), use web search to find credible recent "
    "sources and explain in ≤250 words: (1) what the catalyst is, (2) whether "
    "it is *favorable or unfavorable* for the stock and why, and (3) what it "
    "implies about the company's outlook. End with one short line "
    "`Verdict: bullish | bearish | mixed`. "
    "Format as concise markdown. Cite sources inline as [domain](url) links. "
    "If web search returns no credible source, say so explicitly — do not invent. "
    "Skip preamble; lead with the conclusion."
)


def _build_user_prompt(symbol: str, facts: CatalystFacts) -> str:
    """Assemble the user prompt from structured facts."""
    lines = [
        f"Ticker: {symbol}",
        f"Catalyst category: {facts.category}",
        f"Signal: {facts.short_text or '(none)'}",
        "",
        "Structured details from market data provider:",
        facts.structured_md or "(none)",
        "",
        "Source items (raw):",
    ]
    for item in facts.raw_items[:5]:
        head = item.get("headline") or item.get("description") or ""
        url = item.get("url") or item.get("reportUrl") or ""
        if url:
            lines.append(f"- {head} ({url})")
        else:
            lines.append(f"- {head}")
    lines.extend([
        "",
        "Explain in ≤250 words: what is the catalyst, is it favorable or "
        "unfavorable for the stock, and what does it imply about the company's "
        "outlook? Use web search to confirm and add context (price action, "
        "sector reaction). Finish with `Verdict: bullish | bearish | mixed`.",
    ])
    return "\n".join(lines)


def _get_explainer_llm(provider: str, model: str):
    """Construct an LLM with the appropriate web-search tool bound."""
    provider = (provider or "openai").lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY") or DEFAULT_CONFIG.get("anthropic_api_key")
        ac_kwargs = {"model": model, "api_key": api_key, "timeout": 60}
        if "claude-opus-4" not in model:
            ac_kwargs["temperature"] = 0.3
        llm = ChatAnthropic(**ac_kwargs)
        return llm.bind_tools([{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        }])

    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or DEFAULT_CONFIG.get("openai_api_key")
    no_temp = ("o3", "o4-mini", "gpt-5", "gpt-5-mini", "gpt-5-nano")
    kwargs = {"model": model, "openai_api_key": api_key, "timeout": 60,
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


@with_cache(cache_category="catalyst_explain", max_age_hours=1)
def _explain_cached(symbol: str, category: str, provider: str, model: str,
                    cache_key: str, prompt: str) -> str:
    """Cached LLM call. `cache_key` participates in the cache hash."""
    del cache_key  # purely for cache invalidation
    try:
        llm = _get_explainer_llm(provider=provider, model=model)
        msg = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        text = _extract_text(getattr(msg, "content", msg))
        return text.strip()
    except Exception as exc:
        logger.warning("catalyst explainer failed for %s (%s): %s", symbol, provider, exc)
        return ""


def explain_catalyst(
    symbol: str,
    facts: CatalystFacts,
    provider: str = EXPLAINER_PROVIDER,
    model: str = EXPLAINER_MODEL,
    cache_key: Optional[str] = None,
) -> str:
    """Generate a markdown narrative explaining the catalyst.

    `provider`/`model` default to Anthropic Sonnet (best web-search citations).
    Tests can override; the UI callback uses the defaults.
    Returns empty string if there is no catalyst or on any error.
    """
    if not facts.has_catalyst:
        return ""
    prompt = _build_user_prompt(symbol, facts)
    if cache_key is None:
        # Hour-bucketed key so identical requests within 1h hit cache.
        from datetime import datetime, timezone
        cache_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    return _explain_cached(symbol, facts.category or "", provider,
                           model, cache_key, prompt)
