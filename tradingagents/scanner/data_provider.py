"""Real DataProvider backed by Alpaca + Finnhub + existing project dataflows.

Kept intentionally small — scans are best-effort: any per-symbol API failure
returns None (or a partial snapshot) and the pipeline simply drops that ticker.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dataflows.cache_utils import with_cache
from tradingagents.dataflows.ticker_utils import TickerUtils

from . import universe
from .models import CatalystFacts, KeyLevels, ScanFilters, TickerSnapshot

logger = logging.getLogger(__name__)

_NY = ZoneInfo("America/New_York")


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _compute_macd_cross(closes: pd.Series) -> bool:
    """True if MACD line crossed above signal in the last 2 daily bars."""
    if len(closes) < 35:
        return False
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    diff = macd - signal
    if len(diff) < 3:
        return False
    return bool(diff.iloc[-2] <= 0 and diff.iloc[-1] > 0)


def _session_open_utc(now_utc: datetime) -> datetime:
    """Today's 9:30 America/New_York as UTC."""
    now_et = now_utc.astimezone(_NY)
    open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    return open_et.astimezone(timezone.utc)


def _compute_intraday_metrics(
    df: pd.DataFrame, now_utc: datetime, open_utc: datetime
) -> dict:
    """Pure computation: VWAP + reclaim flag + opening range high + minutes since open.

    `df` is expected to have columns high/low/close/volume and a `timestamp` column
    (or a DatetimeIndex). Bars before `open_utc` are discarded (premarket).
    """
    if df is None or df.empty:
        return {}
    cols = {c.lower() for c in df.columns}
    if not {"high", "low", "close", "volume"}.issubset(cols):
        return {}

    # Normalize timestamp to a UTC DatetimeIndex for session filtering.
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df = df.assign(_ts=ts).set_index("_ts").sort_index()
    elif isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df = df.copy()
            df.index = df.index.tz_localize("UTC")
    else:
        try:
            df = df.copy()
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            return {}

    session = df[df.index >= pd.Timestamp(open_utc)]
    if session.empty:
        return {}

    high = session["high"].astype(float)
    low = session["low"].astype(float)
    close = session["close"].astype(float)
    vol = session["volume"].astype(float)

    typical = (high + low + close) / 3.0
    total_vol = float(vol.sum())
    vwap = float((typical * vol).sum() / total_vol) if total_vol > 0 else None

    # Reclaim = a prior bar closed below *its own* running VWAP, and we're now above final VWAP.
    # (Using running VWAP prevents uptrends from being flagged as "reclaims" — only real
    # cross-backs-above qualify.)
    vwap_reclaim = False
    if vwap is not None and len(session) >= 2 and total_vol > 0:
        cum_vol = vol.cumsum()
        cum_tv = (typical * vol).cumsum()
        running_vwap = cum_tv / cum_vol.replace(0, pd.NA)
        dipped = bool((close < running_vwap).fillna(False).any())
        last_close = float(close.iloc[-1])
        vwap_reclaim = bool(dipped and last_close > vwap)

    opening_range_high: Optional[float] = None
    if len(session) >= 5:
        opening_range_high = float(high.iloc[:5].max())

    minutes_since_open: Optional[int] = None
    delta = (now_utc - open_utc).total_seconds()
    if delta > 0:
        minutes_since_open = int(delta // 60)

    return {
        "vwap": vwap,
        "vwap_reclaim": vwap_reclaim,
        "opening_range_high": opening_range_high,
        "minutes_since_open": minutes_since_open,
    }


@with_cache(cache_category="scanner_daily_metrics", max_age_hours=12)
def _fetch_daily_metrics(symbol: str, today_key: str) -> dict:
    """RVOL + change_pct + SMA10 flag + MACD cross from one daily-bar fetch."""
    del today_key
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        df = AlpacaUtils.get_stock_data(symbol, start.isoformat(), end.isoformat(), "1Day")
        if df is None or df.empty or "volume" not in df.columns or "close" not in df.columns:
            return {}
        volumes = df["volume"].tolist()
        closes = df["close"].astype(float)
        if len(volumes) < 5:
            return {}

        today_vol = int(volumes[-1])
        benchmark = volumes[:-1][-30:]
        avg = sum(benchmark) / len(benchmark) if benchmark else 0
        rvol = (today_vol / avg) if avg > 0 else None
        prior_30d_max = max(benchmark) if benchmark else None

        prev_close = _safe_float(closes.iloc[-2]) if len(closes) >= 2 else None
        last_close = _safe_float(closes.iloc[-1])
        change_pct = None
        if prev_close and prev_close > 0 and last_close is not None:
            change_pct = (last_close - prev_close) / prev_close * 100

        above_sma10 = False
        if len(closes) >= 10:
            sma10 = closes.rolling(window=10).mean().iloc[-1]
            if pd.notna(sma10) and last_close is not None:
                above_sma10 = bool(last_close > float(sma10))

        macd_cross = _compute_macd_cross(closes)

        return {
            "rvol": rvol,
            "today_volume": today_vol,
            "prior_30d_max_volume": prior_30d_max,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "above_sma10": above_sma10,
            "macd_signal_cross": macd_cross,
        }
    except Exception as exc:
        logger.debug("daily metrics fetch failed for %s: %s", symbol, exc)
        return {}


@with_cache(cache_category="scanner_intraday", max_age_hours=1)
def _fetch_intraday_metrics(symbol: str, session_key: str) -> dict:
    """Session VWAP, VWAP reclaim flag, opening range high, minutes since open."""
    del session_key
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        df = AlpacaUtils.get_stock_data(symbol, start.isoformat(), now.isoformat(), "1Min")
        open_utc = _session_open_utc(now)
        return _compute_intraday_metrics(df, now, open_utc)
    except Exception as exc:
        logger.debug("intraday fetch failed for %s: %s", symbol, exc)
        return {}


@with_cache(cache_category="scanner_levels", max_age_hours=1)
def _fetch_levels(symbol: str, date_key: str) -> dict:
    """Previous-day high/low + 52-week high/low from daily bars."""
    del date_key
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=400)
        df = AlpacaUtils.get_stock_data(symbol, start.isoformat(), end.isoformat(), "1Day")
        if df is None or df.empty:
            return {}
        pdh = pdl = None
        if len(df) >= 2:
            prev = df.iloc[-2]
            pdh = _safe_float(prev.get("high"))
            pdl = _safe_float(prev.get("low"))
        wk52 = df.iloc[-min(len(df), 252):]
        return {
            "pdh": pdh,
            "pdl": pdl,
            "wk52_high": _safe_float(wk52["high"].max()) if "high" in wk52 else None,
            "wk52_low": _safe_float(wk52["low"].min()) if "low" in wk52 else None,
            "ath": _safe_float(df["high"].max()) if "high" in df else None,
        }
    except Exception as exc:
        logger.debug("levels fetch failed for %s: %s", symbol, exc)
        return {}


