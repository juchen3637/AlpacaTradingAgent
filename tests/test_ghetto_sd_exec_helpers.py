"""
tests/test_ghetto_sd_exec_helpers.py — pure helpers behind the strangle executor
UI (leg serialization, scan-legs map, debit estimate). No Dash callback wiring is
exercised; just the data-shaping functions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tradingagents.analytics.ghetto_sd_exec import (
    estimate_text as _estimate_text,
    leg_payload as _leg_payload,
    scan_legs_map as _scan_legs_map,
    strangle_payload as _strangle_payload,
)


def _leg(symbol="AAPL260620C00185000", side="call", strike=185.0, ask=0.80):
    return SimpleNamespace(symbol=symbol, side=side, strike=strike, ask=ask)


@pytest.mark.unit
def test_leg_payload_serializes():
    assert _leg_payload(_leg()) == {
        "symbol": "AAPL260620C00185000", "side": "call", "strike": 185.0, "ask": 0.80
    }


@pytest.mark.unit
def test_leg_payload_none_without_symbol():
    assert _leg_payload(None) is None
    assert _leg_payload(_leg(symbol="")) is None


@pytest.mark.unit
def test_strangle_payload_needs_both_legs():
    call = _leg(side="call")
    put = _leg(symbol="AAPL260620P00160000", side="put", strike=160.0, ask=0.75)
    payload = _strangle_payload("AAPL", call, put)
    assert payload["ticker"] == "AAPL"
    assert payload["call"]["symbol"].endswith("C00185000")
    assert payload["put"]["symbol"].endswith("P00160000")

    assert _strangle_payload("AAPL", call, None) is None
    assert _strangle_payload("AAPL", None, put) is None


@pytest.mark.unit
def test_scan_legs_map_keys_by_ticker_and_skips_incomplete():
    full = SimpleNamespace(ticker="AAA", call_leg=_leg(), put_leg=_leg(side="put"))
    half = SimpleNamespace(ticker="BBB", call_leg=_leg(), put_leg=None)
    m = _scan_legs_map([full, half])
    assert set(m) == {"AAA"}
    assert m["AAA"]["call"]["symbol"]


@pytest.mark.unit
def test_estimate_text_computes_debit():
    txt = _estimate_text(0.80, 0.75, 2)
    assert "$310" in txt  # (0.80 + 0.75) * 100 * 2 = 310


@pytest.mark.unit
@pytest.mark.parametrize("qty,c,p", [(0, 0.8, 0.7), (1, 0, 0.7), (1, 0.8, None), ("x", 0.8, 0.7)])
def test_estimate_text_empty_on_bad_input(qty, c, p):
    assert _estimate_text(c, p, qty) == ""
