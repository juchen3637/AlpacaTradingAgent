"""Immutable data models for the scanner pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ScanFilters:
    """User-controlled scan parameters."""

    universe_kind: str = "most_active"  # "most_active" | "watchlist" | "crypto"
    watchlist: tuple[str, ...] = ()
    min_rvol: float = 2.0
    price_min: float = 1.0
    price_max: float = 1000.0
    min_premarket_volume: int = 0  # 0 = skip filter (premarket data is optional)
    max_float_millions: Optional[float] = None  # None = no float filter
    catalyst_only: bool = False
    ath_proximity_pct: float = 5.0  # within X% of ATH for ATH_BREAKOUT
    asset_class: str = "stock"  # "stock" | "crypto"


@dataclass(frozen=True)
class KeyLevels:
    """Key intraday / historical price levels used by strategies."""

    pdh: Optional[float] = None    # previous day high
    pdl: Optional[float] = None    # previous day low
    pmh: Optional[float] = None    # premarket high
    pml: Optional[float] = None    # premarket low
    vwap: Optional[float] = None
    ath: Optional[float] = None
    wk52_high: Optional[float] = None
    wk52_low: Optional[float] = None


@dataclass(frozen=True)
class TickerSnapshot:
    """Pointer-in-time snapshot of a single ticker used by filters/matcher."""

    symbol: str
    is_crypto: bool
    last_price: float
    change_pct: float  # % change from previous close
    premarket_volume: Optional[int] = None
    rvol: Optional[float] = None
    float_shares: Optional[float] = None  # raw shares, not millions
    has_catalyst: bool = False
    catalyst_text: Optional[str] = None
    catalyst_details: Optional[str] = None  # long-form markdown shown in the click-out modal
    catalyst_category: Optional[str] = None  # EARNINGS | M&A | FDA | MANAGEMENT | INSIDER | FILING | CORPORATE_ACTION | NEWS
    catalyst_raw: tuple = ()                  # frozen tuple of source dicts for LLM explainer context
    today_volume: Optional[int] = None
    prior_30d_max_volume: Optional[int] = None
    above_sma10: bool = False
    macd_signal_cross: bool = False
    vwap_reclaim: bool = False
    opening_range_high: Optional[float] = None
    minutes_since_open: Optional[int] = None
    levels: KeyLevels = field(default_factory=KeyLevels)


@dataclass(frozen=True)
class CatalystFacts:
    """Structured catalyst classification for the click-out modal.

    `category` is one of:
        EARNINGS | M&A | FDA | MANAGEMENT | INSIDER | FILING | CORPORATE_ACTION |
        PRESS_RELEASE | NEWS | None
    `raw_items` is a frozen tuple of dicts (Finnhub rows) passed to the LLM
    explainer as web-search seed context.
    """

    has_catalyst: bool = False
    category: Optional[str] = None
    short_text: Optional[str] = None
    structured_md: Optional[str] = None
    raw_items: tuple = ()


@dataclass(frozen=True)
class ScanResult:
    """One qualifying ticker with its matched strategy and score."""

    snapshot: TickerSnapshot
    strategy_id: str
    strategy_name: str
    score: float


@dataclass(frozen=True)
class Playbook:
    """LLM-synthesized execution playbook for a single (ticker, strategy)."""

    symbol: str
    strategy_id: str
    thesis: str
    entry_trigger: str
    entry_price: float
    order_type: str  # "Buy Stop" | "Buy Limit" | "Buy Stop-Limit" | "Buy Market"
    stop_loss: float
    profit_target_1: float
    profit_target_2: float
    risk_reward: float
    position_size_pct: float
    indicators_to_watch: tuple[str, ...]
    invalidation: str
    confidence: str  # "low" | "medium" | "high"
    qualification_reason: str = ""
    confidence_reason: str = ""
