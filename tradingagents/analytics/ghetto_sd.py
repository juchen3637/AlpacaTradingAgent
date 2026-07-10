"""
tradingagents/analytics/ghetto_sd.py — the "Ghetto Standard Deviation" engine.

Pure, I/O-free strategy math. Given ATM call+put asks it derives the priced-in
move (1 SD = call_ask + put_ask), doubles it for a 2 SD target, projects
upside/downside target strikes, screens candidate contracts into color-coded
verdicts, classifies expirations relative to the earnings date, scores stock
suitability 1-10, and surfaces warning flags.

All thresholds come from DEFAULT_CONFIG["ghetto_sd"] via GhettoSDConfig so they
stay tunable without touching this module. Nothing here fetches data — the data
layer (dataflows/options_utils.py) and the Dash callbacks supply the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal, Sequence

from ..default_config import DEFAULT_CONFIG

Side = Literal["call", "put"]


# ─── Config ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GhettoSDConfig:
    too_far_otm_cost: float
    valid_max_cost: float
    borderline_max_cost: float
    ideal_min_cost: float
    two_sd_zone_pct: float
    low_price_warn: float
    earnings_week_days: int
    liquidity_spread_pct: float
    suitability_base: int

    @classmethod
    def default(cls) -> "GhettoSDConfig":
        return cls.from_dict(DEFAULT_CONFIG["ghetto_sd"])

    @classmethod
    def from_dict(cls, d: dict) -> "GhettoSDConfig":
        return cls(
            too_far_otm_cost=float(d["too_far_otm_cost"]),
            valid_max_cost=float(d["valid_max_cost"]),
            borderline_max_cost=float(d["borderline_max_cost"]),
            ideal_min_cost=float(d["ideal_min_cost"]),
            two_sd_zone_pct=float(d["two_sd_zone_pct"]),
            low_price_warn=float(d["low_price_warn"]),
            earnings_week_days=int(d["earnings_week_days"]),
            liquidity_spread_pct=float(d["liquidity_spread_pct"]),
            suitability_base=int(d["suitability_base"]),
        )


# ─── Data model ─────────────────────────────────────────────────────────


class ExpirationClass(Enum):
    INVALID = "invalid"                  # 0 days to expiry — blocks SD calc
    IDEAL = "ideal"                      # week-of earnings
    USABLE_NOT_IDEAL = "usable_not_ideal"


@dataclass(frozen=True)
class SDResult:
    atm_strike: float
    atm_call_ask: float
    atm_put_ask: float
    one_sd: float
    two_sd: float
    one_sd_pct: float
    two_sd_pct: float
    upside_target: float
    downside_target: float


@dataclass(frozen=True)
class ExpirationInfo:
    expiry_date: date
    days_to_expiry: int
    days_after_earnings: int | None
    has_e_badge: bool
    classification: ExpirationClass


@dataclass(frozen=True)
class ContractQuote:
    strike: float
    side: Side
    bid: float
    ask: float
    symbol: str = ""  # OCC contract symbol — what the order layer trades


@dataclass(frozen=True)
class ContractRow:
    strike: float
    side: Side
    bid: float
    ask: float
    cost_per_contract: float
    distance_pct: float           # % distance from the relevant 2SD target
    in_two_sd_zone: bool
    rating: str                   # human-facing 2SD rating
    verdict: str                  # Valid Play / Borderline / Too Expensive / Too Far OTM
    verdict_icon: str
    liquidity_warning: bool
    symbol: str = ""              # OCC contract symbol — what the order layer trades


@dataclass(frozen=True)
class Suitability:
    score: int
    breakdown: tuple[str, ...]


@dataclass(frozen=True)
class Warning:
    level: Literal["critical", "warning", "info"]
    message: str


@dataclass(frozen=True)
class AnalysisInput:
    ticker: str
    current_price: float
    earnings_date: date | None
    today: date
    expiry_date: date
    has_e_badge: bool
    atm_strike: float
    atm_call_ask: float
    atm_put_ask: float
    contracts: tuple[ContractQuote, ...] = ()
    large_historical_moves: bool | None = None


@dataclass(frozen=True)
class Analysis:
    ticker: str
    sd: SDResult | None
    expiration: ExpirationInfo
    screener: tuple[ContractRow, ...]
    suitability: Suitability
    warnings: tuple[Warning, ...] = field(default_factory=tuple)


_VERDICT_ICONS = {
    "Valid Play": "✅",
    "Borderline": "⚠️",
    "Too Expensive": "❌",
    "Too Far OTM": "🚫",
}


# ─── Core math ──────────────────────────────────────────────────────────


def compute_sd(current_price: float, atm_call_ask: float, atm_put_ask: float, atm_strike: float) -> SDResult:
    """1 SD = ATM call ask + ATM put ask; 2 SD = 2 x 1 SD; targets = price ± 2 SD."""
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if atm_call_ask <= 0 or atm_put_ask <= 0:
        raise ValueError("ATM call/put ask must be positive — missing quote data")
    one_sd = atm_call_ask + atm_put_ask
    two_sd = one_sd * 2
    return SDResult(
        atm_strike=atm_strike,
        atm_call_ask=atm_call_ask,
        atm_put_ask=atm_put_ask,
        one_sd=one_sd,
        two_sd=two_sd,
        one_sd_pct=one_sd / current_price * 100,
        two_sd_pct=two_sd / current_price * 100,
        upside_target=current_price + two_sd,
        downside_target=current_price - two_sd,
    )


def select_atm_strike(current_price: float, strikes: Sequence[float]) -> float:
    """Nearest strike at or above the current price; fall back to the highest strike."""
    if not strikes:
        raise ValueError("no strikes available")
    above = [s for s in strikes if s >= current_price]
    return min(above) if above else max(strikes)


# ─── Expiration selection ───────────────────────────────────────────────


def classify_expiration(
    expiry_date: date,
    earnings_date: date | None,
    today: date,
    *,
    has_e_badge: bool = False,
    cfg: GhettoSDConfig | None = None,
) -> ExpirationInfo:
    """Classify an expiration: 0-day → INVALID, week-of-earnings → IDEAL, else USABLE."""
    cfg = cfg or GhettoSDConfig.default()
    days_to_expiry = (expiry_date - today).days
    days_after_earnings = (expiry_date - earnings_date).days if earnings_date else None

    if days_to_expiry <= 0:
        classification = ExpirationClass.INVALID
    elif days_after_earnings is not None and 0 <= days_after_earnings <= cfg.earnings_week_days:
        classification = ExpirationClass.IDEAL
    else:
        classification = ExpirationClass.USABLE_NOT_IDEAL

    return ExpirationInfo(
        expiry_date=expiry_date,
        days_to_expiry=days_to_expiry,
        days_after_earnings=days_after_earnings,
        has_e_badge=has_e_badge,
        classification=classification,
    )


def select_ideal_expiration(
    expiries: Sequence[date],
    earnings_date: date | None,
    today: date,
    *,
    cfg: GhettoSDConfig | None = None,
) -> date | None:
    """The week-of-earnings expiry closest after the event, or None if none qualify."""
    cfg = cfg or GhettoSDConfig.default()
    ideal = [
        e
        for e in expiries
        if classify_expiration(e, earnings_date, today, cfg=cfg).classification is ExpirationClass.IDEAL
    ]
    if not ideal or earnings_date is None:
        return None
    return min(ideal, key=lambda e: (e - earnings_date).days)


def select_nearest_expiration(
    expiries: Sequence[date],
    today: date,
    *,
    min_dte: int = 1,
) -> date | None:
    """The soonest expiry at least `min_dte` days out — the earnings-free analog of
    select_ideal_expiration, used by the scanner. None if nothing qualifies."""
    usable = [e for e in expiries if (e - today).days >= min_dte]
    return min(usable) if usable else None


# ─── Chain shaping (raw dicts → engine types) ───────────────────────────


def atm_from_chain(
    chain: Sequence[dict],
    price: float,
) -> tuple[float, float | None, float | None]:
    """ATM strike (nearest at/above price) plus its call & put asks from a raw chain.

    Returns (atm_strike, call_ask, put_ask); asks are None when the strike is absent.
    Falls back to round(price) for the strike when the chain has no strikes at all.
    """
    calls = {r["strike"]: r for r in chain if r["side"] == "call"}
    puts = {r["strike"]: r for r in chain if r["side"] == "put"}
    strikes = sorted(set(calls) | set(puts))
    above = [s for s in strikes if s >= price]
    atm = min(above) if above else (max(strikes) if strikes else round(price))
    return atm, calls.get(atm, {}).get("ask"), puts.get(atm, {}).get("ask")


def candidate_contracts(
    chain: Sequence[dict],
    price: float,
    one_sd: float,
    *,
    band_pct: float,
) -> list[ContractQuote]:
    """Contracts within `band_pct`% of the 2SD targets (price ± 2·one_sd)."""
    if not chain:
        return []
    upside = price + 2 * one_sd
    downside = price - 2 * one_sd
    out: list[ContractQuote] = []
    for r in chain:
        target = upside if r["side"] == "call" else downside
        if target > 0 and abs(r["strike"] - target) / target * 100 <= band_pct:
            out.append(ContractQuote(strike=r["strike"], side=r["side"], bid=r["bid"], ask=r["ask"],
                                     symbol=r.get("symbol", "")))
    return out


# ─── Screener ───────────────────────────────────────────────────────────


def _verdict_for_cost(cost: float, cfg: GhettoSDConfig) -> str:
    if cost < cfg.too_far_otm_cost:
        return "Too Far OTM"
    if cost <= cfg.valid_max_cost:
        return "Valid Play"
    if cost <= cfg.borderline_max_cost:
        return "Borderline"
    return "Too Expensive"


def _screen_one(quote: ContractQuote, sd: SDResult, cfg: GhettoSDConfig) -> ContractRow:
    cost = quote.ask * 100
    target = sd.upside_target if quote.side == "call" else sd.downside_target
    distance_pct = abs(quote.strike - target) / abs(target) * 100 if target else float("inf")
    in_zone = distance_pct <= cfg.two_sd_zone_pct
    if in_zone:
        rating = "🎯 In 2SD zone"
    elif distance_pct <= cfg.two_sd_zone_pct * 2:
        rating = "Near 2SD zone"
    else:
        rating = "Far from 2SD"

    spread = quote.ask - quote.bid
    liquidity_warning = quote.ask > 0 and (spread / quote.ask * 100) > cfg.liquidity_spread_pct

    verdict = _verdict_for_cost(cost, cfg)
    return ContractRow(
        strike=quote.strike,
        side=quote.side,
        bid=quote.bid,
        ask=quote.ask,
        cost_per_contract=cost,
        distance_pct=distance_pct,
        in_two_sd_zone=in_zone,
        rating=rating,
        verdict=verdict,
        verdict_icon=_VERDICT_ICONS[verdict],
        liquidity_warning=liquidity_warning,
        symbol=quote.symbol,
    )


def build_screener(
    quotes: Sequence[ContractQuote],
    sd: SDResult,
    cfg: GhettoSDConfig | None = None,
) -> list[ContractRow]:
    cfg = cfg or GhettoSDConfig.default()
    return [_screen_one(q, sd, cfg) for q in quotes]


# ─── Suitability scoring ────────────────────────────────────────────────


def score_suitability(
    current_price: float,
    earnings_this_week: bool,
    two_sd_min_cost: float | None,
    large_historical_moves: bool | None,
    same_day_expiry: bool,
    *,
    cfg: GhettoSDConfig | None = None,
) -> Suitability:
    """Score 1-10 from the brief's +/- rules, applied to a configurable base."""
    cfg = cfg or GhettoSDConfig.default()
    score = cfg.suitability_base
    breakdown: list[str] = [f"base {cfg.suitability_base}"]

    if current_price > 150:
        score += 3
        breakdown.append("+3 stock > $150")
    if two_sd_min_cost is not None and two_sd_min_cost < cfg.valid_max_cost:
        score += 3
        breakdown.append("+3 2SD contract under $100")
    if earnings_this_week:
        score += 2
        breakdown.append("+2 earnings this week")
    if large_historical_moves:
        score += 2
        breakdown.append("+2 history of large earnings moves")

    if current_price < cfg.low_price_warn:
        score -= 3
        breakdown.append("-3 stock under $50")
    if two_sd_min_cost is not None and two_sd_min_cost > cfg.borderline_max_cost:
        score -= 2
        breakdown.append("-2 2SD options still over $150")
    if same_day_expiry:
        score -= 2
        breakdown.append("-2 expiration same day as earnings")

    score = max(1, min(10, score))
    return Suitability(score=score, breakdown=tuple(breakdown))


