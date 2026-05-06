"""Unit tests for SavedPlaysStore.set_linked_alpaca.

Used by the Plays-tab Execute (Paper) flow to persist the Alpaca order
linkage on the saved play after a fresh bracket submission.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents.scanner.models import Playbook
from webui.utils.saved_plays import SavedPlaysStore


def _mk_playbook() -> Playbook:
    return Playbook(
        symbol="NVDA", strategy_id="ATH_BREAKOUT",
        thesis="x", entry_trigger="x",
        entry_price=920.5, order_type="Buy Stop",
        stop_loss=905.0, profit_target_1=940.0, profit_target_2=960.0,
        risk_reward=2.6, position_size_pct=0.05,
        indicators_to_watch=("VWAP",), invalidation="x",
        confidence="high",
    )


def _store(tmp_path: Path) -> SavedPlaysStore:
    return SavedPlaysStore(path=tmp_path / "saved_plays" / "index.json")


@pytest.mark.unit
def test_set_linked_alpaca_attaches_to_existing_play(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="NVDA", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={})
    linked = {"client_order_id": "scanner:ATH:abc123",
              "alpaca_order_id": "alpaca-uuid-1"}
    assert store.set_linked_alpaca(e["id"], linked) is True
    loaded = store.load(e["id"])
    assert loaded is not None
    assert loaded["linked_alpaca"] == linked


@pytest.mark.unit
def test_set_linked_alpaca_overwrites_prior_link(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={},
                   linked_alpaca={"client_order_id": "old", "alpaca_order_id": "old"})
    store.set_linked_alpaca(e["id"], {"client_order_id": "new",
                                       "alpaca_order_id": "new-id"})
    loaded = store.load(e["id"])
    assert loaded["linked_alpaca"]["client_order_id"] == "new"
    assert loaded["linked_alpaca"]["alpaca_order_id"] == "new-id"


@pytest.mark.unit
def test_set_linked_alpaca_persists_across_store_instances(tmp_path):
    s1 = _store(tmp_path)
    e = s1.save(symbol="X", strategy_id="S", strategy_name="S",
                model="m", provider="p",
                playbook=_mk_playbook(), scan_row={})
    s1.set_linked_alpaca(e["id"], {"client_order_id": "tag", "alpaca_order_id": "id"})
    s2 = _store(tmp_path)
    loaded = s2.load(e["id"])
    assert loaded["linked_alpaca"]["client_order_id"] == "tag"


@pytest.mark.unit
def test_set_linked_alpaca_missing_id_returns_false(tmp_path):
    store = _store(tmp_path)
    assert store.set_linked_alpaca("nope", {"client_order_id": "x"}) is False


@pytest.mark.unit
def test_set_linked_alpaca_empty_dict_clears_link(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={},
                   linked_alpaca={"client_order_id": "tag",
                                  "alpaca_order_id": "id"})
    store.set_linked_alpaca(e["id"], {})
    loaded = store.load(e["id"])
    assert loaded["linked_alpaca"] == {}
