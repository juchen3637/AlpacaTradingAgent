"""Pure filter predicates. Each takes a snapshot + filters, returns bool.

Filters are ordered cheapest-first in `apply_filters` so the pipeline drops
the majority of tickers before enrichment calls fire.
"""

from __future__ import annotations

from .models import ScanFilters, TickerSnapshot


def passes_price_band(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    return filters.price_min <= snap.last_price <= filters.price_max


def passes_rvol(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    if snap.rvol is None:
        return False
    return snap.rvol >= filters.min_rvol


def passes_premarket_volume(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    # Crypto trades 24/7 — no premarket concept, skip the filter.
    if snap.is_crypto:
        return True
    # Threshold of 0 means "ignore this filter" (premarket data is optional).
    if filters.min_premarket_volume <= 0:
        return True
    if snap.premarket_volume is None:
        return False
    return snap.premarket_volume >= filters.min_premarket_volume


def passes_float(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    if filters.max_float_millions is None:
        return True
    if snap.float_shares is None:
        return False
    return snap.float_shares <= filters.max_float_millions * 1_000_000


def passes_catalyst(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    if not filters.catalyst_only:
        return True
    return snap.has_catalyst


def apply_filters(snap: TickerSnapshot, filters: ScanFilters) -> bool:
    """Cheap filters first; short-circuit on the first failure."""
    return (
        passes_price_band(snap, filters)
        and passes_rvol(snap, filters)
        and passes_premarket_volume(snap, filters)
        and passes_float(snap, filters)
        and passes_catalyst(snap, filters)
    )
