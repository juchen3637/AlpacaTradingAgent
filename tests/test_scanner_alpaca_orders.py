"""Unit tests for AlpacaUtils.get_scanner_orders.

We mock `get_alpaca_trading_client` so we don't hit Alpaca during tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.alpaca_utils import AlpacaUtils


def _mk_order(*, client_order_id, symbol="NVDA", side="buy",
              filled_avg_price=None, filled_qty=None,
              filled_at=None, submitted_at=None, status="filled"):
    """Build a stand-in order object that quacks like the alpaca-py response."""
    return SimpleNamespace(
        client_order_id=client_order_id,
        symbol=symbol,
        side=SimpleNamespace(value=side),
        status=SimpleNamespace(value=status),
        filled_avg_price=filled_avg_price,
        filled_qty=filled_qty,
        filled_at=filled_at,
        submitted_at=submitted_at,
    )


def _patch_client_orders(orders):
    """Helper: patch get_alpaca_trading_client so .get_orders() returns `orders`."""
    fake_client = MagicMock()
    fake_client.get_orders.return_value = orders
    return patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=fake_client,
    )


@pytest.mark.unit
def test_filters_only_scanner_prefixed_orders():
    now = datetime.now(timezone.utc)
    orders = [
        _mk_order(client_order_id="scanner:VWAP_RECLAIM:abc123",
                  filled_avg_price=1.63, filled_qty=100, filled_at=now),
        _mk_order(client_order_id="manual-trade-42",
                  filled_avg_price=2.10, filled_qty=50, filled_at=now),
        _mk_order(client_order_id="scanner:ORB:xyz789",
                  filled_avg_price=2.50, filled_qty=200, filled_at=now),
    ]
    with _patch_client_orders(orders):
        result = AlpacaUtils.get_scanner_orders(since_minutes=60)
    assert len(result) == 2
    cids = {r["client_order_id"] for r in result}
    assert all(c.startswith("scanner:") for c in cids)


@pytest.mark.unit
def test_filters_by_symbol_when_provided():
    now = datetime.now(timezone.utc)
    orders = [
        _mk_order(client_order_id="scanner:s:1", symbol="NVDA",
                  filled_avg_price=100.0, filled_qty=10, filled_at=now),
        _mk_order(client_order_id="scanner:s:2", symbol="AAPL",
                  filled_avg_price=200.0, filled_qty=5, filled_at=now),
    ]
    with _patch_client_orders(orders):
        result = AlpacaUtils.get_scanner_orders(symbol="NVDA", since_minutes=60)
    assert len(result) == 1
    assert result[0]["symbol"] == "NVDA"


@pytest.mark.unit
def test_filters_out_stale_orders_outside_window():
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    orders = [
        _mk_order(client_order_id="scanner:s:fresh",
                  filled_avg_price=1.0, filled_qty=10, filled_at=now),
        _mk_order(client_order_id="scanner:s:stale",
                  filled_avg_price=2.0, filled_qty=20, filled_at=old),
    ]
    with _patch_client_orders(orders):
        result = AlpacaUtils.get_scanner_orders(since_minutes=10)
    assert len(result) == 1
    assert result[0]["client_order_id"].endswith("fresh")


@pytest.mark.unit
def test_skips_unfilled_orders():
    """Orders without a fill price shouldn't produce a chart marker."""
    now = datetime.now(timezone.utc)
    orders = [
        _mk_order(client_order_id="scanner:s:1",
                  filled_avg_price=None, filled_qty=None,
                  submitted_at=now, status="new"),
        _mk_order(client_order_id="scanner:s:2",
                  filled_avg_price=1.5, filled_qty=10, filled_at=now,
                  status="filled"),
    ]
    with _patch_client_orders(orders):
        result = AlpacaUtils.get_scanner_orders(since_minutes=60)
    assert len(result) == 1
    assert result[0]["price"] == 1.5


@pytest.mark.unit
def test_swallows_alpaca_errors_returns_empty_list():
    fake_client = MagicMock()
    fake_client.get_orders.side_effect = RuntimeError("alpaca down")
    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=fake_client,
    ):
        result = AlpacaUtils.get_scanner_orders()
    assert result == []


@pytest.mark.unit
def test_returns_chart_consumable_shape():
    now = datetime.now(timezone.utc)
    orders = [_mk_order(
        client_order_id="scanner:VWAP_RECLAIM:abc",
        symbol="NVDA",
        side="buy",
        filled_avg_price=1.63,
        filled_qty=100,
        filled_at=now,
        status="filled",
    )]
    with _patch_client_orders(orders):
        result = AlpacaUtils.get_scanner_orders(since_minutes=60)
    assert len(result) == 1
    row = result[0]
    # Keys consumed by _apply_fill_markers
    assert set(row.keys()) >= {"price", "qty", "time", "side", "status"}
    assert row["price"] == 1.63
    assert row["qty"] == 100
    assert row["side"] == "buy"
    assert row["status"] == "filled"
