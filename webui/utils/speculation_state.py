"""In-memory state for the Speculation tab.

Mirrors the _ScannerState pattern from scanner_state.py.
Stores last scan results and exposes signals for Day Trading integration.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from tradingagents.speculation.models import SpeculativePlay

_SIGNALS_MAX_AGE = 4 * 3600  # auto-clear signals older than 4 hours


class _SpeculationState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plays: list[SpeculativePlay] = []
        self._last_scan_ts: Optional[float] = None
        self._is_scanning: bool = False

    def set_scanning(self, scanning: bool) -> None:
        with self._lock:
            self._is_scanning = scanning

    def is_scanning(self) -> bool:
        with self._lock:
            return self._is_scanning

    def set_plays(self, plays: list[SpeculativePlay]) -> None:
        with self._lock:
            self._plays = list(plays)
            self._last_scan_ts = time.time()

    def get_plays(self) -> list[SpeculativePlay]:
        with self._lock:
            return list(self._plays)

    def last_scan_ts(self) -> Optional[float]:
        with self._lock:
            return self._last_scan_ts

    def is_expired(self) -> bool:
        with self._lock:
            return self._last_scan_ts is not None and (
                time.time() - self._last_scan_ts > _SIGNALS_MAX_AGE
            )

    def get_signals(self) -> dict[str, str]:
        """Return {ticker: 'bullish'|'bearish'} for active plays."""
        with self._lock:
            if self._last_scan_ts is None:
                return {}
            if time.time() - self._last_scan_ts > _SIGNALS_MAX_AGE:
                return {}
            return {p.ticker: p.direction for p in self._plays}


SPECULATION_STATE = _SpeculationState()
