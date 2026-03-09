# TradingAgents/graph/trading_graph.py

import os
from pathlib import Path
import json
import logging
from datetime import date, datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.interface import set_config
from tradingagents.dataflows.config import get_api_key, get_anthropic_api_key

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor

# Import retry utilities for rate limit handling
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False
    print("[WARNING] tenacity not installed - rate limit retry disabled. Install with: pip install tenacity>=8.2.0")

# Optional openai import for rate limit error type
try:
    import openai as _openai_module
    _OPENAI_RATE_LIMIT_ERROR = _openai_module.RateLimitError
except ImportError:
    _openai_module = None
    _OPENAI_RATE_LIMIT_ERROR = None

# Optional anthropic import for rate limit handling
try:
    import anthropic as _anthropic_module
    _ANTHROPIC_RATE_LIMIT_ERROR = _anthropic_module.RateLimitError
except ImportError:
    _ANTHROPIC_RATE_LIMIT_ERROR = None


def _get_rate_limit_error_types():
    """Return the set of rate limit error types to catch."""
    error_types = []
    if _OPENAI_RATE_LIMIT_ERROR is not None:
        error_types.append(_OPENAI_RATE_LIMIT_ERROR)
    if _ANTHROPIC_RATE_LIMIT_ERROR is not None:
        error_types.append(_ANTHROPIC_RATE_LIMIT_ERROR)
    return tuple(error_types) if error_types else (Exception,)


def invoke_llm_with_retry(llm, messages, max_attempts=3):
    """Invoke LLM with automatic retry on rate limit errors.

    Retries with exponential backoff when rate limits are hit (OpenAI or Anthropic),
    preventing analysis failures due to temporary API throttling.

    Args:
        llm: The LLM instance to invoke
        messages: Messages to send to the LLM
        max_attempts: Maximum number of retry attempts (default: 3)

    Returns:
        LLM response

    Raises:
        Exception: If all retry attempts fail
    """
    if not TENACITY_AVAILABLE:
        # Fallback to direct invocation if tenacity not available
        return llm.invoke(messages)

    rate_limit_errors = _get_rate_limit_error_types()

    @retry(
        retry=retry_if_exception_type(rate_limit_errors),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(max_attempts),
        before_sleep=lambda retry_state: print(
            f"[RATE_LIMIT] Hit rate limit, retrying in {retry_state.next_action.sleep:.1f}s... (attempt {retry_state.attempt_number}/{max_attempts})"
        )
    )
    def _invoke_with_retry():
        return llm.invoke(messages)

    return _invoke_with_retry()