# Aggregation / recap headlines — these are *effects* of a move, not *causes*.
# If we flagged them as catalysts, any ticker that moves would cycle back as its own
# "news" and inflate its score. Match case-insensitively against headline OR summary.
_CATALYST_NOISE_SUBSTRINGS = (
    "after-hours session",
    "after hours session",
    "top gainers",
    "top losers",
    "gainers and losers",
    "movers and shakers",
    "stocks moving",
    "stocks that are moving",
    "stocks that are on the move",
    "biggest movers",
    "mid-day movers",
    "midday movers",
    "pre-market movers",
    "premarket movers",
    "what's moving",
    "what is moving",
    "market recap",
    "market wrap",
    "momentum stocks",
    "stock market today",
    "stocks to watch",
    "stock movers",
    "notable movers",
)


def _is_signal_news(article: dict) -> bool:
    """True if the article looks like a genuine catalyst (not a recap/movers list)."""
    if not isinstance(article, dict):
        return False
    blob = f"{article.get('headline', '')} {article.get('summary', '')}".lower()
    return not any(phrase in blob for phrase in _CATALYST_NOISE_SUBSTRINGS)


# ─── Category detectors (pure) ────────────────────────────────────────

_MA_KEYWORDS = ("acquir", "merger", "merge with", "agreement to acquire", "buyout",
                "definitive agreement", "tender offer", "spin-off", "spin off")
