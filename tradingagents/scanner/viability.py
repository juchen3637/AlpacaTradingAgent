"""LLM-backed viability re-analysis for a saved play.

Compares the original Playbook + scan_row against the latest market state
(current price, recent news, current catalyst, live position, unfilled orders)
and returns a structured verdict + recommended action.

Design:
- Strict pydantic schema so the LLM can't drift the output shape silently.
- Deterministic, snapshot-testable prompt builder (no timestamps, no random
  ordering — fixed input → fixed prompt).
- On any LLM / parse failure, returns a typed `INVALID_VERDICT` (status =
  "invalidated") with the failure reason — never raises into the UI layer.
- No @with_cache: per user spec, every Re-analyze click hits the LLM fresh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import Playbook
from .playbook_llm import _get_llm

logger = logging.getLogger(__name__)


VERDICT_STATUSES = ("still_viable", "degraded", "invalidated", "thesis_played_out")
RECOMMENDED_ACTIONS = (
    "hold", "tighten_stop", "scale_out", "exit_now", "no_position_skip",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class ViabilityVerdict:
    """Structured LLM verdict on a saved play's current viability."""

    status: str  # one of VERDICT_STATUSES
    confidence: str  # one of CONFIDENCE_LEVELS
    reasoning: str
    recommended_action: str  # one of RECOMMENDED_ACTIONS
    key_changes: tuple[str, ...] = ()
    news_signals: tuple[str, ...] = ()
    analyzed_at: str = ""
    model: str = ""
    provider: str = ""
    snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "recommended_action": self.recommended_action,
            "key_changes": list(self.key_changes),
            "news_signals": list(self.news_signals),
            "analyzed_at": self.analyzed_at,
            "model": self.model,
            "provider": self.provider,
            "snapshot": dict(self.snapshot),
        }

    @classmethod
    def invalidated(cls, reason: str, *, provider: str = "",
                    model: str = "") -> "ViabilityVerdict":
        return cls(
            status="invalidated",
            confidence="low",
            reasoning=f"Analysis could not be completed: {reason}",
            recommended_action="hold",
            key_changes=(),
            news_signals=(),
            analyzed_at=_now_iso(),
            model=model,
            provider=provider,
            snapshot={},
        )


class _VerdictSchema(BaseModel):
    """Pydantic schema the LLM must populate."""

    status: str = Field(
        description=(
            "EXACTLY one of: 'still_viable', 'degraded', 'invalidated', "
            "'thesis_played_out'. Pick the single best fit."
        ),
    )
    confidence: str = Field(
        description="EXACTLY one of: 'low', 'medium', 'high'.",
    )
    reasoning: str = Field(
        description=(
            "3-5 sentence narrative comparing original thesis vs current state. "
            "Plain English; trader jargon in parentheses."
        ),
    )
    recommended_action: str = Field(
        description=(
            "EXACTLY one of: 'hold', 'tighten_stop', 'scale_out', 'exit_now', "
            "'no_position_skip'. Use 'no_position_skip' only when no position "
            "is open AND the setup no longer qualifies."
        ),
    )
    key_changes: list[str] = Field(
        default_factory=list,
        description=(
            "1-5 bullet points naming what specifically changed since save: "
            "price action, RVOL, catalyst, news. Cite numbers."
        ),
    )
    news_signals: list[str] = Field(
        default_factory=list,
        description=(
            "0-5 bullet points summarizing today's relevant headlines. "
            "Empty list if there's no relevant news."
        ),
    )


