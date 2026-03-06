"""Unit tests for get_anthropic_api_key and DEFAULT_CONFIG Anthropic additions."""

import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# get_anthropic_api_key
# ---------------------------------------------------------------------------

class TestGetAnthropicApiKey:
    def test_get_anthropic_api_key_from_env(self, monkeypatch):
        """ANTHROPIC_API_KEY env var is returned when set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-ant-key")

        import tradingagents.dataflows.config as cfg_module
        # Clear any cached config so env var is the only source
        with patch.object(cfg_module, "_config", None):
            from tradingagents.dataflows.config import get_anthropic_api_key
            result = get_anthropic_api_key()

        assert result == "env-ant-key"

    def test_get_anthropic_api_key_falls_back_to_config(self, monkeypatch):
        """Falls back to _config dict when env var is absent."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        import tradingagents.dataflows.config as cfg_module
        fake_config = {"anthropic_api_key": "config-ant-key"}
        with patch.object(cfg_module, "_config", fake_config):
            from tradingagents.dataflows.config import get_anthropic_api_key
            result = get_anthropic_api_key()

        assert result == "config-ant-key"

    def test_get_anthropic_api_key_returns_none_when_unset(self, monkeypatch):
        """Returns None when neither env var nor _config contains the key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        import tradingagents.dataflows.config as cfg_module
        with patch.object(cfg_module, "_config", None):
            from tradingagents.dataflows.config import get_anthropic_api_key
            result = get_anthropic_api_key()

        assert result is None

    def test_get_anthropic_api_key_env_takes_precedence_over_config(self, monkeypatch):
        """Env var takes precedence over _config value."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-wins")

        import tradingagents.dataflows.config as cfg_module
        fake_config = {"anthropic_api_key": "config-loses"}
        with patch.object(cfg_module, "_config", fake_config):
            from tradingagents.dataflows.config import get_anthropic_api_key
            result = get_anthropic_api_key()

        assert result == "env-wins"


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def setup_method(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        self.cfg = DEFAULT_CONFIG

    def test_default_config_has_llm_provider(self):
        assert self.cfg.get("llm_provider") == "openai"

    def test_default_config_has_anthropic_models(self):
        assert "anthropic_deep_think_llm" in self.cfg
        assert "anthropic_quick_think_llm" in self.cfg
        assert self.cfg["anthropic_deep_think_llm"]   # non-empty string
        assert self.cfg["anthropic_quick_think_llm"]   # non-empty string

    def test_default_config_has_anthropic_api_key(self):
        """Key must be present; value may be None (populated via env var)."""
        assert "anthropic_api_key" in self.cfg


# ---------------------------------------------------------------------------
# get_config / set_config
# ---------------------------------------------------------------------------

class TestGetSetConfig:
    def test_get_config_initializes_when_none(self):
        """get_config triggers initialize_config when _config is None."""
        import tradingagents.dataflows.config as cfg_module
        with patch.object(cfg_module, "_config", None):
            result = cfg_module.get_config()
        # Should return a dict with at least the default keys
        assert isinstance(result, dict)
        assert "llm_provider" in result

    def test_set_config_updates_existing_keys(self):
        """set_config merges new values into existing _config."""
        import tradingagents.dataflows.config as cfg_module
        original = cfg_module._config.copy() if cfg_module._config else {}
        cfg_module.set_config({"llm_provider": "anthropic"})
        assert cfg_module._config["llm_provider"] == "anthropic"
        # Restore
        cfg_module.set_config(original)

    def test_set_config_initializes_when_none(self):
        """set_config handles the case where _config starts as None."""
        import tradingagents.dataflows.config as cfg_module
        with patch.object(cfg_module, "_config", None):
            cfg_module.set_config({"llm_provider": "openai"})
            assert cfg_module._config["llm_provider"] == "openai"


# ---------------------------------------------------------------------------
# Convenience wrapper functions
# ---------------------------------------------------------------------------

class TestApiKeyWrappers:
    def test_get_openai_api_key_reads_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "openai-val")
        from tradingagents.dataflows.config import get_openai_api_key
        assert get_openai_api_key() == "openai-val"

    def test_get_finnhub_api_key_reads_env(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "finnhub-val")
        from tradingagents.dataflows.config import get_finnhub_api_key
        assert get_finnhub_api_key() == "finnhub-val"
