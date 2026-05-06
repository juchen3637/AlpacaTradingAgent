"""Unit tests for the long-term deep-dive synthesizer.

Covers prompt construction (score breakdown + fundamentals included),
graceful failure (empty string on missing inputs / LLM errors), and the
cache decorator integration.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tradingagents.scanner.longterm_deep_dive import (
    _build_user_prompt,
    _extract_text,
    _score_breakdown,
    generate_deep_dive,
)
from tradingagents.scanner.longterm_models import (
    LongTermScanResult,
    LongTermSnapshot,
)


def _scan_result(symbol: str = "NVDA") -> LongTermScanResult:
    snap = LongTermSnapshot(
        symbol=symbol, last_price=500.0, market_cap_b=1200.0,
        sector="Information Technology", industry="Semiconductors",
        roe_ttm=30.0, net_margin_ttm=40.0, revenue_growth_3y=25.0,
        pe_forward=35.0, debt_to_equity=0.4, dividend_yield_ttm=0.02,
        sma_50=480.0, sma_200=420.0, above_sma_200=True, golden_cross=True,
        wk52_high=520.0, wk52_low=380.0, one_year_return_pct=30.0,
    )
    return LongTermScanResult(snapshot=snap, score=0.85)


def _empty_snap_result() -> LongTermScanResult:
    """All-None metrics — exercises the missing-data path in the breakdown."""
    snap = LongTermSnapshot(symbol="ZZZ", last_price=10.0)
    return LongTermScanResult(snapshot=snap, score=0.5)


# ── Score breakdown helper ─────────────────────────────────────────────


@pytest.mark.unit
def test_score_breakdown_lists_all_seven_metrics() -> None:
    breakdown = _score_breakdown(_scan_result().snapshot)
    for label in ("ROE", "Net margin", "Rev 3y CAGR", "Forward P/E",
                  "LT trend", "Debt/Equity", "Div yield"):
        assert label in breakdown


@pytest.mark.unit
def test_score_breakdown_marks_missing_metrics_neutral() -> None:
    breakdown = _score_breakdown(_empty_snap_result().snapshot)
    # Every metric should be flagged n/a since the snapshot is empty.
    assert breakdown.count("n/a") >= 7
    assert "neutral" in breakdown


@pytest.mark.unit
def test_score_breakdown_includes_contribution_for_present_metrics() -> None:
    breakdown = _score_breakdown(_scan_result().snapshot)
    # ROE 30 → norm 1.0 (capped) × weight 0.20 = 0.200
    assert "ROE" in breakdown
    assert "0.20" in breakdown  # weight or contribution


# ── Prompt construction ────────────────────────────────────────────────


@pytest.mark.unit
def test_user_prompt_includes_symbol_score_and_breakdown() -> None:
    prompt = _build_user_prompt(_scan_result())
    assert "NVDA" in prompt
    assert "0.850" in prompt  # composite score
    assert "SCORE BREAKDOWN" in prompt
    assert "Information Technology" in prompt
    assert "200-SMA" in prompt
    assert "Golden cross" in prompt


@pytest.mark.unit
def test_user_prompt_handles_empty_snapshot() -> None:
    prompt = _build_user_prompt(_empty_snap_result())
    assert "ZZZ" in prompt
    assert "n/a" in prompt
    # The prompt must still instruct the LLM to web-search.
    assert "web search" in prompt.lower()


# ── Text extraction ────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_text_passthrough_string() -> None:
    assert _extract_text("hello") == "hello"


@pytest.mark.unit
def test_extract_text_concatenates_text_blocks() -> None:
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "tool_use", "name": "web_search"},  # ignored
        {"type": "text", "text": "second"},
    ]
    out = _extract_text(blocks)
    assert "first" in out and "second" in out
    assert "tool_use" not in out


@pytest.mark.unit
def test_extract_text_handles_none() -> None:
    assert _extract_text(None) == ""


# ── Top-level entry point ──────────────────────────────────────────────


@pytest.mark.unit
def test_generate_deep_dive_empty_input_returns_empty_string() -> None:
    """Defensive: a malformed scan_result must not raise."""
    bad = LongTermScanResult(
        snapshot=LongTermSnapshot(symbol="", last_price=0.0), score=0.0,
    )
    # Empty symbol short-circuits before any LLM call.
    assert generate_deep_dive(bad) == ""


@pytest.mark.unit
def test_generate_deep_dive_returns_llm_text_on_success() -> None:
    """Patch the cached LLM call so we don't hit the network."""
    expected = "## Why this candidate\n\nGreat margins.\n"
    with patch(
        "tradingagents.scanner.longterm_deep_dive._deep_dive_cached",
        return_value=expected,
    ):
        out = generate_deep_dive(_scan_result(), cache_key="2026-05-06")
    assert out == expected


@pytest.mark.unit
def test_generate_deep_dive_swallows_llm_errors() -> None:
    """A failing LLM should leave the UI with an empty string, not raise."""
    with patch(
        "tradingagents.scanner.longterm_deep_dive._deep_dive_cached",
        return_value="",
    ):
        out = generate_deep_dive(_scan_result(), cache_key="2026-05-06")
    assert out == ""
