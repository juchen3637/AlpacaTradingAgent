"""Tests for the per-ticker entry-thesis store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents.agents.utils import thesis_store
from tradingagents.agents.utils.thesis_store import (
    _MAX_PER_TICKER,
    _THESIS_CHAR_CAP,
    add_entry_thesis,
    clear_entry_thesis,
    get_latest_entry_thesis,
)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Each test gets a fresh, throwaway JSON store path."""
    monkeypatch.setattr(thesis_store, "_STORE_PATH", tmp_path / "entry_theses.json")
    yield


def test_get_returns_none_when_empty():
    assert get_latest_entry_thesis("NVDA") is None


def test_add_then_get_round_trip():
    add_entry_thesis("NVDA", 500.0, "Strong AI demand")
    rec = get_latest_entry_thesis("NVDA")
    assert rec is not None
    assert rec["price"] == 500.0
    assert rec["thesis"] == "Strong AI demand"
    assert "ts" in rec


def test_add_returns_most_recent():
    add_entry_thesis("NVDA", 500.0, "first")
    add_entry_thesis("NVDA", 510.0, "second")
    rec = get_latest_entry_thesis("NVDA")
    assert rec["thesis"] == "second"
    assert rec["price"] == 510.0


def test_per_ticker_cap_keeps_latest_n():
    for i in range(_MAX_PER_TICKER + 5):
        add_entry_thesis("TSLA", 200.0 + i, f"thesis {i}")
    data = json.loads(Path(thesis_store._STORE_PATH).read_text())
    assert len(data["TSLA"]) == _MAX_PER_TICKER
    # The earliest 5 should have been dropped; the latest entry is kept.
    assert data["TSLA"][-1]["thesis"] == f"thesis {_MAX_PER_TICKER + 4}"


def test_thesis_truncated_to_char_cap():
    long_thesis = "x" * (_THESIS_CHAR_CAP + 200)
    add_entry_thesis("AAPL", 200.0, long_thesis)
    rec = get_latest_entry_thesis("AAPL")
    assert len(rec["thesis"]) == _THESIS_CHAR_CAP


def test_clear_removes_ticker_only():
    add_entry_thesis("NVDA", 500.0, "nvda thesis")
    add_entry_thesis("MSFT", 400.0, "msft thesis")
    clear_entry_thesis("NVDA")
    assert get_latest_entry_thesis("NVDA") is None
    assert get_latest_entry_thesis("MSFT") is not None


def test_clear_when_absent_is_no_op():
    clear_entry_thesis("UNKNOWN")
    assert get_latest_entry_thesis("UNKNOWN") is None


def test_empty_ticker_is_safe():
    add_entry_thesis("", 100.0, "thesis")
    assert get_latest_entry_thesis("") is None
    clear_entry_thesis("")  # must not raise


def test_corrupt_json_is_treated_as_empty(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr(thesis_store, "_STORE_PATH", bad)
    assert get_latest_entry_thesis("NVDA") is None
    # Still able to write a fresh thesis on top of corruption.
    add_entry_thesis("NVDA", 500.0, "fresh")
    rec = get_latest_entry_thesis("NVDA")
    assert rec["thesis"] == "fresh"


def test_atomic_write_uses_tmp_then_replace(tmp_path, monkeypatch):
    """Atomic-write detail: the .tmp suffix file should not linger after a successful write."""
    monkeypatch.setattr(thesis_store, "_STORE_PATH", tmp_path / "entry_theses.json")
    add_entry_thesis("NVDA", 500.0, "test")
    assert (tmp_path / "entry_theses.json").exists()
    assert not (tmp_path / "entry_theses.json.tmp").exists()


def test_none_price_is_recorded():
    """None price should not crash; stored as None."""
    add_entry_thesis("NVDA", None, "thesis")  # type: ignore[arg-type]
    rec = get_latest_entry_thesis("NVDA")
    assert rec["price"] is None
