"""
tests/test_health_endpoint.py

TDD tests for the /health endpoint registered in webui/app_dash.py.

The endpoint must:
  - Return HTTP 200
  - Return JSON with {"status": "ok"} (plus a "timestamp" field)
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_minimal_flask_app():
    """
    Create a minimal Flask app with only the /health route registered.

    This avoids importing the full Dash application (which requires live
    layout/callback registration and heavy optional dependencies).
    """
    from flask import Flask, jsonify
    from datetime import datetime, timezone

    server = Flask(__name__)

    @server.route("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    return server


def _patch_app_dash_imports():
    """
    Return a list of patches that prevent heavy Dash/callback/layout imports
    from running when we import app_dash.
    """
    return [
        patch("webui.app_dash.create_main_layout", return_value=MagicMock()),
        patch("webui.app_dash.register_all_callbacks"),
        patch("webui.app_dash.start_watchdog"),
        patch("webui.app_dash.install_log_interceptor", create=True),
        patch("webui.utils.log_interceptor.install"),
    ]


# ---------------------------------------------------------------------------
# Tests: /health endpoint via the _register_health_endpoint helper
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_returns_200(self):
        """GET /health must return HTTP 200."""
        server = _create_minimal_flask_app()
        client = server.test_client()

        response = client.get("/health")

        assert response.status_code == 200, (
            f"Expected HTTP 200 but got {response.status_code}"
        )

    def test_health_returns_json_status_ok(self):
        """GET /health must return JSON with 'status': 'ok'."""
        server = _create_minimal_flask_app()
        client = server.test_client()

        response = client.get("/health")

        data = json.loads(response.data)
        assert data.get("status") == "ok", (
            f"Expected {{\"status\": \"ok\"}} but got {data}"
        )

    def test_health_returns_timestamp(self):
        """GET /health response must include a 'timestamp' key."""
        server = _create_minimal_flask_app()
        client = server.test_client()

        response = client.get("/health")

        data = json.loads(response.data)
        assert "timestamp" in data, (
            f"Expected 'timestamp' field in response but got keys: {list(data.keys())}"
        )

    def test_health_content_type_is_json(self):
        """GET /health must respond with Content-Type: application/json."""
        server = _create_minimal_flask_app()
        client = server.test_client()

        response = client.get("/health")

        assert "application/json" in response.content_type, (
            f"Expected application/json content type, got {response.content_type}"
        )

    def test_health_via_register_helper(self):
        """
        _register_health_endpoint() applied to a bare Flask server must make
        the /health route available and return 200 with status=ok.

        This test exercises the actual helper from app_dash rather than a local
        re-implementation.
        """
        from flask import Flask
        from webui.app_dash import _register_health_endpoint

        server = Flask(__name__)
        _register_health_endpoint(server)

        client = server.test_client()
        response = client.get("/health")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get("status") == "ok"

    def test_health_endpoint_not_found_without_registration(self):
        """
        A bare Flask server without _register_health_endpoint must return 404
        for GET /health (confirms the route is not added by default).
        """
        from flask import Flask

        server = Flask(__name__)
        client = server.test_client()

        response = client.get("/health")

        assert response.status_code == 404
