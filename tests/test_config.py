"""
tests/test_config.py

TDD tests for validate_required_env_vars() in tradingagents/dataflows/config.py.

Key behaviors under test:
  - Missing env vars produce WARNING log messages (not exceptions).
  - The function returns the list of missing variable names.
  - When all vars are present, no warnings are logged and an empty list is returned.
"""

import logging
import os
from unittest.mock import patch

import pytest


_CONFIG_MODULE = "tradingagents.dataflows.config"

# The exact list of vars the function checks (mirrors source)
REQUIRED_VARS = [
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "OPENAI_API_KEY",
    "FINNHUB_API_KEY",
    "FRED_API_KEY",
]


# ---------------------------------------------------------------------------
# Helper: build a clean env dict with none of the required vars set
# ---------------------------------------------------------------------------

def _env_without_required():
    """Return a copy of os.environ with all required vars removed."""
    env = os.environ.copy()
    for var in REQUIRED_VARS:
        env.pop(var, None)
    return env


def _env_with_all_required():
    """Return a copy of os.environ with all required vars set to dummy values."""
    env = os.environ.copy()
    for var in REQUIRED_VARS:
        env[var] = "dummy-value"
    return env


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateRequiredEnvVars:

    def test_validate_missing_keys_logs_warning(self, caplog):
        """
        When required env vars are absent, validate_required_env_vars() must log
        a WARNING for each missing variable and must NOT raise an exception.
        """
        from tradingagents.dataflows.config import validate_required_env_vars

        with patch.dict(os.environ, _env_without_required(), clear=False):
            # Remove any previously set required vars
            for var in REQUIRED_VARS:
                os.environ.pop(var, None)

            with caplog.at_level(logging.WARNING, logger=_CONFIG_MODULE):
                missing = validate_required_env_vars()

        assert isinstance(missing, list), "Expected a list return value"
        assert len(missing) > 0, "Expected at least one missing variable"

        # Each missing var must have triggered a WARNING log record
        warning_text = " ".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
        for var in missing:
            assert var in warning_text, (
                f"Expected WARNING for '{var}' but it was not found in log output"
            )

    def test_validate_does_not_raise_on_missing_vars(self):
        """
        validate_required_env_vars() must never raise an exception, even when
        all required vars are absent.
        """
        from tradingagents.dataflows.config import validate_required_env_vars

        env_without = {var: "" for var in REQUIRED_VARS}
        with patch.dict(os.environ, env_without, clear=False):
            for var in REQUIRED_VARS:
                os.environ.pop(var, None)

            # Must not raise
            try:
                missing = validate_required_env_vars()
            except Exception as exc:
                pytest.fail(
                    f"validate_required_env_vars() raised an unexpected exception: {exc}"
                )

    def test_validate_returns_missing_var_names(self):
        """
        The return value must be a list containing the names of the missing vars.
        """
        from tradingagents.dataflows.config import validate_required_env_vars

        with patch.dict(os.environ, {}, clear=False):
            for var in REQUIRED_VARS:
                os.environ.pop(var, None)

            missing = validate_required_env_vars()

        for var in REQUIRED_VARS:
            assert var in missing, (
                f"Expected '{var}' in missing list but it was absent: {missing}"
            )

    def test_validate_returns_empty_list_when_all_present(self, caplog):
        """
        When all required env vars are set, the function must return an empty
        list and must NOT emit any warnings.
        """
        from tradingagents.dataflows.config import validate_required_env_vars

        dummy_env = {var: "dummy-value-for-testing" for var in REQUIRED_VARS}
        with patch.dict(os.environ, dummy_env, clear=False):
            with caplog.at_level(logging.WARNING, logger=_CONFIG_MODULE):
                missing = validate_required_env_vars()

        assert missing == [], (
            f"Expected empty list when all vars present but got: {missing}"
        )

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 0, (
            f"Expected no warnings but got: {[r.message for r in warning_records]}"
        )

    def test_validate_partial_missing_returns_only_missing(self):
        """
        When some vars are set and some are not, only the missing names must be
        in the returned list.
        """
        from tradingagents.dataflows.config import validate_required_env_vars

        # Set only the first two required vars
        present_vars = REQUIRED_VARS[:2]
        missing_vars = REQUIRED_VARS[2:]

        env_patch = {var: "dummy" for var in present_vars}
        with patch.dict(os.environ, env_patch, clear=False):
            for var in missing_vars:
                os.environ.pop(var, None)

            missing = validate_required_env_vars()

        for var in missing_vars:
            assert var in missing, f"Expected '{var}' in missing list: {missing}"
        for var in present_vars:
            assert var not in missing, f"Did not expect '{var}' in missing list: {missing}"