_FDA_KEYWORDS = ("fda", "phase 3", "phase 2", "phase 1", "clinical trial",
                 "fast-track", "fast track", "approval", "fda approves",
                 "breakthrough designation", "orphan drug")
_MANAGEMENT_KEYWORDS = ("appoints", "names new", "ceo transition", "cfo transition",
                       "departure of", "step down", "resign", "new chief executive",
                       "new chief financial", "new president")


def _detect_press_release_category(headline: str, description: str) -> str:
    """Categorize a press release by keyword match. Order: M&A → FDA → MANAGEMENT → PRESS_RELEASE."""
    blob = f"{headline} {description}".lower()
    if any(k in blob for k in _MA_KEYWORDS):
        return "M&A"
    if any(k in blob for k in _FDA_KEYWORDS):
        return "FDA"
    if any(k in blob for k in _MANAGEMENT_KEYWORDS):
        return "MANAGEMENT"
    return "PRESS_RELEASE"


def _detect_filing_category(form: str, description: str) -> str:
    """Categorize an SEC filing. 8-K item codes drive sub-category."""
    desc_l = (description or "").lower()
    form_u = (form or "").upper()
    if form_u == "8-K":
        if "2.01" in desc_l or "completion of acquisition" in desc_l:
            return "M&A"
        if "5.02" in desc_l or "departure" in desc_l or "appointment" in desc_l:
            return "MANAGEMENT"
    return "FILING"


# ─── Fetch helpers (Finnhub I/O, cached) ──────────────────────────────

@with_cache(cache_category="scanner_press_releases", max_age_hours=6)
def _fetch_press_releases(symbol: str, date_key: str) -> list[dict]:
    """Major-development press releases from Finnhub. Returns list[dict] (empty on failure)."""
    del date_key
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        resp = client.press_releases(symbol, _from=start, to=end) or {}
        items = resp.get("majorDevelopment", []) if isinstance(resp, dict) else []
        return list(items) if isinstance(items, list) else []
    except Exception as exc:
        logger.debug("press releases fetch failed for %s: %s", symbol, exc)
        return []


@with_cache(cache_category="scanner_filings", max_age_hours=6)
def _fetch_filings(symbol: str, date_key: str) -> list[dict]:
    """SEC filings (8-K, S-1, 13D/G, etc) from Finnhub. Returns list[dict]."""
    del date_key
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        items = client.filings(symbol=symbol, _from=start, to=end) or []
        return list(items) if isinstance(items, list) else []
    except Exception as exc:
        logger.debug("filings fetch failed for %s: %s", symbol, exc)
        return []


@with_cache(cache_category="scanner_insider", max_age_hours=12)
def _fetch_insider(symbol: str, date_key: str) -> list[dict]:
    """Insider transactions from Finnhub. Returns list[dict]."""
    del date_key
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        resp = client.stock_insider_transactions(symbol, _from=start, to=end) or {}
        items = resp.get("data", []) if isinstance(resp, dict) else []
        return list(items) if isinstance(items, list) else []
    except Exception as exc:
        logger.debug("insider fetch failed for %s: %s", symbol, exc)
        return []


@with_cache(cache_category="scanner_corp_actions", max_age_hours=24)
def _fetch_corporate_actions(symbol: str, date_key: str) -> list[dict]:
    """Stock splits + special dividends from Finnhub, normalized to {date, type, ...}."""
    del date_key
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        end = (now + timedelta(days=14)).strftime("%Y-%m-%d")

        actions: list[dict] = []
        try:
            splits = client.stock_splits(symbol, _from=start, to=end) or []
            for s in splits:
                if isinstance(s, dict):
                    actions.append({**s, "type": "split"})
        except Exception:
            pass
        try:
            divs = client.stock_dividends2(symbol, _from=start, to=end) or []
            for d in divs:
                if isinstance(d, dict):
                    actions.append({**d, "type": "dividend"})
        except Exception:
            pass
        return actions
    except Exception as exc:
        logger.debug("corp actions fetch failed for %s: %s", symbol, exc)
        return []


