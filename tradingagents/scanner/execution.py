"""Scanner playbook → Alpaca paper bracket execution.

Submits a one-click bracket order (entry + stop + PT1) tagged with
`scanner:{strategy_id}:{nonce}` via Alpaca's `client_order_id`, and writes
a matching decision to the trade journal so the Analysis tab can filter
scanner-driven trades separately from agent and manual trades.

PT2 is intentionally *not* placed as a live order — Alpaca brackets only
support a single take-profit. PT2 is preserved in the journal text for
reference; the user can scale out manually.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from tradingagents.analytics.trade_journal import (
    DecisionRecord,
    TradeJournal,
    get_journal,
)
from tradingagents.dataflows.alpaca_utils import AlpacaUtils

from .models import Playbook

logger = logging.getLogger(__name__)

# Sanity caps so a typo'd position_size_pct can't dump 100k shares of a penny stock.
DEFAULT_MAX_SHARES = 1000
NONCE_LEN = 10  # 16^10 ≈ 1.1T combinations — collisions practically impossible


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of an Execute (Paper) click."""

    success: bool
    message: str = ""
    error: str = ""
    client_order_id: Optional[str] = None
    alpaca_order_id: Optional[str] = None
    qty: int = 0
    decision_id: Optional[int] = None


def compute_scanner_position_size(
    buying_power: float,
    position_size_pct: float,
    entry_price: float,
    max_shares: int = DEFAULT_MAX_SHARES,
) -> int:
    """Pure helper: BP × pct / price → integer shares, capped at max_shares.

    Returns 0 on any invalid input (negative or zero values) — the caller
    interprets 0 as "abort, insufficient buying power for this setup".
    """
    if buying_power <= 0 or position_size_pct <= 0 or entry_price <= 0:
        return 0
    raw = int((buying_power * position_size_pct) // entry_price)
    if raw <= 0:
        return 0
    return min(raw, max_shares)


def _make_client_order_id(strategy_id: str) -> str:
    """`scanner:{strategy_id}:{10-hex nonce}` — fits Alpaca's 128-char limit."""
    nonce = uuid.uuid4().hex[:NONCE_LEN]
    return f"scanner:{strategy_id}:{nonce}"


def _validate(playbook: Playbook) -> Optional[str]:
    """Return None if the playbook is internally consistent, else error string."""
    is_short = getattr(playbook, "side", "buy") == "sell"
    if is_short:
        if playbook.stop_loss <= playbook.entry_price:
            return (
                f"Stop loss (${playbook.stop_loss:.2f}) must be above entry price "
                f"(${playbook.entry_price:.2f}) for a short playbook."
            )
        if playbook.profit_target_1 >= playbook.entry_price:
            return (
                f"Profit target 1 (${playbook.profit_target_1:.2f}) must be below "
                f"entry price (${playbook.entry_price:.2f}) for a short playbook."
            )
    else:
        if playbook.stop_loss >= playbook.entry_price:
            return (
                f"Stop loss (${playbook.stop_loss:.2f}) must be below entry price "
                f"(${playbook.entry_price:.2f}) for a long playbook."
            )
        if playbook.profit_target_1 <= playbook.entry_price:
            return (
                f"Profit target 1 (${playbook.profit_target_1:.2f}) must be above "
                f"entry price (${playbook.entry_price:.2f}) for a long playbook."
            )
    return None


def execute_playbook_paper(
    playbook: Playbook,
    journal: Optional[TradeJournal] = None,
) -> ExecutionResult:
    """Submit a paper bracket order from a playbook and journal it.

    Steps:
      1. Validate playbook levels (stop < entry < PT1).
      2. Fetch buying power, compute share quantity.
      3. Generate scanner-tagged client_order_id.
      4. Submit bracket to Alpaca paper.
      5. On success, persist a `source='scanner'` decision to the journal.

    Crypto symbols are not yet supported (Phase 1 scope = stocks only).
    """
    if "/" in playbook.symbol:
        return ExecutionResult(
            success=False,
            error="Crypto execution is not yet supported. Use stock playbooks.",
        )

    err = _validate(playbook)
    if err:
        return ExecutionResult(success=False, error=err)

    try:
        account = AlpacaUtils.get_account_info()
        buying_power = float(account.get("buying_power") or 0.0)
    except Exception as exc:
        logger.exception("Failed to fetch Alpaca account info")
        return ExecutionResult(
            success=False,
            error=f"Could not read Alpaca account: {exc}",
        )

    qty = compute_scanner_position_size(
        buying_power=buying_power,
        position_size_pct=playbook.position_size_pct,
        entry_price=playbook.entry_price,
    )
    if qty <= 0:
        return ExecutionResult(
            success=False,
            error=(
                f"Insufficient buying power: ${buying_power:,.2f} × "
                f"{playbook.position_size_pct * 100:.1f}% / ${playbook.entry_price:.2f} "
                f"= {qty} shares. Increase BP or position size."
            ),
        )

    # Safety gate — same deterministic checks applied to all order paths
    try:
        from tradingagents.safety_gate import check_order
        from tradingagents.default_config import DEFAULT_CONFIG
        try:
            open_pos = AlpacaUtils.get_positions_data() or []
        except Exception:
            open_pos = []
        signal = "SHORT" if getattr(playbook, "side", "buy") == "sell" else "BUY"
        dollar_amount = qty * playbook.entry_price
        gate = check_order(
            symbol=playbook.symbol,
            signal=signal,
            proposed_size_dollars=dollar_amount,
            entry_price=playbook.entry_price,
            stop_loss=playbook.stop_loss,
            take_profit=[playbook.profit_target_1],
            account_info=account,
            open_positions_count=len(open_pos),
            config=DEFAULT_CONFIG,
        )
        if not gate.passed:
            logger.warning("[GATE] Scanner order blocked for %s: %s", playbook.symbol, gate.reason)
            return ExecutionResult(success=False, error=f"Safety gate blocked: {gate.reason}")
        if gate.adjusted_size is not None:
            adjusted_qty = int(gate.adjusted_size / playbook.entry_price)
            if adjusted_qty > 0:
                logger.warning("[GATE] Scanner qty adjusted %d → %d for %s", qty, adjusted_qty, playbook.symbol)
                qty = adjusted_qty
    except ExecutionResult:
        raise
    except Exception as gate_err:
        logger.warning("[GATE] Scanner gate check failed (%s); proceeding without gate", gate_err)

    client_order_id = _make_client_order_id(playbook.strategy_id)

    is_short = getattr(playbook, "side", "buy") == "sell"
    submission = AlpacaUtils.submit_scanner_bracket_order(
        symbol=playbook.symbol,
        entry_price=playbook.entry_price,
        stop_loss=playbook.stop_loss,
        take_profit=playbook.profit_target_1,
        qty=qty,
        order_type=playbook.order_type,
        client_order_id=client_order_id,
        side="sell" if is_short else "buy",
    )

    if not submission.get("success"):
        return ExecutionResult(
            success=False,
            error=submission.get("error", "Alpaca submission failed"),
            client_order_id=client_order_id,
            qty=qty,
        )

    journal_obj = journal if journal is not None else get_journal()
    decision_id: Optional[int] = None
    try:
        record = DecisionRecord(
            ticker=playbook.symbol,
            trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            signal="SELL SHORT" if is_short else "BUY",
            trader_plan=playbook.thesis,
            final_decision=(
                f"Scanner {playbook.strategy_id} {playbook.order_type} bracket: "
                f"entry ${playbook.entry_price:.2f}, stop ${playbook.stop_loss:.2f}, "
                f"PT1 ${playbook.profit_target_1:.2f} "
                f"(PT2 ${playbook.profit_target_2:.2f} reference only)"
            ),
            position_size_dollars=round(qty * playbook.entry_price, 2),
            entry_price=playbook.entry_price,
            stop_loss=playbook.stop_loss,
            take_profit=[playbook.profit_target_1],
            source="scanner",
            source_order_id=client_order_id,
        )
        decision_id = journal_obj.record_decision(record)
    except Exception as exc:
        logger.warning(
            "Order submitted (alpaca id %s) but journal write failed: %s",
            submission.get("entry_order_id"), exc,
        )

    return ExecutionResult(
        success=True,
        message=submission.get("message", ""),
        client_order_id=client_order_id,
        alpaca_order_id=submission.get("entry_order_id"),
        qty=qty,
        decision_id=decision_id,
    )
