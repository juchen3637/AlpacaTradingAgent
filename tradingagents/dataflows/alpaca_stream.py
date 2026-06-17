# alpaca_stream.py
# Subscribes to Alpaca trade-update websocket and auto-resizes bracket OCO
# legs when a scanner-tagged parent order partially fills.

import asyncio
import logging
import threading
import time
from typing import Optional

from alpaca.trading.enums import OrderClass, OrderStatus, TradeEvent
from alpaca.trading.stream import TradingStream

from .alpaca_utils import AlpacaUtils
from .config import get_api_key

logger = logging.getLogger(__name__)

_SCANNER_PREFIX = "scanner:"
_ACTIVE_STATUSES = {
    OrderStatus.NEW,
    OrderStatus.ACCEPTED,
    OrderStatus.HELD,
    OrderStatus.PENDING_NEW,
    OrderStatus.PARTIALLY_FILLED,
}

_started = False
_started_lock = threading.Lock()
_stream: Optional[TradingStream] = None


class BracketLegAdjuster:
    """Handles trade-update events and resizes bracket legs on partial fills."""

    def __init__(self) -> None:
        self._processed: set[tuple[str, int]] = set()

    async def on_trade_update(self, data) -> None:
        try:
            await asyncio.to_thread(self._handle, data)
        except Exception:
            logger.exception("[BracketLegAdjuster] unhandled error in on_trade_update")

    def _handle(self, data) -> None:
        order = data.order
        event = data.event

        cid = getattr(order, "client_order_id", "") or ""
        if not cid.startswith(_SCANNER_PREFIX):
            return

        order_class = order.order_class
        class_val = order_class.value if hasattr(order_class, "value") else str(order_class)
        if class_val != OrderClass.BRACKET.value:
            return

        event_val = event.value if hasattr(event, "value") else str(event)
        if event_val != TradeEvent.PARTIAL_FILL.value:
            return

        try:
            filled_qty = int(float(order.filled_qty or 0))
        except (TypeError, ValueError):
            filled_qty = 0

        if filled_qty <= 0:
            return

        parent_id = str(order.id)
        key = (parent_id, filled_qty)
        if key in self._processed:
            return
        self._processed.add(key)

        logger.info(
            "[BracketLegAdjuster] partial fill detected: %s %s filled_qty=%d",
            order.symbol, parent_id, filled_qty,
        )
        self._adjust(parent_id, filled_qty, order)

    def _adjust(self, parent_id: str, filled_qty: int, parent_order) -> None:
        legs = AlpacaUtils.get_bracket_legs(parent_id)
        if "error" in legs:
            logger.error("[BracketLegAdjuster] get_bracket_legs failed: %s", legs["error"])
            return

        tp = legs.get("take_profit")
        sl = legs.get("stop_loss")
        if tp is None and sl is None:
            logger.warning("[BracketLegAdjuster] no legs found for parent %s", parent_id)
            return

        replaced_any = False
        for label, leg in (("take_profit", tp), ("stop_loss", sl)):
            if leg is None:
                continue
            leg_status = leg.status
            status_val = leg_status.value if hasattr(leg_status, "value") else str(leg_status)
            leg_status_enum = next(
                (s for s in OrderStatus if s.value == status_val), None
            )
            if leg_status_enum not in _ACTIVE_STATUSES:
                logger.info(
                    "[BracketLegAdjuster] skipping %s leg %s (status=%s)",
                    label, leg.id, status_val,
                )
                continue

            result = AlpacaUtils.replace_order_qty(str(leg.id), filled_qty)
            if result["success"]:
                logger.info(
                    "[BracketLegAdjuster] resized %s leg %s → qty=%d",
                    label, leg.id, filled_qty,
                )
                replaced_any = True
            else:
                # 422 from Alpaca means qty already matches — treat as success
                err = result.get("error", "")
                if "422" in str(err) or "unprocessable" in str(err).lower():
                    logger.info(
                        "[BracketLegAdjuster] %s leg %s already at qty=%d (422)",
                        label, leg.id, filled_qty,
                    )
                    replaced_any = True
                else:
                    logger.error(
                        "[BracketLegAdjuster] failed to resize %s leg %s: %s",
                        label, leg.id, err,
                    )

        if not replaced_any:
            logger.error(
                "[BracketLegAdjuster] no legs resized for %s — leaving parent open",
                parent_id,
            )
            return

        # Cancel the remaining unfilled parent qty to activate the legs.
        parent_status = parent_order.status
        status_val = parent_status.value if hasattr(parent_status, "value") else str(parent_status)
        if status_val == OrderStatus.PARTIALLY_FILLED.value:
            try:
                from alpaca.trading.client import TradingClient as _TC  # noqa: F401
                client = _get_client()
                client.cancel_order_by_id(parent_id)
                logger.info(
                    "[BracketLegAdjuster] cancelled remaining parent qty for %s", parent_id
                )
            except Exception as exc:
                logger.error(
                    "[BracketLegAdjuster] failed to cancel parent %s: %s", parent_id, exc
                )

    def sweep_open_partials(self) -> None:
        """On startup, process any scanner bracket parents already partially filled."""
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            client = _get_client()
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100, nested=True)
            orders = list(client.get_orders(req))
        except Exception as exc:
            logger.error("[BracketLegAdjuster] startup sweep failed: %s", exc)
            return

        for order in orders:
            cid = getattr(order, "client_order_id", "") or ""
            if not cid.startswith(_SCANNER_PREFIX):
                continue
            class_val = (order.order_class.value
                         if hasattr(order.order_class, "value")
                         else str(order.order_class))
            if class_val != OrderClass.BRACKET.value:
                continue
            status_val = (order.status.value
                          if hasattr(order.status, "value")
                          else str(order.status))
            if status_val != OrderStatus.PARTIALLY_FILLED.value:
                continue
            try:
                filled_qty = int(float(order.filled_qty or 0))
            except (TypeError, ValueError):
                filled_qty = 0
            if filled_qty > 0:
                logger.info("[BracketLegAdjuster] sweep: processing partial %s", order.id)
                self._adjust(str(order.id), filled_qty, order)


