"""LLM-backed AI playbook synthesis for the scanner.

Lazy-constructs a ChatOpenAI (or Anthropic) using the project's existing
config. Uses pydantic structured output; on any schema or network failure,
falls back to a deterministic rule-based playbook built from the strategy
template in `constants.STRATEGY_RULES`.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ._llm_factory import get_llm as _get_llm
from .constants import STRATEGY_RULES
from .models import Playbook, ScanResult, TickerSnapshot

logger = logging.getLogger(__name__)


class _PlaybookSchema(BaseModel):
    """Pydantic schema the LLM must populate."""

    thesis: str = Field(
        description=(
            "One-paragraph rationale, ≤60 words. Plain English; put any "
            "trader jargon in parentheses after the everyday phrase."
        )
    )
    entry_trigger: str = Field(
        description=(
            "Plain-English entry condition. After any technical term, include "
            "the trader jargon in parentheses. Example: 'When the price moves "
            "up through $1.70 (breakout above $1.70).'"
        )
    )
    entry_price: float = Field(
        description=(
            "Numeric entry price (absolute dollars). The single best trigger "
            "or limit price to enter — used directly by chart tools."
        )
    )
    order_type: str = Field(
        description=(
            "EXACTLY one of: 'Buy Stop', 'Buy Limit', 'Buy Stop-Limit', "
            "'Buy Market'. Pick based on the entry condition: "
            "breakouts above current price → 'Buy Stop'; pullbacks down to a "
            "level → 'Buy Limit'; breakouts where slippage is a concern → "
            "'Buy Stop-Limit'; immediate fill on signal → 'Buy Market'."
        )
    )
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
    qualification_reason: str = Field(
        description=(
            "1-2 sentences explaining why THIS ticker matches THIS strategy, "
            "citing specific numbers from the snapshot (RVOL, float, price vs "
            "VWAP, catalyst, etc.). Plain English; trader jargon in parentheses."
        )
    )
    confidence_reason: str = Field(
        description=(
            "1-2 sentences explaining what specifically pushed the confidence "
            "to low/medium/high. Cite the supporting (or missing) signals. "
            "Plain English; trader jargon in parentheses."
        )
    )


_SYSTEM_PROMPT = (
    "You are a day-trading playbook generator for a beginner trader. Given a "
    "strategy template and current ticker data, output STRICT JSON matching "
    "the provided schema. No commentary. No hedging. Use the provided price "
    "levels — do not invent.\n\n"
    "PLAIN-ENGLISH RULE — critical: write `thesis`, `entry_trigger`, and "
    "`invalidation` so a beginner can follow them. After any technical term, "
    "put the trader jargon in parentheses. Examples:\n"
    "  ✓ 'When the price moves up through $1.70 (breakout above $1.70).'\n"
    "  ✓ 'Price climbs back above the average price line (VWAP reclaim).'\n"
    "  ✓ 'Today's trading volume is 5× the usual (RVOL 5).'\n"
    "  ✗ 'Break above $1.70.' (too jargony, no plain explanation)\n\n"
    "ORDER TYPE RULE: `order_type` must match the entry intent exactly. "
    "Breakout above current price → 'Buy Stop'. Pullback down to a level → "
    "'Buy Limit'. Use 'Buy Stop-Limit' only if you want to cap slippage. "
    "Use 'Buy Market' only when the trigger is right now.\n\n"
    "PRICE RULES: Stop and targets must be absolute dollar prices consistent "
    "with the entry. `entry_price` is the single concrete trigger/limit "
    "number used by chart tools.\n\n"
    "QUALIFICATION RULE: `qualification_reason` must cite the specific numbers "
    "from the snapshot that make this ticker fit THIS strategy. Examples:\n"
    "  ✓ 'Float is 8M (under the 20M cap for low-float setups), today's volume "
    "is 6× normal (RVOL 6.0), and price reclaimed the average price line at "
    "$1.85 (VWAP reclaim).'\n"
    "  ✓ 'Price is within 2% of its 52-week high with heavy volume (RVOL 4.5) "
    "and a fresh FDA catalyst — exactly what an ATH breakout needs.'\n"
    "  ✗ 'This looks like a good setup.' (too generic, no numbers)\n\n"
    "CONFIDENCE RULE: `confidence_reason` must explain WHICH signals support or "
    "weaken the chosen level. Examples:\n"
    "  ✓ HIGH: 'All three primary signals aligned — catalyst (FDA), heavy "
    "volume (RVOL 8), and price holding above the average price line (VWAP).'\n"
    "  ✓ LOW: 'Volume is light (RVOL 1.2) and there's no fresh catalyst — the "
    "breakout could fail without volume confirmation.'\n"
    "  ✗ 'This is a high-confidence setup.' (no reasoning)"
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


def _format_speculation_prompt(
    ticker: str,
    company_name: str,
    direction: str,
    catalyst_type: str,
    reasoning: str,
    event_headline: str,
    last_price: float,
) -> str:
    lines = [
        f"Strategy: speculation_{direction}",
        f"Strategy rules: Event-driven {direction} play — use news catalyst and current "
        f"price to set entry, stop, and targets.",
        "",
        f"Ticker: {ticker} ({company_name})",
        f"Asset class: stock",
        f"Last price: {last_price}",
        f"Catalyst type: {catalyst_type}",
        f"Triggering event: {event_headline}",
        "",
        "Analysis:",
        reasoning,
        "",
        "Note: Derive all entry/stop/target prices from the current last price. "
        "For bullish plays use Buy Stop or Buy Market. "
        "For bearish plays model as a short-biased play with protective stop above price.",
    ]
    return "\n".join(lines)


def _fallback_speculation_playbook(
    ticker: str,
    direction: str,
    last_price: float,
) -> Playbook:
    price = last_price or 10.0
    if direction == "bullish":
        stop = round(price * 0.97, 2)
        pt1 = round(price * 1.04, 2)
        pt2 = round(price * 1.08, 2)
        order_type = "Buy Stop"
    else:
        stop = round(price * 1.03, 2)
        pt1 = round(price * 0.96, 2)
        pt2 = round(price * 0.92, 2)
        order_type = "Buy Market"
    rr = round(abs(pt1 - price) / max(abs(price - stop), 0.01), 2)
    return Playbook(
        symbol=ticker,
        strategy_id=f"speculation_{direction}",
        thesis=f"Rule-based fallback: event-driven {direction} play on {ticker} at ${price:,.2f}.",
        entry_trigger=f"Enter {'above' if direction == 'bullish' else 'below'} ${price:,.2f} on the news catalyst.",
        entry_price=price,
        order_type=order_type,
        stop_loss=stop,
        profit_target_1=pt1,
        profit_target_2=pt2,
        risk_reward=rr,
        position_size_pct=0.03,
        indicators_to_watch=("Price vs. entry", "Volume", "News flow"),
        invalidation=f"Close {'below' if direction == 'bullish' else 'above'} ${stop:,.2f} invalidates the setup.",
        confidence="low",
        qualification_reason=f"Speculation signal on {ticker} — fallback playbook (LLM unavailable).",
        confidence_reason="Low confidence: rule-based fallback without full signal analysis.",
    )


def generate_speculation_playbook(
    ticker: str,
    company_name: str,
    direction: str,
    catalyst_type: str,
    reasoning: str,
    event_headline: str,
    last_price: float,
    llm=None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Playbook:
    """Generate an AI playbook from a speculation signal (no scanner snapshot required).

    Uses current price + signal context. Falls back to rule-based playbook on failure.
    """
    try:
        llm = llm or _get_llm(provider=provider, model=model)
        structured = llm.with_structured_output(_PlaybookSchema)
        user_prompt = _format_speculation_prompt(
            ticker, company_name, direction, catalyst_type,
            reasoning, event_headline, last_price,
        )
        result: Optional[_PlaybookSchema] = structured.invoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        if result is None:
            raise ValueError("LLM returned None")
        return Playbook(
            symbol=ticker,
            strategy_id=f"speculation_{direction}",
            thesis=result.thesis,
            entry_trigger=result.entry_trigger,
            entry_price=float(result.entry_price),
            order_type=result.order_type,
            stop_loss=float(result.stop_loss),
            profit_target_1=float(result.profit_target_1),
            profit_target_2=float(result.profit_target_2),
            risk_reward=float(result.risk_reward),
            position_size_pct=float(result.position_size_pct),
            indicators_to_watch=tuple(result.indicators_to_watch),
            invalidation=result.invalidation,
            confidence=result.confidence.lower(),
            qualification_reason=result.qualification_reason,
            confidence_reason=result.confidence_reason,
        )
    except Exception as exc:
        logger.warning("Speculation playbook LLM failed for %s (%s) — returning fallback", ticker, exc)
        return _fallback_speculation_playbook(ticker, direction, last_price)


def _fallback_playbook(scan_result: ScanResult) -> Playbook:
    """Deterministic playbook used when the LLM path fails."""
    snap = scan_result.snapshot
    price = snap.last_price
    # Simple 1% stop / 2% and 4% targets — matches R:R of 2 and 4.
    stop = round(price * 0.99, 2)
    pt1 = round(price * 1.02, 2)
    pt2 = round(price * 1.04, 2)
    rr = round((pt1 - price) / max(price - stop, 0.01), 2)
    rvol_str = f"{snap.rvol:.1f}" if snap.rvol is not None else "n/a"
    return Playbook(
        symbol=snap.symbol,
        strategy_id=scan_result.strategy_id,
        thesis=(
            f"Rule-based fallback: {scan_result.strategy_name} setup on {snap.symbol} "
            f"at ${price:,.2f}."
        ),
        entry_trigger=(
            f"Buy when the price moves up through ${price:,.2f} on rising "
            "trading volume (breakout above the trigger price with confirming volume)."
        ),
        entry_price=round(price, 2),
        order_type="Buy Stop",
        stop_loss=stop,
        profit_target_1=pt1,
        profit_target_2=pt2,
        risk_reward=rr,
        position_size_pct=0.05,
        indicators_to_watch=("VWAP", "RVOL", "Price vs. PDH"),
        invalidation=f"Close below ${stop:,.2f} invalidates the setup.",
        confidence="low",
        qualification_reason=(
            f"Matched {scan_result.strategy_name} on {snap.symbol} at ${price:,.2f} "
            f"with RVOL {rvol_str} (rule-based fallback — full reasoning unavailable "
            "because the LLM call failed)."
        ),
        confidence_reason=(
            "Confidence is low because this is a rule-based fallback playbook — "
            "the LLM was unavailable, so we can't verify which signals are aligned."
        ),
    )


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
            entry_price=float(result.entry_price),
            order_type=result.order_type,
            stop_loss=float(result.stop_loss),
            profit_target_1=float(result.profit_target_1),
            profit_target_2=float(result.profit_target_2),
            risk_reward=float(result.risk_reward),
            position_size_pct=float(result.position_size_pct),
            indicators_to_watch=tuple(result.indicators_to_watch),
            invalidation=result.invalidation,
            confidence=result.confidence.lower(),
            qualification_reason=result.qualification_reason,
            confidence_reason=result.confidence_reason,
        )
    except Exception as exc:
        logger.warning("Playbook LLM failed (%s) — returning fallback", exc)
        return _fallback_playbook(scan_result)
