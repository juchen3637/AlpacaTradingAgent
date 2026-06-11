"""Tests for webui.utils.ai_picks — AI Picked Stocks discovery and scheduling."""

from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

from tradingagents.speculation.models import SpeculationEvent, SpeculativePlay
from webui.utils.ai_picks import (
    _MAX_TOTAL_TICKERS,
    _AIPicksState,
    discover_ai_tickers,
    merge_tickers,
)

_EASTERN = pytz.timezone("US/Eastern")


def _eastern_dt(hour: int, day: int = 10) -> datetime:
    return _EASTERN.localize(datetime(2026, 6, day, hour, 5))


def _play(ticker: str, confidence: str = "high") -> SpeculativePlay:
    return SpeculativePlay(
        event=SpeculationEvent(headline="h", source="s", published_at="d", snippet="x"),
        ticker=ticker,
        company_name=f"{ticker} Inc",
        sector="Tech",
        direction="bullish",
        confidence=confidence,
        reasoning="r",
        catalyst_type="sentiment",
    )


# ── merge_tickers ──


@pytest.mark.unit
def test_merge_preserves_manual_order_and_dedupes():
    assert merge_tickers(["NVDA", "AMD"], ["TSLA", "NVDA", "ARCH"]) == [
        "NVDA",
        "AMD",
        "TSLA",
        "ARCH",
    ]


@pytest.mark.unit
def test_merge_caps_total_with_manual_priority():
    manual = [f"M{i}" for i in range(20)]
    ai = [f"A{i}" for i in range(20)]
    merged = merge_tickers(manual, ai)
    assert len(merged) == _MAX_TOTAL_TICKERS
    assert merged[:20] == manual
    assert merged[20:] == ai[:5]


# ── discover_ai_tickers ──


@pytest.mark.unit
def test_discover_merges_high_and_medium_confidence():
    plays = [_play("ARCH", "high"), _play("BWXT", "medium"), _play("PENNY", "low")]
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=plays):
        with patch("webui.utils.ai_picks._is_tradeable", return_value=True):
            merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "claude-sonnet-4-6", ["NVDA"])
    assert merged == ["NVDA", "ARCH", "BWXT"]
    assert ai_only == ["ARCH", "BWXT"]
    assert [p.ticker for p in ai_plays] == ["ARCH", "BWXT"]


@pytest.mark.unit
def test_discover_skips_duplicates_of_manual():
    plays = [_play("NVDA"), _play("ARCH")]
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=plays):
        with patch("webui.utils.ai_picks._is_tradeable", return_value=True):
            merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", ["NVDA"])
    assert merged == ["NVDA", "ARCH"]
    assert ai_only == ["ARCH"]
    assert len(ai_plays) == 1 and ai_plays[0].ticker == "ARCH"


@pytest.mark.unit
def test_discover_empty_picks_returns_manual_only():
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=[]):
        merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", ["NVDA", "AMD"])
    assert merged == ["NVDA", "AMD"]
    assert ai_only == []
    assert ai_plays == []


@pytest.mark.unit
def test_discover_engine_exception_falls_back_to_manual():
    with patch(
        "tradingagents.speculation.engine.SpeculationEngine.run",
        side_effect=RuntimeError("LLM down"),
    ):
        merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", ["NVDA"])
    assert merged == ["NVDA"]
    assert ai_only == []
    assert ai_plays == []


@pytest.mark.unit
def test_discover_respects_max_picks():
    plays = [_play(f"T{i}") for i in range(15)]
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=plays):
        with patch("webui.utils.ai_picks._is_tradeable", return_value=True):
            merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", [], max_picks=10)
    assert len(ai_only) == 10
    assert merged == ai_only
    assert len(ai_plays) == 10


@pytest.mark.unit
def test_discover_filters_slash_tickers():
    plays = [_play("BTC/USD"), _play("ARCH")]
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=plays):
        with patch("webui.utils.ai_picks._is_tradeable", return_value=True):
            _, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", [])
    assert ai_only == ["ARCH"]
    assert len(ai_plays) == 1 and ai_plays[0].ticker == "ARCH"


@pytest.mark.unit
def test_discover_skips_non_tradeable_tickers():
    plays = [_play("SPCX"), _play("ARCH")]
    tradeable = {"ARCH": True, "SPCX": False}
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=plays):
        with patch("webui.utils.ai_picks._is_tradeable", side_effect=lambda t: tradeable.get(t, False)):
            _, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", [])
    assert ai_only == ["ARCH"]
    assert len(ai_plays) == 1 and ai_plays[0].ticker == "ARCH"


@pytest.mark.unit
def test_discover_plays_excluded_by_merge_cap():
    """Plays for tickers that don't survive the merge cap are excluded from ai_plays."""
    manual = [f"M{i}" for i in range(24)]  # 24 manual tickers → only 1 AI slot left
    ai_play_list = [_play(f"A{i}") for i in range(5)]
    with patch("tradingagents.speculation.engine.SpeculationEngine.run", return_value=ai_play_list):
        with patch("webui.utils.ai_picks._is_tradeable", return_value=True):
            merged, ai_only, ai_plays = discover_ai_tickers("anthropic", "m", manual, max_picks=5)
    assert len(merged) == 25
    assert len(ai_only) == 1
    assert len(ai_plays) == 1


# ── _AIPicksState.should_rediscover ──


@pytest.mark.unit
def test_should_rediscover_first_call_any_hour():
    state = _AIPicksState()
    assert state.should_rediscover(_eastern_dt(10)) is True


@pytest.mark.unit
def test_should_rediscover_false_outside_window_after_discovery():
    state = _AIPicksState()
    state.set_tickers(["ARCH"], hour=9, date="2026-06-10")
    for hour in (10, 11, 13, 14, 16):
        assert state.should_rediscover(_eastern_dt(hour)) is False


@pytest.mark.unit
def test_should_rediscover_true_at_12_and_15_same_day():
    state = _AIPicksState()
    state.set_tickers(["ARCH"], hour=9, date="2026-06-10")
    assert state.should_rediscover(_eastern_dt(12)) is True
    state.set_tickers(["ARCH"], hour=12, date="2026-06-10")
    assert state.should_rediscover(_eastern_dt(15)) is True


@pytest.mark.unit
def test_should_rediscover_false_same_hour_same_day():
    state = _AIPicksState()
    state.set_tickers(["ARCH"], hour=12, date="2026-06-10")
    assert state.should_rediscover(_eastern_dt(12)) is False


@pytest.mark.unit
def test_should_rediscover_true_new_day_at_9am():
    state = _AIPicksState()
    state.set_tickers(["ARCH"], hour=15, date="2026-06-10")
    assert state.should_rediscover(_eastern_dt(9, day=11)) is True


@pytest.mark.unit
def test_get_tickers_returns_copy():
    state = _AIPicksState()
    state.set_tickers(["ARCH"], hour=9, date="2026-06-10")
    tickers = state.get_tickers()
    tickers.append("XXX")
    assert state.get_tickers() == ["ARCH"]
