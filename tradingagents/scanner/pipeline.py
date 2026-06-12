"""Scanner pipeline orchestrator.

Takes a DataProvider (real or mocked) and a ScanFilters, returns ranked
ScanResult list. Pure orchestration — no API calls here.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Optional, Protocol

from .constants import MAX_RESULTS
from .filters import apply_filters
from .models import KeyLevels, ScanFilters, ScanResult, TickerSnapshot
from .strategies import get_strategy_name, match_strategy

_SNAPSHOT_WORKERS = 20
_LEVELS_WORKERS = 10


class DataProvider(Protocol):
    def build_universe(self, filters: ScanFilters) -> list[str]: ...
    def fetch_snapshot(self, symbol: str) -> Optional[TickerSnapshot]: ...
    def fetch_key_levels(self, symbol: str) -> KeyLevels: ...


def _score(snap: TickerSnapshot) -> float:
    """Rank composite: RVOL + ATH proximity + catalyst + absolute move."""
    rvol_norm = min(snap.rvol or 0.0, 20.0) / 20.0
    ath = snap.levels.ath or snap.levels.wk52_high or 0.0
    ath_score = 0.0
    if ath > 0:
        ath_score = max(0.0, 1 - abs((ath - snap.last_price) / ath))
    catalyst = 1.0 if snap.has_catalyst else 0.0
    change = min(abs(snap.change_pct) / 100.0, 1.0)
    return 0.4 * rvol_norm + 0.3 * ath_score + 0.2 * catalyst + 0.1 * change


class ScannerPipeline:
    def __init__(self, provider: DataProvider):
        self.provider = provider

    def run(
        self,
        filters: ScanFilters,
        cancel: Optional[threading.Event] = None,
    ) -> list[ScanResult]:
        symbols = self.provider.build_universe(filters)

        if cancel and cancel.is_set():
            return []

        if not symbols:
            return []

        # Phase 1: fetch snapshots for all symbols in parallel
        snapshots: dict[str, TickerSnapshot] = {}
        _failed_snapshots: list[str] = []
        with ThreadPoolExecutor(max_workers=min(len(symbols), _SNAPSHOT_WORKERS)) as pool:
            futures = {pool.submit(self.provider.fetch_snapshot, sym): sym for sym in symbols}
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    snap = future.result()
                except Exception as snap_err:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "[SCANNER] Snapshot fetch failed for %s: %s", sym, snap_err
                    )
                    _failed_snapshots.append(sym)
                    snap = None
                if snap is not None:
                    snapshots[sym] = snap
        if _failed_snapshots:
            import logging as _log
            _log.getLogger(__name__).warning(
                "[SCANNER] %d/%d symbols dropped due to snapshot errors: %s",
                len(_failed_snapshots), len(symbols), _failed_snapshots[:20],
            )

        if cancel and cancel.is_set():
            return []

        # Phase 2: filter survivors (pure compute, no I/O)
        survivors: list[TickerSnapshot] = [
            snap for snap in snapshots.values() if apply_filters(snap, filters)
        ]

        # Phase 3: enrich survivors with key levels in parallel (most expensive per-symbol step)
        def _enrich(snap: TickerSnapshot) -> Optional[ScanResult]:
            if cancel and cancel.is_set():
                return None
            levels = self.provider.fetch_key_levels(snap.symbol)
            snap = replace(snap, levels=levels)
            strategy_id = match_strategy(snap)
            if strategy_id is None:
                return None
            return ScanResult(
                snapshot=snap,
                strategy_id=strategy_id,
                strategy_name=get_strategy_name(strategy_id),
                score=_score(snap),
            )

        results: list[ScanResult] = []
        with ThreadPoolExecutor(max_workers=min(len(survivors), _LEVELS_WORKERS) or 1) as pool:
            for result in pool.map(_enrich, survivors):
                if result is not None:
                    results.append(result)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:MAX_RESULTS]
