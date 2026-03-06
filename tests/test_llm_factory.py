"""Unit tests for _create_llm and _get_rate_limit_error_types in trading_graph.py."""

import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_factory():
    """Re-import symbols so patches applied to sys.modules take effect."""
    from tradingagents.graph.trading_graph import _create_llm, _get_rate_limit_error_types
    return _create_llm, _get_rate_limit_error_types


# ---------------------------------------------------------------------------
# _create_llm — OpenAI path
# ---------------------------------------------------------------------------

class TestCreateLlmOpenAI:
    def test_create_llm_openai_returns_chatopenai(self):
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_cls):
            _create_llm, _ = _import_factory()
            result = _create_llm("gpt-4o", "openai", "sk-test")

        mock_cls.assert_called_once()
        assert result is mock_instance

    def test_create_llm_openai_model_name_passed(self):
        mock_cls = MagicMock()

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_cls):
            _create_llm, _ = _import_factory()
            _create_llm("gpt-4o", "openai", "sk-test")

        _, kwargs = mock_cls.call_args
        assert kwargs["model"] == "gpt-4o"

    def test_create_llm_openai_with_temperature(self):
        """Regular models (e.g. gpt-4o) receive temperature=0.2."""
        mock_cls = MagicMock()

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_cls):
            _create_llm, _ = _import_factory()
            _create_llm("gpt-4o", "openai", "sk-test")

        _, kwargs = mock_cls.call_args
        assert kwargs.get("temperature") == 0.2

    def test_create_llm_openai_no_temperature_for_o3(self):
        """o3 model must NOT receive the temperature parameter."""
        mock_cls = MagicMock()

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_cls):
            _create_llm, _ = _import_factory()
            _create_llm("o3", "openai", "sk-test")

        _, kwargs = mock_cls.call_args
        assert "temperature" not in kwargs

    def test_create_llm_openai_no_temperature_for_gpt5_models(self):
        """gpt-5, gpt-5-mini, gpt-5-nano must NOT receive the temperature parameter."""
        mock_cls = MagicMock()

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_cls):
            _create_llm, _ = _import_factory()
            for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
                mock_cls.reset_mock()
                _create_llm(model, "openai", "sk-test")
                _, kwargs = mock_cls.call_args
                assert "temperature" not in kwargs, f"temperature should be absent for {model}"

    def test_create_llm_unknown_provider_defaults_to_openai(self):
        """Unrecognised provider string falls back to ChatOpenAI."""
        mock_chatopenai = MagicMock()

        with patch("tradingagents.graph.trading_graph.ChatOpenAI", mock_chatopenai):
            _create_llm, _ = _import_factory()
            _create_llm("gpt-4o", "unknown-provider", "sk-test")

        mock_chatopenai.assert_called_once()


# ---------------------------------------------------------------------------
# _create_llm — Anthropic path
# ---------------------------------------------------------------------------

class TestCreateLlmAnthropic:
    def test_create_llm_anthropic_returns_chatanthropic(self):
        mock_instance = MagicMock()
        mock_cls = MagicMock(return_value=mock_instance)
        mock_lc_anthropic = MagicMock()
        mock_lc_anthropic.ChatAnthropic = mock_cls

        with patch.dict(sys.modules, {"langchain_anthropic": mock_lc_anthropic}):
            _create_llm, _ = _import_factory()
            result = _create_llm("claude-opus-4-6", "anthropic", "ant-key")

        mock_cls.assert_called_once_with(
            model="claude-opus-4-6", api_key="ant-key", temperature=0.2
        )
        assert result is mock_instance


# ---------------------------------------------------------------------------
# _get_rate_limit_error_types
# ---------------------------------------------------------------------------