# ─── Richer classifier (CatalystFacts) ────────────────────────────────

def _classify_catalyst_facts(
    earnings: list[dict],
    news: list[dict],
    press_releases: list[dict],
    filings: list[dict],
    insider: list[dict],
    corporate_actions: list[dict],
    *,
    now_utc: datetime,
) -> CatalystFacts:
    """Categorized classifier returning structured `CatalystFacts`.

    Priority: EARNINGS > M&A > FDA > MANAGEMENT > INSIDER > FILING >
    CORPORATE_ACTION > PRESS_RELEASE > NEWS.
    """
    # ── Earnings (±2 days) ──────────────────────────────────────────
    for row in earnings or []:
        if not isinstance(row, dict):
            continue
        date_str = row.get("date")
        if not date_str:
            continue
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if abs((d - now_utc).total_seconds()) <= 2 * 86400:
            return CatalystFacts(
                has_catalyst=True,
                category="EARNINGS",
                short_text=f"Earnings {date_str}",
                structured_md=_format_earnings_details(row),
                raw_items=(row,),
            )

    now_ts = now_utc.timestamp()

    # ── Press releases (last 48h) categorized ───────────────────────
    fresh_pr = [
        pr for pr in (press_releases or [])
        if isinstance(pr, dict) and 0 < (now_ts - _safe_pr_ts(pr)) <= 48 * 3600
    ]
    fresh_pr.sort(key=_safe_pr_ts, reverse=True)
    pr_by_cat: dict[str, dict] = {}
    for pr in fresh_pr:
        cat = _detect_press_release_category(pr.get("headline", ""), pr.get("description", ""))
        pr_by_cat.setdefault(cat, pr)

    for category in ("M&A", "FDA", "MANAGEMENT"):
        if category in pr_by_cat:
            pr = pr_by_cat[category]
            return CatalystFacts(
                has_catalyst=True,
                category=category,
                short_text=f"{category}: {(pr.get('headline') or '')[:80]}",
                structured_md=_format_pr_details([pr_by_cat[category]]),
                raw_items=tuple(fresh_pr[:5]),
            )

    # ── 8-K filings categorized ─────────────────────────────────────
    fresh_filings = [
        f for f in (filings or [])
        if isinstance(f, dict) and _filing_within_days(f, now_utc, 7)
    ]
    filing_by_cat: dict[str, dict] = {}
    for f in fresh_filings:
        cat = _detect_filing_category(f.get("form", ""), f.get("description", ""))
        filing_by_cat.setdefault(cat, f)

    for category in ("M&A", "MANAGEMENT"):
        if category in filing_by_cat:
            f = filing_by_cat[category]
            return CatalystFacts(
                has_catalyst=True,
                category=category,
                short_text=f"{category} filing: {(f.get('form') or '')}",
                structured_md=_format_filing_details([f]),
                raw_items=tuple(fresh_filings[:5]),
            )

    # ── Insider cluster buys (≥2 distinct insiders OR >$1M) in last 14d ──
    fresh_insider = [
        i for i in (insider or [])
        if isinstance(i, dict)
        and (i.get("transactionCode") or "").upper() == "P"
        and _insider_within_days(i, now_utc, 14)
    ]
    if fresh_insider:
        unique_names = {i.get("name") for i in fresh_insider if i.get("name")}
        total_value = sum(
            float(i.get("share") or 0) * float(i.get("transactionPrice") or 0)
            for i in fresh_insider
        )
        if len(unique_names) >= 2 or total_value >= 1_000_000:
            return CatalystFacts(
                has_catalyst=True,
                category="INSIDER",
                short_text=f"Insider buying ({len(unique_names)} insider(s))",
                structured_md=_format_insider_details(fresh_insider),
                raw_items=tuple(fresh_insider[:10]),
            )

    # ── Generic FILING (8-K item 8.01, S-1, 13D, etc.) ──────────────
    if "FILING" in filing_by_cat:
        f = filing_by_cat["FILING"]
        return CatalystFacts(
            has_catalyst=True,
            category="FILING",
            short_text=f"Filing: {(f.get('form') or '')}",
            structured_md=_format_filing_details([f]),
            raw_items=tuple(fresh_filings[:5]),
        )

    # ── Corporate actions (splits, special dividends) within 7d ─────
    fresh_actions = [
        a for a in (corporate_actions or [])
        if isinstance(a, dict) and _action_within_days(a, now_utc, 7)
    ]
    if fresh_actions:
        a = fresh_actions[0]
        action_type = a.get("type", "corporate action")
        return CatalystFacts(
            has_catalyst=True,
            category="CORPORATE_ACTION",
            short_text=f"Corporate action: {action_type}",
            structured_md=_format_corp_action_details(fresh_actions),
            raw_items=tuple(fresh_actions[:5]),
        )

    # ── Generic press release (any other category) ──────────────────
    if "PRESS_RELEASE" in pr_by_cat:
        pr = pr_by_cat["PRESS_RELEASE"]
        return CatalystFacts(
            has_catalyst=True,
            category="PRESS_RELEASE",
            short_text=f"Press release: {(pr.get('headline') or '')[:80]}",
            structured_md=_format_pr_details(fresh_pr[:5]),
            raw_items=tuple(fresh_pr[:5]),
        )

    # ── News (existing logic) ───────────────────────────────────────
    flag, short_text, structured_md = _classify_stock_catalyst(earnings, news, now_utc)
    if flag:
        # Build raw_items from the same filtered/sorted list
        items = sorted(
            (n for n in (news or []) if isinstance(n, dict) and _is_signal_news(n)),
            key=lambda n: float(n.get("datetime", 0) or 0),
            reverse=True,
        )
        return CatalystFacts(
            has_catalyst=True,
            category="NEWS",
            short_text=short_text,
            structured_md=structured_md,
            raw_items=tuple(items[:5]),
        )

    return CatalystFacts()


