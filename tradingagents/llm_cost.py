"""
tradingagents/llm_cost.py — Per-analysis LLM cost estimation.

Accumulates token usage reported by log_llm_end() into a thread-keyed bucket.
In sequential-analyst mode (the default) every LLM call for a ticker's analysis
runs in the analysis thread, so the thread bucket is an accurate per-decision
estimate. In parallel-analyst mode, analyst calls run in worker threads and are
missed — the estimate undercounts. Treat values as estimates, not invoices.
"""

from __future__ import annotations

import threading
from typing import Optional

# USD per 1M tokens (input, output). Approximate; update as pricing changes.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.2": (15.0, 60.0),
    "gpt-5": (15.0, 60.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "o3": (10.0, 40.0),
    "o3-mini": (1.1, 4.4),
    "o4-mini": (1.1, 4.4),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_DEFAULT_PRICING = (3.0, 15.0)  # mid-tier fallback for unknown models

_lock = threading.Lock()
_thread_costs: dict[int, float] = {}


def _price_for(model_name: str) -> tuple[float, float]:
    name = (model_name or "").lower()
    # Longest prefix match so "gpt-5-mini-2025-08-07" hits gpt-5-mini, not gpt-5
    best: Optional[tuple[float, float]] = None
    best_len = 0
    for prefix, price in _PRICING.items():
        if name.startswith(prefix) and len(prefix) > best_len:
            best = price
            best_len = len(prefix)
    return best or _DEFAULT_PRICING


def add_usage(model_name: str, input_tokens: int, output_tokens: int) -> None:
    """Record token usage against the calling thread's cost bucket."""
    in_price, out_price = _price_for(model_name)
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    tid = threading.get_ident()
    with _lock:
        _thread_costs[tid] = _thread_costs.get(tid, 0.0) + cost


def reset_thread_cost() -> None:
    """Zero the calling thread's bucket. Call at the start of an analysis run."""
    tid = threading.get_ident()
    with _lock:
        _thread_costs[tid] = 0.0


def get_thread_cost() -> float:
    """Return the calling thread's accumulated cost since the last reset."""
    tid = threading.get_ident()
    with _lock:
        return _thread_costs.get(tid, 0.0)


def pop_thread_cost() -> float:
    """Return and clear the calling thread's bucket (prevents stale carryover
    when the thread pool reuses this thread for a different ticker)."""
    tid = threading.get_ident()
    with _lock:
        return _thread_costs.pop(tid, 0.0)