def _get_client():
    from alpaca.trading.client import TradingClient
    api_key = get_api_key("alpaca_api_key", "ALPACA_API_KEY")
    secret_key = get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
    use_paper_str = get_api_key("alpaca_use_paper", "ALPACA_USE_PAPER")
    use_paper = use_paper_str.lower() == "true" if use_paper_str else True
    return TradingClient(api_key, secret_key, paper=use_paper)


def _stream_thread(adjuster: BracketLegAdjuster) -> None:
    global _stream
    backoff = 5
    while True:
        try:
            api_key = get_api_key("alpaca_api_key", "ALPACA_API_KEY")
            secret_key = get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
            use_paper_str = get_api_key("alpaca_use_paper", "ALPACA_USE_PAPER")
            use_paper = use_paper_str.lower() == "true" if use_paper_str else True

            adjuster.sweep_open_partials()

            stream = TradingStream(api_key, secret_key, paper=use_paper)
            _stream = stream
            stream.subscribe_trade_updates(adjuster.on_trade_update)
            logger.info("[BracketLegAdjuster] websocket connected (paper=%s)", use_paper)
            backoff = 5
            stream.run()
        except Exception as exc:
            logger.error(
                "[BracketLegAdjuster] stream error: %s — reconnecting in %ds", exc, backoff
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def start_bracket_leg_adjuster() -> None:
    """Start the trade-update stream in a background daemon thread. Idempotent."""
    global _started
    with _started_lock:
        if _started:
            return
        _started = True

    adjuster = BracketLegAdjuster()
    t = threading.Thread(target=_stream_thread, args=(adjuster,), daemon=True, name="bracket-leg-adjuster")
    t.start()
    logger.info("[BracketLegAdjuster] background thread started")


def stop_bracket_leg_adjuster() -> None:
    """Stop the websocket stream gracefully."""
    global _stream
    if _stream is not None:
        try:
            _stream.stop()
            logger.info("[BracketLegAdjuster] stream stopped")
        except Exception as exc:
            logger.error("[BracketLegAdjuster] error stopping stream: %s", exc)
