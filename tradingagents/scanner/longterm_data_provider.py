"""Real DataProvider for the long-term scanner.

Fetches:
  - Quote (Alpaca): last price.
  - Daily bars (Alpaca, 400 days): 50/200-SMA, golden cross, 52wk H/L, 1y return.
  - company_basic_financials (Finnhub): ROE, net margin, revenue 3y CAGR,
    forward P/E, debt/equity, dividend yield.
  - company_profile2 (Finnhub): market cap, sector, industry.

Per-symbol best-effort: any failure returns None or partial data; the
pipeline drops snapshots that fail too many filters.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from tradingagents.dataflows.cache_utils import with_cache

from . import longterm_universe
from .longterm_models import LongTermFilters, LongTermSnapshot

logger = logging.getLogger(__name__)


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _first_present(d: dict, keys: list[str]) -> Optional[float]:
    """Return the first non-None numeric value across `keys`."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            v = _safe_float(d[k])
            if v is not None:
                return v
    return None


@with_cache(cache_category="longterm_fundamentals", max_age_hours=24)
def _fetch_fundamentals(symbol: str, date_key: str) -> dict:
    """Fundamentals from Finnhub `company_basic_financials.metric`.

    Returns dict with keys: roe_ttm, net_margin_ttm, revenue_growth_3y,
    pe_forward, debt_to_equity, dividend_yield_ttm. Missing values are None.
    """
    del date_key
    out = {
        "roe_ttm": None, "net_margin_ttm": None, "revenue_growth_3y": None,
        "pe_forward": None, "debt_to_equity": None, "dividend_yield_ttm": None,
    }
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        resp = client.company_basic_financials(symbol, "all") or {}
        m = resp.get("metric") if isinstance(resp, dict) else None
        if not isinstance(m, dict):
            return out

        # Multi-key fallbacks — Finnhub field names drift.
        out["roe_ttm"] = _first_present(m, [
            "roeTTM", "roeRfy", "roeAnnual",
        ])
        out["net_margin_ttm"] = _first_present(m, [
            "netProfitMarginTTM", "netProfitMarginAnnual",
        ])
        out["revenue_growth_3y"] = _first_present(m, [
            "revenueGrowth3Y", "revenueGrowthTTMYoy", "revenueGrowth5Y",
        ])
        out["pe_forward"] = _first_present(m, [
            "peNormalizedAnnual", "peTTM", "peExclExtraTTM", "peInclExtraTTM",
        ])
        out["debt_to_equity"] = _first_present(m, [
            "totalDebt/totalEquityAnnual", "totalDebt/totalEquityQuarterly",
        ])
        out["dividend_yield_ttm"] = _first_present(m, [
            "currentDividendYieldTTM", "dividendYieldIndicatedAnnual",
        ])
    except Exception as exc:
        logger.debug("longterm fundamentals fetch failed for %s: %s", symbol, exc)
    return out


@with_cache(cache_category="longterm_profile", max_age_hours=24)
def _fetch_profile(symbol: str, date_key: str) -> dict:
    """Market cap (billions), sector, industry from Finnhub `company_profile2`."""
    del date_key
    out: dict[str, Optional[object]] = {
        "market_cap_b": None, "sector": None, "industry": None,
    }
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        prof = client.company_profile2(symbol=symbol) or {}
        # Finnhub returns marketCapitalization in millions.
        mc_m = _safe_float(prof.get("marketCapitalization"))
        if mc_m is not None and mc_m > 0:
            out["market_cap_b"] = mc_m / 1000.0
        # Finnhub's `gicsSector` is the broad GICS sector (e.g. "Information
        # Technology"); `finnhubIndustry` is a finer sub-classification
        # (e.g. "Semiconductors"). Don't conflate the two — the sector
        # exclusion filter and the LLM prompt both read these as distinct.
        sector = prof.get("gicsSector") or prof.get("finnhubIndustry")
        out["sector"] = sector if isinstance(sector, str) and sector else None
        industry = prof.get("finnhubIndustry")
        out["industry"] = industry if isinstance(industry, str) and industry else None
    except Exception as exc:
        logger.debug("longterm profile fetch failed for %s: %s", symbol, exc)
    return out


