"""
tests/test_ghetto_sd_journal.py — building journal records from a placed Ghetto SD
strangle. Pure record-shaping; no DB or Dash involved.
"""

from __future__ import annotations

import pytest

from tradingagents.analytics.ghetto_sd_journal import build_strangle_records


def _payload(ticker="AAPL"):
    return {
        "ticker": ticker,
        "call": {"symbol": "AAPL260622C00305000", "side": "call", "strike": 305.0, "ask": 0.21},
        "put": {"symbol": "AAPL260622P00290000", "side": "put", "strike": 290.0, "ask": 0.26},
    }


def _ok(order_id, symbol):
    return {"success": True, "order_id": order_id, "symbol": symbol, "status": "accepted"}


def _fail(error="rejected"):
    return {"success": False, "error": error}


@pytest.mark.unit
def test_both_legs_make_one_decision_and_two_trades():
    results = {"call": _ok("oid-call", "AAPL260622C00305000"),
               "put": _ok("oid-put", "AAPL260622P00290000")}
    out = build_strangle_records(_payload(), results, qty=1,
                                 call_limit=0.21, put_limit=0.26, timestamp="2026-06-18T20:00:00")
    assert out is not None
    decision, trades = out
    assert decision.ticker == "AAPL"
    assert decision.source == "ghetto_sd"
    assert decision.signal == "STRANGLE"
    assert len(trades) == 2
    assert {t.alpaca_order_id for t in trades} == {"oid-call", "oid-put"}
    assert all(t.side == "buy" and t.order_type == "limit" for t in trades)


@pytest.mark.unit
def test_position_size_is_total_debit():
    results = {"call": _ok("c", "C"), "put": _ok("p", "P")}
    decision, _ = build_strangle_records(_payload(), results, qty=2,
                                         call_limit=0.21, put_limit=0.26, timestamp="t")
    # (0.21 + 0.26) * 100 * 2 = 94.0
    assert decision.position_size_dollars == pytest.approx(94.0)


@pytest.mark.unit
def test_dedup_id_set_from_first_successful_leg():
    results = {"call": _ok("oid-call", "C"), "put": _ok("oid-put", "P")}
    decision, _ = build_strangle_records(_payload(), results, qty=1,
                                         call_limit=0.21, put_limit=0.26, timestamp="t")
    assert decision.source_order_id == "oid-call"


@pytest.mark.unit
def test_partial_success_records_only_filled_leg():
    results = {"call": _ok("oid-call", "C"), "put": _fail("insufficient buying power")}
    out = build_strangle_records(_payload(), results, qty=1,
                                 call_limit=0.21, put_limit=0.26, timestamp="t")
    assert out is not None
    _, trades = out
    assert len(trades) == 1
    assert trades[0].alpaca_order_id == "oid-call"


@pytest.mark.unit
def test_no_successful_leg_returns_none():
    results = {"call": _fail(), "put": _fail()}
    assert build_strangle_records(_payload(), results, qty=1,
                                  call_limit=0.21, put_limit=0.26, timestamp="t") is None


@pytest.mark.unit
def test_final_decision_mentions_both_legs():
    results = {"call": _ok("c", "C"), "put": _ok("p", "P")}
    decision, _ = build_strangle_records(_payload(), results, qty=1,
                                         call_limit=0.21, put_limit=0.26, timestamp="t")
    assert "AAPL260622C00305000" in decision.final_decision
    assert "AAPL260622P00290000" in decision.final_decision