# ─── Warnings ───────────────────────────────────────────────────────────


def collect_warnings(inp: AnalysisInput, expiration: ExpirationInfo, cfg: GhettoSDConfig) -> list[Warning]:
    warnings: list[Warning] = []

    # The one core rule — prominent overpay warning for cheap stocks.
    if inp.current_price < cfg.low_price_warn:
        warnings.append(Warning(
            level="critical",
            message=(
                f"LOW-PRICED STOCK (${inp.current_price:.2f}): you are likely overpaying for the "
                f"option relative to the stock price, even if the dollar amount looks small."
            ),
        ))

    if expiration.classification is ExpirationClass.INVALID:
        warnings.append(Warning(
            level="critical",
            message="Same-day (0 DTE) expiration — SD calculation blocked. Pick the week-of-earnings expiry.",
        ))
    elif expiration.classification is not ExpirationClass.IDEAL:
        warnings.append(Warning(
            level="warning",
            message="Wrong expiration — you are not on the week-of-earnings chain used for the SD calc.",
        ))

    if expiration.days_after_earnings is not None and 0 <= expiration.days_after_earnings <= 1:
        warnings.append(Warning(
            level="warning",
            message="IV Crush risk — expiration is day-of or day-after earnings.",
        ))

    if not inp.has_e_badge and expiration.classification is not ExpirationClass.IDEAL:
        warnings.append(Warning(
            level="info",
            message="Earnings not this week — no 'E' badge on the selected expiration.",
        ))

    return warnings


