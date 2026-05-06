"""Unit tests for AlpacaUtils.get_unfilled_scanner_orders + cancel_unfilled_scanner_order.

We mock `get_alpaca_trading_client` so we don't hit Alpaca during tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.alpaca_utils import AlpacaUtils


def _mk_unfilled_order(
    *,
    order_id="order-id-1",
    client_order_id="scanner:VWAP_RECLAIM:abc",
    symbol="NVDA",
    side="buy",
    qty=100,
    status="new",
    limit_price=None,
    stop_price=None,
    order_type="limit",
):
    return SimpleNamespace(
        id=order_id,
        client_order_id=client_order_id,
        symbol=symbol,
        side=SimpleNamespace(value=side),
        qty=qty,
        status=SimpleNamespace(value=status),
        limit_price=limit_price,
        stop_price=stop_price,
        order_type=SimpleNamespace(value=order_type),
        submitted_at=datetime.now(timezone.utc),
    )


def _patch_client_orders(orders, cancel_side_effect=None):
    fake_client = MagicMock()
    fake_client.get_orders.return_value = orders
    if cancel_side_effect is not None:
        fake_client.cancel_order_by_id.side_effect = cancel_side_effect
    return fake_client, patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=fake_client,
    )


@pytest.mark.unit
def test_get_unfilled_returns_only_scanner_tagged_unfilled():
    orders = [
        _mk_unfilled_order(order_id="o1", client_order_id="scanner:S:1",
                           status="new"),
        _mk_unfilled_order(order_id="o2", client_order_id="manual-99",
                           status="new"),
        _mk_unfilled_order(order_id="o3", client_order_id="scanner:S:2",
                           status="filled"),  # excluded — already filled
        _mk_unfilled_order(order_id="o4", client_order_id="scanner:S:3",
                           status="canceled"),  # excluded
        _mk_unfilled_order(order_id="o5", client_order_id="scanner:S:4",
                           status="partially_filled"),  # included
        _mk_unfilled_order(order_id="o6", client_order_id="scanner:S:5",
                           status="held"),  # included
    ]
    _, ctx = _patch_client_orders(orders)
    with ctx:
        result = AlpacaUtils.get_unfilled_scanner_orders("NVDA")
    ids = {r["id"] for r in result}
    assert ids == {"o1", "o5", "o6"}


@pytest.mark.unit
def test_get_unfilled_returns_chart_consumable_shape():
    orders = [_mk_unfilled_order(
        order_id="abc-123",
        client_order_id="scanner:ORB:xyz",
        symbol="AMD",
        side="buy",
        qty=50,
        status="accepted",
        limit_price=1.62,
        stop_price=None,
        order_type="limit",
    )]
    _, ctx = _patch_client_orders(orders)
    with ctx:
        result = AlpacaUtils.get_unfilled_scanner_orders("AMD")
    assert len(result) == 1
    row = result[0]
    assert set(row.keys()) >= {
        "id", "client_order_id", "symbol", "side", "qty",
        "status", "limit_price", "stop_price", "order_type",
    }
    assert row["id"] == "abc-123"
    assert row["limit_price"] == 1.62
    assert row["stop_price"] is None
    assert row["status"] == "accepted"


@pytest.mark.unit
def test_get_unfilled_swallows_errors_returns_empty():
    fake_client = MagicMock()
    fake_client.get_orders.side_effect = RuntimeError("alpaca down")
    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=fake_client,
    ):
        result = AlpacaUtils.get_unfilled_scanner_orders("NVDA")
    assert result == []


@pytest.mark.unit
def test_cancel_unfilled_no_orders_returns_success_zero():
    _, ctx = _patch_client_orders([])
    with ctx:
        result = AlpacaUtils.cancel_unfilled_scanner_order("NVDA")
    assert result["success"] is True
    assert result["cancelled"] == 0
    assert result["failed"] == 0


@pytest.mark.unit
def test_cancel_unfilled_cancels_each_pending_order():
    orders = [
        _mk_unfilled_order(order_id="o1", client_order_id="scanner:S:1",
                           status="new"),
        _mk_unfilled_order(order_id="o2", client_order_id="scanner:S:2",
                           status="accepted"),
    ]
    fake_client, ctx = _patch_client_orders(orders)
    with ctx:
        result = AlpacaUtils.cancel_unfilled_scanner_order("NVDA")
    assert result["success"] is True
    assert result["cancelled"] == 2
    assert result["failed"] == 0
    assert set(result["cancelled_ids"]) == {"o1", "o2"}
    assert fake_client.cancel_order_by_id.call_count == 2


@pytest.mark.unit
def test_cancel_unfilled_partial_failure_reports_failed_ids():
    orders = [
        _mk_unfilled_order(order_id="o1", client_order_id="scanner:S:1",
                           status="new"),
        _mk_unfilled_order(order_id="o2", client_order_id="scanner:S:2",
                           status="accepted"),
    ]

    def cancel_side(order_id):
        if order_id == "o2":
            raise RuntimeError("422 already filled")
        return None

    _, ctx = _patch_client_orders(orders, cancel_side_effect=cancel_side)
    with ctx:
        result = AlpacaUtils.cancel_unfilled_scanner_order("NVDA")
    assert result["success"] is False
    assert result["cancelled"] == 1
    assert result["failed"] == 1
    assert result["cancelled_ids"] == ["o1"]
    assert any("o2" in e for e in result["errors"])


@pytest.mark.unit
def test_cancel_unfilled_skips_non_scanner_orders():
    orders = [
        _mk_unfilled_order(order_id="o1", client_order_id="manual-99",
                           status="new"),  # not scanner-tagged
        _mk_unfilled_order(order_id="o2", client_order_id="scanner:S:2",
                           status="new"),
    ]
    fake_client, ctx = _patch_client_orders(orders)
    with ctx:
        result = AlpacaUtils.cancel_unfilled_scanner_order("NVDA")
    assert result["cancelled"] == 1
    assert result["cancelled_ids"] == ["o2"]
    fake_client.cancel_order_by_id.assert_called_once_with("o2")
