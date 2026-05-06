"""Unit tests for the pure filter/sort helper used by the Plays grid."""

from __future__ import annotations

import pytest

from webui.utils.plays_filter import filter_and_sort_plays


def _play(**kwargs) -> dict:
    base = {
        "id": "x",
        "symbol": "NVDA",
        "label": "play",
        "created_at": "2026-05-01T10:00:00+00:00",
        "last_opened_at": "2026-05-01T10:00:00+00:00",
        "playbook": {},
    }
    base.update(kwargs)
    return base


@pytest.mark.unit
def test_filter_by_symbol_substring():
    plays = [_play(id="1", symbol="NVDA"), _play(id="2", symbol="AMD"),
             _play(id="3", symbol="TSLA")]
    out = filter_and_sort_plays(plays, symbol="MD")
    assert [p["id"] for p in out] == ["2"]


@pytest.mark.unit
def test_filter_status_has_position():
    plays = [_play(id="1", symbol="NVDA"), _play(id="2", symbol="AMD")]
    pos_by_sym = {"NVDA": {"Symbol": "NVDA"}}
    out = filter_and_sort_plays(plays, status_filter="has_position",
                                positions_by_sym=pos_by_sym)
    assert [p["id"] for p in out] == ["1"]


@pytest.mark.unit
def test_filter_status_pending():
    plays = [_play(id="1", symbol="NVDA"), _play(id="2", symbol="AMD")]
    unfilled_by_sym = {"AMD": [{"id": "o1", "symbol": "AMD"}]}
    out = filter_and_sort_plays(plays, status_filter="pending",
                                unfilled_by_sym=unfilled_by_sym)
    assert [p["id"] for p in out] == ["2"]


@pytest.mark.unit
def test_filter_status_none_excludes_position_and_pending():
    plays = [_play(id="1", symbol="NVDA"), _play(id="2", symbol="AMD"),
             _play(id="3", symbol="TSLA")]
    pos = {"NVDA": {"Symbol": "NVDA"}}
    unfilled = {"AMD": [{"id": "o1", "symbol": "AMD"}]}
    out = filter_and_sort_plays(plays, status_filter="none",
                                positions_by_sym=pos, unfilled_by_sym=unfilled)
    assert [p["id"] for p in out] == ["3"]


@pytest.mark.unit
def test_filter_unanalyzed():
    plays = [
        _play(id="1", verdict={"status": "still_viable"}),
        _play(id="2"),  # no verdict
        _play(id="3", verdict={"status": "degraded"}),
    ]
    out = filter_and_sort_plays(plays, status_filter="unanalyzed")
    assert [p["id"] for p in out] == ["2"]


@pytest.mark.unit
def test_filter_verdict():
    plays = [
        _play(id="1", verdict={"status": "still_viable"}),
        _play(id="2", verdict={"status": "degraded"}),
        _play(id="3", verdict={"status": "invalidated"}),
    ]
    out = filter_and_sort_plays(plays, verdict_filter="degraded")
    assert [p["id"] for p in out] == ["2"]


@pytest.mark.unit
def test_sort_last_opened_desc():
    plays = [
        _play(id="1", last_opened_at="2026-05-01T10:00:00+00:00"),
        _play(id="2", last_opened_at="2026-05-03T10:00:00+00:00"),
        _play(id="3", last_opened_at="2026-05-02T10:00:00+00:00"),
    ]
    out = filter_and_sort_plays(plays, sort_key="last_opened_desc")
    assert [p["id"] for p in out] == ["2", "3", "1"]


@pytest.mark.unit
def test_sort_symbol_asc():
    plays = [_play(id="1", symbol="NVDA"), _play(id="2", symbol="AMD"),
             _play(id="3", symbol="TSLA")]
    out = filter_and_sort_plays(plays, sort_key="symbol_asc")
    assert [p["id"] for p in out] == ["2", "1", "3"]


@pytest.mark.unit
def test_filter_combined_symbol_and_verdict():
    plays = [
        _play(id="1", symbol="NVDA", verdict={"status": "still_viable"}),
        _play(id="2", symbol="NVDQ", verdict={"status": "degraded"}),
        _play(id="3", symbol="NVDA", verdict={"status": "degraded"}),
    ]
    out = filter_and_sort_plays(plays, symbol="NVDA", verdict_filter="degraded")
    assert [p["id"] for p in out] == ["3"]