@with_cache(cache_category="longterm_trend", max_age_hours=24)
def _fetch_trend(symbol: str, date_key: str) -> dict:
    """Long-term trend signals from 400 daily bars."""
    del date_key
    out = {
        "sma_50": None, "sma_200": None, "above_sma_200": False,
        "golden_cross": False, "wk52_high": None, "wk52_low": None,
        "one_year_return_pct": None,
    }
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=400)
        df = AlpacaUtils.get_stock_data(symbol, start.isoformat(), end.isoformat(), "1Day")
        if df is None or df.empty or "close" not in df.columns:
            return out

        closes = df["close"].astype(float)
        last = _safe_float(closes.iloc[-1])
        if last is None:
            return out

        if len(closes) >= 50:
            sma50 = _safe_float(closes.rolling(window=50).mean().iloc[-1])
            out["sma_50"] = sma50
        if len(closes) >= 200:
            sma200 = _safe_float(closes.rolling(window=200).mean().iloc[-1])
            out["sma_200"] = sma200
            if sma200 is not None and sma200 > 0:
                out["above_sma_200"] = bool(last > sma200)
                if out["sma_50"] is not None:
                    out["golden_cross"] = bool(out["sma_50"] > sma200)

        wk52 = df.iloc[-min(len(df), 252):]
        if "high" in wk52:
            out["wk52_high"] = _safe_float(wk52["high"].max())
        if "low" in wk52:
            out["wk52_low"] = _safe_float(wk52["low"].min())

        if len(closes) >= 252:
            year_ago = _safe_float(closes.iloc[-252])
            if year_ago and year_ago > 0:
                out["one_year_return_pct"] = (last - year_ago) / year_ago * 100.0
    except Exception as exc:
        logger.debug("longterm trend fetch failed for %s: %s", symbol, exc)
    return out


class LongTermDataProvider:
    """Concrete provider for the long-term scan pipeline."""

    def build_universe(self, filters: LongTermFilters) -> list[str]:
        return longterm_universe.build(filters)

    def fetch_snapshot(self, symbol: str) -> Optional[LongTermSnapshot]:
        symbol = symbol.upper()
        # Quote — bail early if Alpaca can't price the symbol.
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            quote = AlpacaUtils.get_latest_quote(symbol)
            last_price = (
                _safe_float(quote.get("ask_price"))
                or _safe_float(quote.get("bid_price"))
            )
            if last_price is None or last_price <= 0:
                return None
        except Exception as exc:
            logger.debug("longterm quote fetch failed for %s: %s", symbol, exc)
            return None

        date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prof = _fetch_profile(symbol, date_key)
        fund = _fetch_fundamentals(symbol, date_key)
        trend = _fetch_trend(symbol, date_key)
        # Reuse the day-trade catalyst helper (own 6h cache; symbol-agnostic).
        # Long-term universe is stocks only, so is_crypto=False is safe.
        try:
            from .data_provider import _fetch_catalyst
            cat = _fetch_catalyst(symbol, False, date_key)
        except Exception as exc:
            logger.debug("longterm catalyst fetch failed for %s: %s", symbol, exc)
            cat = {}

        return LongTermSnapshot(
            symbol=symbol,
            last_price=last_price,
            market_cap_b=prof.get("market_cap_b"),
            sector=prof.get("sector"),
            industry=prof.get("industry"),
            roe_ttm=fund.get("roe_ttm"),
            net_margin_ttm=fund.get("net_margin_ttm"),
            revenue_growth_3y=fund.get("revenue_growth_3y"),
            pe_forward=fund.get("pe_forward"),
            debt_to_equity=fund.get("debt_to_equity"),
            dividend_yield_ttm=fund.get("dividend_yield_ttm"),
            sma_50=trend.get("sma_50"),
            sma_200=trend.get("sma_200"),
            above_sma_200=bool(trend.get("above_sma_200")),
            golden_cross=bool(trend.get("golden_cross")),
            wk52_high=trend.get("wk52_high"),
            wk52_low=trend.get("wk52_low"),
            one_year_return_pct=trend.get("one_year_return_pct"),
            has_catalyst=bool(cat.get("has_catalyst")),
            catalyst_text=cat.get("catalyst_text"),
            catalyst_details=cat.get("catalyst_details"),
            catalyst_category=cat.get("catalyst_category"),
            catalyst_raw=tuple(cat.get("catalyst_raw") or ()),
        )
