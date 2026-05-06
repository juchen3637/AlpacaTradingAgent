"""Unit + integration tests for scanner execution (Execute Paper button backend)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.analytics.trade_journal import TradeJournal
from tradingagents.scanner.execution import (
    ExecutionResult,
    compute_scanner_position_size,
    execute_playbook_paper,
)
from tradingagents.scanner.models import Playbook


# ─── Fixtures ─────────────────────────────────────────────────────────


def _playbook(
    symbol: str = "NVDA",
    strategy_id: str = "ATH_BREAKOUT",
    entry_price: float = 100.0,
    order_type: str = "Buy Stop",
    stop_loss: float = 99.0,
    profit_target_1: float = 102.0,
    profit_target_2: float = 104.0,
    position_size_pct: float = 0.05,
) -> Playbook:
    return Playbook(
        symbol=symbol,
        strategy_id=strategy_id,
        thesis="t",
        entry_trigger="When price moves above $100 (breakout).",
        entry_price=entry_price,
        order_type=order_type,
        stop_loss=stop_loss,
        profit_target_1=profit_target_1,
        profit_target_2=profit_target_2,
        risk_reward=2.0,
        position_size_pct=position_size_pct,
        indicators_to_watch=("VWAP",),
        invalidation="inv",
        confidence="high",
    )


@pytest.fixture
def tmp_journal():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        yield TradeJournal(db_path=path)
    finally:
        Path(path).unlink(missing_ok=True)


# ─── compute_scanner_position_size ────────────────────────────────────


@pytest.mark.unit
def test_position_size_normal():
    # $10,000 BP × 5% / $50 = 10 shares
    assert compute_scanner_position_size(10_000.0, 0.05, 50.0) == 10


@pytest.mark.unit
def test_position_size_rounds_down_fractional():
    # $1,000 × 5% / $33 = 1.515… → 1 share
    assert compute_scanner_position_size(1_000.0, 0.05, 33.0) == 1


@pytest.mark.unit
def test_position_size_zero_when_too_small():
    # $100 × 1% / $50 = 0.02 → 0 (rejects)
    assert compute_scanner_position_size(100.0, 0.01, 50.0) == 0


@pytest.mark.unit
def test_position_size_zero_when_zero_bp():
    assert compute_scanner_position_size(0.0, 0.05, 50.0) == 0


@pytest.mark.unit
def test_position_size_zero_when_zero_pct():
    assert compute_scanner_position_size(10_000.0, 0.0, 50.0) == 0


@pytest.mark.unit
def test_position_size_zero_when_zero_price():
    assert compute_scanner_position_size(10_000.0, 0.05, 0.0) == 0


@pytest.mark.unit
def test_position_size_caps_at_max_shares():
    # $1M × 100% / $1 would be 1M shares → capped at 1000
    assert compute_scanner_position_size(1_000_000.0, 1.0, 1.0, max_shares=1000) == 1000


@pytest.mark.unit
def test_position_size_handles_negative_inputs():
    assert compute_scanner_position_size(-100.0, 0.05, 50.0) == 0
    assert compute_scanner_position_size(100.0, -0.05, 50.0) == 0
    assert compute_scanner_position_size(100.0, 0.05, -50.0) == 0


# ─── submit_scanner_bracket_order order_type mapping ──────────────────


@pytest.mark.unit
def test_submit_buy_stop_uses_stop_order_request():
    from alpaca.trading.requests import StopOrderRequest

    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    mock_client = MagicMock()
    mock_order = MagicMock(id="order-123")
    mock_client.submit_order.return_value = mock_order

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=mock_client,
    ):
        result = AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA",
            entry_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            qty=10,
            order_type="Buy Stop",
            client_order_id="scanner:ATH_BREAKOUT:abc123",
        )

    assert result["success"] is True
    assert result["entry_order_id"] == "order-123"
    assert result["client_order_id"] == "scanner:ATH_BREAKOUT:abc123"
    submitted = mock_client.submit_order.call_args[0][0]
    assert isinstance(submitted, StopOrderRequest)
    assert submitted.stop_price == 100.0
    assert submitted.client_order_id == "scanner:ATH_BREAKOUT:abc123"


@pytest.mark.unit
def test_submit_buy_limit_uses_limit_order_request():
    from alpaca.trading.requests import LimitOrderRequest

    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    mock_client = MagicMock()
    mock_client.submit_order.return_value = MagicMock(id="order-456")

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=mock_client,
    ):
        AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA",
            entry_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            qty=10,
            order_type="Buy Limit",
            client_order_id="scanner:VWAP_RECLAIM:xyz",
        )

    submitted = mock_client.submit_order.call_args[0][0]
    assert isinstance(submitted, LimitOrderRequest)
    assert submitted.limit_price == 100.0


@pytest.mark.unit
def test_submit_buy_stop_limit_uses_stop_limit_order_request():
    from alpaca.trading.requests import StopLimitOrderRequest

    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    mock_client = MagicMock()
    mock_client.submit_order.return_value = MagicMock(id="order-789")

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=mock_client,
    ):
        AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA",
            entry_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            qty=10,
            order_type="Buy Stop-Limit",
            client_order_id="scanner:ORB:1",
        )

    submitted = mock_client.submit_order.call_args[0][0]
    assert isinstance(submitted, StopLimitOrderRequest)
    assert submitted.stop_price == 100.0
    # Limit price should be a small slippage allowance above stop
    assert submitted.limit_price >= 100.0


@pytest.mark.unit
def test_submit_buy_market_uses_market_order_request():
    from alpaca.trading.requests import MarketOrderRequest

    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    mock_client = MagicMock()
    mock_client.submit_order.return_value = MagicMock(id="order-999")

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=mock_client,
    ):
        AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA",
            entry_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            qty=10,
            order_type="Buy Market",
            client_order_id="scanner:HVD:1",
        )

    submitted = mock_client.submit_order.call_args[0][0]
    assert isinstance(submitted, MarketOrderRequest)


@pytest.mark.unit
def test_submit_returns_error_on_alpaca_exception():
    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    mock_client = MagicMock()
    mock_client.submit_order.side_effect = RuntimeError("market closed")

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=mock_client,
    ):
        result = AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA", entry_price=100.0, stop_loss=99.0, take_profit=102.0,
            qty=10, order_type="Buy Stop", client_order_id="scanner:X:1",
        )

    assert result["success"] is False
    assert "market closed" in result["error"]


@pytest.mark.unit
def test_submit_rejects_unknown_order_type():
    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    with patch(
        "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
        return_value=MagicMock(),
    ):
        result = AlpacaUtils.submit_scanner_bracket_order(
            symbol="NVDA", entry_price=100.0, stop_loss=99.0, take_profit=102.0,
            qty=10, order_type="Sell Short", client_order_id="scanner:X:1",
        )

    assert result["success"] is False
    assert "order_type" in result["error"].lower()


# ─── execute_playbook_paper orchestrator ──────────────────────────────


@pytest.mark.integration
def test_execute_playbook_paper_happy_path(tmp_journal):
    pb = _playbook(strategy_id="ATH_BREAKOUT", entry_price=100.0)

    with patch(
        "tradingagents.scanner.execution.AlpacaUtils.get_account_info",
        return_value={"buying_power": 100_000.0},
    ), patch(
        "tradingagents.scanner.execution.AlpacaUtils.submit_scanner_bracket_order",
        return_value={
            "success": True,
            "entry_order_id": "alpaca-1",
            "client_order_id": "scanner:ATH_BREAKOUT:abcdef0123",
            "message": "ok",
        },
    ):
        result = execute_playbook_paper(pb, journal=tmp_journal)

    assert result.success is True
    assert result.alpaca_order_id == "alpaca-1"
    assert result.client_order_id.startswith("scanner:ATH_BREAKOUT:")
    assert result.qty > 0
    assert result.decision_id is not None

    rows = tmp_journal.get_decisions(source="scanner")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["source"] == "scanner"
    assert rows[0]["source_order_id"].startswith("scanner:ATH_BREAKOUT:")
    # PT1 only, PT2 reference-only — journal auto-deserializes take_profit to list
    assert rows[0]["take_profit"] == [102.0]


@pytest.mark.integration
def test_execute_playbook_paper_rejects_stop_at_or_above_entry(tmp_journal):
    pb = _playbook(entry_price=100.0, stop_loss=100.5)  # stop > entry, illegal long
    result = execute_playbook_paper(pb, journal=tmp_journal)
    assert result.success is False
    assert "stop" in result.error.lower()
    assert tmp_journal.get_decisions() == []


@pytest.mark.integration
def test_execute_playbook_paper_rejects_pt1_at_or_below_entry(tmp_journal):
    pb = _playbook(entry_price=100.0, profit_target_1=99.5)
    result = execute_playbook_paper(pb, journal=tmp_journal)
    assert result.success is False
    assert "target" in result.error.lower() or "pt1" in result.error.lower()


@pytest.mark.integration
def test_execute_playbook_paper_rejects_zero_qty(tmp_journal):
    # Tiny BP with low pct → 0 shares; PT1/PT2 must still pass validation
    pb = _playbook(
        entry_price=1000.0,
        stop_loss=999.0,
        profit_target_1=1010.0,
        profit_target_2=1020.0,
        position_size_pct=0.01,
    )
    with patch(
        "tradingagents.scanner.execution.AlpacaUtils.get_account_info",
        return_value={"buying_power": 100.0},  # 100 × 0.01 / 1000 = 0.001 → 0 shares
    ):
        result = execute_playbook_paper(pb, journal=tmp_journal)
    assert result.success is False
    assert "qty" in result.error.lower() or "shares" in result.error.lower() or "buying" in result.error.lower()


@pytest.mark.integration
def test_execute_playbook_paper_writes_no_journal_on_alpaca_failure(tmp_journal):
    pb = _playbook()
    with patch(
        "tradingagents.scanner.execution.AlpacaUtils.get_account_info",
        return_value={"buying_power": 100_000.0},
    ), patch(
        "tradingagents.scanner.execution.AlpacaUtils.submit_scanner_bracket_order",
        return_value={"success": False, "error": "market closed"},
    ):
        result = execute_playbook_paper(pb, journal=tmp_journal)

    assert result.success is False
    assert tmp_journal.get_decisions() == []


@pytest.mark.integration
def test_execute_playbook_paper_client_order_id_format(tmp_journal):
    """Tag must round-trip: scanner:{strategy_id}:{nonce}, ≤128 chars."""
    pb = _playbook(strategy_id="LOW_FLOAT_HVD")

    with patch(
        "tradingagents.scanner.execution.AlpacaUtils.get_account_info",
        return_value={"buying_power": 100_000.0},
    ), patch(
        "tradingagents.scanner.execution.AlpacaUtils.submit_scanner_bracket_order",
    ) as mock_submit:
        mock_submit.return_value = {"success": True, "entry_order_id": "x",
                                    "client_order_id": "y", "message": ""}
        execute_playbook_paper(pb, journal=tmp_journal)

    sent_id = mock_submit.call_args.kwargs["client_order_id"]
    assert sent_id.startswith("scanner:LOW_FLOAT_HVD:")
    assert len(sent_id) <= 128
    # Nonce portion is non-empty and alphanumeric
    nonce = sent_id.split(":")[-1]
    assert len(nonce) >= 6
    assert nonce.isalnum()


@pytest.mark.integration
def test_execute_playbook_paper_dedupes_on_repeat_order_id(tmp_journal):
    """Backfill of the same client_order_id should not create a duplicate row."""
    from tradingagents.analytics.trade_journal import DecisionRecord

    fixed_id = "scanner:ATH_BREAKOUT:fixedfixed"
    record = DecisionRecord(
        ticker="NVDA", trade_date="2026-04-30", signal="BUY",
        source="scanner", source_order_id=fixed_id,
        final_decision="first insert",
    )
    first_id = tmp_journal.record_decision(record)

    # Backfill writes a record with the same source_order_id
    backfill_record = DecisionRecord(
        ticker="NVDA", trade_date="2026-04-30", signal="BUY",
        source="backfill", source_order_id=fixed_id,
        final_decision="duplicate from backfill",
    )
    second_id = tmp_journal.record_decision(backfill_record)

    assert first_id == second_id  # dedup hit
    rows = tmp_journal.get_decisions()
    assert len(rows) == 1


# ─── ExecutionResult shape ────────────────────────────────────────────


@pytest.mark.unit
def test_execution_result_is_frozen_dataclass():
    r = ExecutionResult(success=True, message="ok")
    with pytest.raises(Exception):  # FrozenInstanceError
        r.success = False  # type: ignore
