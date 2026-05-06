"""Unit tests for webui.utils.saved_plays.SavedPlaysStore."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tradingagents.scanner.models import Playbook
from webui.utils.saved_plays import (
    SavedPlaysStore,
    SCHEMA_VERSION,
    playbook_from_dict,
)


def _mk_playbook(**overrides) -> Playbook:
    base = dict(
        symbol="NVDA",
        strategy_id="ATH_BREAKOUT",
        thesis="Breakout above ATH on heavy volume.",
        entry_trigger="Buy stop above 920.50 with confirmation",
        entry_price=920.5,
        order_type="Buy Stop",
        stop_loss=905.0,
        profit_target_1=940.0,
        profit_target_2=960.0,
        risk_reward=2.6,
        position_size_pct=0.05,
        indicators_to_watch=("VWAP", "RVOL"),
        invalidation="Loss of VWAP on heavy volume.",
        confidence="high",
        qualification_reason="ATH proximity 0.4%, RVOL 3.1x.",
        confidence_reason="Three confluent signals aligned.",
    )
    base.update(overrides)
    return Playbook(**base)


def _scan_row() -> dict:
    return {
        "symbol": "NVDA",
        "last_price": 920.55,
        "change_pct": 4.2,
        "rvol": 3.1,
        "today_volume": 45_000_000,
        "float_shares": 2_400_000_000,
        "catalyst": "Earnings 2026-05-07",
        "strategy_id": "ATH_BREAKOUT",
        "strategy_name": "ATH Breakout",
        "score": 0.84,
    }


def _store(tmp_path: Path) -> SavedPlaysStore:
    return SavedPlaysStore(path=tmp_path / "saved_plays" / "index.json")


# ─── round-trip ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_save_then_load_roundtrip(tmp_path):
    store = _store(tmp_path)
    pb = _mk_playbook()
    entry = store.save(
        symbol="NVDA",
        strategy_id="ATH_BREAKOUT",
        strategy_name="ATH Breakout",
        model="gpt-5-mini",
        provider="openai",
        playbook=pb,
        scan_row=_scan_row(),
        ui_state={"chart_timeframe": "5m", "chart_toggles": ["playbook", "position"]},
        linked_alpaca={"client_order_id": "scanner:abc:1", "alpaca_order_id": None},
        label="NVDA breakout 5/5",
    )
    loaded = store.load(entry["id"])
    assert loaded is not None
    assert loaded["label"] == "NVDA breakout 5/5"
    assert loaded["symbol"] == "NVDA"
    assert loaded["model"] == "gpt-5-mini"
    assert loaded["ui_state"]["chart_timeframe"] == "5m"
    assert loaded["scan_row"]["score"] == pytest.approx(0.84)
    rehydrated = loaded["playbook_obj"]
    assert isinstance(rehydrated, Playbook)
    assert rehydrated == pb  # frozen dataclass equality


@pytest.mark.unit
def test_indicators_to_watch_returns_as_tuple(tmp_path):
    """Tuple fidelity — JSON gives us a list, loader must re-tuple it."""
    store = _store(tmp_path)
    pb = _mk_playbook(indicators_to_watch=("VWAP", "MACD", "RVOL"))
    entry = store.save(
        symbol="X", strategy_id="S", strategy_name="S",
        model="m", provider="p",
        playbook=pb, scan_row={},
    )
    loaded = store.load(entry["id"])
    assert isinstance(loaded["playbook_obj"].indicators_to_watch, tuple)
    assert loaded["playbook_obj"].indicators_to_watch == ("VWAP", "MACD", "RVOL")


# ─── persistence (survives store re-creation) ──────────────────────


@pytest.mark.unit
def test_persists_across_store_instances(tmp_path):
    """A fresh SavedPlaysStore on the same path should see prior saves —
    this is the 'survives a server restart' contract."""
    s1 = _store(tmp_path)
    s1.save(symbol="X", strategy_id="S", strategy_name="S",
            model="m", provider="p",
            playbook=_mk_playbook(symbol="X"), scan_row={})
    s2 = _store(tmp_path)
    plays = s2.list_all()
    assert len(plays) == 1
    assert plays[0]["symbol"] == "X"


@pytest.mark.unit
def test_list_all_sorts_newest_opened_first(tmp_path):
    store = _store(tmp_path)
    a = store.save(symbol="A", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="A"), scan_row={})
    b = store.save(symbol="B", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="B"), scan_row={})
    # update A's last_opened to be after B's
    store.update_last_opened(a["id"])
    plays = store.list_all()
    assert [p["id"] for p in plays] == [a["id"], b["id"]]


# ─── delete / rename ───────────────────────────────────────────────


@pytest.mark.unit
def test_delete_removes_entry(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="X"), scan_row={})
    assert store.delete(e["id"]) is True
    assert store.load(e["id"]) is None
    assert store.list_all() == []


@pytest.mark.unit
def test_delete_missing_id_returns_false(tmp_path):
    store = _store(tmp_path)
    assert store.delete("nope") is False


@pytest.mark.unit
def test_rename_updates_label_only(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="X"), scan_row={},
                   label="old")
    assert store.rename(e["id"], "new label") is True
    loaded = store.load(e["id"])
    assert loaded["label"] == "new label"
    assert loaded["created_at"] == e["created_at"]


# ─── concurrency ───────────────────────────────────────────────────


@pytest.mark.unit
def test_concurrent_saves_all_persist(tmp_path):
    """10 threads each save once; final file must contain all 10."""
    store = _store(tmp_path)

    def _worker(i):
        store.save(
            symbol=f"T{i}", strategy_id="S", strategy_name="S",
            model="m", provider="p",
            playbook=_mk_playbook(symbol=f"T{i}"),
            scan_row={"i": i},
        )

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    plays = store.list_all()
    assert len(plays) == 10
    assert {p["symbol"] for p in plays} == {f"T{i}" for i in range(10)}


# ─── corruption / schema mismatch ──────────────────────────────────


@pytest.mark.unit
def test_corrupted_json_returns_empty(tmp_path, caplog):
    p = tmp_path / "saved_plays" / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json", encoding="utf-8")
    store = _store(tmp_path)
    assert store.list_all() == []


@pytest.mark.unit
def test_old_schema_version_treated_as_empty(tmp_path):
    p = tmp_path / "saved_plays" / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION - 1,
        "plays": [{"id": "x", "symbol": "OLD"}],
    }), encoding="utf-8")
    store = _store(tmp_path)
    assert store.list_all() == []


@pytest.mark.unit
def test_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    """If os.replace fails mid-write, the on-disk file must remain intact."""
    store = _store(tmp_path)
    e = store.save(symbol="ORIG", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="ORIG"), scan_row={})

    # Now monkeypatch os.replace to fail and try to save another play.
    import os as os_mod
    original_replace = os_mod.replace

    def _failing_replace(*_a, **_kw):
        raise OSError("simulated mid-write crash")

    monkeypatch.setattr(os_mod, "replace", _failing_replace)
    with pytest.raises(OSError):
        store.save(symbol="NEW", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(symbol="NEW"), scan_row={})

    monkeypatch.setattr(os_mod, "replace", original_replace)
    plays = store.list_all()
    assert len(plays) == 1
    assert plays[0]["symbol"] == "ORIG"
    # Tempfile cleanup — no leftover .tmp files in dir
    leftovers = [
        f for f in (tmp_path / "saved_plays").iterdir()
        if f.name.endswith(".tmp")
    ]
    assert leftovers == []


# ─── schema evolution tolerance ────────────────────────────────────


@pytest.mark.unit
def test_load_drops_unknown_playbook_keys(tmp_path):
    """A saved play with an extra field should still load (forward-compat)."""
    store = _store(tmp_path)
    pb = _mk_playbook()
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=pb, scan_row={})
    # Mutate the on-disk file to add a future-only field
    raw = json.loads((tmp_path / "saved_plays" / "index.json").read_text())
    raw["plays"][0]["playbook"]["future_field"] = "ignored"
    (tmp_path / "saved_plays" / "index.json").write_text(json.dumps(raw))

    loaded = store.load(e["id"])
    assert loaded["playbook_obj"] == pb  # extra field silently dropped


@pytest.mark.unit
def test_playbook_from_dict_helper_reexport():
    """Public re-export so callbacks can rehydrate without reaching into _."""
    pb = _mk_playbook()
    from dataclasses import asdict
    rehydrated = playbook_from_dict(asdict(pb))
    assert rehydrated == pb