# ─── Orchestrator ───────────────────────────────────────────────────────


def analyze(inp: AnalysisInput, *, cfg: GhettoSDConfig | None = None) -> Analysis:
    """Full pipeline: classify expiry, compute SD (unless blocked), screen, score, warn."""
    cfg = cfg or GhettoSDConfig.default()

    expiration = classify_expiration(
        inp.expiry_date, inp.earnings_date, inp.today, has_e_badge=inp.has_e_badge, cfg=cfg
    )

    sd: SDResult | None = None
    screener: list[ContractRow] = []
    if expiration.classification is not ExpirationClass.INVALID:
        sd = compute_sd(inp.current_price, inp.atm_call_ask, inp.atm_put_ask, inp.atm_strike)
        screener = build_screener(inp.contracts, sd, cfg)

    two_sd_costs = [r.cost_per_contract for r in screener if r.in_two_sd_zone] or [
        r.cost_per_contract for r in screener
    ]
    two_sd_min_cost = min(two_sd_costs) if two_sd_costs else None

    suitability = score_suitability(
        current_price=inp.current_price,
        earnings_this_week=inp.has_e_badge or expiration.classification is ExpirationClass.IDEAL,
        two_sd_min_cost=two_sd_min_cost,
        large_historical_moves=inp.large_historical_moves,
        same_day_expiry=expiration.days_after_earnings == 0 if expiration.days_after_earnings is not None else False,
        cfg=cfg,
    )

    warnings = collect_warnings(inp, expiration, cfg)

    return Analysis(
        ticker=inp.ticker,
        sd=sd,
        expiration=expiration,
        screener=tuple(screener),
        suitability=suitability,
        warnings=tuple(warnings),
    )


