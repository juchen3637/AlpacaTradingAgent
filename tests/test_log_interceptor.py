"""
tests/test_log_interceptor.py

TDD tests for the ring-buffer cap in webui/utils/log_interceptor.py.

The LogInterceptor must cap app_state.system_logs at exactly _MAX_LOGS=1000
entries, dropping the oldest entry before appending when the cap is reached.
"""

import sys
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_state(initial_logs=None):
    """Return a minimal app_state-like object with a system_logs list."""
    state = SimpleNamespace()
    state.system_logs = list(initial_logs) if initial_logs else []
    state.analyzing_symbol = "TEST"
    return state


def _write_tagged_line(interceptor, tag, message):
    """Write a single [TAG] prefixed log line through the interceptor."""
    interceptor.write(f"[{tag}] {message}\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRingBufferCap:

    def test_ring_buffer_max_1000(self):
        """
        Writing 1001 tagged log lines must result in exactly 1000 entries in
        app_state.system_logs (oldest entry removed before each append once cap
        is reached).
        """
        from webui.utils.log_interceptor import LogInterceptor, _MAX_LOGS

        app_state = _make_app_state()
        real_stdout = io.StringIO()
        interceptor = LogInterceptor(real_stdout, app_state)

        for i in range(_MAX_LOGS + 1):  # 1001 writes
            _write_tagged_line(interceptor, "TEST TAG", f"message {i}")

        assert len(app_state.system_logs) == _MAX_LOGS, (
            f"Expected {_MAX_LOGS} entries but got {len(app_state.system_logs)}"
        )

    def test_ring_buffer_does_not_exceed_max(self):
        """
        Writing many more than _MAX_LOGS entries must never exceed _MAX_LOGS.
        """
        from webui.utils.log_interceptor import LogInterceptor, _MAX_LOGS

        app_state = _make_app_state()
        real_stdout = io.StringIO()
        interceptor = LogInterceptor(real_stdout, app_state)

        for i in range(_MAX_LOGS * 2):  # 2000 writes
            _write_tagged_line(interceptor, "OVERFLOW", f"entry {i}")

        assert len(app_state.system_logs) <= _MAX_LOGS, (
            f"system_logs grew beyond {_MAX_LOGS}: {len(app_state.system_logs)}"
        )

    def test_ring_buffer_oldest_entry_evicted(self):
        """
        When the buffer is full and a new entry arrives, the oldest entry must
        be removed (FIFO eviction).
        """
        from webui.utils.log_interceptor import LogInterceptor, _MAX_LOGS

        app_state = _make_app_state()
        real_stdout = io.StringIO()
        interceptor = LogInterceptor(real_stdout, app_state)

        # Fill the buffer to capacity
        for i in range(_MAX_LOGS):
            _write_tagged_line(interceptor, "FILL", f"entry {i}")

        # The first entry should still be present (buffer is at max, not over)
        assert app_state.system_logs[0]["message"] == "entry 0"

        # Write one more — the oldest must be evicted
        _write_tagged_line(interceptor, "NEW", "newest entry")

        assert len(app_state.system_logs) == _MAX_LOGS
        # "entry 0" must have been evicted
        assert app_state.system_logs[0]["message"] == "entry 1", (
            f"Expected 'entry 1' as oldest but got '{app_state.system_logs[0]['message']}'"
        )
        # The newest must be at the tail
        assert app_state.system_logs[-1]["message"] == "newest entry"

    def test_untagged_lines_not_added(self):
        """Lines without [TAG] prefix must not be added to system_logs."""
        from webui.utils.log_interceptor import LogInterceptor

        app_state = _make_app_state()
        real_stdout = io.StringIO()
        interceptor = LogInterceptor(real_stdout, app_state)

        interceptor.write("no tag here\n")
        interceptor.write("also no tag\n")
        interceptor.write("[TAGGED] this should appear\n")

        assert len(app_state.system_logs) == 1
        assert app_state.system_logs[0]["tag"] == "TAGGED"

    def test_buffer_below_max_allows_growth(self):
        """When the buffer has fewer than _MAX_LOGS entries, it grows normally."""
        from webui.utils.log_interceptor import LogInterceptor, _MAX_LOGS

        app_state = _make_app_state()
        real_stdout = io.StringIO()
        interceptor = LogInterceptor(real_stdout, app_state)

        for i in range(10):
            _write_tagged_line(interceptor, "SMALL", f"msg {i}")

        assert len(app_state.system_logs) == 10

    def test_install_is_idempotent(self):
        """
        Calling install() twice must not nest interceptors — the second call
        updates the app_state reference but does not wrap again.
        """
        from webui.utils import log_interceptor

        original_stdout = sys.stdout

        try:
            app_state1 = _make_app_state()
            app_state2 = _make_app_state()

            log_interceptor.install(app_state1)
            first_interceptor = sys.stdout

            log_interceptor.install(app_state2)
            second_interceptor = sys.stdout

            # The interceptor object must be the same instance
            assert first_interceptor is second_interceptor, (
                "install() must be idempotent — got two different interceptors"
            )
            # But the app_state reference must have been updated
            assert sys.stdout._app_state is app_state2
        finally:
            sys.stdout = original_stdout
