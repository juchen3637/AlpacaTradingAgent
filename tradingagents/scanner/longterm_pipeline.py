"""Long-term scan pipeline orchestrator.

Pure orchestration: takes a `LongTermDataProvider` (real or mocked) and a
`LongTermFilters`, returns ranked `LongTermScanResult` list. No I/O of its
own.

Snapshots are fetched in parallel via ThreadPoolExecutor (Finnhub free-tier
is 60 calls/min; with ~100 symbols × 2 calls = ~200 calls, sequential would
take ~3-4 minutes on a cold cache).
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Optional, Protocol

from .longterm_filters import apply_longterm_filters
from .longterm_models import LongTermFilters, LongTermScanResult, LongTermSnapshot
from .longterm_scoring import score_longterm

logger = logging.getLogger(__name__)

LONGTERM_MAX_RESULTS = 25
_DEFAULT_WORKERS = 8


class LongTermProvider(Protocol):
    def build_universe(self, filters: LongTermFilters) -> list[str]: ...
    def fetch_snapshot(self, symbol: str) -> Optional[LongTermSnapshot]: ...


class LongTermPipeline:
    def __init__(self, provider: LongTermProvider, *, max_workers: int = _DEFAULT_WORKERS):
        self.provider = provider
        self.max_workers = max(1, max_workers)

    def _fetch_all(self, symbols: list[str]) -> list[LongTermSnapshot]:
        if self.max_workers == 1 or len(symbols) <= 1:
            out: list[LongTermSnapshot] = []
            for s in symbols:
                snap = self.provider.fetch_snapshot(s)
                if snap is not None:
                    out.append(snap)
            return out

        out2: list[LongTermSnapshot] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self.provider.fetch_snapshot, s): s for s in symbols}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    snap = fut.result()
                except Exception as exc:
                    logger.debug("snapshot future failed for %s: %s",
                                 futures[fut], exc)
                    continue
                if snap is not None:
                    out2.append(snap)
        return out2

    def run(self, filters: LongTermFilters) -> list[LongTermScanResult]:
        symbols = self.provider.build_universe(filters)
        snaps = self._fetch_all(symbols)
        results: list[LongTermScanResult] = []
        for snap in snaps:
            if not apply_longterm_filters(snap, filters):
                continue
            results.append(LongTermScanResult(snapshot=snap, score=score_longterm(snap)))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:LONGTERM_MAX_RESULTS]
