"""
tests/test_trading_graph.py

TDD tests for production-hardening changes in tradingagents/graph/trading_graph.py:
  1. _get_rate_limit_error_types() works correctly when tenacity is absent.
  2. _log_state() sanitizes crypto tickers (BTC/USD -> BTC_USD) in the path.
  3. _log_state() evicts the entry from log_states_dict after writing to disk.
"""

import copy
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Shared helpers (mirrors pattern from test_trading_graph_provider.py)
# ---------------------------------------------------------------------------

_MODULE = "tradingagents.graph.trading_graph"


def _base_config(**overrides):
    from tradingagents.default_config import DEFAULT_CONFIG
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(overrides)
    return cfg


def _all_patches(extra_patches=None):
    """Return a list of patch objects covering every heavyweight dep in __init__."""
    patches = [
        patch(f"{_MODULE}.set_config"),
        patch(f"{_MODULE}.os.makedirs"),
        patch(f"{_MODULE}.get_api_key", return_value="openai-test-key"),
        patch(f"{_MODULE}.get_anthropic_api_key", return_value="anthropic-test-key"),
        patch(f"{_MODULE}._create_llm", return_value=MagicMock()),
        patch(f"{_MODULE}.Toolkit"),
        patch(f"{_MODULE}.FinancialSituationMemory"),
        patch(f"{_MODULE}.ConditionalLogic"),
        patch(f"{_MODULE}.GraphSetup"),
        patch(f"{_MODULE}.Propagator"),
        patch(f"{_MODULE}.Reflector"),
        patch(f"{_MODULE}.SignalProcessor"),
        patch(f"{_MODULE}.get_debate_rounds_from_depth", return_value=(3, 3)),
    ]
    if extra_patches:
        patches.extend(extra_patches)
    return patches


class _MultiPatch:
    def __init__(self, patch_list):
        self._patches = patch_list
        self._mocks = []

    def __enter__(self):
        self._mocks = [p.start() for p in self._patches]
        return self._mocks

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


