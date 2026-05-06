"""TradingView Lightweight Charts payload builder.

Returns a dict shaped for the `dash_tvlwc.Tvlwc` component:
    {
        "seriesData":       [candles, volume],
        "seriesTypes":      ["candlestick", "histogram"],
        "seriesOptions":    [{...}, {...}],
        "seriesPriceLines": [[entry/stop/pt1/pt2 lines], []],
        "seriesMarkers":    [[buy/sell markers], []],
        "chartOptions":     {...},
    }

Pure data transform — no plotting library used. Reuses
`AlpacaUtils.get_stock_data` for candle fetching.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Union

import pandas as pd
import pytz

from tradingagents.dataflows.alpaca_utils import AlpacaUtils

logger = logging.getLogger(__name__)


# ── Visual styles ──────────────────────────────────────────────────
# LWC `LineStyle` enum: 0=solid, 1=dotted, 2=dashed, 3=largeDashed, 4=sparseDotted
_OVERLAY_STYLES: dict[str, tuple[str, int, str]] = {
    "entry": ("#3B82F6", 0, "ENTRY"),
    "stop":  ("#EF4444", 0, "STOP"),
    "pt1":   ("#22C55E", 0, "PT1"),
    "pt2":   ("#22C55E", 2, "PT2"),
}

# Open-position lines — distinct from playbook (uses bright colors with dotted
# style so they stand out against the playbook plan).
_POSITION_STYLES: dict[str, tuple[str, int, str]] = {
    "avg":  ("#FBBF24", 1, "POS AVG"),  # yellow dotted — actual fill avg
    "tp":   ("#10B981", 1, "POS TP"),   # emerald dotted — active take-profit
    "sl":   ("#F97316", 1, "POS SL"),   # orange dotted — active stop-loss
}

_CANDLE_OPTIONS = {
    "upColor": "#22C55E",
    "downColor": "#EF4444",
    "borderUpColor": "#22C55E",
    "borderDownColor": "#EF4444",
    "wickUpColor": "#22C55E",
    "wickDownColor": "#EF4444",
}

_VOLUME_OPTIONS = {
    "color": "#94A3B8",
    "priceFormat": {"type": "volume"},
    "priceScaleId": "",
    "scaleMargins": {"top": 0.75, "bottom": 0},
}

_CHART_OPTIONS_DEFAULT = {
    "layout": {
        "background": {"type": "solid", "color": "#0F172A"},
        "textColor": "#CBD5E1",
        "fontFamily": "'Inter', system-ui, sans-serif",
    },
    "grid": {
        "vertLines": {"color": "rgba(148, 163, 184, 0.1)"},
        "horzLines": {"color": "rgba(148, 163, 184, 0.1)"},
    },
    "crosshair": {"mode": 1},
    "rightPriceScale": {"borderColor": "rgba(148, 163, 184, 0.2)"},
    "timeScale": {
        "borderColor": "rgba(148, 163, 184, 0.2)",
        "timeVisible": True,
        "secondsVisible": False,
    },
}


# ── Period → Alpaca timeframe mapping ──────────────────────────────
_PERIOD_MAP: dict[str, tuple[str, timedelta]] = {
    "1m":  ("1Min",  timedelta(hours=6)),
    "5m":  ("5Min",  timedelta(days=2)),
    "15m": ("15Min", timedelta(days=5)),
    "1h":  ("1Hour", timedelta(days=7)),
    "1d":  ("5Min",  timedelta(days=2)),
    "1w":  ("30Min", timedelta(days=10)),
    "1mo": ("1Hour", timedelta(days=45)),
    "1y":  ("1Day",  timedelta(days=365)),
    # Long-term chart panels (daily bars over multi-year windows).
    "3y":  ("1Day",  timedelta(days=3 * 365)),
    "5y":  ("1Day",  timedelta(days=5 * 365)),
}


def _empty_payload() -> dict[str, Any]:
    """Welcome / empty-state payload — renders an empty chart frame."""
    return {
        "seriesData": [[], []],
        "seriesTypes": ["candlestick", "histogram"],
        "seriesOptions": [_CANDLE_OPTIONS, _VOLUME_OPTIONS],
        "seriesPriceLines": [[], []],
        "seriesMarkers": [[], []],
        "chartOptions": _CHART_OPTIONS_DEFAULT,
    }


def _to_unix_seconds(ts: Any) -> Optional[int]:
    """Convert a pandas/datetime timestamp to integer UTC seconds for LWC."""
    if ts is None:
        return None
    try:
        dt = pd.to_datetime(ts, utc=True)
    except (TypeError, ValueError):
        return None
    if pd.isna(dt):
        return None
    return int(dt.timestamp())


def _build_price_lines(overlay_levels: Optional[dict]) -> list[dict]:
    """Build LWC priceLine objects from playbook levels."""
    return _build_lines_from(overlay_levels, _OVERLAY_STYLES)


def _build_position_lines(position_levels: Optional[dict]) -> list[dict]:
    """Build LWC priceLine objects for the active open position."""
    return _build_lines_from(position_levels, _POSITION_STYLES)


def _build_lines_from(levels: Optional[dict], styles: dict[str, tuple[str, int, str]]) -> list[dict]:
    if not levels:
        return []
    lines: list[dict] = []
    for key, (color, line_style, label) in styles.items():
        price = levels.get(key)
        if price is None:
            continue
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            continue
        lines.append({
            "price": price_f,
            "color": color,
            "lineWidth": 2,
            "lineStyle": line_style,
            "axisLabelVisible": True,
            "title": f"{label} ${price_f:,.2f}",
        })
    return lines


def _build_markers(fills: Optional[list]) -> list[dict]:
    """Build LWC seriesMarker objects from fill records."""
    if not fills:
        return []
    markers: list[dict] = []
    for f in fills:
        if not isinstance(f, dict):
            continue
        try:
            price = float(f.get("price"))
        except (TypeError, ValueError):
            continue
        time_s = _to_unix_seconds(f.get("time"))
        if time_s is None:
            continue
        side = (f.get("side") or "buy").lower()
        is_buy = side != "sell"
        qty = f.get("qty") or ""
        markers.append({
            "time": time_s,
            "position": "belowBar" if is_buy else "aboveBar",
            "color": "#22C55E" if is_buy else "#EF4444",
            "shape": "arrowUp" if is_buy else "arrowDown",
            "text": f"{'BUY' if is_buy else 'SELL'} {qty}".strip(),
        })
    # LWC requires markers sorted ascending by time
    markers.sort(key=lambda m: m["time"])
    return markers


def _candles_payload(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Convert OHLCV dataframe to (candle_data, volume_data) lists."""
    candles: list[dict] = []
    volume: list[dict] = []
    for _, row in df.iterrows():
        time_s = _to_unix_seconds(row["timestamp"])
        if time_s is None:
            continue
        try:
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            v = float(row["volume"])
        except (TypeError, ValueError, KeyError):
            continue
        candles.append({"time": time_s, "open": o, "high": h, "low": l, "close": c})
        volume.append({
            "time": time_s,
            "value": v,
            "color": "rgba(34, 197, 94, 0.4)" if c >= o else "rgba(239, 68, 68, 0.4)",
        })
    return candles, volume


