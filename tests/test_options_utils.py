"""
tests/test_options_utils.py — data-layer tests for the Alpaca options fetcher.

The Alpaca clients are mocked; no network calls are made. Pure parsing helpers
(OCC symbol parsing, ATM selection) are exercised directly.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from tradingagents.dataflows import options_utils as ou


# ─── OCC symbol parsing ─────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_occ_symbol_call():
    strike, side, expiry = ou.parse_occ_symbol("DRI260717C00250000")
    assert strike == pytest.approx(250.0)
    assert side == "call"
    assert expiry == date(2026, 7, 17)


@pytest.mark.unit
def test_parse_occ_symbol_put_fractional_strike():
    strike, side, expiry = ou.parse_occ_symbol("SPY240119P00475500")
    assert strike == pytest.approx(475.5)
    assert side == "put"
    assert expiry == date(2024, 1, 19)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", "SHORT", "DRI260717X00250000XXX" * 0 + "ABC"])
def test_parse_occ_symbol_malformed_returns_none(bad):
    assert ou.parse_occ_symbol(bad) is None


@pytest.mark.unit
def test_parse_occ_symbol_multichar_underlying():
    strike, side, expiry = ou.parse_occ_symbol("AAPL250627C00220000")
    assert strike == pytest.approx(220.0)
    assert side == "call"


# ─── ATM selection ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_atm_quotes_selects_nearest_strike_above(monkeypatch):
    chain = [
        {"strike": 215.0, "side": "call", "bid": 10.0, "ask": 10.5, "iv": 0.4},
        {"strike": 220.0, "side": "call", "bid": 8.5, "ask": 8.90, "iv": 0.4},
        {"strike": 220.0, "side": "put", "bid": 9.2, "ask": 9.50, "iv": 0.4},
        {"strike": 215.0, "side": "put", "bid": 6.0, "ask": 6.4, "iv": 0.4},
    ]
    monkeypatch.setattr(ou, "get_option_chain_quotes", lambda *a, **k: chain)
    atm = ou.get_atm_quotes("DRI", 218.10, "2026-07-17")
    assert atm["atm_strike"] == 220.0
    assert atm["call_ask"] == pytest.approx(8.90)
    assert atm["put_ask"] == pytest.approx(9.50)


@pytest.mark.unit
def test_get_atm_quotes_missing_side_returns_none(monkeypatch):
    chain = [{"strike": 220.0, "side": "call", "bid": 8.5, "ask": 8.90, "iv": 0.4}]
    monkeypatch.setattr(ou, "get_option_chain_quotes", lambda *a, **k: chain)
    atm = ou.get_atm_quotes("DRI", 218.10, "2026-07-17")
    assert atm["call_ask"] == pytest.approx(8.90)
    assert atm["put_ask"] is None


# ─── Expirations enumeration (mocked trading client) ────────────────────


@pytest.mark.unit
def test_get_option_expirations_dedupes_and_sorts(monkeypatch):
    contracts = [
        SimpleNamespace(expiration_date=date(2026, 7, 17)),
        SimpleNamespace(expiration_date=date(2026, 6, 27)),
        SimpleNamespace(expiration_date=date(2026, 7, 17)),
        SimpleNamespace(expiration_date=date(2026, 6, 18)),
    ]
    fake_client = SimpleNamespace(
        get_option_contracts=lambda req: SimpleNamespace(option_contracts=contracts, next_page_token=None)
    )
    monkeypatch.setattr(ou, "get_alpaca_trading_client", lambda: fake_client)
    exps = ou.get_option_expirations.__wrapped__("DRI")  # bypass cache decorator
    assert exps == ["2026-06-18", "2026-06-27", "2026-07-17"]


@pytest.mark.unit
def test_get_option_expirations_requests_future_window(monkeypatch):
    # Regression: Alpaca returns ONLY the nearest expiration unless expiration_date_gte
    # is supplied, so the request must carry a today→+window date filter.
    captured = {}

    def capture(req):
        captured["gte"] = req.expiration_date_gte
        captured["lte"] = req.expiration_date_lte
        return SimpleNamespace(option_contracts=[], next_page_token=None)

    fake_client = SimpleNamespace(get_option_contracts=capture)
    monkeypatch.setattr(ou, "get_alpaca_trading_client", lambda: fake_client)
    ou.get_option_expirations.__wrapped__("SPY")
    assert captured["gte"] is not None
    assert captured["lte"] is not None
    assert captured["lte"] > captured["gte"]


# ─── Chain quote parsing (mocked data client) ───────────────────────────


@pytest.mark.unit
def test_get_option_chain_quotes_parses_snapshots(monkeypatch):
    snapshots = {
        "DRI260717C00250000": SimpleNamespace(
            latest_quote=SimpleNamespace(bid_price=1.9, ask_price=2.0), implied_volatility=0.45
        ),
        "DRI260717P00185000": SimpleNamespace(
            latest_quote=SimpleNamespace(bid_price=1.4, ask_price=1.5), implied_volatility=0.5
        ),
        "DRI260717C00260000": SimpleNamespace(latest_quote=None, implied_volatility=None),  # dropped
    }
    fake_client = SimpleNamespace(get_option_chain=lambda req: snapshots)
    monkeypatch.setattr(ou, "get_alpaca_option_data_client", lambda: fake_client)
    rows = ou.get_option_chain_quotes("DRI", "2026-07-17")
    by_key = {(r["strike"], r["side"]): r for r in rows}
    assert (250.0, "call") in by_key
    assert (185.0, "put") in by_key
    assert (260.0, "call") not in by_key  # no quote → excluded
    assert by_key[(250.0, "call")]["ask"] == pytest.approx(2.0)


@pytest.mark.unit
def test_get_option_chain_quotes_carries_occ_symbol(monkeypatch):
    # The OCC contract symbol must survive into each row — it is what the order
    # layer needs to actually trade the contract.
    snapshots = {
        "DRI260717C00250000": SimpleNamespace(
            latest_quote=SimpleNamespace(bid_price=1.9, ask_price=2.0), implied_volatility=0.45
        ),
    }
    fake_client = SimpleNamespace(get_option_chain=lambda req: snapshots)
    monkeypatch.setattr(ou, "get_alpaca_option_data_client", lambda: fake_client)
    rows = ou.get_option_chain_quotes("DRI", "2026-07-17")
    assert rows[0]["symbol"] == "DRI260717C00250000"
