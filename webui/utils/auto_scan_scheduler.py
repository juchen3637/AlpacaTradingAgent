"""Background scheduler that fires the pre-market and market-open scans automatically.

Pre-market scan:  8:00 AM – 9:24 AM ET  (runs once per market day)
  - Universe from Alpaca ScreenerClient most-actives
  - Premarket prices from Yahoo Finance (yfinance) — works on any Alpaca tier

Market-open scan: 9:45 AM – 10:30 AM ET (runs once per market day)
  - Full ScannerPipeline run (RVOL, strategy matching, catalyst detection)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import pytz

from webui.utils.market_hours import ALL_HOLIDAYS

logger = logging.getLogger(__name__)

_EASTERN = pytz.timezone("US/Eastern")


def _is_market_day(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    return now_et.strftime("%Y-%m-%d") not in ALL_HOLIDAYS


def _should_run_premarket(now_et: datetime, app_state, today_str: str) -> bool:
    if not (8 <= now_et.hour <= 9):
        return False
    if now_et.hour == 9 and now_et.minute >= 25:
        return False
    last_ran = app_state.premarket_scan_ran_at
    if last_ran is None:
        return True
    return last_ran.strftime("%Y-%m-%d") != today_str


def _should_run_market_open(now_et: datetime, app_state, today_str: str) -> bool:
    if now_et.hour == 9 and now_et.minute < 45:
        return False
    if now_et.hour >= 11:
        return False
    if not (9 <= now_et.hour <= 10):
        return False
    last_ran = app_state.market_open_scan_ran_at
    if last_ran is None:
        return True
    return last_ran.strftime("%Y-%m-%d") != today_str


def _run_premarket_scan(app_state) -> None:
    app_state.auto_scan_running = True
    try:
        logger.info("[AUTO-SCAN] Running pre-market movers scan...")
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        from tradingagents.scanner.data_provider import has_catalyst

        movers = AlpacaUtils.get_premarket_movers(top_n=20)
        for mover in movers:
            try:
                mover["has_catalyst"] = has_catalyst(mover["symbol"])
            except Exception:
                mover["has_catalyst"] = False

        app_state.premarket_scan_results = movers
        app_state.premarket_scan_ran_at = datetime.now(_EASTERN)
        logger.info("[AUTO-SCAN] Pre-market scan done: %d movers", len(movers))
    except Exception as exc:
        logger.warning("[AUTO-SCAN] Pre-market scan failed: %s", exc)
        app_state.premarket_scan_results = []
        app_state.premarket_scan_ran_at = datetime.now(_EASTERN)
    finally:
        app_state.auto_scan_running = False


def _run_market_open_scan(app_state) -> None:
    app_state.auto_scan_running = True
    try:
        logger.info("[AUTO-SCAN] Running market-open scan...")
        from tradingagents.scanner.models import ScanFilters
        from tradingagents.scanner.pipeline import ScannerPipeline
        from tradingagents.scanner.data_provider import AlpacaDataProvider

        filters = ScanFilters(
            universe_kind="most_active",
            min_rvol=1.5,
            price_min=1.0,
            price_max=1000.0,
            catalyst_only=False,
        )
        results = ScannerPipeline(AlpacaDataProvider()).run(filters) or []
        app_state.market_open_scan_results = results
        app_state.market_open_scan_ran_at = datetime.now(_EASTERN)
        logger.info("[AUTO-SCAN] Market-open scan done: %d results", len(results))
    except Exception as exc:
        logger.warning("[AUTO-SCAN] Market-open scan failed: %s", exc)
        app_state.market_open_scan_results = []
        app_state.market_open_scan_ran_at = datetime.now(_EASTERN)
    finally:
        app_state.auto_scan_running = False


def trigger_premarket_scan(app_state) -> bool:
    """Manually trigger a pre-market scan in a background thread. Returns False if one is already running."""
    if app_state.auto_scan_running:
        return False
    thread = threading.Thread(
        target=_run_premarket_scan,
        args=(app_state,),
        daemon=True,
        name="manual-premarket-scan",
    )
    thread.start()
    return True


def trigger_market_open_scan(app_state) -> bool:
    """Manually trigger a market-open scan in a background thread. Returns False if one is already running."""
    if app_state.auto_scan_running:
        return False
    thread = threading.Thread(
        target=_run_market_open_scan,
        args=(app_state,),
        daemon=True,
        name="manual-market-open-scan",
    )
    thread.start()
    return True


def _scheduler_loop(app_state) -> None:
    while True:
        try:
            now_et = datetime.now(_EASTERN)
            if _is_market_day(now_et) and not app_state.auto_scan_running:
                today_str = now_et.strftime("%Y-%m-%d")
                if _should_run_premarket(now_et, app_state, today_str):
                    _run_premarket_scan(app_state)
                elif _should_run_market_open(now_et, app_state, today_str):
                    _run_market_open_scan(app_state)
        except Exception as exc:
            logger.warning("[AUTO-SCAN] Scheduler error: %s", exc)
        time.sleep(60)


def start_auto_scan_scheduler(app_state) -> None:
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(app_state,),
        daemon=True,
        name="auto-scan-scheduler",
    )
    thread.start()
    logger.info("[AUTO-SCAN] Scheduler started")