def _create_llm(model_name: str, provider: str, api_key: str = None):
    """Factory function to create an LLM instance based on the provider.

    Args:
        model_name: Name of the model to use
        provider: LLM provider ("openai" or "anthropic")
        api_key: API key for the provider

    Returns:
        LLM instance (ChatOpenAI or ChatAnthropic)
    """
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, api_key=api_key, temperature=0.2)

    # Default: OpenAI
    kwargs = {}
    # Models that don't support temperature parameter
    no_temp_models = ["o3", "o4-mini", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
    if not any(prefix in model_name for prefix in no_temp_models):
        kwargs["temperature"] = 0.2
    return ChatOpenAI(model=model_name, openai_api_key=api_key, **kwargs)


def get_debate_rounds_from_depth(research_depth: str) -> Tuple[int, int]:
    """
    Map research depth to debate round counts.

    Args:
        research_depth: One of "shallow"/"Shallow", "medium"/"Medium", "deep"/"Deep"

    Returns:
        Tuple of (max_debate_rounds, max_risk_discuss_rounds)
        - max_debate_rounds: For bull/bear investment debate
        - max_risk_discuss_rounds: For risky/safe/neutral risk debate

    Research depth levels:
        - shallow: 1 round (2 bull/bear calls, 3 risk analyst calls)
        - medium: 3 rounds (6 bull/bear calls, 9 risk analyst calls)
        - deep: 5 rounds (10 bull/bear calls, 15 risk analyst calls)
    """
    # Normalize to lowercase for case-insensitive matching
    depth_normalized = research_depth.lower() if isinstance(research_depth, str) else "medium"

    depth_map = {
        "shallow": (1, 1),
        "medium": (3, 3),
        "deep": (5, 5),
    }

    if depth_normalized not in depth_map:
        print(f"[CONFIG] Warning: Invalid research_depth '{research_depth}', defaulting to 'medium'")
        depth_normalized = "medium"

    max_debate_rounds, max_risk_discuss_rounds = depth_map[depth_normalized]
    print(f"[CONFIG] Research depth: {depth_normalized} → Investment debate: {max_debate_rounds} rounds, Risk debate: {max_risk_discuss_rounds} rounds")

    return max_debate_rounds, max_risk_discuss_rounds


def _cleanup_old_eval_results(ticker: str, max_age_days: int = 30) -> None:
    """Delete eval_results directories for a ticker where the log file is older than max_age_days.

    Args:
        ticker: The ticker symbol whose eval_results directory to inspect.
        max_age_days: Remove the directory when the log file is older than this many days.
    """
    safe_ticker = ticker.replace("/", "_")
    log_path = Path(f"eval_results/{safe_ticker}/TradingAgentsStrategy_logs/full_states_log.json")
    if not log_path.exists():
        return
    try:
        file_age = datetime.now() - datetime.fromtimestamp(log_path.stat().st_mtime)
        if file_age > timedelta(days=max_age_days):
            import shutil
            ticker_dir = Path(f"eval_results/{safe_ticker}")
            shutil.rmtree(ticker_dir, ignore_errors=True)
            logger.info("[EVAL_RESULTS] Removed stale eval_results for %s (age: %s days)", ticker, file_age.days)
    except Exception as exc:
        logger.warning("[EVAL_RESULTS] Cleanup check failed for %s: %s", ticker, exc)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals", "macro"],
        debug=False,
        config: Dict[str, Any] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )

        # Determine provider and pick appropriate API key / model names
        provider = self.config.get("llm_provider", "openai")

        if provider == "anthropic":
            api_key = get_anthropic_api_key()
            deep_think_model = self.config.get(
                "deep_think_llm", self.config.get("anthropic_deep_think_llm", "claude-opus-4-6")
            )
            quick_think_model = self.config.get(
                "quick_think_llm", self.config.get("anthropic_quick_think_llm", "claude-haiku-4-5-20251001")
            )
        else:
            api_key = get_api_key("openai_api_key", "OPENAI_API_KEY")
            deep_think_model = self.config["deep_think_llm"]
            quick_think_model = self.config["quick_think_llm"]

        logger.info("[CONFIG] LLM provider: %s, deep=%s, quick=%s", provider, deep_think_model, quick_think_model)

        self.deep_thinking_llm = _create_llm(deep_think_model, provider, api_key)
        self.quick_thinking_llm = _create_llm(quick_think_model, provider, api_key)
        
        self.toolkit = Toolkit(config=self.config)

        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory")
        self.bear_memory = FinancialSituationMemory("bear_memory")
        self.trader_memory = FinancialSituationMemory("trader_memory")
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory")
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory")

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Determine debate rounds based on research depth
        research_depth = self.config.get("research_depth", "medium")

        # Allow legacy config to override if explicitly set
        if self.config.get("max_debate_rounds") is not None or self.config.get("max_risk_discuss_rounds") is not None:
            # Use legacy config values if provided
            max_debate_rounds = self.config.get("max_debate_rounds", 3)
            max_risk_discuss_rounds = self.config.get("max_risk_discuss_rounds", 3)
            logger.info("[CONFIG] Using legacy debate settings: max_debate_rounds=%s, max_risk_discuss_rounds=%s", max_debate_rounds, max_risk_discuss_rounds)
        else:
            # Use research_depth to determine debate rounds
            max_debate_rounds, max_risk_discuss_rounds = get_debate_rounds_from_depth(research_depth)

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=max_debate_rounds,
            max_risk_discuss_rounds=max_risk_discuss_rounds
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.toolkit,
            self.tool_nodes,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.risk_manager_memory,
            self.conditional_logic,
            self.config,
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources."""
        return {
            "market": ToolNode(
                [
                    # online tools
                    self.toolkit.get_alpaca_data,
                    self.toolkit.get_stockstats_indicators_report_online,
                    # offline tools
                    self.toolkit.get_stockstats_indicators_report,
                    self.toolkit.get_alpaca_data_report,
                    # crypto
                    self.toolkit.get_coindesk_news,
                ]
            ),
            "social": ToolNode(
                [
                    # online tools
                    self.toolkit.get_stock_news_openai,
                    # offline tools
                    self.toolkit.get_reddit_stock_info,
                    # crypto
                    self.toolkit.get_coindesk_news,
                ]
            ),
            "news": ToolNode(
                [
                    # online tools
                    self.toolkit.get_global_news_openai,
                    self.toolkit.get_google_news,
                    # offline tools
                    self.toolkit.get_finnhub_news,
                    self.toolkit.get_reddit_news,
                    # crypto
                    self.toolkit.get_coindesk_news,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # online tools
                    self.toolkit.get_fundamentals_openai,
                    self.toolkit.get_defillama_fundamentals,
                    # offline tools
                    self.toolkit.get_finnhub_company_insider_sentiment,
                    self.toolkit.get_finnhub_company_insider_transactions,
                    self.toolkit.get_simfin_balance_sheet,
                    self.toolkit.get_simfin_cashflow,
                    self.toolkit.get_simfin_income_stmt,
                    # earnings tools
                    self.toolkit.get_earnings_calendar,
                    self.toolkit.get_earnings_surprise_analysis,
                ]
            ),
            "macro": ToolNode(
                [
                    # macro economic tools
                    self.toolkit.get_macro_analysis,
                    self.toolkit.get_economic_indicators,
                    self.toolkit.get_yield_curve_analysis,
                ]
            ),
        }

    def propagate(self, company_name, trade_date):
        """Run the trading agents graph for a company on a specific date."""

        self.ticker = company_name

        # Initialize state
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date
        )
        args = self.propagator.get_graph_args()

        if self.debug:
            # Debug mode with tracing
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)

            final_state = trace[-1]
        else:
            # Standard mode without tracing
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        # Return decision and processed signal
        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        # Remove stale eval_results before writing new ones
        _cleanup_old_eval_results(self.ticker)

        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "risky_history": final_state["risk_debate_state"]["risky_history"],
                "safe_history": final_state["risk_debate_state"]["safe_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file (sanitize ticker to avoid filesystem issues with crypto pairs like BTC/USD)
        safe_ticker = self.ticker.replace("/", "_")
        directory = Path(f"eval_results/{safe_ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)

        with open(
            f"eval_results/{safe_ticker}/TradingAgentsStrategy_logs/full_states_log.json",
            "w",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4)

        # Evict the entry after writing to prevent unbounded memory growth
        del self.log_states_dict[str(trade_date)]
        logger.debug("[TRADING_GRAPH] State for %s written and evicted from memory", trade_date)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            self.curr_state, returns_losses, self.risk_manager_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
