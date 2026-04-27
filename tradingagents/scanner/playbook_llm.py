"""LLM-backed AI playbook synthesis for the scanner.

Lazy-constructs a ChatOpenAI (or Anthropic) using the project's existing
config. Uses pydantic structured output; on any schema or network failure,
falls back to a deterministic rule-based playbook built from the strategy
template in `constants.STRATEGY_RULES`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from tradingagents.default_config import DEFAULT_CONFIG

from .constants import STRATEGY_RULES
from .models import Playbook, ScanResult, TickerSnapshot

logger = logging.getLogger(__name__)


class _PlaybookSchema(BaseModel):
    """Pydantic schema the LLM must populate."""

    thesis: str = Field(description="One-paragraph rationale, ≤60 words.")
    entry_trigger: str = Field(description="Concrete price/condition for entry.")
    stop_loss: float = Field(description="Stop loss price, absolute dollars.")
    profit_target_1: float = Field(description="First profit target, absolute dollars.")
    profit_target_2: float = Field(description="Second profit target, absolute dollars.")
    risk_reward: float = Field(description="R:R ratio (target1 vs stop).")
    position_size_pct: float = Field(
        description="Suggested fraction of buying power (0–1).",
        ge=0.0, le=1.0,
    )
    indicators_to_watch: list[str] = Field(description="Key indicators / levels.")
    invalidation: str = Field(description="What makes this setup wrong.")
    confidence: str = Field(description="low | medium | high")


_SYSTEM_PROMPT = (
    "You are a day-trading playbook generator. Given a strategy template and "
    "current ticker data, output STRICT JSON matching the provided schema. "
    "No commentary. No hedging. Use the provided price levels — do not invent. "
    "Stop and targets must be absolute dollar prices consistent with the entry."
)


def _format_user_prompt(snap: TickerSnapshot, strategy_id: str) -> str:
    lv = snap.levels
    lines = [
        f"Strategy: {strategy_id}",
        f"Strategy rules: {STRATEGY_RULES.get(strategy_id, '(no template)')}",
        "",
        f"Ticker: {snap.symbol}",
        f"Asset class: {'crypto' if snap.is_crypto else 'stock'}",
        f"Last price: {snap.last_price}",
        f"Change % today: {snap.change_pct:.2f}",
        f"Premarket volume: {snap.premarket_volume}",
        f"RVOL: {snap.rvol}",
        f"Float (shares): {snap.float_shares}",
        f"Today volume: {snap.today_volume}",
        f"Prior 30d max volume: {snap.prior_30d_max_volume}",
        "Key levels:",
        f"  PDH: {lv.pdh}, PDL: {lv.pdl}",
        f"  PMH: {lv.pmh}, PML: {lv.pml}",
        f"  VWAP: {lv.vwap}",
        f"  ATH: {lv.ath}, 52W high: {lv.wk52_high}, 52W low: {lv.wk52_low}",
        f"Catalyst: {snap.catalyst_text or 'none'}",
    ]
    return "\n".join(lines)


def _fallback_playbook(scan_result: ScanResult) -> Playbook:
    """Deterministic playbook used when the LLM path fails."""
    snap = scan_result.snapshot
    price = snap.last_price
    # Simple 1% stop / 2% and 4% targets — matches R:R of 2 and 4.
    stop = round(price * 0.99, 2)
    pt1 = round(price * 1.02, 2)
    pt2 = round(price * 1.04, 2)
    rr = round((pt1 - price) / max(price - stop, 0.01), 2)
    return Playbook(
        symbol=snap.symbol,
        strategy_id=scan_result.strategy_id,
        thesis=(
            f"Rule-based fallback: {scan_result.strategy_name} setup on {snap.symbol} "
            f"at ${price:,.2f}."
        ),
        entry_trigger=f"Break above ${price:,.2f} on confirming volume.",
        stop_loss=stop,
        profit_target_1=pt1,
        profit_target_2=pt2,
        risk_reward=rr,
        position_size_pct=0.05,
        indicators_to_watch=("VWAP", "RVOL", "Price vs. PDH"),
        invalidation=f"Close below ${stop:,.2f} invalidates the setup.",
        confidence="low",
    )


def _get_llm(provider: Optional[str] = None, model: Optional[str] = None):
    """Construct the quick-think LLM. `provider` and `model` override DEFAULT_CONFIG."""
    provider = (provider or DEFAULT_CONFIG.get("llm_provider", "openai")).lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY") or DEFAULT_CONFIG.get("anthropic_api_key")
        model = model or DEFAULT_CONFIG.get("anthropic_quick_think_llm", "claude-sonnet-4-6")
        return ChatAnthropic(model=model, api_key=api_key, temperature=0.2)

    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or DEFAULT_CONFIG.get("openai_api_key")
    model = model or DEFAULT_CONFIG.get("quick_think_llm", "gpt-4o-mini")
    kwargs = {}
    no_temp = ["o3", "o4-mini", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
    if not any(prefix in model for prefix in no_temp):
        kwargs["temperature"] = 0.2
    return ChatOpenAI(model=model, openai_api_key=api_key, **kwargs)


def generate_playbook(
    scan_result: ScanResult,
    llm=None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Playbook:
    """Generate an AI playbook for a single (ticker, strategy) pair.

    `llm` is injectable for tests. `provider`/`model` override DEFAULT_CONFIG.
    On any failure, returns the fallback playbook.
    """
    snap = scan_result.snapshot
    strategy_id = scan_result.strategy_id

    try:
        llm = llm or _get_llm(provider=provider, model=model)
        structured = llm.with_structured_output(_PlaybookSchema)
        user_prompt = _format_user_prompt(snap, strategy_id)
        result: Optional[_PlaybookSchema] = structured.invoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        if result is None:
            raise ValueError("LLM returned None")
        return Playbook(
            symbol=snap.symbol,
            strategy_id=strategy_id,
            thesis=result.thesis,
            entry_trigger=result.entry_trigger,
            stop_loss=float(result.stop_loss),
            profit_target_1=float(result.profit_target_1),
            profit_target_2=float(result.profit_target_2),
            risk_reward=float(result.risk_reward),
            position_size_pct=float(result.position_size_pct),
            indicators_to_watch=tuple(result.indicators_to_watch),
            invalidation=result.invalidation,
            confidence=result.confidence.lower(),
        )
    except Exception as exc:
        logger.warning("Playbook LLM failed (%s) — returning fallback", exc)
        return _fallback_playbook(scan_result)