def _safe_pr_ts(pr: dict) -> float:
    """Best-effort timestamp from press release dict (datetime str or unix epoch)."""
    raw = pr.get("datetime")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
    return 0.0


def _filing_within_days(filing: dict, now_utc: datetime, days: int) -> bool:
    raw = filing.get("filedDate") or filing.get("acceptedDate")
    if not isinstance(raw, str):
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return abs((now_utc - d).total_seconds()) <= days * 86400
        except ValueError:
            continue
    return False


def _insider_within_days(item: dict, now_utc: datetime, days: int) -> bool:
    raw = item.get("transactionDate") or item.get("filingDate")
    if not isinstance(raw, str):
        return False
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return abs((now_utc - d).total_seconds()) <= days * 86400
    except ValueError:
        return False


def _action_within_days(action: dict, now_utc: datetime, days: int) -> bool:
    raw = action.get("date") or action.get("paymentDate")
    if not isinstance(raw, str):
        return False
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return abs((now_utc - d).total_seconds()) <= days * 86400
    except ValueError:
        return False


def _format_pr_details(items: list[dict]) -> str:
    lines = []
    for pr in items:
        headline = (pr.get("headline") or "(no headline)").strip()
        url = (pr.get("url") or "").strip()
        desc = (pr.get("description") or "").strip()
        raw_dt = pr.get("datetime")
        if isinstance(raw_dt, (int, float)):
            try:
                date = datetime.fromtimestamp(float(raw_dt), tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                date = ""
        else:
            date = (raw_dt or "")[:10] if isinstance(raw_dt, str) else ""
        head_md = f"[{headline}]({url})" if url.startswith("http") else headline
        lines.append(f"**{head_md}** _({date})_")
        if desc:
            snippet = desc if len(desc) <= 500 else desc[:500].rsplit(" ", 1)[0] + "…"
            lines.append(snippet)
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_filing_details(items: list[dict]) -> str:
    lines = []
    for f in items:
        form = f.get("form", "?")
        date = (f.get("filedDate") or "")[:10]
        desc = (f.get("description") or "").strip()
        url = (f.get("reportUrl") or f.get("filingUrl") or "").strip()
        title = f"**SEC Filing — {form}** _({date})_"
        if url.startswith("http"):
            title = f"**[{form}]({url})** _({date})_"
        lines.append(title)
        if desc:
            lines.append(desc[:500])
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_insider_details(items: list[dict]) -> str:
    lines = ["**Recent insider buys**"]
    for i in items[:10]:
        name = i.get("name", "?")
        shares = i.get("share") or 0
        price = i.get("transactionPrice") or 0
        date = i.get("transactionDate", "")
        try:
            value = float(shares) * float(price)
            value_str = f"${value:,.0f}"
        except (TypeError, ValueError):
            value_str = "n/a"
        lines.append(f"- {date} · {name} · {shares:,} shares @ ${price} = {value_str}")
    return "\n".join(lines)


def _format_corp_action_details(items: list[dict]) -> str:
    lines = []
    for a in items:
        a_type = a.get("type", "action")
        date = a.get("date", "")
        if a_type == "split":
            f = a.get("fromFactor", "?")
            t = a.get("toFactor", "?")
            lines.append(f"**Stock split** _{date}_: {f}-for-{t}")
        elif a_type == "dividend":
            amt = a.get("amount", "")
            lines.append(f"**Dividend** _{date}_: {amt}")
        else:
            lines.append(f"**{a_type}** _{date}_")
    return "\n".join(lines)


def _classify_stock_catalyst(
    earnings: list[dict],
    news: list[dict],
    now_utc: datetime,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Pure classifier → (flag, short_text, details_markdown).

    Earnings within ±2 days wins; else 2+ articles in 24h or 1 fresh <6h.
    `details_markdown` is a longer bullet-list summary for the UI click-out modal.
    """
    for row in earnings or []:
        date_str = row.get("date") if isinstance(row, dict) else None
        if not date_str:
            continue
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if abs((d - now_utc).total_seconds()) <= 2 * 86400:
            short = f"Earnings {date_str}"
            details = _format_earnings_details(row)
            return True, short, details

    # Sort news newest-first by unix `datetime` (Finnhub format).
    def _ts(n: dict) -> float:
        try:
            return float(n.get("datetime", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    # Drop aggregation/recap articles so a ticker doesn't get flagged as its own catalyst.
    items = sorted(
        (n for n in (news or []) if isinstance(n, dict) and _is_signal_news(n)),
        key=_ts,
        reverse=True,
    )
    now_ts = now_utc.timestamp()
    fresh_24h = [n for n in items if 0 < (now_ts - _ts(n)) <= 24 * 3600]
    fresh_6h = [n for n in items if 0 < (now_ts - _ts(n)) <= 6 * 3600]
    if len(fresh_24h) >= 2 or len(fresh_6h) >= 1:
        top = items[0]
        headline = str(top.get("headline", "")).strip() or "recent news"
        if len(headline) > 80:
            short = f"News: {headline[:80]}…"
        else:
            short = f"News: {headline}"
        details = _format_news_details(fresh_24h or [top], now_ts)
        return True, short, details

    return False, None, None


def _format_earnings_details(row: dict) -> str:
    """Markdown bullet for an earnings-calendar entry (from Finnhub)."""
    date = row.get("date", "?")
    hour = row.get("hour") or ""
    hour_map = {"bmo": "before market open", "amc": "after market close", "dmh": "during market hours"}
    hour_str = hour_map.get(hour, hour)
    eps_est = row.get("epsEstimate")
    rev_est = row.get("revenueEstimate")

    lines = [f"**Earnings report on {date}**"]
    if hour_str:
        lines.append(f"_{hour_str}_")
    if eps_est not in (None, ""):
        lines.append(f"- EPS estimate: **{eps_est}**")
    if rev_est not in (None, ""):
        try:
            rev_b = float(rev_est) / 1e9
            lines.append(f"- Revenue estimate: **${rev_b:,.2f}B**")
        except (TypeError, ValueError):
            lines.append(f"- Revenue estimate: **{rev_est}**")
    lines.append(
        "\nEarnings reports are high-volatility events — expect sharp moves in either "
        "direction on beats/misses and guidance surprises."
    )
    return "\n".join(lines)


def _format_news_details(articles: list[dict], now_ts: float, limit: int = 5) -> str:
    """Markdown list of the top-N fresh articles with summaries + clickable source links."""
    lines = []
    for art in articles[:limit]:
        headline = str(art.get("headline", "")).strip() or "(no headline)"
        summary = str(art.get("summary", "")).strip()
        source = str(art.get("source", "")).strip()
        url = str(art.get("url", "")).strip()
        try:
            ts = float(art.get("datetime", 0) or 0)
        except (TypeError, ValueError):
            ts = 0
        age_min = max(int((now_ts - ts) / 60), 0) if ts else None
        age_str = ""
        if age_min is not None:
            if age_min < 60:
                age_str = f"{age_min}m ago"
            elif age_min < 24 * 60:
                age_str = f"{age_min // 60}h ago"
            else:
                age_str = f"{age_min // (24 * 60)}d ago"
        meta_bits = [b for b in (source, age_str) if b]
        meta = f" _({' · '.join(meta_bits)})_" if meta_bits else ""

        # Headline becomes a clickable link when a URL is present — gives the user a
        # one-click path to the full article body.
        headline_md = f"[{headline}]({url})" if url.startswith("http") else headline
        lines.append(f"**{headline_md}**{meta}")
        if summary and summary.lower() != headline.lower():
            snippet = summary if len(summary) <= 500 else summary[:500].rsplit(" ", 1)[0] + "…"
            lines.append(snippet)
        lines.append("")  # blank line between articles
    return "\n".join(lines).rstrip()


@with_cache(cache_category="scanner_catalyst", max_age_hours=6)
def _fetch_catalyst(symbol: str, is_crypto: bool, date_key: str) -> dict:
    """Catalyst flag + structured facts from Finnhub multi-source query. Crypto skipped."""
    del date_key
    empty = {
        "has_catalyst": False,
        "catalyst_text": None,
        "catalyst_details": None,
        "catalyst_category": None,
        "catalyst_raw": [],
    }
    if is_crypto:
        return empty
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (now + timedelta(days=2)).strftime("%Y-%m-%d")

        try:
            cal = client.earnings_calendar(_from=start, to=end, symbol=symbol) or {}
            earnings = cal.get("earningsCalendar", []) if isinstance(cal, dict) else []
        except Exception:
            earnings = []

        try:
            news_start = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            news_end = now.strftime("%Y-%m-%d")
            news = client.company_news(symbol, _from=news_start, to=news_end) or []
        except Exception:
            news = []

        # New structured sources — each helper handles its own errors and caching.
        # Use a per-day key so the helpers cache 6h independently of the parent.
        struct_key = now.strftime("%Y-%m-%d")
        press = _fetch_press_releases(symbol, struct_key)
        filings = _fetch_filings(symbol, struct_key)
        ins = _fetch_insider(symbol, struct_key)
        actions = _fetch_corporate_actions(symbol, struct_key)

        facts = _classify_catalyst_facts(
            earnings, news, press, filings, ins, actions, now_utc=now,
        )
        return {
            "has_catalyst": facts.has_catalyst,
            "catalyst_text": facts.short_text,
            "catalyst_details": facts.structured_md,
            "catalyst_category": facts.category,
            "catalyst_raw": list(facts.raw_items),
        }
    except Exception as exc:
        logger.debug("catalyst fetch failed for %s: %s", symbol, exc)
        return empty


@with_cache(cache_category="scanner_float", max_age_hours=168)
def _fetch_float_shares(symbol: str, week_key: str) -> Optional[float]:
    """Shares outstanding (used as float proxy) from Finnhub, in raw shares."""
    del week_key
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        profile = client.company_profile2(symbol=symbol) or {}
        shares_m = profile.get("shareOutstanding")
        if shares_m is None:
            return None
        return float(shares_m) * 1_000_000.0
    except Exception as exc:
        logger.debug("float fetch failed for %s: %s", symbol, exc)
        return None


class AlpacaDataProvider:
    """Concrete DataProvider for the ScannerPipeline Protocol."""

    def build_universe(self, filters: ScanFilters) -> list[str]:
        return universe.build(filters)

    def fetch_snapshot(self, symbol: str) -> Optional[TickerSnapshot]:
        try:
            info = TickerUtils.standardize_ticker(symbol)
            is_crypto = info["is_crypto"]
            alpaca_symbol = info["alpaca_format"]
        except Exception:
            return None

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils

            quote = AlpacaUtils.get_latest_quote(alpaca_symbol)
            last_price = _safe_float(quote.get("ask_price")) or _safe_float(quote.get("bid_price"))
            if last_price is None or last_price <= 0:
                return None
        except Exception as exc:
            logger.debug("quote fetch failed for %s: %s", symbol, exc)
            return None

        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        metrics = _fetch_daily_metrics(alpaca_symbol, today_key) or {}

        change_pct = 0.0
        prev_close = metrics.get("prev_close")
        if prev_close and prev_close > 0:
            change_pct = (last_price - prev_close) / prev_close * 100
        elif metrics.get("change_pct") is not None:
            change_pct = metrics["change_pct"]

        # Float — stocks only; Finnhub `company_profile2.shareOutstanding` in millions.
        float_shares: Optional[float] = None
        if not is_crypto:
            week_key = datetime.now(timezone.utc).strftime("%G-W%V")
            float_shares = _fetch_float_shares(alpaca_symbol, week_key)

        # Intraday metrics — shared cache with fetch_key_levels (same session_key).
        intraday = _fetch_intraday_metrics(alpaca_symbol, today_key) or {}

        # Catalyst (Finnhub multi-source) — crypto skipped.
        # v5: structured categories (M&A, FDA, MANAGEMENT, INSIDER, CORPORATE_ACTION).
        catalyst_key = f"{today_key}-v5"
        catalyst = _fetch_catalyst(alpaca_symbol, is_crypto, catalyst_key) or {}
        raw = catalyst.get("catalyst_raw") or []
        # Convert to a frozen tuple of frozenset-style read-only views; we keep dicts
        # but wrap in tuple so the snapshot stays hashable enough for state stores.
        raw_tuple = tuple(raw) if isinstance(raw, list) else ()

        return TickerSnapshot(
            symbol=alpaca_symbol,
            is_crypto=is_crypto,
            last_price=last_price,
            change_pct=change_pct,
            rvol=metrics.get("rvol"),
            today_volume=metrics.get("today_volume"),
            prior_30d_max_volume=metrics.get("prior_30d_max_volume"),
            above_sma10=bool(metrics.get("above_sma10", False)),
            macd_signal_cross=bool(metrics.get("macd_signal_cross", False)),
            float_shares=float_shares,
            vwap_reclaim=bool(intraday.get("vwap_reclaim", False)),
            opening_range_high=intraday.get("opening_range_high"),
            minutes_since_open=intraday.get("minutes_since_open"),
            premarket_volume=None,
            has_catalyst=bool(catalyst.get("has_catalyst", False)),
            catalyst_text=catalyst.get("catalyst_text"),
            catalyst_details=catalyst.get("catalyst_details"),
            catalyst_category=catalyst.get("catalyst_category"),
            catalyst_raw=raw_tuple,
        )

    def fetch_key_levels(self, symbol: str) -> KeyLevels:
        date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        levels = _fetch_levels(symbol, date_key) or {}
        intraday = _fetch_intraday_metrics(symbol, date_key) or {}
        return KeyLevels(
            pdh=levels.get("pdh"),
            pdl=levels.get("pdl"),
            ath=levels.get("ath"),
            wk52_high=levels.get("wk52_high"),
            wk52_low=levels.get("wk52_low"),
            vwap=intraday.get("vwap"),
        )