def build_lwc_payload(
    ticker: str,
    period: str = "1y",
    end_date: Union[str, datetime, None] = None,
    *,
    overlay_levels: Optional[dict] = None,
    position_levels: Optional[dict] = None,
    fills: Optional[list] = None,
) -> dict[str, Any]:
    """Build a complete LWC payload for `ticker` over `period`.

    `overlay_levels` keys: entry/stop/pt1/pt2 — playbook plan.
    `position_levels` keys: avg/tp/sl — actual open position + bracket legs.
    Either may be None; both render together when present.

    Returns the empty-state payload if data fetching fails or returns nothing.
    """
    now_utc = datetime.now(pytz.UTC)
    if end_date:
        end_dt = pd.to_datetime(end_date)
        end_dt = end_dt.tz_localize(pytz.UTC) if end_dt.tzinfo is None else end_dt
    else:
        end_dt = now_utc

    tf_str, delta = _PERIOD_MAP.get(period, _PERIOD_MAP["1y"])
    start_dt = end_dt - delta

    try:
        df = AlpacaUtils.get_stock_data(
            symbol=ticker,
            start_date=start_dt,
            end_date=end_dt,
            timeframe=tf_str,
        )
    except Exception as exc:
        logger.warning("LWC data fetch failed for %s/%s: %s", ticker, period, exc)
        df = pd.DataFrame()

    price_lines = _build_price_lines(overlay_levels) + _build_position_lines(position_levels)
    markers = _build_markers(fills)

    if df.empty:
        payload = _empty_payload()
        payload["seriesPriceLines"] = [price_lines, []]
        payload["seriesMarkers"] = [markers, []]
        return payload

    candles, volume = _candles_payload(df)

    return {
        "seriesData": [candles, volume],
        "seriesTypes": ["candlestick", "histogram"],
        "seriesOptions": [_CANDLE_OPTIONS, _VOLUME_OPTIONS],
        "seriesPriceLines": [price_lines, []],
        "seriesMarkers": [markers, []],
        "chartOptions": _CHART_OPTIONS_DEFAULT,
    }


def empty_lwc_payload() -> dict[str, Any]:
    """Public empty-state helper for welcome / no-symbol-selected screens."""
    return _empty_payload()
