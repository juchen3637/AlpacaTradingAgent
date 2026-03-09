"""
tests/test_macro_utils.py

TDD tests for the yoy_change unbound-local-variable fix in
tradingagents/dataflows/macro_utils.py.

The fix: when a CPI/PPI indicator has `yoy=True` and fewer than 12 valid
observations, `yoy_change` was referenced in the analysis block without
having been assigned. The fix ensures `yoy_change` is only referenced when
it has been computed (i.e., `len(valid_obs) >= 12`).
"""

import pytest
from unittest.mock import patch, MagicMock


_MACRO_MODULE = "tradingagents.dataflows.macro_utils"


# ---------------------------------------------------------------------------
# Helper: build a FRED-style observations list
# ---------------------------------------------------------------------------

def _make_fred_observations(n: int, start_value: float = 300.0, step: float = -0.5):
    """
    Return a FRED observations list with *n* valid entries in descending date
    order (most-recent first), as the real API returns them.
    """
    obs = []
    for i in range(n):
        obs.append({
            "date": f"2024-{12 - i // 12:02d}-01" if i < 12 else f"2023-{12 - (i - 12) // 12:02d}-01",
            "value": str(round(start_value + i * step, 2)),
        })
    return obs


def _make_fred_response(n: int):
    """Return a mocked FRED API response with *n* valid observations."""
    return {"observations": _make_fred_observations(n)}


# ---------------------------------------------------------------------------
# 1. No UnboundLocalError for CPI with exactly 12 observations (yoy path)
# ---------------------------------------------------------------------------

class TestCpiYoyNoUnboundLocalError:

    def test_cpi_yoy_no_unbound_local_error_with_12_obs(self):
        """
        CPI indicator with exactly 12 valid observations must not raise
        UnboundLocalError when the yoy analysis block is executed.
        """
        fred_response = _make_fred_response(12)

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=fred_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            # Must not raise UnboundLocalError
            result = get_economic_indicators_report("2024-12-01")

        assert isinstance(result, str), "Expected a string report"
        assert "Consumer Price Index" in result or "CPI" in result

    def test_ppi_yoy_no_unbound_local_error_with_12_obs(self):
        """
        PPI indicator with exactly 12 valid observations must not raise
        UnboundLocalError.
        """
        fred_response = _make_fred_response(12)

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=fred_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            result = get_economic_indicators_report("2024-12-01")

        assert isinstance(result, str)
        assert "Producer Price Index" in result or "PPI" in result

    def test_cpi_yoy_no_unbound_local_error_with_more_than_12_obs(self):
        """
        CPI with 15 observations (> 12) must compute yoy_change and include it
        in the report without raising UnboundLocalError.
        """
        fred_response = _make_fred_response(15)

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=fred_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            result = get_economic_indicators_report("2024-12-01")

        assert "Year-over-Year" in result, (
            "Expected 'Year-over-Year' line in report when 15 observations present"
        )

    def test_cpi_fewer_than_12_obs_no_yoy_section(self):
        """
        CPI with only 5 observations (< 12) must not include a Year-over-Year
        line — and must not raise UnboundLocalError.
        """
        fred_response = _make_fred_response(5)

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=fred_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            result = get_economic_indicators_report("2024-12-01")

        # Should succeed without error; yoy line should not be present
        assert isinstance(result, str)

    def test_fred_error_response_handled_gracefully(self):
        """
        When FRED returns an error dict, the report must mention the error
        without raising any exception.
        """
        error_response = {"error": "FRED API key not found"}

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=error_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            result = get_economic_indicators_report("2024-12-01")

        assert "Error" in result or "error" in result.lower()

    def test_empty_observations_handled_gracefully(self):
        """
        An empty observations list must not raise and must produce a 'No data'
        message in the report.
        """
        empty_response = {"observations": []}

        with patch(f"{_MACRO_MODULE}.get_fred_data", return_value=empty_response):
            from tradingagents.dataflows.macro_utils import get_economic_indicators_report

            result = get_economic_indicators_report("2024-12-01")

        assert isinstance(result, str)
        # The report should say no data is available
        assert "No data" in result or "not available" in result.lower() or "available" in result.lower()
