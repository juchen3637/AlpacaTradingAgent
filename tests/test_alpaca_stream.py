"""Tests for tradingagents/dataflows/alpaca_stream.py"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.alpaca_stream import BracketLegAdjuster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(
    order_id="parent-1",
    symbol="BYAH",
    cid="scanner:BYAH-1",
    order_class="bracket",
    status="partially_filled",
    filled_qty="999",
    legs=None,
):
    o = SimpleNamespace(
        id=order_id,
        symbol=symbol,
        client_order_id=cid,
        order_class=SimpleNamespace(value=order_class),
        status=SimpleNamespace(value=status),
        filled_qty=filled_qty,
        legs=legs or [],
    )
    return o


def _make_leg(leg_id, order_type, status="new"):
    return SimpleNamespace(
        id=leg_id,
        type=SimpleNamespace(value=order_type),
        status=SimpleNamespace(value=status),
    )


def _make_trade_update(order, event="partial_fill"):
    return SimpleNamespace(
        order=order,
        event=SimpleNamespace(value=event),
    )


# ---------------------------------------------------------------------------
# Route: scanner bracket partial_fill → legs resized + parent cancelled
# ---------------------------------------------------------------------------

def test_partial_fill_resizes_legs_and_cancels_parent():
    adjuster = BracketLegAdjuster()
    order = _make_order()
    update = _make_trade_update(order)

    tp_leg = _make_leg("leg-tp", "limit")
    sl_leg = _make_leg("leg-sl", "stop")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result) as mock_legs, \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty", return_value={"success": True, "order_id": "x"}) as mock_replace, \
         patch("tradingagents.dataflows.alpaca_stream._get_client") as mock_client:

        adjuster._handle(update)

        mock_legs.assert_called_once_with("parent-1")
        assert mock_replace.call_count == 2
        mock_replace.assert_any_call("leg-tp", 999)
        mock_replace.assert_any_call("leg-sl", 999)
        mock_client.return_value.cancel_order_by_id.assert_called_once_with("parent-1")


# ---------------------------------------------------------------------------
# Route: non-scanner order → no action
# ---------------------------------------------------------------------------

def test_non_scanner_order_ignored():
    adjuster = BracketLegAdjuster()
    order = _make_order(cid="manual:BYAH-1")
    update = _make_trade_update(order)

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs") as mock_legs:
        adjuster._handle(update)
        mock_legs.assert_not_called()


# ---------------------------------------------------------------------------
# Route: bracket child leg event → no action (child has simple order_class)
# ---------------------------------------------------------------------------

def test_bracket_child_leg_event_ignored():
    adjuster = BracketLegAdjuster()
    order = _make_order(order_class="simple")
    update = _make_trade_update(order)

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs") as mock_legs:
        adjuster._handle(update)
        mock_legs.assert_not_called()


# ---------------------------------------------------------------------------
# Route: partial_fill with filled_qty == 0 → no action
# ---------------------------------------------------------------------------

def test_zero_filled_qty_ignored():
    adjuster = BracketLegAdjuster()
    order = _make_order(filled_qty="0")
    update = _make_trade_update(order)

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs") as mock_legs:
        adjuster._handle(update)
        mock_legs.assert_not_called()


# ---------------------------------------------------------------------------
# Route: one leg already cancelled → skip it, still replace the other
# ---------------------------------------------------------------------------

def test_cancelled_leg_skipped_other_replaced():
    adjuster = BracketLegAdjuster()
    order = _make_order()
    update = _make_trade_update(order)

    tp_leg = _make_leg("leg-tp", "limit", status="canceled")
    sl_leg = _make_leg("leg-sl", "stop", status="new")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result), \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty", return_value={"success": True, "order_id": "x"}) as mock_replace, \
         patch("tradingagents.dataflows.alpaca_stream._get_client"):

        adjuster._handle(update)
        # only SL leg should be replaced
        mock_replace.assert_called_once_with("leg-sl", 999)


# ---------------------------------------------------------------------------
# Route: both replace calls fail → parent NOT cancelled
# ---------------------------------------------------------------------------

def test_both_replace_fail_parent_not_cancelled():
    adjuster = BracketLegAdjuster()
    order = _make_order()
    update = _make_trade_update(order)

    tp_leg = _make_leg("leg-tp", "limit")
    sl_leg = _make_leg("leg-sl", "stop")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result), \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty", return_value={"success": False, "error": "500 server error"}) as mock_replace, \
         patch("tradingagents.dataflows.alpaca_stream._get_client") as mock_client:

        adjuster._handle(update)
        assert mock_replace.call_count == 2
        mock_client.return_value.cancel_order_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency: same (parent_id, filled_qty) processed only once
# ---------------------------------------------------------------------------

def test_duplicate_event_is_noop():
    adjuster = BracketLegAdjuster()
    order = _make_order()
    update = _make_trade_update(order)

    tp_leg = _make_leg("leg-tp", "limit")
    sl_leg = _make_leg("leg-sl", "stop")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result) as mock_legs, \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty", return_value={"success": True, "order_id": "x"}), \
         patch("tradingagents.dataflows.alpaca_stream._get_client"):

        adjuster._handle(update)
        adjuster._handle(update)  # duplicate

        # get_bracket_legs called only once
        assert mock_legs.call_count == 1


# ---------------------------------------------------------------------------
# Idempotency: different filled_qty (second partial fill) IS processed
# ---------------------------------------------------------------------------

def test_second_partial_fill_different_qty_processed():
    adjuster = BracketLegAdjuster()
    tp_leg = _make_leg("leg-tp", "limit")
    sl_leg = _make_leg("leg-sl", "stop")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result) as mock_legs, \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty", return_value={"success": True, "order_id": "x"}), \
         patch("tradingagents.dataflows.alpaca_stream._get_client"):

        order1 = _make_order(filled_qty="500")
        adjuster._handle(_make_trade_update(order1))

        order2 = _make_order(filled_qty="999")
        adjuster._handle(_make_trade_update(order2))

        assert mock_legs.call_count == 2


# ---------------------------------------------------------------------------
# Route: fill event (not partial_fill) → no action
# ---------------------------------------------------------------------------

def test_full_fill_event_ignored():
    adjuster = BracketLegAdjuster()
    order = _make_order(status="filled")
    update = _make_trade_update(order, event="fill")

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs") as mock_legs:
        adjuster._handle(update)
        mock_legs.assert_not_called()


# ---------------------------------------------------------------------------
# 422 from Alpaca on replace treated as success
# ---------------------------------------------------------------------------

def test_422_replace_treated_as_success_and_parent_cancelled():
    adjuster = BracketLegAdjuster()
    order = _make_order()
    update = _make_trade_update(order)

    tp_leg = _make_leg("leg-tp", "limit")
    sl_leg = _make_leg("leg-sl", "stop")
    legs_result = {"take_profit": tp_leg, "stop_loss": sl_leg}

    with patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.get_bracket_legs", return_value=legs_result), \
         patch("tradingagents.dataflows.alpaca_stream.AlpacaUtils.replace_order_qty",
               return_value={"success": False, "error": "422 Unprocessable Entity"}) as mock_replace, \
         patch("tradingagents.dataflows.alpaca_stream._get_client") as mock_client:

        adjuster._handle(update)
        assert mock_replace.call_count == 2
        # 422s count as success, parent should still be cancelled
        mock_client.return_value.cancel_order_by_id.assert_called_once_with("parent-1")


# ---------------------------------------------------------------------------
# start_bracket_leg_adjuster is idempotent (thread not started twice)
# ---------------------------------------------------------------------------

def test_start_idempotent():
    import tradingagents.dataflows.alpaca_stream as stream_mod

    # Reset module state for isolation
    original_started = stream_mod._started
    stream_mod._started = False

    thread_starts = []

    real_thread = threading.Thread

    class CountingThread(real_thread):
        def start(self):
            thread_starts.append(1)
            # Don't actually run the stream — just record the call
            pass

    with patch("tradingagents.dataflows.alpaca_stream.threading.Thread", CountingThread):
        stream_mod.start_bracket_leg_adjuster()
        stream_mod.start_bracket_leg_adjuster()  # second call — should be no-op

    assert len(thread_starts) == 1

    # Restore
    stream_mod._started = original_started
