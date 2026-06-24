"""
tradingagents/analytics/ghetto_sd_journal.py — turn a placed Ghetto SD strangle
into journal records.

Maps the strangle payload + per-leg order results from
``AlpacaUtils.place_strangle`` into one ``DecisionRecord`` (source="ghetto_sd")
and one ``TradeRecord`` per leg that actually submitted. Pure: no DB, no Dash —
the caller persists the returned records.
"""

from __future__ import annotations

from .trade_journal import DecisionRecord, TradeRecord


def _leg_limit(payload_leg: dict, limit) -> float:
    try:
        return round(float(limit), 2)
    except (TypeError, ValueError):
        return round(float(payload_leg.get("ask", 0.0)), 2)


def build_strangle_records(
    payload: dict,
    order_results: dict,
    *,
    qty: int,
    call_limit,
    put_limit,
    timestamp: str,
) -> tuple[DecisionRecord, list[TradeRecord]] | None:
    """Build (DecisionRecord, [TradeRecord, ...]) for a submitted strangle.

    Returns None when neither leg submitted successfully.
    """
    call, put = payload["call"], payload["put"]
    c_limit, p_limit = _leg_limit(call, call_limit), _leg_limit(put, put_limit)
    ticker = payload["ticker"]

    legs = (
        ("call", call, c_limit, order_results.get("call", {})),
        ("put", put, p_limit, order_results.get("put", {})),
    )
    filled = [(leg, lim, res) for (_, leg, lim, res) in legs if res.get("success")]
    if not filled:
        return None

    debit = round((c_limit + p_limit) * 100 * qty, 2)
    final = (
        f"Ghetto SD strangle: BUY {qty}x {call['symbol']} (call ${call['strike']:g}) "
        f"@ {c_limit:.2f} + BUY {qty}x {put['symbol']} (put ${put['strike']:g}) @ {p_limit:.2f}. "
        f"Est. debit ${debit:,.0f}."
    )

    decision = DecisionRecord(
        ticker=ticker,
        trade_date=timestamp[:10],
        signal="STRANGLE",
        trader_plan=final,
        final_decision=final,
        position_size_dollars=debit,
        source="ghetto_sd",
        source_order_id=filled[0][2].get("order_id"),
        timestamp=timestamp,
    )

    trades = [
        TradeRecord(
            decision_id=None,
            ticker=leg["symbol"],
            side="buy",
            qty=qty,
            filled_price=lim,
            order_type="limit",
            alpaca_order_id=res.get("order_id"),
            status=res.get("status"),
            timestamp=timestamp,
        )
        for (leg, lim, res) in filled
    ]

    return decision, trades
