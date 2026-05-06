"""LLM-backed long-term thesis synthesis.

Mirrors `playbook_llm.py` shape but with a different schema (DCA-style
entry zone + multi-year hold horizon + 3y target). On any failure, falls
back to a deterministic scaffold so the UI always has something to show.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ._llm_factory import get_llm
from .longterm_models import (
    LONGTERM_STRATEGY_ID,
    LongTermPlaybook,
    LongTermScanResult,
    LongTermSnapshot,
)

logger = logging.getLogger(__name__)


class _LongTermPlaybookSchema(BaseModel):
    thesis: str = Field(
        description=(
            "One-paragraph buy-and-hold rationale, ≤80 words. Plain English. "
            "Cite specific numbers from the snapshot (ROE, margins, growth)."
        )
    )
    key_drivers: list[str] = Field(
        description="3–5 bullets — durable tailwinds and competitive advantages.",
        min_length=2,
        max_length=8,
    )
    key_risks: list[str] = Field(
        description="3–5 bullets — what could break the thesis over a 3–5y horizon.",
        min_length=2,
        max_length=8,
    )
    entry_zone_low: float = Field(
        description="Accumulate-below price (lower bound of the buy zone, in dollars).",
        gt=0,
    )
    entry_zone_high: float = Field(
        description="Top of the buy zone — beyond this, wait for a pullback.",
        gt=0,
    )
    dca_weeks: int = Field(
        description="Weeks to scale into a full position (4 / 8 / 12).",
        ge=1, le=52,
    )
    hold_horizon_years: int = Field(
        description="Intended holding period (1 / 3 / 5 / 10).",
        ge=1, le=15,
    )
    target_price_3y: float = Field(
        description=(
            "3-year price target in dollars. Anchor to current price × "
            "(1 + revenue CAGR)^3 with multiple-compression hedge — show your "
            "math in conviction_reason."
        ),
        gt=0,
    )
    conviction: Literal["low", "medium", "high", "LOW", "MEDIUM", "HIGH",
                        "Low", "Medium", "High"] = Field(
        description="low | medium | high",
    )
    conviction_reason: str = Field(
        description=(
            "1–2 sentences explaining what specifically supports this conviction "
            "level — cite ROE, margin, growth, valuation, or trend signals."
        )
    )

    # ── Bracket-order fields ──────────────────────────────────────────
    entry_price: float = Field(
        description=(
            "Bracket entry trigger in dollars. Anchor near `entry_zone_high` "
            "(top of the accumulation zone). This is the price that fires the "
            "Buy Limit / Buy Stop."
        ),
        gt=0,
    )
    stop_loss: float = Field(
        description=(
            "THESIS-BROKEN FLOOR in dollars — NOT a tight intraday stop. "
            "Place 15–25% below `entry_zone_low` at a structural support "
            "(200-SMA, prior base, key Fib). If the stock closes below this "
            "for multiple sessions, the buy-and-hold case is invalidated."
        ),
        gt=0,
    )
    profit_target_1: float = Field(
        description=(
            "First scale-out level — roughly a 1-year target. Anchor to "
            "current_price × (1 + revenue CAGR). Above entry_price."
        ),
        gt=0,
    )
    profit_target_2: float = Field(
        description=(
            "Second scale-out — should equal `target_price_3y` (the 3-year "
            "target). Above profit_target_1."
        ),
        gt=0,
    )
    position_size_pct: float = Field(
        description=(
            "Fraction of buying power to allocate (0..1). Long-term picks: "
            "0.03 for low conviction, 0.05 medium, 0.08–0.10 high. Never > 0.10."
        ),
        gt=0, le=0.10,
    )
    order_type: Literal["Buy Limit", "Buy Stop"] = Field(
        description=(
            "'Buy Limit' if waiting for pullback into entry zone. 'Buy Stop' "
            "if entering on confirmed breakout above current resistance."
        ),
    )

    @model_validator(mode="after")
    def _check_entry_zone_ordered(self):
        if self.entry_zone_low > self.entry_zone_high:
            self.entry_zone_low, self.entry_zone_high = (
                self.entry_zone_high, self.entry_zone_low
            )
        return self

    @model_validator(mode="after")
    def _check_bracket_levels(self):
        """Cross-field invariants: stop < entry < PT1 ≤ PT2.

        Reject rather than swap — getting the bracket structure wrong is
        a real LLM error (it implies the model didn't reason about the
        trade), unlike the entry-zone swap which is a slot-filling slip.
        """
        if self.stop_loss >= self.entry_price:
            raise ValueError(
                f"stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})"
            )
        if self.profit_target_1 <= self.entry_price:
            raise ValueError(
                f"profit_target_1 ({self.profit_target_1}) must be > "
                f"entry_price ({self.entry_price})"
            )
        if self.profit_target_2 < self.profit_target_1:
            raise ValueError(
                f"profit_target_2 ({self.profit_target_2}) must be ≥ "
                f"profit_target_1 ({self.profit_target_1})"
            )
        return self


_SYSTEM_PROMPT = (
    "You are a long-term equity research analyst writing for a buy-and-hold "
    "investor (3-10 year horizon). Output STRICT JSON matching the schema. "
    "No commentary outside the JSON. No financial advice disclaimers — those "
    "are added in the UI.\n\n"
    "PLAIN-ENGLISH RULE: write `thesis`, `key_drivers`, `key_risks`, and "
    "`conviction_reason` so a beginner investor can follow them. Cite "
    "specific numbers from the data (ROE 25%, net margin 30%, etc.) — vague "
    "claims are worthless.\n\n"
    "ENTRY ZONE RULE: `entry_zone_low` and `entry_zone_high` define a "
    "DCA-friendly accumulation band, not a single trigger. Anchor "
    "`entry_zone_high` near the current price; `entry_zone_low` should be a "
    "5-15% pullback level (key support, 200-SMA, recent base low). Both "
    "must be positive dollar values.\n\n"
    "TARGET RULE: `target_price_3y` must be defensible. Show your math in "
    "`conviction_reason` — e.g. 'current $500 × (1.15)^3 × multiple "
    "compression 0.85 ≈ $640'. Don't just pick a round number.\n\n"
    "BRACKET RULE: the user can also place a one-shot bracket order from "
    "this thesis. Set `entry_price` near `entry_zone_high` (top of the "
    "accumulation zone — this is the price that fires the order). "
    "`stop_loss` is a THESIS-BROKEN FLOOR, NOT a tight intraday stop: place "
    "it 15–25% below `entry_zone_low`, anchored at structural support "
    "(200-SMA / prior base / key Fib level). It must be < entry_price. "
    "`profit_target_1` is roughly a 1-year target: current_price × "
    "(1 + revenue_CAGR), and must be > entry_price. `profit_target_2` "
    "should equal `target_price_3y` and be ≥ profit_target_1. "
    "`position_size_pct` reflects conviction: 0.03 for low, 0.05 medium, "
    "0.08–0.10 high — never above 0.10. `order_type` = 'Buy Limit' if "
    "waiting for a pullback into the zone, 'Buy Stop' if entering on a "
    "confirmed breakout.\n\n"
    "CONVICTION RULE: HIGH only when ROE > 20%, net margin > 20%, revenue "
    "growth > 10%, and price above 200-SMA. MEDIUM when most signals are "
    "favorable but valuation is stretched OR growth is slowing. LOW when "
    "the thesis depends on assumptions (turnaround, multiple expansion) "
    "rather than current operating performance."
)


def _format_user_prompt(snap: LongTermSnapshot) -> str:
    def fmt(v: Optional[float], suffix: str = "") -> str:
        return "n/a" if v is None else f"{v:,.2f}{suffix}"

    lines = [
        f"Symbol: {snap.symbol}",
        f"Sector: {snap.sector or 'n/a'}",
        f"Industry: {snap.industry or 'n/a'}",
        f"Last price: ${fmt(snap.last_price)}",
        f"Market cap: ${fmt(snap.market_cap_b)}B",
        "",
        "FUNDAMENTALS (TTM):",
        f"  ROE: {fmt(snap.roe_ttm, '%')}",
        f"  Net margin: {fmt(snap.net_margin_ttm, '%')}",
        f"  Revenue 3y CAGR: {fmt(snap.revenue_growth_3y, '%')}",
        f"  Forward P/E: {fmt(snap.pe_forward)}",
        f"  Debt/Equity: {fmt(snap.debt_to_equity)}",
        f"  Dividend yield: {fmt(snap.dividend_yield_ttm, '%')}",
        "",
        "LONG-TERM TREND:",
        f"  50-SMA: ${fmt(snap.sma_50)}",
        f"  200-SMA: ${fmt(snap.sma_200)}",
        f"  Price above 200-SMA: {snap.above_sma_200}",
        f"  Golden cross (50 > 200): {snap.golden_cross}",
        f"  52-week high: ${fmt(snap.wk52_high)}",
        f"  52-week low: ${fmt(snap.wk52_low)}",
        f"  1-year return: {fmt(snap.one_year_return_pct, '%')}",
    ]
    return "\n".join(lines)


def _fallback_playbook(scan_result: LongTermScanResult) -> LongTermPlaybook:
    """Deterministic scaffold used when the LLM path fails."""
    snap = scan_result.snapshot
    price = snap.last_price
    entry_zone_low = round(price * 0.92, 2)
    entry_zone_high = round(price * 1.00, 2)
    target_3y = round(price * 1.30, 2)
    return LongTermPlaybook(
        symbol=snap.symbol,
        thesis=(
            f"Rule-based fallback: {snap.symbol} screens as a long-term "
            f"hold candidate at ${price:,.2f} (composite score "
            f"{scan_result.score:.2f}). LLM unavailable — full thesis pending."
        ),
        key_drivers=(
            "Mega-cap scale and balance-sheet strength.",
            "Persistent operating margins (per snapshot).",
            "Multi-year revenue growth trend (per snapshot).",
        ),
        key_risks=(
            "Valuation compression in a higher-rate regime.",
            "Sector rotation away from current leaders.",
            "Execution risk on growth assumptions.",
        ),
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        dca_weeks=8,
        hold_horizon_years=3,
        target_price_3y=target_3y,
        conviction="low",
        conviction_reason=(
            "Conviction is low because this is a rule-based fallback — the "
            "LLM was unavailable, so the underlying thesis hasn't been "
            "verified against the snapshot."
        ),
        # Bracket scaffold: stop 20% below entry_zone_low, PT1 = +15%, PT2 = +30%.
        entry_price=entry_zone_high,
        stop_loss=round(entry_zone_low * 0.80, 2),
        profit_target_1=round(price * 1.15, 2),
        profit_target_2=target_3y,
        position_size_pct=0.05,
        order_type="Buy Limit",
    )


def generate_longterm_playbook(
    scan_result: LongTermScanResult,
    llm=None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LongTermPlaybook:
    """Generate a long-term hold thesis. Returns the fallback on any failure."""
    snap = scan_result.snapshot
    try:
        llm = llm or get_llm(provider=provider, model=model)
        structured = llm.with_structured_output(_LongTermPlaybookSchema)
        user_prompt = _format_user_prompt(snap)
        result: Optional[_LongTermPlaybookSchema] = structured.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])
        if result is None:
            raise ValueError("LLM returned None")
        return LongTermPlaybook(
            symbol=snap.symbol,
            thesis=result.thesis,
            key_drivers=tuple(result.key_drivers),
            key_risks=tuple(result.key_risks),
            entry_zone_low=float(result.entry_zone_low),
            entry_zone_high=float(result.entry_zone_high),
            dca_weeks=int(result.dca_weeks),
            hold_horizon_years=int(result.hold_horizon_years),
            target_price_3y=float(result.target_price_3y),
            conviction=result.conviction.lower(),
            conviction_reason=result.conviction_reason,
            entry_price=float(result.entry_price),
            stop_loss=float(result.stop_loss),
            profit_target_1=float(result.profit_target_1),
            profit_target_2=float(result.profit_target_2),
            position_size_pct=float(result.position_size_pct),
            order_type=result.order_type,
        )
    except Exception as exc:
        logger.warning("LongTerm playbook LLM failed (%s) — returning fallback", exc)
        return _fallback_playbook(scan_result)


# Public re-exports so callers don't need to know it's the same id.
STRATEGY_ID = LONGTERM_STRATEGY_ID
