"""Immutable data models for the Long-Term scanner pipeline.

Parallel to `scanner/models.py` but tuned for buy-and-hold investing:
fundamentals (margins, growth, ROE, valuation), long-term trend signals
(200-SMA, golden cross), and a DCA-style playbook instead of single-trigger
entry/stop/PT levels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Shared strategy identifier so saved-plays storage and the Plays page can
# branch on it (long-term plays render differently from day-trade plays).
LONGTERM_STRATEGY_ID = "LONGTERM_HOLD"
LONGTERM_STRATEGY_NAME = "Long-Term Hold"


@dataclass(frozen=True)
class LongTermFilters:
    """User-controlled long-term scan parameters."""

    universe_kind: str = "mega_cap"          # "mega_cap" | "watchlist"
    watchlist: tuple[str, ...] = ()
    min_market_cap_b: float = 100.0          # billions; 0 disables the filter
    must_be_profitable: bool = True          # net margin > 0
    max_pe: Optional[float] = None           # None disables; e.g. 60.0
    excluded_sectors: tuple[str, ...] = ()
    catalyst_only: bool = False              # require recent catalyst


@dataclass(frozen=True)
class LongTermSnapshot:
    """Pointer-in-time snapshot of one ticker for long-term ranking."""

    symbol: str
    last_price: float
    market_cap_b: Optional[float] = None     # billions
    sector: Optional[str] = None
    industry: Optional[str] = None

    # Fundamentals (Finnhub `company_basic_financials.metric`)
    roe_ttm: Optional[float] = None          # ROE TTM in percent
    net_margin_ttm: Optional[float] = None   # net margin TTM in percent
    revenue_growth_3y: Optional[float] = None  # 3y revenue CAGR in percent
    pe_forward: Optional[float] = None       # forward / normalized P/E
    debt_to_equity: Optional[float] = None
    dividend_yield_ttm: Optional[float] = None  # in percent

    # Long-term trend signals (computed from Alpaca daily bars)
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    above_sma_200: bool = False
    golden_cross: bool = False               # 50-SMA > 200-SMA
    wk52_high: Optional[float] = None
    wk52_low: Optional[float] = None
    one_year_return_pct: Optional[float] = None

    # Catalyst signals (reuses day-trade scanner's _fetch_catalyst helper)
    has_catalyst: bool = False
    catalyst_text: Optional[str] = None
    catalyst_details: Optional[str] = None   # structured Finnhub markdown card
    catalyst_category: Optional[str] = None  # EARNINGS | M&A | FDA | ...
    catalyst_raw: tuple = ()                 # frozen tuple of raw source dicts


@dataclass(frozen=True)
class LongTermScanResult:
    """One qualifying ticker with its composite long-term score."""

    snapshot: LongTermSnapshot
    score: float


@dataclass(frozen=True)
class LongTermPlaybook:
    """LLM-synthesized buy-and-hold thesis for one mega-cap.

    Carries both the DCA framing (entry zone, weeks, 3y horizon) AND a
    bracket-compatible level set (entry/stop/PT1/PT2/size/order_type) so
    that `Execute (Paper)` can place a live bracket order through the
    same Alpaca path used by the day-trade scanner. The `stop_loss` here
    is intentionally a *thesis-broken floor* (15–25% below entry zone),
    not a tight intraday stop.
    """

    symbol: str
    thesis: str
    key_drivers: tuple[str, ...]
    key_risks: tuple[str, ...]
    entry_zone_low: float
    entry_zone_high: float
    dca_weeks: int
    hold_horizon_years: int
    target_price_3y: float
    conviction: str                          # "low" | "medium" | "high"
    conviction_reason: str = ""

    # Bracket-order fields — defaults of 0.0 keep older saved plays loadable
    # via _longterm_playbook_from_dict (missing keys → default). The UI
    # surfaces a "regenerate to enable Execute" hint when entry_price == 0.
    entry_price: float = 0.0
    stop_loss: float = 0.0
    profit_target_1: float = 0.0
    profit_target_2: float = 0.0
    position_size_pct: float = 0.05          # 0..1 of buying power
    order_type: str = "Buy Limit"            # "Buy Limit" | "Buy Stop"
    strategy_id: str = LONGTERM_STRATEGY_ID  # used for client_order_id tag
