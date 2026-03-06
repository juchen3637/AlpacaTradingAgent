"""Unit tests for provider-selection logic in TradingAgentsGraph.__init__."""

import copy
import os
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Minimal config helpers
# ---------------------------------------------------------------------------

def _base_config(**overrides):
    """Return a minimal config dict that won't crash TradingAgentsGraph.__init__."""
    from tradingagents.default_config import DEFAULT_CONFIG
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Context manager that patches all heavy dependencies inside __init__
# so tests can focus purely on the provider-selection logic.
# ---------------------------------------------------------------------------

_MODULE = "tradingagents.graph.trading_graph"


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
    """Helper to start/stop a list of patch objects as a context manager."""

    def __init__(self, patch_list):
        self._patches = patch_list
        self._mocks = []

    def __enter__(self):
        self._mocks = [p.start() for p in self._patches]
        return self._mocks

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


def _build_graph(config):
    """Instantiate TradingAgentsGraph with all deps mocked; return (graph, mocks)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    patches = _all_patches()
    with _MultiPatch(patches) as mocks:
        # Patch _create_tool_nodes at the instance level via the class
        with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
            graph = TradingAgentsGraph(config=config)
        # Capture the mocks we care about by name for assertions
        return graph, {
            "set_config": mocks[0],
            "makedirs": mocks[1],
            "get_api_key": mocks[2],
            "get_anthropic_api_key": mocks[3],
            "_create_llm": mocks[4],
        }


# ---------------------------------------------------------------------------
# Provider-selection tests
# ---------------------------------------------------------------------------

class TestProviderSelection:
    def test_openai_provider_uses_openai_api_key(self):
        """llm_provider='openai' → get_api_key called with OPENAI_API_KEY env var name."""
        config = _base_config(llm_provider="openai")
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_get_api_key = mocks[2]
            mock_get_anthropic_api_key = mocks[3]
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        mock_get_api_key.assert_called_once_with("openai_api_key", "OPENAI_API_KEY")
        mock_get_anthropic_api_key.assert_not_called()

    def test_anthropic_provider_uses_anthropic_api_key(self):
        """llm_provider='anthropic' → get_anthropic_api_key is called."""
        config = _base_config(llm_provider="anthropic")
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_get_api_key = mocks[2]
            mock_get_anthropic_api_key = mocks[3]
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        mock_get_anthropic_api_key.assert_called_once()
        # get_api_key should NOT be called with OpenAI credentials
        for c in mock_get_api_key.call_args_list:
            assert "OPENAI_API_KEY" not in c.args, "openai key fetched for anthropic provider"

    def test_anthropic_provider_uses_configured_models(self):
        """When provider=anthropic, anthropic_*_llm keys are forwarded to _create_llm."""
        config = _base_config(
            llm_provider="anthropic",
            anthropic_deep_think_llm="claude-opus-configured",
            anthropic_quick_think_llm="claude-haiku-configured",
        )
        # Remove override keys so __init__ uses anthropic_ prefixed keys
        config.pop("deep_think_llm", None)
        config.pop("quick_think_llm", None)
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_create_llm = mocks[4]
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        called_models = [c.args[0] for c in mock_create_llm.call_args_list]
        assert "claude-opus-configured" in called_models
        assert "claude-haiku-configured" in called_models

    def test_openai_provider_creates_chatopenai_llms(self):
        """_create_llm is invoked with provider='openai' for both LLMs."""
        config = _base_config(llm_provider="openai")
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_create_llm = mocks[4]
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        called_providers = [c.args[1] for c in mock_create_llm.call_args_list]
        assert all(p == "openai" for p in called_providers), (
            f"Expected all calls with provider='openai', got {called_providers}"
        )

    def test_legacy_debate_rounds_config_used_when_set(self):
        """When max_debate_rounds is set explicitly, get_debate_rounds_from_depth is NOT called."""
        config = _base_config(
            llm_provider="openai",
            max_debate_rounds=2,
            max_risk_discuss_rounds=2,
        )
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_depth_fn = mocks[-1]  # get_debate_rounds_from_depth is last
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        mock_depth_fn.assert_not_called()

    def test_anthropic_provider_creates_chatanthropic_llms(self):
        """_create_llm is invoked with provider='anthropic' for both LLMs."""
        config = _base_config(llm_provider="anthropic")
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        patches = _all_patches()
        with _MultiPatch(patches) as mocks:
            mock_create_llm = mocks[4]
            with patch.object(TradingAgentsGraph, "_create_tool_nodes", return_value={}):
                TradingAgentsGraph(config=config)

        called_providers = [c.args[1] for c in mock_create_llm.call_args_list]
        assert all(p == "anthropic" for p in called_providers), (
            f"Expected all calls with provider='anthropic', got {called_providers}"
        )


# ---------------------------------------------------------------------------
# Instance method smoke tests (keep patches live while calling methods)
# ---------------------------------------------------------------------------

class TestInstanceMethods:
    def _make_graph(self, config=None):
        """Build a fully-mocked TradingAgentsGraph and return it with patches still active."""
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        cfg = config or _base_config()
        self._patch_objs = _all_patches()
        self._mocks = [p.start() for p in self._patch_objs]
        self._create_tool_nodes_patch = patch.object(
            TradingAgentsGraph, "_create_tool_nodes", return_value={}
        )
        self._create_tool_nodes_patch.start()
        graph = TradingAgentsGraph(config=cfg)
        return graph

    def teardown_method(self):
        for p in getattr(self, "_patch_objs", []):
            p.stop()
        if hasattr(self, "_create_tool_nodes_patch"):
            self._create_tool_nodes_patch.stop()

    def test_process_signal_delegates_to_signal_processor(self):
        graph = self._make_graph()
        graph.signal_processor.process_signal.return_value = "BUY"
        result = graph.process_signal("BUY: strong momentum")
        graph.signal_processor.process_signal.assert_called_once_with("BUY: strong momentum")
        assert result == "BUY"

    def test_reflect_and_remember_calls_all_reflector_methods(self):
        graph = self._make_graph()
        graph.curr_state = {"some": "state"}
        graph.reflect_and_remember(0.05)

        graph.reflector.reflect_bull_researcher.assert_called_once()
        graph.reflector.reflect_bear_researcher.assert_called_once()
        graph.reflector.reflect_trader.assert_called_once()
        graph.reflector.reflect_invest_judge.assert_called_once()
        graph.reflector.reflect_risk_manager.assert_called_once()
