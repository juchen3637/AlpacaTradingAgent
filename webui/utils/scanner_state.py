"""In-memory state for the Trading (scanner) tab.

Stores the most recent scan results and a small LRU of AI playbooks keyed by
(symbol, strategy_id, 5-minute bucket). Lives in-process only — no disk.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Optional

from tradingagents.scanner.models import Playbook, ScanResult

_PLAYBOOK_TTL_SECONDS = 12 * 3600  # 12 hours — covers a full trading session
_PLAYBOOK_MAX_ENTRIES = 64


class _ScannerState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_results: list[ScanResult] = []
        self._last_scan_ts: Optional[float] = None
        self._scan_id: int = 0
        self._playbooks: OrderedDict[tuple, tuple[float, Playbook]] = OrderedDict()

    # ─── scan results ──────────────────────────────────────────────────

    def set_results(self, results: list[ScanResult]) -> None:
        with self._lock:
            self._last_results = list(results)
            self._last_scan_ts = time.time()
            self._scan_id += 1

    def get_results(self) -> list[ScanResult]:
        with self._lock:
            return list(self._last_results)

    def last_scan_ts(self) -> Optional[float]:
        with self._lock:
            return self._last_scan_ts

    def scan_id(self) -> int:
        with self._lock:
            return self._scan_id

    # ─── playbook LRU ──────────────────────────────────────────────────

    @staticmethod
    def _bucket_key(symbol: str, strategy_id: str, model: str = "", scan_id: int = 0) -> tuple:
        # scan_id is incremented on every set_results() call so a new scan
        # always busts the playbook cache while repeated clicks within the same
        # scan session still hit the cache.
        return (symbol.upper(), strategy_id, model or "", scan_id)

    def get_playbook(
        self, symbol: str, strategy_id: str, model: str = "", scan_id: int = 0
    ) -> Optional[Playbook]:
        key = self._bucket_key(symbol, strategy_id, model, scan_id)
        with self._lock:
            entry = self._playbooks.get(key)
            if entry is None:
                return None
            ts, playbook = entry
            if time.time() - ts > _PLAYBOOK_TTL_SECONDS:
                del self._playbooks[key]
                return None
            # LRU bump
            self._playbooks.move_to_end(key)
            return playbook

    def set_playbook(
        self, symbol: str, strategy_id: str, playbook: Playbook, model: str = "", scan_id: int = 0
    ) -> None:
        key = self._bucket_key(symbol, strategy_id, model, scan_id)
        with self._lock:
            self._playbooks[key] = (time.time(), playbook)
            while len(self._playbooks) > _PLAYBOOK_MAX_ENTRIES:
                self._playbooks.popitem(last=False)


# Module-level singleton
SCANNER_STATE = _ScannerState()
