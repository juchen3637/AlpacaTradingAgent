"""Pure long-term filter predicates.

Each takes a snapshot + filters, returns bool. `apply_longterm_filters`
short-circuits on the first failure. No I/O.
"""

from __future__ import annotations

from .longterm_models import LongTermFilters, LongTermSnapshot


def passes_min_market_cap(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    if filters.min_market_cap_b <= 0:
        return True
    if snap.market_cap_b is None:
        return False
    return snap.market_cap_b >= filters.min_market_cap_b


def passes_profitability(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    if not filters.must_be_profitable:
        return True
    if snap.net_margin_ttm is None:
        # No data → fail-closed when profitability is required.
        return False
    return snap.net_margin_ttm > 0


def passes_max_pe(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    if filters.max_pe is None:
        return True
    pe = snap.pe_forward
    # Negative or missing P/E falls through (companies in transition); only
    # reject when we have a positive P/E that exceeds the cap.
    if pe is None or pe <= 0:
        return True
    return pe <= filters.max_pe


def passes_catalyst_only(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    """When `catalyst_only` is on, require the snapshot to carry a catalyst flag.

    Mirrors the day-trade scanner's filter: a long-term hold "with a catalyst
    right now" is often a more compelling entry point than a quiet sideways
    name with the same fundamentals.
    """
    if not filters.catalyst_only:
        return True
    return bool(snap.has_catalyst)


def passes_sector_exclusion(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    if not filters.excluded_sectors:
        return True
    if snap.sector is None:
        # Treat missing sector as "Unknown" — keep in results.
        return True
    # Case-insensitive substring match: a UI option "Consumer" matches both
    # "Consumer Discretionary" and "Consumer Staples". Finnhub's gicsSector
    # strings vary slightly across tickers, so exact equality is too brittle.
    sector_lower = snap.sector.lower()
    for excl in filters.excluded_sectors:
        if excl and excl.lower() in sector_lower:
            return False
    return True


def apply_longterm_filters(snap: LongTermSnapshot, filters: LongTermFilters) -> bool:
    """Cheap filters first; short-circuit on the first failure."""
    return (
        passes_min_market_cap(snap, filters)
        and passes_profitability(snap, filters)
        and passes_max_pe(snap, filters)
        and passes_sector_exclusion(snap, filters)
        and passes_catalyst_only(snap, filters)
    )
