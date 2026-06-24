import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    # "data_dir": "/Users/yluo/Documents/Code/ScAI/FR1-data",
    "data_dir": "data/ScAI/FR1-data",
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "openai",          # "openai" or "anthropic"
    "deep_think_llm": "gpt-5.2-2025-12-11",
    "quick_think_llm": "gpt-5-mini-2025-08-07",  # Supports web search via responses.create()
    "anthropic_deep_think_llm": "claude-opus-4-6",
    "anthropic_quick_think_llm": "claude-sonnet-4-6",
    # Research depth settings - controls debate rounds for both investment and risk analysis
    # Options: "shallow" (1 round), "medium" (3 rounds), "deep" (5 rounds)
    "research_depth": "medium",  # shallow = fast, medium = balanced, deep = thorough
    # Legacy settings (deprecated - use research_depth instead)
    "max_debate_rounds": None,  # Will be set based on research_depth if None
    "max_risk_discuss_rounds": None,  # Will be set based on research_depth if None
    "max_recur_limit": 200,
    # Trading settings
    "allow_shorts": False,  # False = Investment mode (BUY/HOLD/SELL), True = Trading mode (LONG/NEUTRAL/SHORT)
    # Position sizing settings
    "ai_position_sizing": True,  # True = AI determines position size, False = fixed amount
    "max_position_pct_of_buying_power": 30,  # Maximum % of buying power per trade
    "max_risk_pct_per_trade": 3,  # Maximum % account risk per trade
    "min_position_size": 100,  # Minimum position size in dollars
    # Safety gate — hard limits enforced before any Alpaca order (non-LLM)
    "max_daily_loss_pct": 5.0,   # Halt new entries if account down >N% today; 0 = disabled
    "max_open_positions": 10,    # Hard cap on concurrent open positions; 0 = disabled
    # Phase 4 note: upgrade to Alpaca SIP feed (Algo Trader+ ~$99/mo) for real premarket
    # bars. Until then, ATH_BREAKOUT strategy falls back to 52-week high and
    # premarket_volume is unavailable. Scanner strategies ORB, VWAP_RECLAIM work fine
    # on IEX (post-9:30 data); day-trading playbooks should weight those over ATH_BREAKOUT.
    # Stop loss and take profit settings
    "use_bracket_orders": True,  # Use native Alpaca bracket orders (entry + SL + TP as one atomic order)
    "use_stop_loss": True,  # Enable stop loss orders
    "use_take_profit": True,  # Enable take profit orders
    "stop_loss_order_type": "stop",  # "stop" or "stop_limit"
    "scale_out_targets": True,  # Use multiple targets to scale out
    # Exit gate settings — prevent flip-flop liquidations of fresh positions
    "respect_brackets_when_held": True,  # Once a bracket is placed, TP/SL is the primary exit
    "position_age_min_hold_hours": 4,  # AI cannot exit a position younger than this (unless adverse move)
    "exit_conviction_threshold": 0.75,  # Minimum conviction (0..1) required to override an active bracket
    "exit_adverse_move_pct": 2.0,  # Hard-dissent override: adverse move % vs entry that bypasses min-hold
    # Health-check mode for held positions — full debate only on entries; held use lightweight check
    "held_position_health_check_only": True,  # Held positions use a slimmed analyst set + quick LLM
    "health_check_analysts": ["market", "news"],  # Analysts to run for held-position health checks
    "health_check_use_quick_llm_only": True,  # Use quick LLM for both quick and deep think during health checks
    # Per-ticker cooldown / change-detection — skip re-analysis when nothing material has changed
    "per_ticker_cooldown_hours": 4,  # Minimum hours between re-analyses of the same ticker
    "min_price_move_pct_for_reanalysis": 0.0,  # If >0, skip re-analysis when price moved less than this %
    "require_fresh_news_for_reanalysis": False,  # If True, only re-analyze when news cache shows new items
    # Execution settings
    "parallel_analysts": False,  # False = Sequential execution (more reliable), True = Parallel execution (faster)
    # Tool settings (DEPRECATED: All tools now use smart caching automatically)
    "online_tools": True,  # DEPRECATED - Tools automatically check cache first, then use API. This flag is ignored.
    # API keys (these will be overridden by environment variables if present)
    "openai_api_key": None,
    "anthropic_api_key": None,
    "finnhub_api_key": None,
    "alpaca_api_key": None,
    "alpaca_secret_key": None,
    "alpaca_use_paper": "True",  # Set to "True" to use paper trading, "False" for live trading
    "coindesk_api_key": None,
    # Ghetto Standard Deviation options analyzer — all thresholds tunable here.
    # Verdict bands are keyed off cost-per-contract (ask * 100). Canonical source
    # is the screener-table spec (Valid <100 / Borderline 100-150 / Too Expensive
    # >150 / Too Far OTM <20).
    "ghetto_sd": {
        "too_far_otm_cost": 20.0,      # cost < this  → 🚫 Too Far OTM
        "valid_max_cost": 100.0,       # cost <= this → ✅ Valid Play (and >= too_far)
        "borderline_max_cost": 150.0,  # cost <= this → ⚠️ Borderline; above → ❌ Too Expensive
        "ideal_min_cost": 30.0,        # advisory ideal range lower bound
        "two_sd_zone_pct": 5.0,        # strike within ±N% of target → "in 2SD zone"
        "low_price_warn": 50.0,        # stock under this → prominent overpay warning (the core rule)
        "earnings_week_days": 7,       # expiry within N days AFTER earnings → "week-of" / ideal
        "liquidity_spread_pct": 30.0,  # bid/ask spread > N% of ask → liquidity warning
        "suitability_base": 5,         # base score before +/- deltas, clamped to 1..10
    },
    # Ghetto SD scanner: sweep a universe and surface tickers that clear all gates.
    "ghetto_sd_scan": {
        "universe_size": 25,    # most-actives to sweep (caps latency / rate limits)
        "min_price": 20.0,      # skip sub-$N tickers (penny stocks / leveraged ETFs)
        "min_suitability": 6,   # gate: suitability score >= this
        "max_2sd_cost": 100.0,  # gate: best Valid Play 2SD cost-per-contract <= this
        "min_dte": 1,           # nearest-expiration floor (skip 0 DTE)
        "max_workers": 8,       # parallel per-ticker fetch workers
    },
}
