"""
tradingagents/analytics/ghetto_sd_scanner.py — Ghetto SD ticker scanner.

Sweeps a universe of symbols, runs the pure Ghetto SD engine on each one's
nearest usable (earnings-free) expiration, and returns only the tickers that
clear every ScanCriteria gate, ranked best-first.

All network I/O is isolated behind injectable fetchers so the orchestration is
unit-testable with fakes. The default fetchers wire to Alpaca via the existing
data layer (alpaca_utils / options_utils).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from typing import Callable, Sequence

from ..default_config import DEFAULT_CONFIG
from .ghetto_sd import (
    AnalysisInput,
    CandidateResult,
    GhettoSDConfig,
    ScanCriteria,
    analyze,
    atm_from_chain,
    candidate_contracts,
    evaluate_candidate,
    select_nearest_expiration,
)

logger = logging.getLogger(__name__)

# Strikes within this % of a 2SD target are screened (matches the analyzer UI).
_SHOPPING_BAND_PCT = 15.0

PriceFetcher = Callable[[str], float | None]
ExpirationsFetcher = Callable[[str], Sequence[str]]
ChainFetcher = Callable[[str, str], Sequence[dict]]
EarningsFetcher = Callable[[str], str | None]


# ─── Default Alpaca-backed fetchers ─────────────────────────────────────


def _default_price_fetcher(symbol: str) -> float | None:
    """Mid of the latest quote, or None if unavailable."""
    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    q = AlpacaUtils.get_latest_quote(symbol)
    bid, ask = q.get("bid_price"), q.get("ask_price")
    if bid and ask:
        return round((bid + ask) / 2, 2)
    return None


def _default_expirations_fetcher(symbol: str) -> list[str]:
    from tradingagents.dataflows.options_utils import get_option_expirations

    return get_option_expirations(symbol)


def _default_chain_fetcher(symbol: str, expiration: str) -> list[dict]:
    from tradingagents.dataflows.options_utils import get_option_chain_quotes

    return get_option_chain_quotes(symbol, expiration)


def _default_earnings_fetcher(symbol: str) -> str | None:
    from tradingagents.dataflows.earnings_utils import get_next_earnings_date

    return get_next_earnings_date(symbol)


# ─── Per-ticker pipeline ────────────────────────────────────────────────


def _parse_iso(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _scan_one(
    symbol: str,
    today: date,
    criteria: ScanCriteria,
    cfg: GhettoSDConfig,
    *,
    min_dte: int,
    min_price: float,
    price_fetcher: PriceFetcher,
    expirations_fetcher: ExpirationsFetcher,
    chain_fetcher: ChainFetcher,
) -> CandidateResult | None:
    """Run the full pipeline for one symbol; return a qualifying result or None.

    Any missing data or fetcher error skips the symbol — a scan never aborts on
    a single bad ticker.
    """
    try:
        price = price_fetcher(symbol)
        if not price or price < min_price:
            return None

        expiries = [d for d in (_parse_iso(s) for s in expirations_fetcher(symbol)) if d]
        expiry = select_nearest_expiration(expiries, today, min_dte=min_dte)
        if expiry is None:
            return None

        chain = chain_fetcher(symbol, expiry.isoformat())
        if not chain:
            return None

        atm_strike, call_ask, put_ask = atm_from_chain(chain, price)
        if not call_ask or not put_ask:
            return None

        one_sd = float(call_ask) + float(put_ask)
        contracts = candidate_contracts(chain, price, one_sd, band_pct=_SHOPPING_BAND_PCT)

        inp = AnalysisInput(
            ticker=symbol,
            current_price=float(price),
            earnings_date=None,
            today=today,
            expiry_date=expiry,
            has_e_badge=False,
            atm_strike=float(atm_strike),
            atm_call_ask=float(call_ask),
            atm_put_ask=float(put_ask),
            contracts=tuple(contracts),
        )
        candidate = evaluate_candidate(analyze(inp, cfg=cfg), criteria, price=float(price))
        return candidate if candidate.qualifies else None
    except Exception:
        logger.exception("ghetto SD scan failed for %s", symbol)
        return None


# ─── Orchestration ──────────────────────────────────────────────────────


def scan_tickers(
    symbols: Sequence[str],
    today: date,
    *,
    criteria: ScanCriteria | None = None,
    cfg: GhettoSDConfig | None = None,
    price_fetcher: PriceFetcher = _default_price_fetcher,
    expirations_fetcher: ExpirationsFetcher = _default_expirations_fetcher,
    chain_fetcher: ChainFetcher = _default_chain_fetcher,
    earnings_fetcher: EarningsFetcher = _default_earnings_fetcher,
    min_dte: int | None = None,
    min_price: float | None = None,
    max_workers: int | None = None,
) -> list[CandidateResult]:
    """Scan `symbols` in parallel; return qualifying results ranked best-first.

    Ranking: suitability score descending, then best-play cost ascending.
    """
    criteria = criteria or ScanCriteria.default()
    cfg = cfg or GhettoSDConfig.default()
    scan_cfg = DEFAULT_CONFIG["ghetto_sd_scan"]
    min_dte = scan_cfg["min_dte"] if min_dte is None else min_dte
    min_price = scan_cfg["min_price"] if min_price is None else min_price
    max_workers = scan_cfg["max_workers"] if max_workers is None else max_workers

    if not symbols:
        return []

    results: list[CandidateResult] = []
    with ThreadPoolExecutor(max_workers=min(len(symbols), max_workers)) as pool:
        futures = {
            pool.submit(
                _scan_one,
                sym,
                today,
                criteria,
                cfg,
                min_dte=min_dte,
                min_price=min_price,
                price_fetcher=price_fetcher,
                expirations_fetcher=expirations_fetcher,
                chain_fetcher=chain_fetcher,
            ): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            candidate = future.result()
            if candidate is not None:
                results.append(candidate)

    results.sort(
        key=lambda c: (
            -c.analysis.suitability.score,
            c.strangle_cost if c.strangle_cost is not None else float("inf"),
        )
    )

    # Enrich qualifiers with their next earnings date (display-only; never gates).
    if results:
        with ThreadPoolExecutor(max_workers=min(len(results), max_workers)) as pool:
            futures = {pool.submit(earnings_fetcher, c.ticker): i for i, c in enumerate(results)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    parsed = _parse_iso(future.result())
                except Exception:
                    parsed = None
                if parsed is not None:
                    results[idx] = replace(results[idx], earnings_date=parsed)

    return results


def scan_most_actives(
    today: date,
    *,
    limit: int | None = None,
    criteria: ScanCriteria | None = None,
    cfg: GhettoSDConfig | None = None,
    min_price: float | None = None,
) -> list[CandidateResult]:
    """Resolve the Alpaca most-actives universe and scan it for qualifying tickers."""
    from tradingagents.scanner.models import ScanFilters
    from tradingagents.scanner.universe import build

    limit = DEFAULT_CONFIG["ghetto_sd_scan"]["universe_size"] if limit is None else limit
    symbols = build(ScanFilters(universe_kind="most_active"))[:limit]
    return scan_tickers(symbols, today, criteria=criteria, cfg=cfg, min_price=min_price)