class TestGetRateLimitErrorTypes:
    def test_get_rate_limit_error_types_includes_openai(self):
        """When tenacity is available, openai.RateLimitError must be in the tuple."""
        FakeOpenAIRateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai = MagicMock()
        mock_openai.RateLimitError = FakeOpenAIRateLimitError

        with patch("tradingagents.graph.trading_graph.TENACITY_AVAILABLE", True), \
             patch("tradingagents.graph.trading_graph.openai", mock_openai), \
             patch("tradingagents.graph.trading_graph._ANTHROPIC_RATE_LIMIT_ERROR", None):
            _, _get_rate_limit_error_types = _import_factory()
            result = _get_rate_limit_error_types()

        assert FakeOpenAIRateLimitError in result

    def test_get_rate_limit_error_types_includes_anthropic(self):
        """When anthropic is installed, its RateLimitError must be in the tuple."""
        FakeOpenAIRateLimitError = type("RateLimitError", (Exception,), {})
        FakeAnthropicRateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai = MagicMock()
        mock_openai.RateLimitError = FakeOpenAIRateLimitError

        with patch("tradingagents.graph.trading_graph.TENACITY_AVAILABLE", True), \
             patch("tradingagents.graph.trading_graph.openai", mock_openai), \
             patch("tradingagents.graph.trading_graph._ANTHROPIC_RATE_LIMIT_ERROR", FakeAnthropicRateLimitError):
            _, _get_rate_limit_error_types = _import_factory()
            result = _get_rate_limit_error_types()

        assert FakeAnthropicRateLimitError in result

    def test_get_rate_limit_error_types_fallback_when_tenacity_unavailable(self):
        """When tenacity is unavailable the result should contain Exception as fallback."""
        with patch("tradingagents.graph.trading_graph.TENACITY_AVAILABLE", False), \
             patch("tradingagents.graph.trading_graph._ANTHROPIC_RATE_LIMIT_ERROR", None):
            _, _get_rate_limit_error_types = _import_factory()
            result = _get_rate_limit_error_types()

        assert result == (Exception,)


# ---------------------------------------------------------------------------
# invoke_llm_with_retry
# ---------------------------------------------------------------------------

class TestInvokeLlmWithRetry:
    def test_direct_invoke_when_tenacity_unavailable(self):
        """When tenacity is not available, llm.invoke is called directly."""
        from tradingagents.graph.trading_graph import invoke_llm_with_retry

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "response"

        with patch("tradingagents.graph.trading_graph.TENACITY_AVAILABLE", False):
            result = invoke_llm_with_retry(mock_llm, ["msg"])

        mock_llm.invoke.assert_called_once_with(["msg"])
        assert result == "response"

    def test_retry_invoke_when_tenacity_available(self):
        """When tenacity is available, llm.invoke is still called and returns a value."""
        from tradingagents.graph.trading_graph import invoke_llm_with_retry

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "retry-response"

        FakeOpenAIRateLimitError = type("RateLimitError", (Exception,), {})
        mock_openai = MagicMock()
        mock_openai.RateLimitError = FakeOpenAIRateLimitError

        with patch("tradingagents.graph.trading_graph.TENACITY_AVAILABLE", True), \
             patch("tradingagents.graph.trading_graph.openai", mock_openai), \
             patch("tradingagents.graph.trading_graph._ANTHROPIC_RATE_LIMIT_ERROR", None):
            result = invoke_llm_with_retry(mock_llm, ["msg"], max_attempts=1)

        mock_llm.invoke.assert_called_once_with(["msg"])
        assert result == "retry-response"


# ---------------------------------------------------------------------------
# get_debate_rounds_from_depth
# ---------------------------------------------------------------------------

class TestGetDebateRoundsFromDepth:
    def _fn(self):
        from tradingagents.graph.trading_graph import get_debate_rounds_from_depth
        return get_debate_rounds_from_depth

    def test_shallow_returns_one_round(self):
        assert self._fn()("shallow") == (1, 1)

    def test_medium_returns_three_rounds(self):
        assert self._fn()("medium") == (3, 3)

    def test_deep_returns_five_rounds(self):
        assert self._fn()("deep") == (5, 5)

    def test_case_insensitive(self):
        fn = self._fn()
        assert fn("Shallow") == (1, 1)
        assert fn("Medium") == (3, 3)
        assert fn("Deep") == (5, 5)

    def test_invalid_depth_defaults_to_medium(self):
        assert self._fn()("extreme") == (3, 3)
