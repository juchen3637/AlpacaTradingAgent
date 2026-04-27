"""Scanner pipeline orchestrator.

Takes a DataProvider (real or mocked) and a ScanFilters, returns ranked
ScanResult list. Pure orchestration — no API calls here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, Protocol

from .constants import MAX_RESULTS
from .filters import apply_filters
from .models import KeyLevels, ScanFilters, ScanResult, TickerSnapshot
from .strategies import get_strategy_name, match_strategy


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

    def run(self, filters: ScanFilters) -> list[ScanResult]:
        symbols = self.provider.build_universe(filters)
        results: list[ScanResult] = []

        for symbol in symbols:
            snap = self.provider.fetch_snapshot(symbol)
            if snap is None:
                continue
            if not apply_filters(snap, filters):
                continue

            # Level enrichment only for survivors (most expensive step)
            levels = self.provider.fetch_key_levels(symbol)
            snap = replace(snap, levels=levels)

            strategy_id = match_strategy(snap)
            if strategy_id is None:
                continue

            results.append(
                ScanResult(
                    snapshot=snap,
                    strategy_id=strategy_id,
                    strategy_name=get_strategy_name(strategy_id),
                    score=_score(snap),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:MAX_RESULTS]
