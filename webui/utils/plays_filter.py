"""Pure filter/sort logic for the Plays grid — no Dash imports.

Split out from `webui/callbacks/plays_callbacks.py` so it can be unit-tested
without dragging Dash, Plotly, or dash-bootstrap-components into the test
process. The callback module re-exports `filter_and_sort_plays` from here.
"""

from __future__ import annotations

from typing import Optional


def filter_and_sort_plays(
    plays: list[dict],
    *,
    symbol: str = "",
    status_filter: str = "all",
    verdict_filter: str = "any",
    sort_key: str = "last_opened_desc",
    positions_by_sym: Optional[dict] = None,
    unfilled_by_sym: Optional[dict] = None,
) -> list[dict]:
    """Apply filter + sort to the saved-plays list."""
    positions_by_sym = positions_by_sym or {}
    unfilled_by_sym = unfilled_by_sym or {}
    needle = (symbol or "").strip().upper()

    def _match(p: dict) -> bool:
        sym = (p.get("symbol") or "").upper()
        if needle and needle not in sym:
            return False
        if status_filter == "has_position" and sym not in positions_by_sym:
            return False
        if status_filter == "pending" and sym not in unfilled_by_sym:
            return False
        if status_filter == "none":
            if sym in positions_by_sym or sym in unfilled_by_sym:
                return False
        if status_filter == "unanalyzed" and p.get("verdict"):
            return False
        if verdict_filter != "any":
            v = (p.get("verdict") or {}).get("status")
            if v != verdict_filter:
                return False
        return True

    filtered = [p for p in plays if _match(p)]

    sorters = {
        "last_opened_desc": lambda p: (p.get("last_opened_at") or p.get("created_at") or "", True),
        "created_desc": lambda p: (p.get("created_at") or "", True),
        "created_asc": lambda p: (p.get("created_at") or "", False),
        "symbol_asc": lambda p: ((p.get("symbol") or "").upper(), False),
    }
    fn = sorters.get(sort_key, sorters["last_opened_desc"])
    samples = [(fn(p), p) for p in filtered]
    if not samples:
        return []
    descending = samples[0][0][1]
    samples.sort(key=lambda kv: kv[0][0], reverse=descending)
    return [p for _, p in samples]
