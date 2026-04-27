"""Scanner constants and strategy identifiers."""

DEFAULT_MOST_ACTIVE_LIMIT = 50
DEFAULT_CRYPTO_UNIVERSE_LIMIT = 20
MAX_RESULTS = 25

# Strategy identifiers (stable keys; names are display-only)
ATH_BREAKOUT = "ATH_BREAKOUT"
SMA10_MACD = "SMA10_MACD"
SPY_0DTE_FADE = "SPY_0DTE_FADE"
LOW_FLOAT_HVD = "LOW_FLOAT_HVD"
LOW_FLOAT_L2 = "LOW_FLOAT_L2"
VWAP_RECLAIM = "VWAP_RECLAIM"
ORB = "ORB"

STRATEGY_NAMES: dict[str, str] = {
    ATH_BREAKOUT: "ATH Breakout",
    SMA10_MACD: "10-SMA + MACD Crossover",
    SPY_0DTE_FADE: "SPY 0DTE PDH/PDL Fade",
    LOW_FLOAT_HVD: "Small-Cap Highest Volume Day",
    LOW_FLOAT_L2: "Low-Float Momentum + Level 2",
    VWAP_RECLAIM: "VWAP Reclaim",
    ORB: "Opening Range Breakout",
}

STRATEGY_RULES: dict[str, str] = {
    ATH_BREAKOUT: (
        "Enter on break of premarket high (PMH) or ATH with RVOL > 2 and price above VWAP. "
        "Stop below VWAP or PMH retest. Targets: next round number, then 1.5x R."
    ),
    SMA10_MACD: (
        "Enter on pullback to rising 10-SMA with MACD signal-line cross back up. "
        "Stop below 10-SMA swing low. Targets: recent swing high, then measured move."
    ),
    SPY_0DTE_FADE: (
        "Fade touches of PDH or PDL on SPY/QQQ when momentum stalls. "
        "Stop beyond the level by 1x ATR(5m). Target: VWAP reversion, then opposite level."
    ),
    LOW_FLOAT_HVD: (
        "Small-cap (<20M float) printing new highest-volume day. Enter on first pullback that "
        "holds VWAP. Stop below VWAP. Scale out at HOD, then extension target."
    ),
    LOW_FLOAT_L2: (
        "Low-float ($0.75–$10) with RVOL > 5 and clean Level-2 bid support. Enter on break of "
        "consolidation high. Stop below nearest bid support. Target: round number + extension."
    ),
    VWAP_RECLAIM: (
        "Price reclaims VWAP from below with confirming volume. Enter on first 1m or 5m close "
        "back above VWAP. Stop below reclaim candle. Target: PDH or opening range high."
    ),
    ORB: (
        "Break of first 5-minute (or 15-minute) range high with volume. Stop at range low. "
        "Target: 1x range extension, then 2x."
    ),
}
