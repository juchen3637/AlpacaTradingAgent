"""Day-trade scanner deep-dive synthesis with web search.

Given a `ScanResult` (the qualifying ticker + matched intraday strategy
+ composite score), ask a web-search-bound LLM to produce a structured
markdown report covering:

  1. Why this strategy fits this ticker (interpret the signals that
     drove the match — RVOL, ATH proximity, VWAP reclaim, catalyst…)
  2. Today's setup (catalyst category, price action, key levels)
  3. What the bulls are saying (last 24–72h sources)
  4. What the bears are saying (counter-narrative, risk factors)
  5. Risk factors specific to a day-trade (gap-fill risk, low float,
     halts, post-catalyst fade)

This is the day-trade companion to `longterm_deep_dive.py`. Same shape,
same Anthropic Sonnet web-search default, but the prompt is tuned for
intraday context instead of multi-year fundamentals.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from tradingagents.dataflows.cache_utils import with_cache
from tradingagents.default_config import DEFAULT_CONFIG

from .models import ScanResult, TickerSnapshot

logger = logging.getLogger(__name__)

DEEP_DIVE_PROVIDER = "anthropic"
DEEP_DIVE_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are an intraday equity research analyst writing a deep-dive memo "
    "for a day trader who has shortlisted this ticker. The user has already "
    "matched it to a specific intraday strategy — your job is to explain "
    "WHY that strategy fits this ticker RIGHT NOW, what's driving the move, "
    "and what would invalidate the trade.\n\n"
    "Use web search to surface concrete recent developments (last 72 hours): "
    "earnings, M&A, FDA, management changes, sector reaction, social-media "
    "chatter. Cite credible sources inline as [domain](url).\n\n"
    "OUTPUT FORMAT — strict markdown with these exact section headers:\n"
    "## Why this strategy fits\n"
    "## Today's setup\n"
    "## Bull case (last 72h)\n"
    "## Bear case (last 72h)\n"
    "## Day-trade risks\n\n"
    "Each section: 2–4 sentences or a tight bullet list. Plain English, "
    "no jargon, no boilerplate disclaimers. Lead with the conclusion. "
    "If web search returns nothing for the bull/bear sections, say so "
    "explicitly — do not invent."
)


def _fmt(v: Optional[float], suffix: str = "") -> str:
    return "n/a" if v is None else f"{v:,.2f}{suffix}"


def _fmt_int(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{int(v):,}"


def _signal_summary(snap: TickerSnapshot) -> str:
    """Render the intraday signal flags so the LLM can interpret which
    technical conditions actually fired (vs. guessing from raw numbers)."""
    lines = []
    if snap.rvol is not None:
        elevated = snap.rvol >= 2.0
        lines.append(f"  - RVOL: {snap.rvol:.2f} "
                     f"({'elevated' if elevated else 'normal'})")
    if snap.above_sma10:
        lines.append("  - Trading above 10-SMA (uptrend bias)")
    if snap.macd_signal_cross:
        lines.append("  - MACD bullish cross today")
    if snap.vwap_reclaim:
        lines.append("  - Price reclaimed VWAP (intraday strength)")
    if snap.has_catalyst and snap.catalyst_category:
        lines.append(f"  - Catalyst category: {snap.catalyst_category}")
        if snap.catalyst_text:
            lines.append(f"    Headline: {snap.catalyst_text}")
    lev = snap.levels
    if any(v is not None for v in (lev.pdh, lev.pdl, lev.vwap, lev.ath)):
        lines.append("  - Key levels:")
        if lev.pdh is not None:
            lines.append(f"      PDH ${_fmt(lev.pdh)}")
        if lev.pdl is not None:
            lines.append(f"      PDL ${_fmt(lev.pdl)}")
        if lev.vwap is not None:
            lines.append(f"      VWAP ${_fmt(lev.vwap)}")
        if lev.ath is not None:
            lines.append(f"      ATH ${_fmt(lev.ath)}")
    return "\n".join(lines) if lines else "  (no flagged signals)"


def _build_user_prompt(scan_result: ScanResult) -> str:
    snap = scan_result.snapshot
    lines = [
        f"Symbol: {snap.symbol}",
        f"Asset class: {'crypto' if snap.is_crypto else 'stock'}",
        f"Last price: ${_fmt(snap.last_price)}",
        f"Change today: {_fmt(snap.change_pct, '%')}",
        f"Today's volume: {_fmt_int(snap.today_volume)}",
        f"Float: {_fmt_int(snap.float_shares)}",
        "",
        f"MATCHED STRATEGY: {scan_result.strategy_name} "
        f"(id={scan_result.strategy_id})",
        f"Composite score (0..1, higher=better): {scan_result.score:.3f}",
        "",
        "INTRADAY SIGNALS (interpret these in 'Why this strategy fits'):",
        _signal_summary(snap),
        "",
    ]
    if snap.catalyst_details:
        lines.extend([
            "CATALYST DETAILS (from market data provider):",
            snap.catalyst_details,
            "",
        ])
    raw = list(snap.catalyst_raw or ())
    if raw:
        lines.append("Source items (raw):")
        for item in raw[:5]:
            head = item.get("headline") or item.get("description") or ""
            url = item.get("url") or item.get("reportUrl") or ""
            lines.append(f"  - {head} ({url})" if url else f"  - {head}")
        lines.append("")
    lines.append(
        "Now write the deep-dive memo. Use web search to surface "
        "credible last-72h coverage. Cite sources inline."
    )
    return "\n".join(lines)


def _get_deep_dive_llm(provider: str, model: str):
    """LLM with the appropriate web-search tool bound."""
    provider = (provider or "anthropic").lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY") or DEFAULT_CONFIG.get("anthropic_api_key")
        llm = ChatAnthropic(model=model, api_key=api_key, temperature=0.3, timeout=90)
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


@with_cache(cache_category="scanner_deep_dive", max_age_hours=1)
def _deep_dive_cached(symbol: str, strategy_id: str, provider: str,
                      model: str, cache_key: str, prompt: str) -> str:
    """Cached LLM call. Day-trade context goes stale fast — 1h bucket.
    `cache_key` participates in the cache hash."""
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
        logger.warning("scanner deep-dive failed for %s/%s (%s): %s",
                       symbol, strategy_id, provider, exc)
        return ""


def generate_deep_dive(
    scan_result: ScanResult,
    provider: str = DEEP_DIVE_PROVIDER,
    model: str = DEEP_DIVE_MODEL,
    cache_key: Optional[str] = None,
) -> str:
    """Generate a day-trade deep-dive markdown memo for one candidate.

    Returns markdown on success, or an empty string on failure (UI degrades
    gracefully). Cached for 1h on (symbol, strategy_id, provider, model,
    hour-bucket) — short window because intraday context moves fast.
    """
    if not scan_result or not scan_result.snapshot or not scan_result.snapshot.symbol:
        return ""
    symbol = scan_result.snapshot.symbol
    prompt = _build_user_prompt(scan_result)
    if cache_key is None:
        # Hour bucket — intraday news churns by the hour.
        cache_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    return _deep_dive_cached(symbol, scan_result.strategy_id, provider,
                             model, cache_key, prompt)
