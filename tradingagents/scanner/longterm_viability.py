"""Deterministic long-term re-analysis.

For long-term plays, viability isn't a stop-loss check — it's a "have the
fundamentals deteriorated since I saved this thesis?" check. We re-fetch
the snapshot, recompute the score, compare current price against the saved
entry zone and 3y target, and return a verdict in the same shape as
`ViabilityVerdict.to_dict()` so the existing Plays UI renders it without
changes.

Pure-Python heuristics — no LLM call. Fast, free, deterministic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .longterm_data_provider import LongTermDataProvider
from .longterm_models import LongTermPlaybook, LongTermSnapshot
from .longterm_scoring import score_longterm

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_pct_change(old: Optional[float], new: Optional[float]) -> Optional[str]:
    if old is None or new is None:
        return None
    return f"{new - old:+.2f} pp"


def analyze_longterm_viability(
    *,
    playbook: LongTermPlaybook,
    saved_score: Optional[float],
    provider: Optional[LongTermDataProvider] = None,
) -> dict:
    """Re-analyze a long-term thesis. Returns a dict matching ViabilityVerdict.to_dict()."""
    provider = provider or LongTermDataProvider()
    symbol = playbook.symbol

    snap: Optional[LongTermSnapshot] = None
    try:
        snap = provider.fetch_snapshot(symbol)
    except Exception as exc:
        logger.warning("longterm viability snapshot failed for %s: %s", symbol, exc)

    if snap is None:
        return {
            "status": "invalidated",
            "confidence": "low",
            "reasoning": (
                f"Could not fetch a fresh snapshot for {symbol} — "
                "viability check skipped. Try again in a few minutes."
            ),
            "recommended_action": "hold",
            "key_changes": [],
            "news_signals": [],
            "analyzed_at": _now_iso(),
            "model": "",
            "provider": "longterm-deterministic",
            "snapshot": {"symbol": symbol},
        }

    cur_price = snap.last_price
    new_score = score_longterm(snap)

    # Compare against saved entry zone
    in_zone = (playbook.entry_zone_low <= cur_price <= playbook.entry_zone_high)
    above_target = cur_price >= playbook.target_price_3y

    # Heuristic decisioning
    key_changes: list[str] = []
    if saved_score is not None:
        score_delta = new_score - saved_score
        key_changes.append(
            f"Composite score: {saved_score:.3f} → {new_score:.3f} "
            f"({score_delta:+.3f})"
        )
    else:
        key_changes.append(f"Current composite score: {new_score:.3f}")

    if cur_price < playbook.entry_zone_low:
        key_changes.append(
            f"Price ${cur_price:,.2f} now below entry zone "
            f"${playbook.entry_zone_low:,.2f}–${playbook.entry_zone_high:,.2f} "
            "(better DCA opportunity)."
        )
    elif in_zone:
        key_changes.append(
            f"Price ${cur_price:,.2f} still inside entry zone — "
            "continue DCA on schedule."
        )
    else:
        key_changes.append(
            f"Price ${cur_price:,.2f} above entry zone "
            f"${playbook.entry_zone_high:,.2f} — pause new DCA buys; "
            "wait for pullback."
        )

    if snap.net_margin_ttm is not None and snap.net_margin_ttm <= 0:
        key_changes.append(
            f"Net margin turned negative ({snap.net_margin_ttm:.1f}%) — "
            "core profitability eroded."
        )
    if (snap.roe_ttm is not None and snap.roe_ttm < 5
            and saved_score is not None and saved_score >= 0.6):
        key_changes.append(
            f"ROE collapsed to {snap.roe_ttm:.1f}% — quality thesis weakening."
        )

    # Decide status
    score_dropped_hard = (
        saved_score is not None and (new_score - saved_score) <= -0.20
    )
    score_dropped_mild = (
        saved_score is not None and -0.20 < (new_score - saved_score) <= -0.08
    )
    fundamentals_broken = (
        (snap.net_margin_ttm is not None and snap.net_margin_ttm <= 0)
        or (snap.roe_ttm is not None and snap.roe_ttm < 0)
    )

    if above_target:
        status = "thesis_played_out"
        action = "scale_out"
        confidence = "high"
        reasoning = (
            f"Price ${cur_price:,.2f} hit or exceeded the 3-year target "
            f"${playbook.target_price_3y:,.2f}. Consider trimming and "
            "redeploying capital — the original thesis has played out."
        )
    elif fundamentals_broken or score_dropped_hard:
        status = "invalidated"
        action = "exit_now" if fundamentals_broken else "scale_out"
        confidence = "medium"
        reasoning = (
            "Fundamentals have deteriorated significantly. "
            "Net margin or ROE turned negative, or the composite quality "
            "score dropped by more than 0.20. Re-evaluate the thesis."
        )
    elif score_dropped_mild:
        status = "degraded"
        action = "hold"
        confidence = "medium"
        reasoning = (
            "The composite quality score has slipped modestly. The thesis "
            "still has merit — pause DCA additions and watch the next "
            "earnings print before adding."
        )
    else:
        status = "still_viable"
        action = "hold"
        confidence = "high"
        reasoning = (
            f"Fundamentals are intact (ROE {snap.roe_ttm or 0:.1f}%, "
            f"net margin {snap.net_margin_ttm or 0:.1f}%) and the composite "
            f"score ({new_score:.2f}) remains in the buy range. Continue "
            "the DCA schedule."
        )

    return {
        "status": status,
        "confidence": confidence,
        "reasoning": reasoning,
        "recommended_action": action,
        "key_changes": key_changes,
        "news_signals": [],
        "analyzed_at": _now_iso(),
        "model": "",
        "provider": "longterm-deterministic",
        "snapshot": {
            "symbol": symbol,
            "current_price": cur_price,
            "new_score": new_score,
            "roe_ttm": snap.roe_ttm,
            "net_margin_ttm": snap.net_margin_ttm,
            "revenue_growth_3y": snap.revenue_growth_3y,
            "above_sma_200": snap.above_sma_200,
        },
    }
