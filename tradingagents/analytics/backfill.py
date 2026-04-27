"""
tradingagents/analytics/backfill.py - Alpaca historical trade backfill.

Pulls closed orders from Alpaca, matches buys against sells using the
weighted-average-cost method (same accounting Alpaca uses for
avg_entry_price), and writes synthetic decisions + outcomes to the journal
with source='backfill' so analytics can tell them apart from live agent
decisions.

Idempotent: uses each Alpaca order's client_order_id (falling back to order id)
as a dedup key. Re-running the same window is safe.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .trade_journal import DecisionRecord, TradeJournal, TradeRecord, get_journal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillReport:
    """Summary of what a backfill run did."""
    decisions_added: int
    trades_added: int
    outcomes_added: int
    skipped_duplicates: int
    orders_scanned: int
    error: str | None = None


def _fetch_closed_orders(lookback_days: int) -> list[dict[str, Any]]:
    """Fetch all closed/filled orders from Alpaca in the last `lookback_days`.

    Paginated via 'until' cursor (Alpaca caps single response at 500).
    """
    # Lazy import so tests can run without Alpaca creds.
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

    client = get_alpaca_trading_client()
    after = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    orders: list[Any] = []
    until: datetime | None = None
    page_size = 500
    max_pages = 50  # safety cap — 25k orders

    for _ in range(max_pages):
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            limit=page_size,
            after=after,
            until=until,
            direction="desc",
            nested=False,
        )
        page = list(client.get_orders(req))
        if not page:
            break
        orders.extend(page)
        if len(page) < page_size:
            break
        # Next page: orders older than the oldest one we just saw
        oldest = min(
            (o.submitted_at for o in page if o.submitted_at is not None),
            default=None,
        )
        if oldest is None:
            break
        until = oldest

    return [_serialize_order(o) for o in orders]


def _serialize_order(order: Any) -> dict[str, Any]:
    """Convert an Alpaca Order SDK object into a plain dict we can pass around."""
    def _v(e: Any) -> Any:
        return e.value if hasattr(e, "value") else e

    filled_qty = float(order.filled_qty) if order.filled_qty else 0.0
    filled_price = float(order.filled_avg_price) if order.filled_avg_price else 0.0
    filled_at = order.filled_at.isoformat() if order.filled_at else None
    submitted_at = order.submitted_at.isoformat() if order.submitted_at else None

    return {
        "id": str(order.id),
        "client_order_id": getattr(order, "client_order_id", None),
        "symbol": order.symbol,
        "side": str(_v(order.side)).lower(),
        "qty": filled_qty,
        "filled_price": filled_price,
        "order_type": str(_v(order.type)),
        "status": str(_v(order.status)),
        "filled_at": filled_at,
        "submitted_at": submitted_at,
    }


def _dedup_key(order: dict[str, Any]) -> str:
    """Stable key for detecting already-backfilled orders."""
    return order.get("client_order_id") or f"alpaca:{order['id']}"


def _match_avg_cost(orders_for_symbol: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match buys against sells using running weighted-average cost.

    This is the same accounting Alpaca uses for ``avg_entry_price``. For each
    symbol we track ``(total_shares, total_cost)``:

    * **Buy**: ``total_shares += qty``; ``total_cost += qty * price``.
    * **Sell**: ``avg_cost = total_cost / total_shares``;
      ``realized = (sell_price - avg_cost) * matched_qty``; then decrement
      ``total_shares`` and ``total_cost`` proportionally.

    Only handles long round-trips (buy → later sell). Shorts and open positions
    are left as decisions without outcomes. Sells with no prior buys in the
    window are skipped (happens at backfill edges).
    """
    # Oldest first
    chronological = sorted(
        orders_for_symbol,
        key=lambda o: o.get("filled_at") or o.get("submitted_at") or "",
    )

    total_shares = 0.0
    total_cost = 0.0
    last_buy_timestamp: str | None = None
    outcomes: list[dict[str, Any]] = []

    for o in chronological:
        if o["qty"] <= 0 or not o.get("filled_at"):
            continue
        side = o["side"]
        qty = o["qty"]
        price = o["filled_price"]

        if side == "buy":
            total_shares += qty
            total_cost += qty * price
            last_buy_timestamp = o["filled_at"]
        elif side == "sell":
            if total_shares <= 1e-9:
                # Sell with no opening buy in the window — skip.
                continue
            matched = min(qty, total_shares)
            avg_cost = total_cost / total_shares
            pnl_dollars = (price - avg_cost) * matched
            pnl_percent = (
                (price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0.0
            )
            hold_hours = _hours_between(last_buy_timestamp, o["filled_at"])
            outcomes.append({
                "ticker": o["symbol"],
                "entry_timestamp": last_buy_timestamp,
                "entry_price": avg_cost,
                "exit_timestamp": o["filled_at"],
                "exit_price": price,
                "qty": matched,
                "pnl_dollars": pnl_dollars,
                "pnl_percent": pnl_percent,
                "hold_duration_hours": hold_hours,
                "exit_reason": "backfill",
            })
            # Decrement proportionally: removing `matched` shares at avg cost.
            total_cost -= matched * avg_cost
            total_shares -= matched
            if total_shares <= 1e-9:
                total_shares = 0.0
                total_cost = 0.0

    return outcomes


def _hours_between(iso_a: str | None, iso_b: str | None) -> float | None:
    if not iso_a or not iso_b:
        return None
    try:
        a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
        return (b - a).total_seconds() / 3600.0
    except ValueError:
        return None


def _normalize_ticker(symbol: str) -> str:
    """Alpaca crypto symbols come through as e.g. BTC/USD; stocks as NVDA."""
    return symbol


def backfill_from_alpaca(
    journal: TradeJournal | None = None,
    *,
    lookback_days: int = 90,
    orders: Iterable[dict[str, Any]] | None = None,
) -> BackfillReport:
    """Import historical Alpaca orders into the journal.

    Parameters
    ----------
    journal : optional TradeJournal, uses singleton if None
    lookback_days : how far back to pull from Alpaca
    orders : optional pre-fetched orders (for testing); bypasses Alpaca client

    Returns
    -------
    BackfillReport with counts of what was added vs skipped.
    """
    j = journal or get_journal()

    try:
        raw_orders = list(orders) if orders is not None else _fetch_closed_orders(lookback_days)
    except Exception as e:
        logger.exception("Backfill: failed to fetch Alpaca orders")
        return BackfillReport(0, 0, 0, 0, 0, error=str(e))

    decisions_added = 0
    trades_added = 0
    skipped = 0

    # Group by symbol for FIFO matching
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # First pass: write one decision + trade per filled order
    # (or skip if already imported)
    for o in raw_orders:
        if o["qty"] <= 0 or not o.get("filled_at"):
            continue  # canceled/unfilled

        key = _dedup_key(o)
        signal = "BUY" if o["side"] == "buy" else "SELL"
        ticker = _normalize_ticker(o["symbol"])
        trade_date = (o.get("filled_at") or "")[:10]

        decision = DecisionRecord(
            ticker=ticker,
            trade_date=trade_date,
            signal=signal,
            final_decision=f"Alpaca {o['side'].upper()} {o['qty']} @ {o['filled_price']}",
            entry_price=o["filled_price"],
            position_size_dollars=o["qty"] * o["filled_price"],
            selected_analysts=[],
            source="backfill",
            source_order_id=key,
            timestamp=o.get("filled_at") or o.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
        )

        # record_decision returns the existing id if source_order_id already exists
        existing_count_before = j.count_decisions()
        decision_id = j.record_decision(decision)
        if j.count_decisions() == existing_count_before:
            skipped += 1
        else:
            decisions_added += 1

        # Attach a trade row (skip if a trade with this alpaca_order_id exists)
        try:
            existing_trades = [
                t for t in j.get_trades_for_decision(decision_id)
                if t.get("alpaca_order_id") == o["id"]
            ]
            if not existing_trades:
                j.record_trade(TradeRecord(
                    decision_id=decision_id,
                    ticker=ticker,
                    side=o["side"],
                    qty=o["qty"],
                    filled_price=o["filled_price"],
                    order_type=o["order_type"],
                    alpaca_order_id=o["id"],
                    status=o["status"],
                    timestamp=o.get("filled_at") or datetime.now(timezone.utc).isoformat(),
                ))
                trades_added += 1
        except Exception:
            logger.exception("Backfill: failed to record trade for %s", o["id"])

        by_symbol[ticker].append({**o, "decision_id": decision_id})

    # Second pass: FIFO-match and write outcomes. Skip if any outcomes already
    # exist for these decisions (rough dedup — avoids duplicating the full chain
    # on re-runs).
    outcomes_added = 0
    for symbol, orders_for_symbol in by_symbol.items():
        existing_outcome_keys: set[tuple[str, str]] = set()
        for o in orders_for_symbol:
            for existing in j.get_outcomes_for_decision(o["decision_id"]):
                existing_outcome_keys.add((
                    existing.get("entry_timestamp") or "",
                    existing.get("exit_timestamp") or "",
                ))

        outcomes = _match_avg_cost(orders_for_symbol)
        # Map exit_timestamp back to the sell order's decision_id so the outcome
        # row links to the sell, not the buy.
        sell_by_filled_at = {
            o["filled_at"]: o["decision_id"]
            for o in orders_for_symbol if o["side"] == "sell" and o.get("filled_at")
        }

        for outc in outcomes:
            dedup_key = (outc["entry_timestamp"] or "", outc["exit_timestamp"] or "")
            if dedup_key in existing_outcome_keys:
                continue
            decision_id = sell_by_filled_at.get(outc["exit_timestamp"])
            try:
                j.record_outcome(
                    decision_id=decision_id,
                    ticker=symbol,
                    entry_timestamp=outc["entry_timestamp"],
                    entry_price=outc["entry_price"],
                    exit_timestamp=outc["exit_timestamp"],
                    exit_price=outc["exit_price"],
                    qty=outc["qty"],
                    pnl_dollars=outc["pnl_dollars"],
                    pnl_percent=outc["pnl_percent"],
                    hold_duration_hours=outc["hold_duration_hours"],
                    exit_reason=outc["exit_reason"],
                )
                outcomes_added += 1
            except Exception:
                logger.exception("Backfill: failed to record outcome for %s", symbol)

    return BackfillReport(
        decisions_added=decisions_added,
        trades_added=trades_added,
        outcomes_added=outcomes_added,
        skipped_duplicates=skipped,
        orders_scanned=len(raw_orders),
    )
