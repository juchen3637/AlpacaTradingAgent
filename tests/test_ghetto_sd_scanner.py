"""
tests/test_ghetto_sd_scanner.py — unit tests for the Ghetto SD scan orchestration.

The orchestrator does the network fan-out; here every fetcher is faked so the
pipeline (price → expirations → chain → analyze → evaluate) is exercised with
zero I/O. Only qualifying tickers come back, ranked.
"""

from __future__ import annotations

from datetime import date

import pytest

from tradingagents.analytics.ghetto_sd import ScanCriteria
from tradingagents.analytics.ghetto_sd_scanner import scan_tickers

TODAY = date(2026, 6, 18)
CRIT = ScanCriteria(min_suitability=6, max_2sd_cost=100.0)


def _good_chain(price: float):
    """ATM strike at/above price plus in-zone Valid Play legs on both sides (strangle)."""
    one_sd = 9.0 + 9.0  # call+put ATM asks below → 1SD 18, 2SD 36
    upside = price + 2 * one_sd
    downside = price - 2 * one_sd
    chain = [
        {"strike": round(price), "side": "call", "bid": 8.9, "ask": 9.0},
        {"strike": round(price), "side": "put", "bid": 8.9, "ask": 9.0},
        {"strike": round(upside), "side": "call", "bid": 0.75, "ask": 0.80},  # $80 valid call, in-zone
    ]
    if downside > 0:
        chain.append({"strike": round(downside), "side": "put", "bid": 0.75, "ask": 0.80})  # $80 valid put
    return chain


def _fakes(prices: dict, chains: dict, expirations: dict | None = None, earnings: dict | None = None):
    exps = expirations or {s: ["2026-06-27"] for s in prices}
    earn = earnings or {}

    def price_fetcher(sym):
        return prices.get(sym)

    def expirations_fetcher(sym):
        return exps.get(sym, [])

    def chain_fetcher(sym, expiration):
        return chains.get(sym, [])

    def earnings_fetcher(sym):
        return earn.get(sym)

    return dict(
        price_fetcher=price_fetcher,
        expirations_fetcher=expirations_fetcher,
        chain_fetcher=chain_fetcher,
        earnings_fetcher=earnings_fetcher,
    )


@pytest.mark.unit
def test_scan_returns_only_qualifiers():
    prices = {"AAA": 220.0, "BBB": 30.0}  # AAA qualifies, BBB too cheap → fails
    chains = {"AAA": _good_chain(220.0), "BBB": _good_chain(30.0)}
    results = scan_tickers(["AAA", "BBB"], TODAY, criteria=CRIT, **_fakes(prices, chains))
    tickers = [r.ticker for r in results]
    assert tickers == ["AAA"]
    assert results[0].qualifies is True
    assert results[0].call_leg is not None and results[0].put_leg is not None


@pytest.mark.unit
def test_scan_enriches_earnings_date():
    prices = {"AAA": 220.0}
    chains = {"AAA": _good_chain(220.0)}
    fakes = _fakes(prices, chains, earnings={"AAA": "2026-06-25"})
    results = scan_tickers(["AAA"], TODAY, criteria=CRIT, **fakes)
    assert results[0].earnings_date == date(2026, 6, 25)


@pytest.mark.unit
def test_scan_earnings_none_when_unavailable():
    prices = {"AAA": 220.0}
    chains = {"AAA": _good_chain(220.0)}
    # earnings map empty → fetcher returns None; scan still succeeds.
    results = scan_tickers(["AAA"], TODAY, criteria=CRIT, **_fakes(prices, chains))
    assert results[0].earnings_date is None


@pytest.mark.unit
def test_scan_ranks_by_suitability_then_cost():
    # Two qualifiers; HI scores 10 (price>150), LO scores lower (price<150, no bonuses).
    prices = {"HI": 220.0, "LO": 120.0}
    chains = {"HI": _good_chain(220.0), "LO": _good_chain(120.0)}
    results = scan_tickers(["LO", "HI"], TODAY, criteria=CRIT, **_fakes(prices, chains))
    assert [r.ticker for r in results] == ["HI", "LO"]
    assert results[0].analysis.suitability.score >= results[1].analysis.suitability.score


@pytest.mark.unit
def test_scan_skips_below_price_floor():
    prices = {"HI": 220.0, "LOW": 12.0}
    chains = {"HI": _good_chain(220.0), "LOW": _good_chain(12.0)}
    results = scan_tickers(
        ["HI", "LOW"], TODAY, criteria=CRIT, min_price=20.0, **_fakes(prices, chains)
    )
    assert [r.ticker for r in results] == ["HI"]  # LOW is under the $20 floor


@pytest.mark.unit
def test_scan_skips_missing_price():
    prices = {"AAA": None}
    chains = {"AAA": _good_chain(220.0)}
    results = scan_tickers(["AAA"], TODAY, criteria=CRIT, **_fakes(prices, chains))
    assert results == []


@pytest.mark.unit
def test_scan_skips_no_usable_expiration():
    prices = {"AAA": 220.0}
    chains = {"AAA": _good_chain(220.0)}
    fakes = _fakes(prices, chains, expirations={"AAA": ["2026-06-18"]})  # 0 DTE only
    results = scan_tickers(["AAA"], TODAY, criteria=CRIT, **fakes)
    assert results == []


@pytest.mark.unit
def test_scan_skips_empty_chain():
    prices = {"AAA": 220.0}
    results = scan_tickers(["AAA"], TODAY, criteria=CRIT, **_fakes(prices, {"AAA": []}))
    assert results == []


@pytest.mark.unit
def test_scan_survives_fetcher_exception():
    prices = {"AAA": 220.0, "BBB": 220.0}
    chains = {"AAA": _good_chain(220.0), "BBB": _good_chain(220.0)}
    fakes = _fakes(prices, chains)

    def boom(sym):
        if sym == "BBB":
            raise RuntimeError("alpaca exploded")
        return prices[sym]

    fakes["price_fetcher"] = boom
    results = scan_tickers(["AAA", "BBB"], TODAY, criteria=CRIT, **fakes)
    assert [r.ticker for r in results] == ["AAA"]  # BBB's exception is swallowed, AAA still returned
