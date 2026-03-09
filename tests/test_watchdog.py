"""
tests/test_watchdog.py

TDD tests for the PID-based stale flag detection in webui/watchdog.py.

Key scenario: on startup, if the flag file exists but its stored PID no longer
corresponds to a running process, start_watchdog() (and its helper
_is_flag_stale() / _remove_stale_flag()) must remove the flag file.
"""

import os
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_flag(path: str, pid: int) -> None:
    """Write a PID into the flag file at *path*."""
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w") as fh:
        fh.write(str(pid))


# ---------------------------------------------------------------------------
# Tests for stale-flag detection helpers
# ---------------------------------------------------------------------------

class TestStaleFlagDetection:

    def test_stale_flag_removed_on_startup(self, tmp_path):
        """
        A flag file containing a non-existent PID must be detected as stale and
        removed when start_watchdog() is called.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".analysis_active")
        non_existent_pid = 99999999

        _write_flag(flag_path, non_existent_pid)
        assert os.path.exists(flag_path), "Precondition: flag file must exist before test"

        # Patch the module-level flag path and reset the started flag
        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        original_started = watchdog._watchdog_started
        original_count = watchdog._active_count

        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            watchdog._watchdog_started = False

            # Patch threading.Thread so we don't actually start a daemon thread
            with patch("webui.watchdog.threading.Thread") as mock_thread_cls:
                mock_thread = MagicMock()
                mock_thread_cls.return_value = mock_thread

                # Patch _is_pid_running to confirm the PID is dead
                with patch("webui.watchdog._is_pid_running", return_value=False):
                    watchdog.start_watchdog()

            # The flag file must have been removed
            assert not os.path.exists(flag_path), (
                "Expected stale flag file to be removed, but it still exists"
            )
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path
            watchdog._watchdog_started = original_started
            watchdog._active_count = original_count

    def test_non_stale_flag_not_removed(self, tmp_path):
        """
        A flag file containing the PID of a running process must NOT be removed.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".analysis_active_live")
        live_pid = os.getpid()  # our own PID is definitely running

        _write_flag(flag_path, live_pid)

        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        original_started = watchdog._watchdog_started

        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            watchdog._watchdog_started = False

            with patch("webui.watchdog.threading.Thread") as mock_thread_cls:
                mock_thread = MagicMock()
                mock_thread_cls.return_value = mock_thread
                # Do NOT patch _is_pid_running — our own PID is running
                watchdog.start_watchdog()

            # The flag file must NOT have been removed (PID is live)
            assert os.path.exists(flag_path), (
                "Expected live flag file to be preserved, but it was removed"
            )
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path
            watchdog._watchdog_started = original_started
            if os.path.exists(flag_path):
                os.remove(flag_path)

    def test_is_flag_stale_returns_true_for_dead_pid(self, tmp_path):
        """
        _is_flag_stale() must return True when the flag file contains a dead PID.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".stale_check")
        _write_flag(flag_path, 99999999)

        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            with patch("webui.watchdog._is_pid_running", return_value=False):
                result = watchdog._is_flag_stale()
            assert result is True
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path

    def test_is_flag_stale_returns_false_when_no_flag(self, tmp_path):
        """
        _is_flag_stale() must return False when the flag file does not exist.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".missing_flag")
        # Do not create the file

        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            result = watchdog._is_flag_stale()
            assert result is False
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path

    def test_read_pid_from_flag_returns_none_for_invalid_content(self, tmp_path):
        """
        _read_pid_from_flag() must return None when the file contains non-numeric content.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".bad_flag")
        with open(flag_path, "w") as fh:
            fh.write("not-a-pid")

        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            result = watchdog._read_pid_from_flag()
            assert result is None
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path

    def test_read_pid_from_flag_returns_correct_pid(self, tmp_path):
        """
        _read_pid_from_flag() must return the integer PID written to the file.
        """
        import webui.watchdog as watchdog

        flag_path = str(tmp_path / ".valid_flag")
        expected_pid = 12345
        _write_flag(flag_path, expected_pid)

        original_flag_path = watchdog.ANALYSIS_FLAG_PATH
        try:
            watchdog.ANALYSIS_FLAG_PATH = flag_path
            result = watchdog._read_pid_from_flag()
            assert result == expected_pid
        finally:
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path

    def test_start_watchdog_is_idempotent(self, tmp_path):
        """
        Calling start_watchdog() twice must only start a single daemon thread.
        """
        import webui.watchdog as watchdog

        original_started = watchdog._watchdog_started
        original_flag_path = watchdog.ANALYSIS_FLAG_PATH

        try:
            watchdog.ANALYSIS_FLAG_PATH = str(tmp_path / ".no_flag")
            watchdog._watchdog_started = False

            thread_start_count = 0

            def counting_start():
                nonlocal thread_start_count
                thread_start_count += 1

            with patch("webui.watchdog.threading.Thread") as mock_thread_cls:
                mock_thread = MagicMock()
                mock_thread.start = counting_start
                mock_thread_cls.return_value = mock_thread

                watchdog.start_watchdog()
                watchdog.start_watchdog()  # second call — must be no-op

            assert thread_start_count == 1, (
                f"Expected exactly 1 thread start, got {thread_start_count}"
            )
        finally:
            watchdog._watchdog_started = original_started
            watchdog.ANALYSIS_FLAG_PATH = original_flag_path
