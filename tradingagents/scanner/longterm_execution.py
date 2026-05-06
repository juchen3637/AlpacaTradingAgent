"""Long-term play → bracket-execution adapter.

The day-trade `execute_playbook_paper(playbook)` already submits a tagged
bracket order, journals it, and returns an `ExecutionResult`. Long-term
plays carry the same bracket fields, but on a separate dataclass with
extra DCA framing. This module bridges the two:

    longterm_pb → to_bracket_playbook → Playbook → execute_playbook_paper

Keeping the adapter in its own file isolates the mapping logic and lets
the existing execution path stay unchanged.
"""

from __future__ import annotations

from .longterm_models import LongTermPlaybook
from .models import Playbook


def to_bracket_playbook(lt: LongTermPlaybook) -> Playbook:
    """Convert a long-term playbook into the day-trade `Playbook` shape.

    `risk_reward` is computed from the bracket levels. `indicators_to_watch`
    and `invalidation` are populated with long-term-appropriate text so the
    journal entry reads correctly. `confidence` reuses the conviction value.
    """
    risk_per_share = max(lt.entry_price - lt.stop_loss, 1e-6)
    reward_per_share = lt.profit_target_1 - lt.entry_price
    risk_reward = round(reward_per_share / risk_per_share, 2)

    return Playbook(
        symbol=lt.symbol,
        strategy_id=lt.strategy_id,
        thesis=lt.thesis,
        entry_trigger=(
            f"Long-term entry: zone ${lt.entry_zone_low:.2f}–"
            f"${lt.entry_zone_high:.2f}, hold {lt.hold_horizon_years}y"
        ),
        entry_price=lt.entry_price,
        order_type=lt.order_type,
        stop_loss=lt.stop_loss,
        profit_target_1=lt.profit_target_1,
        profit_target_2=lt.profit_target_2,
        risk_reward=risk_reward,
        position_size_pct=lt.position_size_pct,
        indicators_to_watch=("200-SMA", "Quarterly earnings"),
        invalidation=(
            f"Multi-session close below ${lt.stop_loss:.2f} — buy-and-hold "
            "thesis is broken at that level."
        ),
        confidence=(lt.conviction or "low").lower(),
        qualification_reason=(
            f"Long-term composite screen passed; DCA over {lt.dca_weeks} weeks; "
            f"3y target ${lt.target_price_3y:.2f}."
        ),
        confidence_reason=lt.conviction_reason or "",
    )


def is_executable(lt: LongTermPlaybook) -> bool:
    """True if the playbook has the bracket fields populated.

    Older saved long-term plays (pre-bracket schema) load with
    entry_price=0.0 — the UI uses this to gate the Execute button and
    prompt the user to regenerate.
    """
    return (
        lt.entry_price > 0
        and lt.stop_loss > 0
        and lt.profit_target_1 > 0
        and lt.stop_loss < lt.entry_price < lt.profit_target_1
    )
