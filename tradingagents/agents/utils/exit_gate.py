"""Bracket-first exit gate.

Prevents the scheduled re-analysis loop from prematurely liquidating a fresh
position before its bracket take-profit / stop-loss has had a chance to fire.

Once a bracket order is in place, it is the primary exit mechanism. The AI
re-analysis can only override it when ALL of the following are true:

  1. The position is older than ``position_age_min_hold_hours``
  2. The new exit signal carries conviction >= ``exit_conviction_threshold``

OR a single hard-dissent override fires:

  - Adverse price move >= ``exit_adverse_move_pct`` against entry, OR
  - An explicit ``thesis_break`` flag (e.g. material news flagged upstream)

A 5-minute "fresh fill" guard always respects the bracket regardless of
conviction — fills propagate slowly through Alpaca's API and a brand-new
position should never be flipped in the same cycle that opened it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

ExitAction = Literal["respect_bracket", "close", "keep"]
_VALID_ACTIONS = {"respect_bracket", "close", "keep"}

_RECENT_FILL_GUARD = timedelta(minutes=5)
# Mirrors execute_trading_action in alpaca_utils.py:
#   LONG closes on SELL (investment mode) or NEUTRAL / SHORT (trading mode).
#   SHORT closes on NEUTRAL / LONG (trading mode); investment mode never has SHORT.
# HOLD, BUY, and same-side signals are NOT close signals.
_CLOSE_SIGNALS_FOR_LONG = {"SELL", "NEUTRAL", "SHORT"}
_CLOSE_SIGNALS_FOR_SHORT = {"BUY", "NEUTRAL", "LONG"}


@dataclass(frozen=True)
class ExitDecision:
    """Outcome of the exit-gate evaluation.

    Attributes:
        action: ``respect_bracket`` blocks the close; ``close`` allows it; ``keep``
            indicates the gate did not engage (signal was not a close signal,
            or no position is held).
        reason: Human-readable explanation suitable for logs.
    """

    action: ExitAction
    reason: str

    def __post_init__(self) -> None:
        if self.action not in _VALID_ACTIONS:
            raise ValueError(
                f"Invalid ExitDecision.action={self.action!r}; "
                f"must be one of {_VALID_ACTIONS}"
            )


def _is_crypto(symbol: str) -> bool:
    return "/" in symbol


def _signal_would_close(current_position: str, signal: str) -> bool:
    pos = (current_position or "").upper()
    sig = (signal or "").upper()
    if pos == "LONG":
        return sig in _CLOSE_SIGNALS_FOR_LONG
    if pos == "SHORT":
        return sig in _CLOSE_SIGNALS_FOR_SHORT
    return False


def _adverse_move_pct(current_position: str, avg_entry: float, current_price: float) -> float:
    """Return the adverse move % vs entry. Positive = unfavourable.

    For LONG: adverse = entry - current (price falling hurts).
    For SHORT: adverse = current - entry (price rising hurts).
    """
    if avg_entry <= 0 or current_price <= 0:
        return 0.0
    pos = (current_position or "").upper()
    if pos == "LONG":
        delta = avg_entry - current_price
    elif pos == "SHORT":
        delta = current_price - avg_entry
    else:
        return 0.0
    return (delta / avg_entry) * 100.0


def evaluate_exit_gate(
    symbol: str,
    current_position: str,
    signal: str,
    avg_entry: float,
    current_price: float,
    position_opened_at: Optional[datetime],
    conviction: float,
    thesis_break: bool,
    config: dict,
) -> ExitDecision:
    """Decide whether to honour an AI-generated close signal or respect the bracket.

    Args:
        symbol: Ticker (equities or ``BASE/QUOTE`` crypto). Crypto skips the gate.
        current_position: ``LONG`` | ``SHORT`` | ``NEUTRAL``.
        signal: New AI signal — typically ``BUY`` | ``HOLD`` | ``SELL`` |
            ``LONG`` | ``NEUTRAL`` | ``SHORT``.
        avg_entry: Position's average entry price.
        current_price: Latest market price.
        position_opened_at: Timezone-aware datetime of the original entry fill,
            or ``None`` if unknown (manual position, missing order history).
        conviction: 0..1 score parsed from the judge / risk-manager output.
        thesis_break: True if upstream flagged a material thesis violation.
        config: Project config dict; reads ``respect_brackets_when_held``,
            ``position_age_min_hold_hours``, ``exit_conviction_threshold``,
            ``exit_adverse_move_pct``.

    Returns:
        ExitDecision describing the outcome and a log-ready reason.
    """
    # Gate disabled → never engage.
    if not config.get("respect_brackets_when_held", True):
        return ExitDecision("keep", "exit gate disabled by config")

    # Crypto bracket orders behave differently in alpaca_utils; skip.
    if _is_crypto(symbol):
        return ExitDecision("keep", "crypto symbol — skipping bracket gate")

    # No position held → nothing to gate.
    if (current_position or "").upper() not in {"LONG", "SHORT"}:
        return ExitDecision("keep", "no position held")

    # Signal does not imply a close → nothing to gate.
    if not _signal_would_close(current_position, signal):
        return ExitDecision("keep", f"signal {signal} does not close {current_position}")

    # --- Hard-dissent overrides (bypass min-hold) ---
    if thesis_break:
        return ExitDecision("close", "thesis break flagged — override min-hold")

    adverse_move_threshold = float(config.get("exit_adverse_move_pct", 2.0))
    adverse_move = _adverse_move_pct(current_position, avg_entry, current_price)
    if adverse_move >= adverse_move_threshold:
        return ExitDecision(
            "close",
            f"adverse move {adverse_move:.2f}% >= threshold {adverse_move_threshold:.2f}%",
        )

    # --- Recent-fill guard ---
    now = datetime.now(timezone.utc)
    if position_opened_at is not None:
        if position_opened_at.tzinfo is None:
            position_opened_at = position_opened_at.replace(tzinfo=timezone.utc)
        age = now - position_opened_at
        if age < _RECENT_FILL_GUARD:
            return ExitDecision(
                "respect_bracket",
                f"position opened {age.total_seconds() / 60:.1f} min ago — recent fill guard",
            )

    # --- Min-hold + conviction gate ---
    min_hold = timedelta(hours=float(config.get("position_age_min_hold_hours", 4)))
    conviction_threshold = float(config.get("exit_conviction_threshold", 0.75))

    if position_opened_at is None:
        # Unknown age (e.g. manually opened position). Apply conviction-only check.
        if conviction >= conviction_threshold:
            return ExitDecision(
                "close",
                f"unknown age, conviction {conviction:.2f} >= {conviction_threshold:.2f}",
            )
        return ExitDecision(
            "respect_bracket",
            f"unknown age, conviction {conviction:.2f} < {conviction_threshold:.2f}",
        )

    age = now - position_opened_at
    if age < min_hold:
        return ExitDecision(
            "respect_bracket",
            f"position age {age.total_seconds() / 3600:.2f}h < min-hold {min_hold.total_seconds() / 3600:.1f}h",
        )

    if conviction < conviction_threshold:
        return ExitDecision(
            "respect_bracket",
            f"conviction {conviction:.2f} < threshold {conviction_threshold:.2f}",
        )

    return ExitDecision(
        "close",
        f"min-hold cleared (age {age.total_seconds() / 3600:.2f}h) and conviction {conviction:.2f} >= {conviction_threshold:.2f}",
    )
