"""Tests for Alpaca historical trade backfill."""

from __future__ import annotations

import os
import tempfile

import pytest

from tradingagents.analytics.backfill import (
    BackfillReport,
    _match_avg_cost,
    backfill_from_alpaca,
)
from tradingagents.analytics.strategy_analysis import (
    calculate_analyst_effectiveness,
    calculate_streaks,
)
from tradingagents.analytics.trade_journal import TradeJournal


@pytest.fixture
def journal():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    j = TradeJournal(db_path=tmp.name)
    yield j
    os.unlink(tmp.name)


def _order(
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    filled_at: str,
    client_order_id: str | None = None,
    status: str = "filled",
    order_type: str = "market",
) -> dict:
    return {
        "id": order_id,
        "client_order_id": client_order_id or f"client-{order_id}",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "filled_price": price,
        "order_type": order_type,
        "status": status,
        "filled_at": filled_at,
        "submitted_at": filled_at,
    }


# ─── Average-cost matching ─────────────────────────────────────────────


def test_avg_cost_simple_round_trip():
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert len(outcomes) == 1
    o = outcomes[0]
    assert o["qty"] == 10
    assert o["pnl_dollars"] == pytest.approx(100.0)  # (110-100) * 10
    assert o["pnl_percent"] == pytest.approx(10.0)
    assert o["entry_price"] == pytest.approx(100.0)
    assert o["exit_price"] == 110.0
    assert o["hold_duration_hours"] == pytest.approx(24.0)


def test_avg_cost_collapses_multiple_buys_to_weighted_avg():
    orders = [
        _order("1", "NVDA", "buy", 5, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "buy", 5, 120.0, "2026-04-01T11:00:00+00:00"),
        _order("3", "NVDA", "sell", 10, 130.0, "2026-04-02T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    # Avg-cost: one outcome using weighted avg (110) rather than two FIFO lots.
    assert len(outcomes) == 1
    o = outcomes[0]
    assert o["qty"] == 10
    assert o["entry_price"] == pytest.approx(110.0)  # (5*100 + 5*120) / 10
    assert o["pnl_dollars"] == pytest.approx(200.0)  # (130-110)*10


def test_avg_cost_open_position_no_outcome():
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert outcomes == []


def test_avg_cost_partial_sell_leaves_open_position():
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 3, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert len(outcomes) == 1
    assert outcomes[0]["qty"] == 3
    assert outcomes[0]["pnl_dollars"] == pytest.approx(30.0)


def test_avg_cost_sell_after_partial_reduces_basis_proportionally():
    """Buying more after a partial sell should blend into the remaining basis."""
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 4, 110.0, "2026-04-02T10:00:00+00:00"),
        _order("3", "NVDA", "buy", 6, 130.0, "2026-04-03T10:00:00+00:00"),
        _order("4", "NVDA", "sell", 12, 140.0, "2026-04-04T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert len(outcomes) == 2
    # After first sell: 6 shares remain @ 100 avg, cost=600.
    assert outcomes[0]["entry_price"] == pytest.approx(100.0)
    assert outcomes[0]["pnl_dollars"] == pytest.approx(40.0)
    # After buy 6 @ 130: total=12 shares, cost=600+780=1380, avg=115.
    assert outcomes[1]["entry_price"] == pytest.approx(115.0)
    assert outcomes[1]["pnl_dollars"] == pytest.approx(300.0)  # (140-115)*12


def test_avg_cost_skips_unfilled_orders():
    orders = [
        _order("1", "NVDA", "buy", 0, 0.0, "2026-04-01T10:00:00+00:00", status="canceled"),
        _order("2", "NVDA", "buy", 10, 100.0, "2026-04-01T11:00:00+00:00"),
        _order("3", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert len(outcomes) == 1


def test_avg_cost_sell_with_no_prior_buy_is_skipped():
    """A sell with no opening buy in the window (happens at backfill edges)."""
    orders = [
        _order("1", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    outcomes = _match_avg_cost(orders)
    assert outcomes == []


# ─── End-to-end backfill ────────────────────────────────────────────────


def test_backfill_writes_decisions_and_outcomes(journal):
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
        _order("3", "AMD", "buy", 5, 50.0, "2026-04-01T11:00:00+00:00"),
    ]
    report = backfill_from_alpaca(journal, orders=orders)

    assert isinstance(report, BackfillReport)
    assert report.decisions_added == 3
    assert report.trades_added == 3
    assert report.outcomes_added == 1  # NVDA round-trip
    assert report.skipped_duplicates == 0

    # All decisions tagged as backfill source
    all_decisions = journal.get_decisions(limit=100)
    assert len(all_decisions) == 3
    assert all(d["source"] == "backfill" for d in all_decisions)
    assert all(d["source_order_id"] is not None for d in all_decisions)


def test_backfill_is_idempotent(journal):
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    first = backfill_from_alpaca(journal, orders=orders)
    assert first.decisions_added == 2
    assert first.outcomes_added == 1

    second = backfill_from_alpaca(journal, orders=orders)
    assert second.decisions_added == 0  # all skipped as duplicates
    assert second.skipped_duplicates == 2
    assert second.outcomes_added == 0  # outcome already exists

    # Still only 2 decisions and 1 outcome in the DB
    assert journal.count_decisions() == 2


def test_backfill_signal_reflects_side(journal):
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    backfill_from_alpaca(journal, orders=orders)
    decisions = journal.get_decisions(limit=10)
    signals = sorted(d["signal"] for d in decisions)
    assert signals == ["BUY", "SELL"]


# ─── Analytics integration: backfill excluded from radar + streaks ─────


def test_analyst_effectiveness_excludes_backfill(journal):
    # Insert a backfill decision (no agent reports)
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    backfill_from_alpaca(journal, orders=orders)

    eff = calculate_analyst_effectiveness(journal)
    # Backfill decisions have no analyst reports, so they should be ignored
    for name in ("market", "social", "news", "fundamentals", "macro"):
        assert eff[name]["total_decisions"] == 0


def test_streaks_exclude_backfill(journal):
    orders = [
        _order("1", "NVDA", "buy", 10, 100.0, "2026-04-01T10:00:00+00:00"),
        _order("2", "NVDA", "sell", 10, 110.0, "2026-04-02T10:00:00+00:00"),
    ]
    backfill_from_alpaca(journal, orders=orders)

    s = calculate_streaks(journal)
    # Backfill outcome excluded → no streak
    assert s["longest_win"] == 0
    assert s["current_streak"] == 0
    assert s["streak_timeline"] == []


def test_backfill_empty_orders(journal):
    report = backfill_from_alpaca(journal, orders=[])
    assert report.decisions_added == 0
    assert report.outcomes_added == 0
    assert report.orders_scanned == 0
