"""In-memory state for the Long-Term subtab.

Mirrors `scanner_state.SCANNER_STATE` but for `LongTermScanResult` and
`LongTermPlaybook`. Lives in-process only — no disk.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Optional

from tradingagents.scanner.longterm_models import LongTermPlaybook, LongTermScanResult

_PLAYBOOK_TTL_SECONDS = 24 * 3600
_PLAYBOOK_MAX_ENTRIES = 64


class _LongTermState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_results: list[LongTermScanResult] = []
        self._last_scan_ts: Optional[float] = None
        self._playbooks: OrderedDict[tuple, tuple[float, LongTermPlaybook]] = OrderedDict()

    def set_results(self, results: list[LongTermScanResult]) -> None:
        with self._lock:
            self._last_results = list(results)
            self._last_scan_ts = time.time()

    def get_results(self) -> list[LongTermScanResult]:
        with self._lock:
            return list(self._last_results)

    def last_scan_ts(self) -> Optional[float]:
        with self._lock:
            return self._last_scan_ts

    @staticmethod
    def _bucket_key(symbol: str, model: str = "") -> tuple:
        return (symbol.upper(), model or "")

    def get_playbook(self, symbol: str, model: str = "") -> Optional[LongTermPlaybook]:
        key = self._bucket_key(symbol, model)
        with self._lock:
            entry = self._playbooks.get(key)
            if entry is None:
                return None
            ts, pb = entry
            if time.time() - ts > _PLAYBOOK_TTL_SECONDS:
                del self._playbooks[key]
                return None
            self._playbooks.move_to_end(key)
            return pb

    def set_playbook(self, symbol: str, playbook: LongTermPlaybook,
                     model: str = "") -> None:
        key = self._bucket_key(symbol, model)
        with self._lock:
            self._playbooks[key] = (time.time(), playbook)
            while len(self._playbooks) > _PLAYBOOK_MAX_ENTRIES:
                self._playbooks.popitem(last=False)


LONGTERM_STATE = _LongTermState()
