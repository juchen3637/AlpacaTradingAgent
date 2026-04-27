"""Unit tests for scanner data_provider helpers (pure compute functions + Finnhub float)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.scanner.data_provider import (
    _classify_catalyst_facts,
    _classify_stock_catalyst,
    _compute_intraday_metrics,
    _compute_macd_cross,
    _detect_press_release_category,
    _detect_filing_category,
    _fetch_catalyst,
    _fetch_corporate_actions,
    _fetch_filings,
    _fetch_float_shares,
    _fetch_insider,
    _fetch_press_releases,
    _session_open_utc,
)
from tradingagents.scanner.models import CatalystFacts


# ─── MACD cross ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_macd_cross_empty_series_returns_false():
    assert _compute_macd_cross(pd.Series([])) is False


@pytest.mark.unit
def test_macd_cross_too_short_returns_false():
    assert _compute_macd_cross(pd.Series([100.0] * 20)) is False


@pytest.mark.unit
def test_macd_cross_flat_series_no_cross():
    assert _compute_macd_cross(pd.Series([100.0] * 60)) is False


@pytest.mark.unit
def test_macd_cross_rising_trend_eventually_crosses():
    flat = [100.0] * 40
    rising = [100.0 + i for i in range(1, 30)]
    series = pd.Series(flat + rising)
    found_cross = any(
        _compute_macd_cross(series.iloc[: 40 + i])
        for i in range(1, 30)
    )
    assert found_cross


# ─── Intraday metrics ─────────────────────────────────────────────────

def _minute_bars(open_utc: datetime, prices: list[tuple[float, float, float, float]],
                 volumes: list[float]) -> pd.DataFrame:
    """Build a minute-bar DataFrame with a `timestamp` column starting at open_utc."""
    rows = []
    for i, ((o, h, l, c), v) in enumerate(zip(prices, volumes)):
        rows.append({
            "timestamp": open_utc + pd.Timedelta(minutes=i),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return pd.DataFrame(rows)


@pytest.mark.unit
def test_intraday_empty_df_returns_empty_dict():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=30)
    assert _compute_intraday_metrics(pd.DataFrame(), now, open_utc) == {}


@pytest.mark.unit
def test_intraday_missing_columns_returns_empty_dict():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    df = pd.DataFrame({"timestamp": [open_utc], "close": [100.0]})
    assert _compute_intraday_metrics(df, open_utc, open_utc) == {}


@pytest.mark.unit
def test_intraday_vwap_reclaim_true_when_dipped_then_recovers():
    # 6 bars: price pushes down below VWAP, closes back above.
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=6)
    df = _minute_bars(
        open_utc,
        # (open, high, low, close)
        [
            (100, 101, 99, 100),   # typical ~100
            (100, 100, 97, 98),    # dip below avg
            (98, 98, 96, 97),      # lower
            (97, 99, 97, 98),      # bounce
            (98, 102, 98, 101),    # reclaim
            (101, 103, 101, 102),  # continuation
        ],
        volumes=[1000] * 6,
    )
    metrics = _compute_intraday_metrics(df, now, open_utc)
    assert metrics["vwap"] is not None
    assert metrics["vwap_reclaim"] is True


@pytest.mark.unit
def test_intraday_vwap_reclaim_false_when_stayed_above():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=5)
    df = _minute_bars(
        open_utc,
        [
            (100, 102, 100, 101),
            (101, 103, 101, 102),
            (102, 104, 102, 103),
            (103, 105, 103, 104),
            (104, 106, 104, 105),
        ],
        volumes=[1000] * 5,
    )
    metrics = _compute_intraday_metrics(df, now, open_utc)
    assert metrics["vwap_reclaim"] is False


@pytest.mark.unit
def test_intraday_opening_range_high_is_max_of_first_5_bars():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=10)
    df = _minute_bars(
        open_utc,
        [
            (100, 105, 99, 102),
            (102, 108, 101, 107),  # highest of first 5
            (107, 106, 105, 106),
            (106, 107, 104, 105),
            (105, 106, 103, 104),
            # bars after the ORH window
            (104, 120, 104, 119),  # higher but excluded — ORH already fixed
        ],
        volumes=[1000] * 6,
    )
    metrics = _compute_intraday_metrics(df, now, open_utc)
    assert metrics["opening_range_high"] == pytest.approx(108.0)


@pytest.mark.unit
def test_intraday_opening_range_high_none_when_fewer_than_5_bars():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=3)
    df = _minute_bars(
        open_utc,
        [(100, 101, 99, 100)] * 3,
        volumes=[1000] * 3,
    )
    metrics = _compute_intraday_metrics(df, now, open_utc)
    assert metrics["opening_range_high"] is None


@pytest.mark.unit
def test_intraday_minutes_since_open_is_positive_during_session():
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=45)
    df = _minute_bars(open_utc, [(100, 101, 99, 100)] * 5, volumes=[1000] * 5)
    metrics = _compute_intraday_metrics(df, now, open_utc)
    assert metrics["minutes_since_open"] == 45


@pytest.mark.unit
def test_intraday_skips_premarket_bars_before_open():
    # Bars span 13:00 (pre-market) through 13:40. Only 13:30+ count.
    open_utc = datetime(2026, 4, 22, 13, 30, tzinfo=timezone.utc)
    now = open_utc + pd.Timedelta(minutes=10)
    bars_start = open_utc - pd.Timedelta(minutes=30)
    df = _minute_bars(bars_start, [(50, 50, 50, 50)] * 30 + [(100, 101, 99, 100)] * 10,
                      volumes=[1] * 30 + [1000] * 10)
    metrics = _compute_intraday_metrics(df, now, open_utc)
    # VWAP should be ~100, not diluted by the 50-priced premarket bars.
    assert metrics["vwap"] == pytest.approx(100.0, abs=1.0)


# ─── Session-open helper ──────────────────────────────────────────────

@pytest.mark.unit
def test_session_open_utc_summer_returns_13_30():
    # June = EDT (UTC-4) → 9:30 ET = 13:30 UTC
    now = datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc)
    result = _session_open_utc(now)
    assert result.hour == 13
    assert result.minute == 30


@pytest.mark.unit
def test_session_open_utc_winter_returns_14_30():
    # January = EST (UTC-5) → 9:30 ET = 14:30 UTC
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    result = _session_open_utc(now)
    assert result.hour == 14
    assert result.minute == 30


# ─── Float shares (Finnhub) ────────────────────────────────────────────

@pytest.mark.unit
def test_fetch_float_shares_converts_millions_to_raw():
    fake_client = MagicMock()
    fake_client.company_profile2.return_value = {"shareOutstanding": 150.0}
    # Use a unique week_key to force cache miss.
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_float_shares("TESTFLOATA", "unique-week-1")
    assert result == 150_000_000.0


@pytest.mark.unit
def test_fetch_float_shares_returns_none_when_missing():
    fake_client = MagicMock()
    fake_client.company_profile2.return_value = {}  # no shareOutstanding key
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_float_shares("TESTFLOATB", "unique-week-2")
    assert result is None


@pytest.mark.unit
def test_fetch_float_shares_returns_none_on_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("api down"),
    ):
        result = _fetch_float_shares("TESTFLOATC", "unique-week-3")
    assert result is None


# ─── Catalyst classifier (pure) ───────────────────────────────────────

def _news_dt(now_utc: datetime, hours_ago: float) -> int:
    """Return a Finnhub-style unix epoch seconds timestamp N hours before now."""
    return int((now_utc - pd.Timedelta(hours=hours_ago)).timestamp())


@pytest.mark.unit
def test_classify_catalyst_earnings_within_window_flags_catalyst():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    earnings = [{"date": "2026-04-23", "symbol": "NVDA"}]
    flag, text, details = _classify_stock_catalyst(earnings, [], now)
    assert flag is True
    assert "Earnings" in text
    assert "2026-04-23" in text


@pytest.mark.unit
def test_classify_catalyst_earnings_outside_window_ignored():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    earnings = [{"date": "2026-05-10", "symbol": "NVDA"}]  # far future
    flag, text, details = _classify_stock_catalyst(earnings, [], now)
    assert flag is False
    assert text is None


@pytest.mark.unit
def test_classify_catalyst_two_plus_articles_in_24h():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [
        {"headline": "Beats earnings handily", "datetime": _news_dt(now, 8)},
        {"headline": "Analyst upgrade to Buy", "datetime": _news_dt(now, 20)},
    ]
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is True
    assert text.startswith("News:")
    assert "Beats earnings" in text  # newest article (lowest hours_ago)


@pytest.mark.unit
def test_classify_catalyst_single_fresh_article_within_6h():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [{"headline": "FDA grants fast-track designation", "datetime": _news_dt(now, 2)}]
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is True
    assert "FDA" in text


@pytest.mark.unit
def test_classify_catalyst_single_stale_article_no_catalyst():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [{"headline": "Old news", "datetime": _news_dt(now, 20)}]  # 20h old, only 1
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is False
    assert text is None


@pytest.mark.unit
def test_classify_catalyst_empty_inputs():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    flag, text, details = _classify_stock_catalyst([], [], now)
    assert flag is False
    assert details is None
    assert text is None


@pytest.mark.unit
def test_classify_catalyst_earnings_takes_precedence_over_news():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    earnings = [{"date": "2026-04-22", "symbol": "NVDA"}]
    news = [
        {"headline": "Big story", "datetime": _news_dt(now, 1)},
        {"headline": "Other story", "datetime": _news_dt(now, 3)},
    ]
    flag, text, details = _classify_stock_catalyst(earnings, news, now)
    assert flag is True
    assert text.startswith("Earnings")


@pytest.mark.unit
def test_classify_catalyst_ignores_aggregation_headlines():
    # Movers/recap articles are effects of a move, not causes — must not flag catalyst.
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [
        {
            "headline": "Stay updated with the stocks that are on the move in today's after-hours session",
            "summary": "Top gainers and losers in today's after hours session.",
            "datetime": _news_dt(now, 3),
        },
        {
            "headline": "12 Health Care Stocks Moving In Wednesday's After-Market Session",
            "summary": "",
            "datetime": _news_dt(now, 7),
        },
        {
            "headline": "Biggest movers and shakers",
            "summary": "",
            "datetime": _news_dt(now, 8),
        },
    ]
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is False
    assert text is None


@pytest.mark.unit
def test_classify_catalyst_real_signal_survives_noise_filter():
    # Real news alongside aggregation noise still flags catalyst.
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [
        {"headline": "ACME receives FDA fast-track designation", "summary": "",
         "datetime": _news_dt(now, 2)},
        {"headline": "Top gainers and losers in today's session", "summary": "",
         "datetime": _news_dt(now, 3)},
    ]
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is True
    assert "FDA" in text


@pytest.mark.unit
def test_classify_catalyst_headline_truncated_to_80_chars():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    long_headline = "A" * 200
    news = [{"headline": long_headline, "datetime": _news_dt(now, 1)}]
    flag, text, details = _classify_stock_catalyst([], news, now)
    assert flag is True
    # "News: " prefix + up to 80 chars of headline
    assert len(text) <= len("News: ") + 80 + len("…")


# ─── Catalyst fetch (I/O) ─────────────────────────────────────────────

@pytest.mark.unit
def test_fetch_catalyst_crypto_short_circuits_returns_negative():
    # Crypto skips the Finnhub round-trip entirely (v1).
    result = _fetch_catalyst("BTC/USD", True, "unique-catalyst-key-v5-1")
    assert result["has_catalyst"] is False
    assert result["catalyst_text"] is None
    assert result["catalyst_details"] is None
    assert result["catalyst_category"] is None


@pytest.mark.unit
def test_fetch_catalyst_returns_negative_on_finnhub_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("boom"),
    ):
        result = _fetch_catalyst("TESTCATA", False, "unique-catalyst-key-v5-2")
    assert result["has_catalyst"] is False
    assert result["catalyst_text"] is None
    assert result["catalyst_category"] is None


@pytest.mark.unit
def test_fetch_catalyst_populates_from_earnings():
    fake_client = MagicMock()
    # Use today's date so the ±2-day window classifier always flags it.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake_client.earnings_calendar.return_value = {
        "earningsCalendar": [{"date": today, "symbol": "TESTCATB"}]
    }
    fake_client.company_news.return_value = []
    fake_client.press_releases.return_value = {"majorDevelopment": []}
    fake_client.filings.return_value = []
    fake_client.stock_insider_transactions.return_value = {"data": []}
    fake_client.stock_splits.return_value = []
    fake_client.stock_dividends2.return_value = []
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_catalyst("TESTCATB", False, "unique-catalyst-key-v5-3-today")
    assert result["has_catalyst"] is True
    assert "Earnings" in result["catalyst_text"]
    assert result["catalyst_category"] == "EARNINGS"


# ─── CatalystFacts (richer classifier) ───────────────────────────────

@pytest.mark.unit
def test_facts_earnings_category():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    earnings = [{"date": "2026-04-23", "symbol": "NVDA"}]
    facts = _classify_catalyst_facts(earnings, [], [], [], [], [], now_utc=now)
    assert isinstance(facts, CatalystFacts)
    assert facts.has_catalyst is True
    assert facts.category == "EARNINGS"
    assert "Earnings" in facts.short_text
    assert facts.raw_items  # not empty


@pytest.mark.unit
def test_facts_no_catalyst_returns_falsy_facts():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    facts = _classify_catalyst_facts([], [], [], [], [], [], now_utc=now)
    assert facts.has_catalyst is False
    assert facts.category is None
    assert facts.short_text is None


@pytest.mark.unit
def test_facts_priority_earnings_over_press_release():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    earnings = [{"date": "2026-04-23"}]
    press_releases = [
        {
            "headline": "Acquires Foo Inc",
            "datetime": _news_dt(now, 2),
            "description": "merger announcement",
        }
    ]
    facts = _classify_catalyst_facts(earnings, [], press_releases, [], [], [], now_utc=now)
    assert facts.category == "EARNINGS"


@pytest.mark.unit
def test_facts_press_release_categorized_as_ma():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    pr = [
        {
            "headline": "ACME announces definitive agreement to acquire Foo",
            "datetime": _news_dt(now, 3),
            "description": "M&A activity announcement",
            "url": "https://example.com/pr1",
        }
    ]
    facts = _classify_catalyst_facts([], [], pr, [], [], [], now_utc=now)
    assert facts.has_catalyst is True
    assert facts.category == "M&A"


@pytest.mark.unit
def test_facts_press_release_categorized_as_fda():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    pr = [
        {
            "headline": "ACME receives FDA approval for treatment X",
            "datetime": _news_dt(now, 1),
            "description": "FDA grants approval",
        }
    ]
    facts = _classify_catalyst_facts([], [], pr, [], [], [], now_utc=now)
    assert facts.category == "FDA"


@pytest.mark.unit
def test_facts_press_release_categorized_as_management():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    pr = [
        {
            "headline": "ACME appoints new Chief Executive Officer",
            "datetime": _news_dt(now, 4),
            "description": "CEO transition",
        }
    ]
    facts = _classify_catalyst_facts([], [], pr, [], [], [], now_utc=now)
    assert facts.category == "MANAGEMENT"


@pytest.mark.unit
def test_facts_filing_8k_item_201_is_ma():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    filings = [
        {
            "form": "8-K",
            "filedDate": "2026-04-22 09:00:00",
            "reportUrl": "https://sec.gov/example",
            "description": "Item 2.01 Completion of Acquisition",
        }
    ]
    facts = _classify_catalyst_facts([], [], [], filings, [], [], now_utc=now)
    assert facts.has_catalyst is True
    assert facts.category == "M&A"


@pytest.mark.unit
def test_facts_filing_8k_item_502_is_management():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    filings = [
        {
            "form": "8-K",
            "filedDate": "2026-04-22 09:00:00",
            "description": "Item 5.02 Departure of Directors or Certain Officers",
        }
    ]
    facts = _classify_catalyst_facts([], [], [], filings, [], [], now_utc=now)
    assert facts.category == "MANAGEMENT"


@pytest.mark.unit
def test_facts_insider_cluster_buys_flagged():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    insider = [
        {"name": "Alice", "transactionCode": "P", "transactionDate": "2026-04-20",
         "transactionPrice": 10.0, "share": 50000},
        {"name": "Bob", "transactionCode": "P", "transactionDate": "2026-04-19",
         "transactionPrice": 10.0, "share": 30000},
        {"name": "Carol", "transactionCode": "P", "transactionDate": "2026-04-18",
         "transactionPrice": 10.0, "share": 20000},
    ]
    facts = _classify_catalyst_facts([], [], [], [], insider, [], now_utc=now)
    assert facts.has_catalyst is True
    assert facts.category == "INSIDER"


@pytest.mark.unit
def test_facts_insider_single_small_buy_ignored():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    insider = [
        {"name": "Alice", "transactionCode": "P", "transactionDate": "2026-04-20",
         "transactionPrice": 10.0, "share": 100},
    ]
    facts = _classify_catalyst_facts([], [], [], [], insider, [], now_utc=now)
    assert facts.has_catalyst is False


@pytest.mark.unit
def test_facts_corporate_action_split_flagged():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    actions = [{"date": "2026-04-25", "fromFactor": 1, "toFactor": 10, "type": "split"}]
    facts = _classify_catalyst_facts([], [], [], [], [], actions, now_utc=now)
    assert facts.has_catalyst is True
    assert facts.category == "CORPORATE_ACTION"


@pytest.mark.unit
def test_facts_news_fallback_when_no_structured_signal():
    now = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
    news = [
        {"headline": "Beats earnings handily", "datetime": _news_dt(now, 8)},
        {"headline": "Analyst upgrade to Buy", "datetime": _news_dt(now, 20)},
    ]
    facts = _classify_catalyst_facts([], news, [], [], [], [], now_utc=now)
    assert facts.has_catalyst is True
    assert facts.category == "NEWS"


@pytest.mark.unit
def test_detect_press_release_category_keywords():
    assert _detect_press_release_category("ACME acquires Foo Inc", "merger") == "M&A"
    assert _detect_press_release_category("FDA fast-track designation granted", "") == "FDA"
    assert _detect_press_release_category("Phase 3 clinical trial results", "") == "FDA"
    assert _detect_press_release_category("Names new CFO", "") == "MANAGEMENT"
    assert _detect_press_release_category("Reports record quarterly revenue", "") == "PRESS_RELEASE"


@pytest.mark.unit
def test_detect_filing_category_8k_items():
    assert _detect_filing_category("8-K", "Item 2.01 Completion of Acquisition") == "M&A"
    assert _detect_filing_category("8-K", "Item 5.02 Departure of Officers") == "MANAGEMENT"
    assert _detect_filing_category("8-K", "Item 8.01 Other Events") == "FILING"
    assert _detect_filing_category("S-1", "registration") == "FILING"
    assert _detect_filing_category("13D", "beneficial ownership") == "FILING"


# ─── New fetch helpers (mocked Finnhub) ──────────────────────────────

@pytest.mark.unit
def test_fetch_press_releases_returns_list_on_success():
    fake_client = MagicMock()
    fake_client.press_releases.return_value = {
        "majorDevelopment": [{"headline": "FDA approval", "datetime": "2026-04-22"}]
    }
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_press_releases("TESTPR1", "unique-pr-1")
    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.unit
def test_fetch_press_releases_returns_empty_on_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("boom"),
    ):
        result = _fetch_press_releases("TESTPR2", "unique-pr-2")
    assert result == []


@pytest.mark.unit
def test_fetch_filings_returns_list_on_success():
    fake_client = MagicMock()
    fake_client.filings.return_value = [
        {"form": "8-K", "filedDate": "2026-04-22 09:00:00", "description": "Item 2.01"}
    ]
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_filings("TESTF1", "unique-f-1")
    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.unit
def test_fetch_filings_returns_empty_on_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("boom"),
    ):
        result = _fetch_filings("TESTF2", "unique-f-2")
    assert result == []


@pytest.mark.unit
def test_fetch_insider_returns_list_on_success():
    fake_client = MagicMock()
    fake_client.stock_insider_transactions.return_value = {
        "data": [{"name": "Alice", "transactionCode": "P", "share": 1000}]
    }
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_insider("TESTI1", "unique-i-1")
    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.unit
def test_fetch_insider_returns_empty_on_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("boom"),
    ):
        result = _fetch_insider("TESTI2", "unique-i-2")
    assert result == []


@pytest.mark.unit
def test_fetch_corporate_actions_combines_splits_and_dividends():
    fake_client = MagicMock()
    fake_client.stock_splits.return_value = [
        {"date": "2026-04-25", "fromFactor": 1, "toFactor": 10}
    ]
    fake_client.stock_dividends2.return_value = []
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        return_value=fake_client,
    ):
        result = _fetch_corporate_actions("TESTCA1", "unique-ca-1")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "split"


@pytest.mark.unit
def test_fetch_corporate_actions_returns_empty_on_exception():
    with patch(
        "tradingagents.dataflows.finnhub_utils.get_finnhub_client",
        side_effect=RuntimeError("boom"),
    ):
        result = _fetch_corporate_actions("TESTCA2", "unique-ca-2")
    assert result == []
