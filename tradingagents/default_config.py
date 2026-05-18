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
    # Stop loss and take profit settings
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
}
