"""Per-ticker entry-thesis store.

Records the short thesis behind each trade entry so the trader and risk-manager
prompts can recall *why* a position was opened when re-evaluating it later.

A flat JSON file under ``agent_memories/`` — no embeddings, no API calls. We
look up by ticker, so similarity search is unnecessary; cheap and reliable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

# Anchor to the repo root regardless of process cwd. This file lives at
# tradingagents/agents/utils/thesis_store.py — three parents up is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_STORE_PATH = _REPO_ROOT / "agent_memories" / "entry_theses.json"
_LOCK = Lock()
_MAX_PER_TICKER = 10
_THESIS_CHAR_CAP = 500


def _load() -> dict[str, list[dict[str, Any]]]:
    if not _STORE_PATH.exists():
        return {}
    try:
        data = json.loads(_STORE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _STORE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp_path.replace(_STORE_PATH)


def add_entry_thesis(ticker: str, price: float, thesis: str) -> None:
    """Append a new entry-thesis record for ``ticker``.

    Truncates ``thesis`` to a compact summary and caps history at
    ``_MAX_PER_TICKER`` entries per ticker to bound disk growth.
    Best-effort: any I/O error is swallowed so trading flow is never blocked.
    """
    if not ticker:
        return
    summary = (thesis or "").strip()[:_THESIS_CHAR_CAP]
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "price": float(price) if price is not None else None,
        "thesis": summary,
    }
    try:
        with _LOCK:
            data = _load()
            entries = data.get(ticker, [])
            entries.append(record)
            data[ticker] = entries[-_MAX_PER_TICKER:]
            _save(data)
    except Exception as e:
        print(f"[THESIS_STORE] Failed to persist thesis for {ticker}: {e}")


def get_latest_entry_thesis(ticker: str) -> Optional[dict[str, Any]]:
    """Return the most recent entry thesis for ``ticker``, or None."""
    if not ticker:
        return None
    try:
        with _LOCK:
            data = _load()
            entries = data.get(ticker, [])
            return entries[-1] if entries else None
    except Exception:
        return None


def clear_entry_thesis(ticker: str) -> None:
    """Remove the recorded entry-thesis history for a ticker.

    Should be called when a position is closed (manually or via stop-loss)
    so the next entry doesn't surface a stale thesis.
    """
    if not ticker:
        return
    try:
        with _LOCK:
            data = _load()
            if ticker in data:
                del data[ticker]
                _save(data)
    except Exception as e:
        print(f"[THESIS_STORE] Failed to clear thesis for {ticker}: {e}")
