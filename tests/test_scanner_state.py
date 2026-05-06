"""Tests for the in-memory scanner state (results store + playbook LRU)."""

from __future__ import annotations

import pytest

from tradingagents.scanner.models import KeyLevels, Playbook, ScanResult, TickerSnapshot
from webui.utils.scanner_state import _ScannerState


def _snap(symbol: str = "NVDA") -> TickerSnapshot:
    return TickerSnapshot(
        symbol=symbol, is_crypto=False, last_price=100.0, change_pct=1.0,
        levels=KeyLevels(),
    )


def _playbook(symbol: str = "NVDA") -> Playbook:
    return Playbook(
        symbol=symbol, strategy_id="ATH_BREAKOUT",
        thesis="t", entry_trigger="e", entry_price=100.0,
        order_type="Buy Stop",
        stop_loss=99.0, profit_target_1=102.0, profit_target_2=104.0,
        risk_reward=2.0, position_size_pct=0.05,
        indicators_to_watch=("VWAP",), invalidation="inv", confidence="medium",
    )


@pytest.mark.unit
def test_results_round_trip():
    state = _ScannerState()
    assert state.get_results() == []
    results = [ScanResult(snapshot=_snap(), strategy_id="X", strategy_name="X", score=1)]
    state.set_results(results)
    assert len(state.get_results()) == 1
    assert state.last_scan_ts() is not None


@pytest.mark.unit
def test_playbook_cache_miss_returns_none():
    state = _ScannerState()
    assert state.get_playbook("NVDA", "ATH_BREAKOUT") is None


@pytest.mark.unit
def test_playbook_cache_hit_returns_same_playbook():
    state = _ScannerState()
    pb = _playbook()
    state.set_playbook("NVDA", "ATH_BREAKOUT", pb)
    got = state.get_playbook("NVDA", "ATH_BREAKOUT")
    assert got is pb


@pytest.mark.unit
def test_playbook_cache_case_insensitive_symbol():
    state = _ScannerState()
    pb = _playbook()
    state.set_playbook("nvda", "ATH_BREAKOUT", pb)
    assert state.get_playbook("NVDA", "ATH_BREAKOUT") is pb


@pytest.mark.unit
def test_playbook_cache_lru_evicts_oldest():
    state = _ScannerState()
    # Fill past capacity
    for i in range(70):
        state.set_playbook(f"T{i}", "S", _playbook(symbol=f"T{i}"))
    # First few entries should be evicted
    assert state.get_playbook("T0", "S") is None
    # Most recent entries should still be there
    assert state.get_playbook("T69", "S") is not None