_SYSTEM_PROMPT = (
    "You are a day-trading risk reviewer. A trader saved a playbook earlier "
    "and is asking whether the setup is still valid now. You will receive: "
    "the original playbook (thesis, levels, qualification reasoning), the "
    "scan-row at save time, the current market snapshot, recent news, the "
    "current catalyst, and the live Alpaca position + open orders.\n\n"
    "Your job: decide whether the original thesis still holds, and recommend "
    "exactly ONE action. Output STRICT JSON matching the schema. No commentary, "
    "no hedging.\n\n"
    "STATUS RULES:\n"
    "  - 'still_viable': the thesis still holds; original levels remain "
    "relevant; signals haven't materially weakened.\n"
    "  - 'degraded': the thesis is weakened (e.g. RVOL collapsed, catalyst "
    "faded, price grinding sideways) but not yet invalidated.\n"
    "  - 'invalidated': a hard invalidation triggered — stop hit, news "
    "contradicts the thesis, or the setup-qualifying condition is gone.\n"
    "  - 'thesis_played_out': the trade already worked — price hit PT1 or PT2, "
    "or moved past the original target zone.\n\n"
    "ACTION RULES:\n"
    "  - 'hold': leave existing position / pending order alone.\n"
    "  - 'tighten_stop': in a green trade — pull the stop closer to lock gains.\n"
    "  - 'scale_out': trim part of the position (e.g. half at PT1).\n"
    "  - 'exit_now': close fully — invalidation triggered or thesis dead.\n"
    "  - 'no_position_skip': no position open AND setup no longer qualifies; "
    "do NOT enter.\n\n"
    "PLAIN-ENGLISH RULE: explain in everyday language; put trader jargon in "
    "parentheses. 'Today's volume is 5x the usual (RVOL 5).' not 'RVOL 5.'\n\n"
    "Cite the specific numbers you used: the original entry/stop, the current "
    "price, % move since save, RVOL change. If news is present, name the "
    "headline."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_num(v: Any) -> str:
    """Format a numeric for the prompt; '—' for None, 2 decimals otherwise."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f) >= 1000:
        return f"{f:,.2f}"
    return f"{f:.2f}"


def _fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return str(v)


def build_viability_user_prompt(
    *,
    playbook: Playbook,
    scan_row: dict,
    current_snapshot: dict,
    news: list[dict],
    catalyst_now: Optional[str],
    position: Optional[dict],
    unfilled_orders: list[dict],
) -> str:
    """Assemble the deterministic user prompt.

    Inputs are kept as plain dicts so callers can build them from any source
    (Alpaca, fixtures, tests) without dragging dataclass deps into here.
    """
    saved_price = scan_row.get("last_price")
    saved_rvol = scan_row.get("rvol")
    saved_catalyst = scan_row.get("catalyst") or "(none)"

    cur_price = current_snapshot.get("current_price")
    cur_rvol = current_snapshot.get("current_rvol")
    change_since_save_pct = current_snapshot.get("change_since_save_pct")
    today_change_pct = current_snapshot.get("today_change_pct")

    lines = [
        "ORIGINAL PLAYBOOK (saved earlier)",
        f"  Symbol: {playbook.symbol}",
        f"  Strategy: {playbook.strategy_id}",
        f"  Thesis: {playbook.thesis}",
        f"  Qualification reason: {playbook.qualification_reason or '(none)'}",
        f"  Confidence reason: {playbook.confidence_reason or '(none)'}",
        f"  Order type: {playbook.order_type}",
        f"  Entry: ${_fmt_num(playbook.entry_price)}",
        f"  Stop: ${_fmt_num(playbook.stop_loss)}",
        f"  PT1: ${_fmt_num(playbook.profit_target_1)}",
        f"  PT2: ${_fmt_num(playbook.profit_target_2)}",
        f"  R:R: {_fmt_num(playbook.risk_reward)}",
        f"  Position size: {playbook.position_size_pct * 100:.1f}% of BP",
        f"  Indicators to watch: {', '.join(playbook.indicators_to_watch) or '—'}",
        f"  Invalidation: {playbook.invalidation}",
        f"  Original confidence: {playbook.confidence}",
        "",
        "AT SAVE TIME (scan row)",
        f"  Price: ${_fmt_num(saved_price)}",
        f"  RVOL: {_fmt_num(saved_rvol)}",
        f"  Catalyst: {saved_catalyst}",
        "",
        "CURRENT MARKET SNAPSHOT",
        f"  Price now: ${_fmt_num(cur_price)}",
        f"  Change vs save price: {_fmt_pct(change_since_save_pct)}",
        f"  Change today: {_fmt_pct(today_change_pct)}",
        f"  RVOL now: {_fmt_num(cur_rvol)}",
        f"  Catalyst now: {catalyst_now or '(none)'}",
        "",
        "RECENT NEWS (last 24h, up to 5 headlines)",
    ]
    if not news:
        lines.append("  (no recent news)")
    else:
        for item in news[:5]:
            head = (item.get("headline") or item.get("description") or "").strip()
            src = (item.get("source") or "").strip()
            lines.append(f"  - {head}" + (f" — {src}" if src else ""))
    lines.append("")
    lines.append("LIVE ALPACA STATE")
    if position:
        qty = position.get("qty")
        avg = position.get("avg_entry_price")
        pl = position.get("unrealized_pl")
        plpc = position.get("unrealized_plpc")
        side = (position.get("side") or "long").upper()
        lines.append(
            f"  Position: {side} {_fmt_num(qty)} @ ${_fmt_num(avg)} · "
            f"unrealized P/L ${_fmt_num(pl)} ({_fmt_pct(plpc)})"
        )
    else:
        lines.append("  Position: none")
    if unfilled_orders:
        for o in unfilled_orders:
            lines.append(
                f"  Unfilled order: {(o.get('side') or '').upper()} "
                f"{_fmt_num(o.get('qty'))} {o.get('order_type', '')} "
                f"limit={_fmt_num(o.get('limit_price'))} "
                f"stop={_fmt_num(o.get('stop_price'))} "
                f"status={o.get('status', '')}"
            )
    else:
        lines.append("  Unfilled orders: none")
    lines.append("")
    lines.append(
        "Decide: is the original thesis still viable now? Recommend ONE action."
    )
    return "\n".join(lines)


def _normalize_status(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in VERDICT_STATUSES else "invalidated"


def _normalize_action(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in RECOMMENDED_ACTIONS else "hold"


def _normalize_confidence(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in CONFIDENCE_LEVELS else "low"


def analyze_viability(
    *,
    playbook: Playbook,
    scan_row: dict,
    current_snapshot: dict,
    news: list[dict],
    catalyst_now: Optional[str],
    position: Optional[dict],
    unfilled_orders: list[dict],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    llm: Any = None,
) -> ViabilityVerdict:
    """Run the LLM and return a typed verdict.

    `llm` is injectable for tests. On any failure returns an invalidated
    verdict with the reason — never raises.
    """
    snapshot_inputs = {
        "current_price": current_snapshot.get("current_price"),
        "change_since_save_pct": current_snapshot.get("change_since_save_pct"),
        "today_change_pct": current_snapshot.get("today_change_pct"),
        "current_rvol": current_snapshot.get("current_rvol"),
        "position_qty": position.get("qty") if position else None,
        "position_unrealized_pl": position.get("unrealized_pl") if position else None,
        "unfilled_count": len(unfilled_orders or []),
    }

    user_prompt = build_viability_user_prompt(
        playbook=playbook,
        scan_row=scan_row,
        current_snapshot=current_snapshot,
        news=news,
        catalyst_now=catalyst_now,
        position=position,
        unfilled_orders=unfilled_orders,
    )

    try:
        llm = llm or _get_llm(provider=provider, model=model)
        structured = llm.with_structured_output(_VerdictSchema)
        result: Optional[_VerdictSchema] = structured.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])
        if result is None:
            raise ValueError("LLM returned None")
        return ViabilityVerdict(
            status=_normalize_status(result.status),
            confidence=_normalize_confidence(result.confidence),
            reasoning=result.reasoning.strip(),
            recommended_action=_normalize_action(result.recommended_action),
            key_changes=tuple(s.strip() for s in result.key_changes if s and s.strip()),
            news_signals=tuple(s.strip() for s in result.news_signals if s and s.strip()),
            analyzed_at=_now_iso(),
            model=model or "",
            provider=provider or "",
            snapshot=snapshot_inputs,
        )
    except Exception as exc:
        logger.warning("Viability LLM failed (%s) — returning invalidated", exc)
        return ViabilityVerdict.invalidated(
            str(exc), provider=provider or "", model=model or "",
        )
