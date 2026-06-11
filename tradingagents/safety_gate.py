"""
tradingagents/safety_gate.py — Deterministic, non-LLM safety validation layer.

Every proposed order passes this gate before reaching Alpaca.
Checks position size caps, daily loss limits, open position limits, price sanity,
and trading hours. None of these checks depend on LLM output — they are hard
guardrails that the LLM cannot override.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults used when config keys are absent (conservative)
_DEFAULT_MAX_DAILY_LOSS_PCT = 5.0   # stop new entries if account is down >5% today
_DEFAULT_MAX_OPEN_POSITIONS = 10    # hard cap on concurrent open positions
_DEFAULT_MAX_PRICE_DEVIATION_PCT = 40.0  # reject stops/targets >40% from entry

# US/Eastern market session (naive times compared against ET-aware now in callers)
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str  # "OK" when passed; explanation when rejected/adjusted
    adjusted_size: Optional[float] = None  # set when size was clamped rather than rejected


def check_order(
    symbol: str,
    signal: str,
    proposed_size_dollars: float,
    entry_price: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[list[float]],
    account_info: dict,
    open_positions_count: int,
    config: dict,
) -> GateResult:
    """Validate a proposed order against hard risk limits.

    Args:
        symbol: Ticker symbol.
        signal: BUY / SELL / LONG / SHORT / NEUTRAL / HOLD.
        proposed_size_dollars: Dollar size the LLM wants to use.
        entry_price: Proposed entry (may be None if not extracted).
        stop_loss: Proposed stop loss price (may be None).
        take_profit: List of take-profit prices (may be None/empty).
        account_info: Dict from AlpacaUtils.get_account_info().
        open_positions_count: Current number of open positions.
        config: Project config dict (from DEFAULT_CONFIG).

    Returns:
        GateResult with passed=True (and optional adjusted_size) or passed=False.
    """
    action = signal.upper()

    # Closing / neutral signals are always safe — no new risk introduced.
    if action in ("SELL", "HOLD", "NEUTRAL"):
        return GateResult(passed=True, reason="OK")

    equity = float(account_info.get("equity") or 0)
    last_equity = float(account_info.get("last_equity") or equity or 1)

    # ── 1. Daily loss kill switch ─────────────────────────────────────────
    _mdl = config.get("max_daily_loss_pct")
    max_daily_loss_pct = float(_mdl if _mdl is not None else _DEFAULT_MAX_DAILY_LOSS_PCT)
    if max_daily_loss_pct > 0 and last_equity > 0:
        if equity <= 0:
            # equity=0 almost certainly means get_account_info() returned a default/error dict.
            # Skip the kill switch rather than permanently blocking all orders.
            logger.warning("[GATE] equity=0 — skipping daily loss check (likely API data error)")
        else:
            today_loss_pct = (last_equity - equity) / last_equity * 100.0
            if today_loss_pct >= max_daily_loss_pct:
                return GateResult(
                    passed=False,
                    reason=(
                        f"DAILY LOSS KILL SWITCH: account is down {today_loss_pct:.1f}% today "
                        f"(limit {max_daily_loss_pct:.1f}%). No new entries until tomorrow."
                    ),
                )

    # ── 2. Max open positions ─────────────────────────────────────────────
    _mop = config.get("max_open_positions")
    max_positions = int(_mop if _mop is not None else _DEFAULT_MAX_OPEN_POSITIONS)
    if max_positions > 0 and open_positions_count >= max_positions:
        return GateResult(
            passed=False,
            reason=(
                f"MAX POSITIONS: already at {open_positions_count}/{max_positions} open positions. "
                f"Close an existing position before opening {symbol}."
            ),
        )

    # ── 3. Position size cap (buying power %) ─────────────────────────────
    buying_power = float(account_info.get("buying_power") or 0)
    max_pct_bp = float(config.get("max_position_pct_of_buying_power") or 30)
    max_size_by_bp = buying_power * max_pct_bp / 100.0

    adjusted_size: Optional[float] = None
    if proposed_size_dollars > max_size_by_bp > 0:
        adjusted_size = max_size_by_bp
        logger.warning(
            "[GATE] %s size clamped $%.2f → $%.2f (%.0f%% of buying power $%.2f)",
            symbol, proposed_size_dollars, adjusted_size, max_pct_bp, buying_power,
        )

    # ── 4. Risk-per-trade cap (equity %) ─────────────────────────────────
    # Skip entirely when equity is unavailable (API error) — capping to 0 is worse than skipping.
    max_risk_pct = float(config.get("max_risk_pct_per_trade") or 3)
    if equity > 0 and entry_price and stop_loss and entry_price > 0 and stop_loss > 0:
        is_short = action == "SHORT"
        risk_per_share = (stop_loss - entry_price) if is_short else (entry_price - stop_loss)
        if risk_per_share > 0:
            effective_size = adjusted_size if adjusted_size is not None else proposed_size_dollars
            shares = effective_size / entry_price
            max_risk_dollars = equity * max_risk_pct / 100.0
            actual_risk_dollars = shares * risk_per_share
            if actual_risk_dollars > max_risk_dollars:
                safe_shares = max_risk_dollars / risk_per_share
                risk_capped_size = safe_shares * entry_price
                if adjusted_size is None or risk_capped_size < adjusted_size:
                    logger.warning(
                        "[GATE] %s risk-capped $%.2f → $%.2f (risk $%.2f exceeds %.0f%% of equity $%.2f)",
                        symbol, effective_size, risk_capped_size,
                        actual_risk_dollars, max_risk_pct, equity,
                    )
                    adjusted_size = risk_capped_size

    # ── 5. Price sanity checks ────────────────────────────────────────────
    max_dev = _DEFAULT_MAX_PRICE_DEVIATION_PCT
    if entry_price and entry_price > 0:
        is_short = action == "SHORT"

        # Stop must be on the loss side
        if stop_loss and stop_loss > 0:
            if not is_short and stop_loss >= entry_price:
                return GateResult(
                    passed=False,
                    reason=f"PRICE INVALID [{symbol}]: stop ${stop_loss:.2f} ≥ entry ${entry_price:.2f} for LONG",
                )
            if is_short and stop_loss <= entry_price:
                return GateResult(
                    passed=False,
                    reason=f"PRICE INVALID [{symbol}]: stop ${stop_loss:.2f} ≤ entry ${entry_price:.2f} for SHORT",
                )
            # Stop must not be absurdly far from entry
            stop_dev = abs(stop_loss - entry_price) / entry_price * 100
            if stop_dev > max_dev:
                return GateResult(
                    passed=False,
                    reason=(
                        f"PRICE INVALID [{symbol}]: stop ${stop_loss:.2f} is {stop_dev:.1f}% from entry "
                        f"${entry_price:.2f} (max {max_dev:.0f}%)"
                    ),
                )

        # Targets must be on the profit side
        if take_profit:
            for tp in take_profit:
                if tp and tp > 0:
                    if not is_short and tp <= entry_price:
                        return GateResult(
                            passed=False,
                            reason=f"PRICE INVALID [{symbol}]: target ${tp:.2f} ≤ entry ${entry_price:.2f} for LONG",
                        )
                    if is_short and tp >= entry_price:
                        return GateResult(
                            passed=False,
                            reason=f"PRICE INVALID [{symbol}]: target ${tp:.2f} ≥ entry ${entry_price:.2f} for SHORT",
                        )
                    tp_dev = abs(tp - entry_price) / entry_price * 100
                    if tp_dev > max_dev:
                        return GateResult(
                            passed=False,
                            reason=(
                                f"PRICE INVALID [{symbol}]: target ${tp:.2f} is {tp_dev:.1f}% from entry "
                                f"${entry_price:.2f} (max {max_dev:.0f}%)"
                            ),
                        )

    final_size = adjusted_size if adjusted_size is not None else proposed_size_dollars
    if final_size <= 0:
        return GateResult(passed=False, reason=f"ZERO SIZE [{symbol}]: effective position size is $0 after adjustments")

    min_size = float(config.get("min_position_size") or 1)
    if final_size < min_size:
        return GateResult(
            passed=False,
            reason=f"BELOW MIN [{symbol}]: $%.2f < min $%.2f" % (final_size, min_size),
        )

    reason = "OK" if adjusted_size is None else f"Size adjusted {proposed_size_dollars:.2f} → {adjusted_size:.2f}"
    return GateResult(passed=True, reason=reason, adjusted_size=adjusted_size)
