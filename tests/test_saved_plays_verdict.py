"""Unit tests for SavedPlaysStore.set_verdict."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tradingagents.scanner.models import Playbook
from webui.utils.saved_plays import SavedPlaysStore


def _mk_playbook() -> Playbook:
    return Playbook(
        symbol="NVDA",
        strategy_id="ATH_BREAKOUT",
        thesis="Breakout above ATH on heavy volume.",
        entry_trigger="Buy stop above 920.50",
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


def _store(tmp_path: Path) -> SavedPlaysStore:
    return SavedPlaysStore(path=tmp_path / "saved_plays" / "index.json")


def _verdict_dict(status: str = "still_viable") -> dict:
    return {
        "status": status,
        "confidence": "high",
        "reasoning": "Thesis intact.",
        "recommended_action": "hold",
        "key_changes": ["RVOL holding at 3x"],
        "news_signals": [],
        "analyzed_at": "2026-05-05T16:30:00+00:00",
        "model": "gpt-5-mini",
        "provider": "openai",
        "snapshot": {"current_price": 921.10},
    }


@pytest.mark.unit
def test_set_verdict_attaches_to_existing_play(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="NVDA", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={})
    assert store.set_verdict(e["id"], _verdict_dict()) is True
    loaded = store.load(e["id"])
    assert loaded is not None
    assert loaded["verdict"]["status"] == "still_viable"
    assert loaded["verdict"]["recommended_action"] == "hold"
    assert loaded["verdict"]["snapshot"]["current_price"] == pytest.approx(921.10)


@pytest.mark.unit
def test_set_verdict_persists_across_store_instances(tmp_path):
    s1 = _store(tmp_path)
    e = s1.save(symbol="X", strategy_id="S", strategy_name="S",
                model="m", provider="p",
                playbook=_mk_playbook(), scan_row={})
    s1.set_verdict(e["id"], _verdict_dict("degraded"))
    s2 = _store(tmp_path)
    loaded = s2.load(e["id"])
    assert loaded["verdict"]["status"] == "degraded"


@pytest.mark.unit
def test_set_verdict_overwrites_prior(tmp_path):
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={})
    store.set_verdict(e["id"], _verdict_dict("still_viable"))
    store.set_verdict(e["id"], _verdict_dict("invalidated"))
    loaded = store.load(e["id"])
    assert loaded["verdict"]["status"] == "invalidated"


@pytest.mark.unit
def test_set_verdict_missing_id_returns_false(tmp_path):
    store = _store(tmp_path)
    assert store.set_verdict("nope", _verdict_dict()) is False


@pytest.mark.unit
def test_concurrent_set_verdict(tmp_path):
    """10 threads each set a verdict on the same play; final value is one of them."""
    store = _store(tmp_path)
    e = store.save(symbol="X", strategy_id="S", strategy_name="S",
                   model="m", provider="p",
                   playbook=_mk_playbook(), scan_row={})

    def _worker(i):
        store.set_verdict(e["id"], _verdict_dict(f"status_{i}"))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = store.load(e["id"])
    # Whatever status is on disk must be exactly one of the workers' writes,
    # not a mangled / partial one.
    assert loaded["verdict"]["status"].startswith("status_")
