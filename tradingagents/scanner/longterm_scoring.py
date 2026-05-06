"""Long-term composite scoring.

Pure functions: takes a `LongTermSnapshot`, returns a 0..1 composite score.
No I/O. Each metric is normalized to 0..1, winsorized at a sensible upper
bound to keep one outlier from dominating any single column. Missing
metrics contribute their weight × 0.5 (neutral) so a single Finnhub gap
doesn't tank an otherwise great pick.
"""

from __future__ import annotations

from typing import Optional

from .longterm_models import LongTermSnapshot

# Weights sum to 1.0. Keep this explicit so the invariant test catches drift.
WEIGHTS: dict[str, float] = {
    "roe": 0.20,
    "net_margin": 0.15,
    "rev_growth_3y": 0.20,
    "pe_forward": 0.15,
    "lt_trend": 0.15,
    "debt_equity": 0.10,
    "div_yield": 0.05,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def normalize_roe(roe_pct: Optional[float]) -> Optional[float]:
    """ROE: 0% → 0.0, 25% → 1.0, capped at 1.0. Negative → 0."""
    if roe_pct is None:
        return None
    return _clamp(roe_pct / 25.0)


def normalize_net_margin(margin_pct: Optional[float]) -> Optional[float]:
    """Net margin: 0% → 0.0, 30% → 1.0."""
    if margin_pct is None:
        return None
    return _clamp(margin_pct / 30.0)


def normalize_rev_growth(growth_pct: Optional[float]) -> Optional[float]:
    """Revenue 3y CAGR: 0% → 0.0, 20% → 1.0. Negative growth → 0."""
    if growth_pct is None:
        return None
    return _clamp(growth_pct / 20.0)


def normalize_pe_inverted(pe: Optional[float]) -> Optional[float]:
    """Forward P/E (lower=better): 10 → 1.0, 50 → 0.0.

    Negative or zero P/E (loss-making companies) returns 0.
    """
    if pe is None or pe <= 0:
        return None if pe is None else 0.0
    # Linear from 10..50 → 1..0
    return _clamp(1.0 - (pe - 10.0) / 40.0)


def normalize_lt_trend(snap: LongTermSnapshot) -> Optional[float]:
    """Long-term trend: 1.0 if above 200-SMA AND golden cross, 0.5 if one,
    0.0 if neither. None if no trend data at all.
    """
    if snap.sma_200 is None and snap.sma_50 is None:
        return None
    score = 0.0
    if snap.above_sma_200:
        score += 0.5
    if snap.golden_cross:
        score += 0.5
    return score


def normalize_debt_equity(de: Optional[float]) -> Optional[float]:
    """Debt/Equity (lower=better): 0 → 1.0, 2.0 → 0.0. Caps at 2.0."""
    if de is None:
        return None
    if de < 0:
        # Negative equity (rare, indicates distress) → worst score
        return 0.0
    return _clamp(1.0 - de / 2.0)


def normalize_div_yield(yld_pct: Optional[float]) -> Optional[float]:
    """Dividend yield: 0% → 0.0, 4% → 1.0 (capped). Tiebreaker only."""
    if yld_pct is None:
        return None
    return _clamp(yld_pct / 4.0)


def _weighted(value: Optional[float], weight: float) -> float:
    """Apply weight; missing data contributes neutral 0.5 × weight."""
    if value is None:
        return 0.5 * weight
    return value * weight


def score_longterm(snap: LongTermSnapshot) -> float:
    """Composite 0..1 score. Higher = better long-term hold candidate."""
    components = [
        _weighted(normalize_roe(snap.roe_ttm), WEIGHTS["roe"]),
        _weighted(normalize_net_margin(snap.net_margin_ttm), WEIGHTS["net_margin"]),
        _weighted(normalize_rev_growth(snap.revenue_growth_3y), WEIGHTS["rev_growth_3y"]),
        _weighted(normalize_pe_inverted(snap.pe_forward), WEIGHTS["pe_forward"]),
        _weighted(normalize_lt_trend(snap), WEIGHTS["lt_trend"]),
        _weighted(normalize_debt_equity(snap.debt_to_equity), WEIGHTS["debt_equity"]),
        _weighted(normalize_div_yield(snap.dividend_yield_ttm), WEIGHTS["div_yield"]),
    ]
    return _clamp(sum(components))
