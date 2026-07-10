"""
tradingagents/analytics/ghetto_sd_exec.py — pure data-shaping for the Ghetto SD
strangle executor.

These helpers turn engine ContractRow legs into JSON-safe order payloads for the
UI/order layer and compute the estimated debit. No I/O, no Dash — so they stay
unit-testable in isolation.
"""

from __future__ import annotations

from typing import Sequence


def leg_payload(row) -> dict | None:
    """Serialize a ContractRow leg into an order payload, or None if untradeable."""
    if row is None or not getattr(row, "symbol", ""):
        return None
    return {"symbol": row.symbol, "side": row.side, "strike": row.strike, "ask": row.ask}


def strangle_payload(ticker: str, call_leg, put_leg) -> dict | None:
    """A two-leg strangle payload, or None if either leg can't be traded."""
    call, put = leg_payload(call_leg), leg_payload(put_leg)
    if call is None or put is None:
        return None
    return {"ticker": ticker, "call": call, "put": put}


def scan_legs_map(results: Sequence) -> dict:
    """Map ticker → strangle payload for every scan result with both legs tradeable."""
    out: dict = {}
    for c in results:
        payload = strangle_payload(c.ticker, c.call_leg, c.put_leg)
        if payload is not None:
            out[c.ticker] = payload
    return out


def estimate_text(call_limit, put_limit, qty) -> str:
    """Estimated total debit for the strangle at the given per-share limits and qty."""
    try:
        q = int(qty)
        c, p = float(call_limit), float(put_limit)
    except (TypeError, ValueError):
        return ""
    if q <= 0 or c <= 0 or p <= 0:
        return ""
    debit = (c + p) * 100 * q
    return f"Est. debit: ${debit:,.0f}  ({q} × (call ${c * 100:.0f} + put ${p * 100:.0f}))"