# ─── Scan qualification ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ScanCriteria:
    """Gates a scanned ticker must clear to qualify. All gates are AND-ed."""

    min_suitability: int
    max_2sd_cost: float
    require_valid_play: bool = True
    require_liquidity_ok: bool = True

    @classmethod
    def default(cls) -> "ScanCriteria":
        d = DEFAULT_CONFIG["ghetto_sd_scan"]
        return cls(
            min_suitability=int(d["min_suitability"]),
            max_2sd_cost=float(d["max_2sd_cost"]),
        )


@dataclass(frozen=True)
class CandidateResult:
    """A scanned ticker. The play is a strangle — a call leg near the upside 2SD
    target plus a put leg near the downside — so both legs are tracked."""

    ticker: str
    analysis: Analysis
    qualifies: bool
    failed_gates: tuple[str, ...]
    call_leg: ContractRow | None
    put_leg: ContractRow | None
    price: float
    earnings_date: date | None = None  # next scheduled earnings (display-only)

    @property
    def strangle_cost(self) -> float | None:
        """Combined cost of both legs, or None if either leg is missing."""
        if self.call_leg and self.put_leg:
            return self.call_leg.cost_per_contract + self.put_leg.cost_per_contract
        return None


def _best_leg(analysis: Analysis, side: Side) -> ContractRow | None:
    """Cheapest Valid Play on one side, preferring contracts inside the 2SD zone."""
    valid = [r for r in analysis.screener if r.side == side and r.verdict == "Valid Play"]
    if not valid:
        return None
    in_zone = [r for r in valid if r.in_two_sd_zone]
    return min(in_zone or valid, key=lambda r: r.cost_per_contract)


def pick_best_strangle(analysis: Analysis) -> tuple[ContractRow | None, ContractRow | None]:
    """The best call leg (near upside target) and put leg (near downside) for the strangle."""
    return _best_leg(analysis, "call"), _best_leg(analysis, "put")


def evaluate_candidate(
    analysis: Analysis,
    criteria: ScanCriteria,
    *,
    price: float,
) -> CandidateResult:
    """Apply the four scan gates to a strangle; a ticker qualifies only when none fail.

    The play needs BOTH legs: a viable call near the upside target and a viable put
    near the downside. Cost and liquidity are judged per leg.
    """
    call_leg, put_leg = pick_best_strangle(analysis)
    both = call_leg is not None and put_leg is not None
    legs = [leg for leg in (call_leg, put_leg) if leg is not None]
    failed: list[str] = []

    if analysis.suitability.score < criteria.min_suitability:
        failed.append("suitability")
    if criteria.require_valid_play and not both:
        failed.append("valid_play")
    if not both or any(leg.cost_per_contract > criteria.max_2sd_cost for leg in legs):
        failed.append("cost")
    if criteria.require_liquidity_ok and (not both or any(leg.liquidity_warning for leg in legs)):
        failed.append("liquidity")

    return CandidateResult(
        ticker=analysis.ticker,
        analysis=analysis,
        qualifies=not failed,
        failed_gates=tuple(failed),
        call_leg=call_leg,
        put_leg=put_leg,
        price=price,
    )
