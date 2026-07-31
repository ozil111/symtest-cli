"""Tests for cli_test_framework.core.execution.

Covers the ``errors="replace"`` behaviour: when a subprocess emits bytes that
cannot be decoded by the platform's default encoding, execution must not crash
with ``UnicodeDecodeError``; the offending bytes are replaced and the legal
portions of the output are preserved.

Also covers ``retry_count``: automatic retry-on-failure with configurable
attempt count, duration accumulation, and early-return on first success.
"""
import sys
from unittest.mock import patch

import pytest

from cli_test_framework.core.execution import execute_single_test_case


def _run(command: str, args, expected=None, workspace=None):
    case = {
        "name": "undecodable-output",
        "command": command,
        "args": list(args),
        "expected": expected or {"return_code": 0},
    }
    return execute_single_test_case(case, workspace=workspace)


def test_undecodable_output_bytes_do_not_crash(tmp_path):
    """Subprocess output containing bytes illegal under the default encoding
    must not raise UnicodeDecodeError; execution should still succeed and the
    decodable parts of the output must be preserved.

    ``0x80`` is illegal under both UTF-8 and GBK/cp936 (the two encodings most
    commonly implicated in the original crash), so this test is meaningful on
    both Linux CI and Chinese-Windows environments. Note: bytes like ``0x88``
    are *not* suitable because under GBK they act as a valid lead byte and
    consume the following byte, corrupting the suffix.
    """
    # Write raw bytes: ASCII prefix, an illegal byte, ASCII suffix.
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'ok-before\\x80ok-after'); "
        "sys.stdout.buffer.flush()"
    )
    result = _run(sys.executable, ["-c", script], workspace=str(tmp_path))

    assert result["status"] == "passed"
    assert result["return_code"] == 0
    # No execution error leaked into the message.
    assert "UnicodeDecodeError" not in result["message"]
    # The decodable portions survive.
    assert "ok-before" in result["output"]
    assert "ok-after" in result["output"]


def test_undecodable_bytes_still_allow_output_contains_assertion(tmp_path):
    """Even with garbage bytes mixed in, a valid ``output_contains`` assertion
    against the decodable part should pass — proving the output stream is usable
    for validation after the fix.
    """
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'DONE\\xff\\xfe'); "
        "sys.stdout.buffer.flush()"
    )
    result = _run(
        sys.executable,
        ["-c", script],
        expected={"return_code": 0, "output_contains": ["DONE"]},
        workspace=str(tmp_path),
    )

    assert result["status"] == "passed"
    assert "DONE" in result["output"]
    assert "UnicodeDecodeError" not in result["message"]


# ---------------------------------------------------------------------------
# retry_count  tests
# ---------------------------------------------------------------------------

def _make_result(status="passed", duration=0.1, name="test"):
    """Minimal helper to build a ``TestResultData``-like dict for mocking."""
    return {
        "name": name,
        "status": status,
        "message": "failure" if status != "passed" else "",
        "command": "cmd args",
        "output": "stdout",
        "return_code": 1 if status != "passed" else 0,
        "duration": duration,
    }


class TestRetryCount:
    """Tests for the ``retry_count`` feature in ``execute_single_test_case``."""

    def _case(self, retry_count=None):
        case = {
            "name": "retry-test",
            "command": "echo",
            "args": ["ok"],
            "expected": {"return_code": 0},
        }
        if retry_count is not None:
            case["retry_count"] = retry_count
        return case

    # -- default behavior (no retry) -----------------------------------------

    def test_default_retry_count_zero_no_retry(self):
        """When ``retry_count`` is absent from the case dict, execution
        should attempt exactly once (no retry)."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.return_value = _make_result(status="failed", duration=0.5)
            result = execute_single_test_case(self._case())

        mock_exec.assert_called_once()
        assert result["status"] == "failed"
        assert result["duration"] == 0.5

    def test_explicit_zero_no_retry(self):
        """``retry_count=0`` should behave identically to omitting the field."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.return_value = _make_result(status="failed", duration=0.5)
            result = execute_single_test_case(self._case(retry_count=0))

        mock_exec.assert_called_once()
        assert result["status"] == "failed"

    # -- early-return on first success --------------------------------------

    def test_retry_stops_on_first_success(self):
        """With ``retry_count=3``, a passing first attempt must NOT retry."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.return_value = _make_result(status="passed", duration=0.2)
            result = execute_single_test_case(self._case(retry_count=3))

        mock_exec.assert_called_once()
        assert result["status"] == "passed"

    # -- actual retry on failure --------------------------------------------

    def test_retry_after_failure(self):
        """With ``retry_count=2``, fail once then pass → 2 attempts total."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.side_effect = [
                _make_result(status="failed", duration=0.1),
                _make_result(status="passed", duration=0.2),
            ]
            result = execute_single_test_case(self._case(retry_count=2))

        assert mock_exec.call_count == 2
        assert result["status"] == "passed"

    def test_retry_exhausted_returns_failure(self):
        """With ``retry_count=2``, all 3 attempts fail → final status 'failed'."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.side_effect = [
                _make_result(status="failed", duration=0.1),
                _make_result(status="failed", duration=0.1),
                _make_result(status="failed", duration=0.1),
            ]
            result = execute_single_test_case(self._case(retry_count=2))

        assert mock_exec.call_count == 3
        assert result["status"] == "failed"

    def test_retry_preserves_timeout_status(self):
        """A timeout should be retried just like any other failure."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            timeout_result = {**_make_result(status="timeout", duration=5.0),
                              "message": "Timeout reached! Killed after 5 seconds.",
                              "return_code": None}
            mock_exec.side_effect = [
                timeout_result,
                _make_result(status="passed", duration=0.2),
            ]
            result = execute_single_test_case(self._case(retry_count=1))

        assert mock_exec.call_count == 2
        assert result["status"] == "passed"

    # -- duration accumulation ----------------------------------------------

    def test_retry_duration_accumulation(self):
        """Total duration must equal the sum of all attempt durations."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.side_effect = [
                _make_result(status="failed", duration=1.0),
                _make_result(status="failed", duration=2.0),
                _make_result(status="passed", duration=1.5),
            ]
            result = execute_single_test_case(self._case(retry_count=5))

        assert result["duration"] == pytest.approx(4.5)

    def test_retry_duration_all_failures(self):
        """Duration sum holds even when every attempt fails."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.side_effect = [
                _make_result(status="failed", duration=0.5),
                _make_result(status="failed", duration=0.5),
                _make_result(status="failed", duration=0.5),
            ]
            result = execute_single_test_case(self._case(retry_count=2))

        assert result["duration"] == pytest.approx(1.5)

    # -- retry_count=1  (exactly 2 attempts on failure) --------------------

    def test_retry_count_one(self):
        """``retry_count=1`` → up to 2 attempts."""
        with patch(
            "cli_test_framework.core.execution._execute_command_once"
        ) as mock_exec:
            mock_exec.side_effect = [
                _make_result(status="failed", duration=0.1),
                _make_result(status="passed", duration=0.1),
            ]
            result = execute_single_test_case(self._case(retry_count=1))

        assert mock_exec.call_count == 2
        assert result["status"] == "passed"
