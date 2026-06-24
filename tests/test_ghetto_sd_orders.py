"""
tests/test_ghetto_sd_orders.py — unit tests for the options order layer used by
the Ghetto SD strangle executor.

The Alpaca trading client is mocked; no network calls are made. We assert the
request fields (OCC symbol, side, qty, limit price) and the result envelope.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.alpaca_utils import AlpacaUtils


def _fake_order(order_id="opt-1", symbol="AAPL260620C00185000", qty="1", status="accepted"):
    return SimpleNamespace(
        id=order_id, symbol=symbol, side=SimpleNamespace(value="buy"),
        qty=qty, status=SimpleNamespace(value=status),
    )


def _patch_client(submit_capture):
    fake = MagicMock()
    fake.submit_order.side_effect = submit_capture
    return patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=fake,
    )


@pytest.mark.unit
def test_place_option_limit_order_builds_request():
    captured = {}

    def submit(req):
        captured["symbol"] = req.symbol
        captured["side"] = req.side
        captured["qty"] = req.qty
        captured["limit_price"] = req.limit_price
        return _fake_order(symbol=req.symbol)

    with _patch_client(submit):
        res = AlpacaUtils.place_option_limit_order(
            "AAPL260620C00185000", side="buy", qty=2, limit_price=0.804
        )
    assert captured["symbol"] == "AAPL260620C00185000"
    assert captured["qty"] == 2
    assert captured["limit_price"] == pytest.approx(0.80)  # rounded to cents
    assert res["success"] is True
    assert res["order_id"] == "opt-1"


@pytest.mark.unit
@pytest.mark.parametrize("qty,limit", [(0, 0.80), (-1, 0.80), (1, 0), (1, -0.5)])
def test_place_option_limit_order_rejects_bad_inputs(qty, limit):
    with _patch_client(lambda req: _fake_order()) as _:
        res = AlpacaUtils.place_option_limit_order("AAPL260620C00185000", "buy", qty, limit)
    assert res["success"] is False


@pytest.mark.unit
def test_place_option_limit_order_swallows_alpaca_error():
    def boom(req):
        raise RuntimeError("alpaca rejected")

    with _patch_client(boom):
        res = AlpacaUtils.place_option_limit_order("AAPL260620C00185000", "buy", 1, 0.80)
    assert res["success"] is False
    assert "alpaca rejected" in res["error"]


@pytest.mark.unit
def test_place_strangle_submits_both_legs():
    submitted = []

    def submit(req):
        submitted.append((req.symbol, req.limit_price, req.qty))
        return _fake_order(symbol=req.symbol)

    with _patch_client(submit):
        res = AlpacaUtils.place_strangle(
            call_symbol="AAPL260620C00185000", call_limit=0.80,
            put_symbol="AAPL260620P00160000", put_limit=0.75, qty=1,
        )
    assert len(submitted) == 2
    symbols = {s[0] for s in submitted}
    assert symbols == {"AAPL260620C00185000", "AAPL260620P00160000"}
    assert res["call"]["success"] is True
    assert res["put"]["success"] is True


@pytest.mark.unit
def test_place_strangle_reports_per_leg_failure():
    def submit(req):
        if req.symbol.endswith("P00160000"):
            raise RuntimeError("put leg rejected")
        return _fake_order(symbol=req.symbol)

    with _patch_client(submit):
        res = AlpacaUtils.place_strangle(
            call_symbol="AAPL260620C00185000", call_limit=0.80,
            put_symbol="AAPL260620P00160000", put_limit=0.75, qty=1,
        )
    assert res["call"]["success"] is True
    assert res["put"]["success"] is False