def _make_graph(config=None):
    """Instantiate a TradingAgentsGraph with all heavy deps mocked."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    cfg = config or _base_config()
    patches = _all_patches()
    mocks = [p.start() for p in patches]
    ctn_patch = patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={})
    ctn_patch.start()
    graph = TradingAgentsGraph(config=cfg)
    return graph, patches, ctn_patch


def _stop_patches(patches, ctn_patch):
    for p in patches:
        try:
            p.stop()
        except RuntimeError:
            pass
    try:
        ctn_patch.stop()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# 1. _get_rate_limit_error_types() must not raise NameError when tenacity absent
# ---------------------------------------------------------------------------

class TestGetRateLimitErrorTypesNoTenacity:
    """_get_rate_limit_error_types() should work regardless of tenacity availability."""

    def test_no_name_error_without_tenacity(self):
        """
        Simulate an environment where tenacity was NOT importable.

        The module-level guard sets TENACITY_AVAILABLE=False and defines no-op
        shims. _get_rate_limit_error_types() must still return a tuple without
        raising NameError or any other error.
        """
        import tradingagents.graph.trading_graph as tg

        # Temporarily pretend tenacity is absent by patching the flag
        original_flag = tg.TENACITY_AVAILABLE
        try:
            tg.TENACITY_AVAILABLE = False
            # This call must not raise NameError or any exception
            result = tg._get_rate_limit_error_types()
            assert isinstance(result, tuple), (
                f"Expected a tuple, got {type(result)}"
            )
            # Must always return at least one error type as a fallback
            assert len(result) >= 1, "Expected at least one error type in tuple"
        finally:
            tg.TENACITY_AVAILABLE = original_flag

    def test_returns_tuple_with_tenacity_present(self):
        """When tenacity IS available, result is still a non-empty tuple."""
        import tradingagents.graph.trading_graph as tg

        result = tg._get_rate_limit_error_types()
        assert isinstance(result, tuple)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# 2. _log_state() sanitizes '/' in crypto tickers to '_'
# ---------------------------------------------------------------------------

def _make_minimal_final_state(ticker="BTC/USD"):
    """Return a minimal final-state dict compatible with _log_state."""
    return {
        "company_of_interest": ticker,
        "trade_date": "2024-01-01",
        "market_report": "market",
        "sentiment_report": "sentiment",
        "news_report": "news",
        "fundamentals_report": "fundamentals",
        "investment_debate_state": {
            "bull_history": [],
            "bear_history": [],
            "history": [],
            "current_response": "",
            "judge_decision": "",
        },
        "trader_investment_plan": "plan",
        "risk_debate_state": {
            "risky_history": [],
            "safe_history": [],
            "neutral_history": [],
            "history": [],
            "judge_decision": "",
        },
        "investment_plan": "invest",
        "final_trade_decision": "BUY",
    }


class TestLogStateCryptoTickerPath:
    """_log_state must sanitize '/' in ticker symbols when building file paths."""

    def test_log_state_crypto_ticker_path(self, tmp_path):
        """BTC/USD ticker must produce BTC_USD in the filesystem path, not BTC/USD."""
        graph, patches, ctn_patch = _make_graph()
        try:
            graph.ticker = "BTC/USD"
            final_state = _make_minimal_final_state("BTC/USD")

            # Redirect eval_results writes to a temp directory
            with patch(f"{_MODULE}._cleanup_old_eval_results"):
                with patch(f"{_MODULE}.Path") as mock_path_cls:
                    # Capture the directory argument
                    captured_dirs = []

                    def fake_path(arg):
                        captured_dirs.append(str(arg))
                        real = Path(tmp_path / str(arg).lstrip("/"))
                        real.mkdir(parents=True, exist_ok=True)
                        m = MagicMock(spec=Path)
                        m.__str__ = lambda self: str(real)
                        m.mkdir = MagicMock()
                        return m

                    mock_path_cls.side_effect = fake_path

                    with patch("builtins.open", mock_open()):
                        with patch(f"{_MODULE}.json.dump"):
                            graph._log_state("2024-01-01", final_state)

            # At least one captured directory path must use BTC_USD
            assert any("BTC_USD" in d for d in captured_dirs), (
                f"Expected 'BTC_USD' in path but captured: {captured_dirs}"
            )
            # Must NOT have a raw slash in any of the captured paths
            assert not any("BTC/USD" in d for d in captured_dirs), (
                f"Found unsanitized 'BTC/USD' in path: {captured_dirs}"
            )
        finally:
            _stop_patches(patches, ctn_patch)

    def test_log_state_stock_ticker_path_unchanged(self, tmp_path):
        """Stock tickers without '/' must be used as-is in the path."""
        graph, patches, ctn_patch = _make_graph()
        try:
            graph.ticker = "NVDA"
            final_state = _make_minimal_final_state("NVDA")

            with patch(f"{_MODULE}._cleanup_old_eval_results"):
                with patch(f"{_MODULE}.Path") as mock_path_cls:
                    captured_dirs = []

                    def fake_path(arg):
                        captured_dirs.append(str(arg))
                        real = Path(tmp_path / str(arg).lstrip("/"))
                        real.mkdir(parents=True, exist_ok=True)
                        m = MagicMock(spec=Path)
                        m.__str__ = lambda self: str(real)
                        m.mkdir = MagicMock()
                        return m

                    mock_path_cls.side_effect = fake_path
                    with patch("builtins.open", mock_open()):
                        with patch(f"{_MODULE}.json.dump"):
                            graph._log_state("2024-01-01", final_state)

            assert any("NVDA" in d for d in captured_dirs), (
                f"Expected 'NVDA' in path but captured: {captured_dirs}"
            )
        finally:
            _stop_patches(patches, ctn_patch)


# ---------------------------------------------------------------------------
# 3. _log_state() evicts the entry from log_states_dict after writing to disk
# ---------------------------------------------------------------------------

class TestLogStatesDictEviction:
    """After _log_state writes to disk the entry must be removed from log_states_dict."""

    def test_log_states_dict_eviction(self, tmp_path):
        """Entry for the trade date must NOT remain in log_states_dict after _log_state."""
        graph, patches, ctn_patch = _make_graph()
        try:
            graph.ticker = "AAPL"
            trade_date = "2024-06-15"
            final_state = _make_minimal_final_state("AAPL")

            with patch(f"{_MODULE}._cleanup_old_eval_results"):
                with patch(f"{_MODULE}.Path") as mock_path_cls:
                    def fake_path(arg):
                        real = Path(tmp_path / str(arg).lstrip("/"))
                        real.mkdir(parents=True, exist_ok=True)
                        m = MagicMock(spec=Path)
                        m.__str__ = lambda self: str(real)
                        m.mkdir = MagicMock()
                        return m

                    mock_path_cls.side_effect = fake_path
                    with patch("builtins.open", mock_open()):
                        with patch(f"{_MODULE}.json.dump"):
                            graph._log_state(trade_date, final_state)

            assert trade_date not in graph.log_states_dict, (
                f"Expected '{trade_date}' to be evicted from log_states_dict "
                f"but it is still present: {list(graph.log_states_dict.keys())}"
            )
        finally:
            _stop_patches(patches, ctn_patch)

    def test_log_states_dict_starts_empty_after_single_write(self, tmp_path):
        """log_states_dict must be empty after a single _log_state call."""
        graph, patches, ctn_patch = _make_graph()
        try:
            graph.ticker = "TSLA"
            final_state = _make_minimal_final_state("TSLA")

            with patch(f"{_MODULE}._cleanup_old_eval_results"):
                with patch(f"{_MODULE}.Path") as mock_path_cls:
                    def fake_path(arg):
                        real = Path(tmp_path / str(arg).lstrip("/"))
                        real.mkdir(parents=True, exist_ok=True)
                        m = MagicMock(spec=Path)
                        m.__str__ = lambda self: str(real)
                        m.mkdir = MagicMock()
                        return m

                    mock_path_cls.side_effect = fake_path
                    with patch("builtins.open", mock_open()):
                        with patch(f"{_MODULE}.json.dump"):
                            graph._log_state("2024-01-01", final_state)

            assert len(graph.log_states_dict) == 0, (
                f"Expected empty log_states_dict after eviction, "
                f"but has {len(graph.log_states_dict)} entries"
            )
        finally:
            _stop_patches(patches, ctn_patch)
