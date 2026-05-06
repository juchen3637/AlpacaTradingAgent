"""Disk-backed store of saved playbook 'plays' for the Trading tab.

A 'play' bundles everything the user needs to reopen a generated playbook
exactly where they left off:
  - the chosen scan row
  - the AI-generated `Playbook`
  - the model/provider used to generate it
  - chart UI state (timeframe + view toggles)
  - optional Alpaca order linkage

Stored as a single JSON file (`index.json`) with a list of plays. Atomic
writes via tempfile + os.replace, threaded access via a module-level lock.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tradingagents.scanner.longterm_models import LONGTERM_STRATEGY_ID, LongTermPlaybook
from tradingagents.scanner.models import Playbook

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tradingagents" / "dataflows" / "data_cache" / "saved_plays" / "index.json"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _playbook_to_dict(pb) -> dict:
    """Serialize either a day-trade Playbook or a LongTermPlaybook to a JSON-safe dict.

    asdict turns tuples into lists; we re-tuple on load.
    """
    return asdict(pb)


def _playbook_from_dict(d: dict) -> Playbook:
    """Rebuild a day-trade Playbook, dropping unknown keys and tuple-ifying lists.

    Tolerates schema evolution: extra keys ignored, missing optional keys
    fall back to dataclass defaults.
    """
    fields = set(Playbook.__dataclass_fields__.keys())
    clean = {k: v for k, v in d.items() if k in fields}
    if "indicators_to_watch" in clean and isinstance(clean["indicators_to_watch"], list):
        clean["indicators_to_watch"] = tuple(clean["indicators_to_watch"])
    return Playbook(**clean)


def _longterm_playbook_from_dict(d: dict) -> LongTermPlaybook:
    """Rebuild a LongTermPlaybook from its on-disk dict shape."""
    fields = set(LongTermPlaybook.__dataclass_fields__.keys())
    clean = {k: v for k, v in d.items() if k in fields}
    for key in ("key_drivers", "key_risks"):
        if key in clean and isinstance(clean[key], list):
            clean[key] = tuple(clean[key])
    return LongTermPlaybook(**clean)


class SavedPlaysStore:
    """Thread-safe, file-backed store of saved plays.

    Concurrency model: a single module-level lock guards both reads and writes.
    All writes go through `_write_all()` which performs an atomic
    tempfile→os.replace. A crash mid-write leaves the previous file intact.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ─── internals ─────────────────────────────────────────────────────

    def _read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("saved_plays: read failed (%s) — returning empty list", exc)
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("saved_plays: corrupted JSON (%s) — returning empty list", exc)
            return []
        if not isinstance(data, dict):
            return []
        if int(data.get("schema_version") or 0) != SCHEMA_VERSION:
            logger.warning(
                "saved_plays: schema_version mismatch (got %r, expected %d) — "
                "treating as empty",
                data.get("schema_version"), SCHEMA_VERSION,
            )
            return []
        plays = data.get("plays")
        return list(plays) if isinstance(plays, list) else []

    def _write_all(self, plays: list[dict]) -> None:
        """Atomic write: write to a sibling tempfile, then os.replace."""
        payload = {"schema_version": SCHEMA_VERSION, "plays": plays}
        encoded = json.dumps(payload, indent=2, default=str)

        # NamedTemporaryFile in the same directory so os.replace stays atomic
        # (cross-filesystem rename would not be atomic).
        fd, tmp_path = tempfile.mkstemp(
            prefix="saved_plays.", suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            # Tempfile may still exist if replace failed — clean up.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ─── public API ────────────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        """Return all saved plays, newest-opened first."""
        with self._lock:
            plays = self._read_all()
        plays.sort(
            key=lambda p: p.get("last_opened_at") or p.get("created_at") or "",
            reverse=True,
        )
        return plays

    def save(
        self,
        *,
        symbol: str,
        strategy_id: str,
        strategy_name: str,
        model: str,
        provider: str,
        playbook,  # Playbook | LongTermPlaybook
        scan_row: dict,
        ui_state: Optional[dict] = None,
        linked_alpaca: Optional[dict] = None,
        label: Optional[str] = None,
    ) -> dict:
        """Persist a new play. Returns the saved entry."""
        play_id = uuid.uuid4().hex
        now = _now_iso()
        entry = {
            "id": play_id,
            "label": label or f"{symbol} {strategy_id} {now[:10]}",
            "created_at": now,
            "last_opened_at": now,
            "status": "active",
            "symbol": symbol,
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "model": model,
            "provider": provider,
            "playbook": _playbook_to_dict(playbook),
            "scan_row": dict(scan_row or {}),
            "ui_state": dict(ui_state or {}),
            "linked_alpaca": dict(linked_alpaca or {}),
        }
        with self._lock:
            plays = self._read_all()
            plays.append(entry)
            self._write_all(plays)
        return entry

    def load(self, play_id: str) -> Optional[dict]:
        """Look up a play by id and return its dict (with playbook re-hydrated)."""
        with self._lock:
            plays = self._read_all()
        for p in plays:
            if p.get("id") == play_id:
                # Don't mutate the on-disk shape — return a copy with the
                # rehydrated Playbook attached so the caller can use either.
                out = dict(p)
                try:
                    if p.get("strategy_id") == LONGTERM_STRATEGY_ID:
                        out["playbook_obj"] = _longterm_playbook_from_dict(
                            p.get("playbook") or {}
                        )
                    else:
                        out["playbook_obj"] = _playbook_from_dict(p.get("playbook") or {})
                except Exception as exc:
                    logger.warning("saved_plays: failed to rehydrate playbook for %s: %s",
                                   play_id, exc)
                    out["playbook_obj"] = None
                return out
        return None

    def update_last_opened(self, play_id: str) -> None:
        with self._lock:
            plays = self._read_all()
            for p in plays:
                if p.get("id") == play_id:
                    p["last_opened_at"] = _now_iso()
                    self._write_all(plays)
                    return

    def delete(self, play_id: str) -> bool:
        """Remove a play by id. Returns True if removed, False if not found."""
        with self._lock:
            plays = self._read_all()
            new_plays = [p for p in plays if p.get("id") != play_id]
            if len(new_plays) == len(plays):
                return False
            self._write_all(new_plays)
            return True

    def rename(self, play_id: str, label: str) -> bool:
        with self._lock:
            plays = self._read_all()
            for p in plays:
                if p.get("id") == play_id:
                    p["label"] = label
                    self._write_all(plays)
                    return True
            return False

    def set_linked_alpaca(self, play_id: str, linked: dict) -> bool:
        """Attach Alpaca order linkage to a saved play. Used after Execute (Paper)
        re-submits a bracket from a saved playbook so subsequent Cancel/Exit
        flows can find the order. Overwrites any prior link."""
        with self._lock:
            plays = self._read_all()
            for p in plays:
                if p.get("id") == play_id:
                    p["linked_alpaca"] = dict(linked or {})
                    self._write_all(plays)
                    return True
            return False

    def set_verdict(self, play_id: str, verdict: dict) -> bool:
        """Attach an LLM viability verdict to a saved play. Overwrites any prior."""
        with self._lock:
            plays = self._read_all()
            for p in plays:
                if p.get("id") == play_id:
                    p["verdict"] = dict(verdict or {})
                    self._write_all(plays)
                    return True
            return False


# Module-level singleton — webui imports SAVED_PLAYS directly.
SAVED_PLAYS = SavedPlaysStore()


def playbook_from_dict(d: dict) -> Playbook:
    """Public re-export so callbacks can rehydrate a Playbook without
    reaching into the underscore helper."""
    return _playbook_from_dict(d)


def longterm_playbook_from_dict(d: dict) -> LongTermPlaybook:
    """Public re-export for long-term play rehydration."""
    return _longterm_playbook_from_dict(d)
