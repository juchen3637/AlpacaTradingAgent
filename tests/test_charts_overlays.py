"""Unit tests for the LWC payload builder helpers in webui/utils/charts_lwc.py.

Pure dict transformations — no Alpaca, no plotting library required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from webui.utils.charts_lwc import (
    _build_markers,
    _build_price_lines,
    _to_unix_seconds,
    empty_lwc_payload,
)


# ─── _build_price_lines ───────────────────────────────────────────────


@pytest.mark.unit
def test_price_lines_includes_all_four_levels_when_present():
    levels = {"entry": 1.62, "stop": 1.55, "pt1": 1.74, "pt2": 1.85}
    lines = _build_price_lines(levels)
    assert len(lines) == 4
    titles = [l["title"] for l in lines]
    assert any("ENTRY" in t for t in titles)
    assert any("STOP" in t for t in titles)
    assert any("PT1" in t for t in titles)
    assert any("PT2" in t for t in titles)


@pytest.mark.unit
def test_price_lines_skips_missing_levels():
    lines = _build_price_lines({"entry": 1.62, "stop": None})
    assert len(lines) == 1
    assert "ENTRY" in lines[0]["title"]


@pytest.mark.unit
def test_price_lines_skips_invalid_values():
    lines = _build_price_lines({"entry": "not-a-number", "stop": 1.55})
    assert len(lines) == 1
    assert "STOP" in lines[0]["title"]


@pytest.mark.unit
def test_price_lines_no_op_when_levels_none_or_empty():
    assert _build_price_lines(None) == []
    assert _build_price_lines({}) == []


@pytest.mark.unit
def test_price_lines_pt2_uses_dashed_line_style():
    # LWC LineStyle: 0=solid, 2=dashed
    lines = _build_price_lines({"pt2": 1.85})
    assert lines[0]["lineStyle"] == 2


@pytest.mark.unit
def test_price_lines_entry_uses_blue_solid():
    lines = _build_price_lines({"entry": 1.62})
    assert lines[0]["color"] == "#3B82F6"
    assert lines[0]["lineStyle"] == 0


@pytest.mark.unit
def test_price_lines_label_includes_price():
    lines = _build_price_lines({"entry": 1.62})
    assert "1.62" in lines[0]["title"]


# ─── _build_markers ───────────────────────────────────────────────────


@pytest.mark.unit
def test_markers_buy_uses_arrow_up_below_bar():
    fills = [{"price": 1.63, "qty": 100, "time": "2026-05-01T13:30:00Z", "side": "buy"}]
    markers = _build_markers(fills)
    assert len(markers) == 1
    assert markers[0]["shape"] == "arrowUp"
    assert markers[0]["position"] == "belowBar"
    assert markers[0]["color"] == "#22C55E"


@pytest.mark.unit
def test_markers_sell_uses_arrow_down_above_bar():
    fills = [{"price": 1.85, "qty": 100, "time": "2026-05-01T14:00:00Z", "side": "sell"}]
    markers = _build_markers(fills)
    assert len(markers) == 1
    assert markers[0]["shape"] == "arrowDown"
    assert markers[0]["position"] == "aboveBar"
    assert markers[0]["color"] == "#EF4444"


@pytest.mark.unit
def test_markers_separates_buy_and_sell_and_sorts_by_time():
    fills = [
        {"price": 1.85, "qty": 100, "time": "2026-05-01T14:00:00Z", "side": "sell"},
        {"price": 1.63, "qty": 100, "time": "2026-05-01T13:30:00Z", "side": "buy"},
    ]
    markers = _build_markers(fills)
    assert len(markers) == 2
    assert markers[0]["time"] < markers[1]["time"]
    assert markers[0]["shape"] == "arrowUp"
    assert markers[1]["shape"] == "arrowDown"


@pytest.mark.unit
def test_markers_skips_invalid_entries():
    fills = [
        {"price": "junk", "qty": 100, "time": "2026-05-01T13:30:00Z", "side": "buy"},
        {"price": 1.63, "qty": 100, "time": None, "side": "buy"},
        "not-a-dict",
    ]
    markers = _build_markers(fills)
    assert markers == []


@pytest.mark.unit
def test_markers_no_op_when_none_or_empty():
    assert _build_markers(None) == []
    assert _build_markers([]) == []


@pytest.mark.unit
def test_markers_default_side_is_buy():
    fills = [{"price": 1.63, "qty": 100, "time": "2026-05-01T13:30:00Z"}]
    markers = _build_markers(fills)
    assert len(markers) == 1
    assert markers[0]["shape"] == "arrowUp"


@pytest.mark.unit
def test_markers_text_includes_qty():
    fills = [{"price": 1.63, "qty": 250, "time": "2026-05-01T13:30:00Z", "side": "buy"}]
    markers = _build_markers(fills)
    assert "250" in markers[0]["text"]


# ─── _to_unix_seconds ─────────────────────────────────────────────────


@pytest.mark.unit
def test_to_unix_seconds_handles_iso_string_with_z():
    s = _to_unix_seconds("2026-05-01T13:30:00Z")
    assert s is not None
    expected = int(datetime(2026, 5, 1, 13, 30, tzinfo=timezone.utc).timestamp())
    assert s == expected


@pytest.mark.unit
def test_to_unix_seconds_returns_none_for_invalid():
    assert _to_unix_seconds(None) is None
    assert _to_unix_seconds("not-a-date") is None


# ─── empty_lwc_payload ────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_payload_has_two_series():
    payload = empty_lwc_payload()
    assert payload["seriesTypes"] == ["candlestick", "histogram"]
    assert payload["seriesData"] == [[], []]
    assert payload["seriesPriceLines"] == [[], []]
    assert payload["seriesMarkers"] == [[], []]
    assert "chartOptions" in payload
