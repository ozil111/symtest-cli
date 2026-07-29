"""Tests for new execution features: retry history, flaky, output trimming."""
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from cli_test_framework.core.execution import (
    execute_single_test_case,
    _trim_output,
    DEFAULT_OUTPUT_MAX_CHARS,
)


class TestRetryFeatures:
    """Test retry history, flaky detection, and attempts tracking."""

    @pytest.fixture
    def case(self):
        return {
            "name": "test_case",
            "command": "echo",
            "args": ["hello"],
            "expected": {"return_code": 0},
            "description": None,
            "timeout": None,
            "resources": None,
            "retry_count": 2,
        }

    def test_retry_flaky_flag(self, case):
        """When a case passes after retry, flaky=True."""
        with patch("subprocess.Popen") as mock_popen:
            # First attempt fails (return_code=1), second succeeds (return_code=0)
            mock_popen.side_effect = [
                MagicMock(
                    communicate=MagicMock(return_value=("", "")),
                    returncode=1,
                    pid=1,
                ),
                MagicMock(
                    communicate=MagicMock(return_value=("", "")),
                    returncode=0,
                    pid=2,
                ),
            ]
            result = execute_single_test_case(case)
            assert result["status"] == "passed"
            assert result["flaky"] is True
            assert result["attempts"] == 2

    def test_no_retry_not_flaky(self, case):
        """Single attempt passing is not flaky."""
        case["retry_count"] = 0
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("", "")),
                returncode=0,
                pid=1,
            )
            result = execute_single_test_case(case)
            assert result["status"] == "passed"
            assert result["flaky"] is False
            assert result["attempts"] == 1

    def test_retry_all_fail_not_flaky(self, case):
        """All attempts fail → not flaky."""
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [
                MagicMock(communicate=MagicMock(return_value=("", "")), returncode=1, pid=i)
                for i in range(1, 4)
            ]
            result = execute_single_test_case(case)
            assert result["status"] == "failed"
            assert result["flaky"] is False
            assert result["attempts"] == 3

    def test_attempt_history_structure(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [
                MagicMock(communicate=MagicMock(return_value=("fail1", "")), returncode=1, pid=1),
                MagicMock(communicate=MagicMock(return_value=("success", "")), returncode=0, pid=2),
            ]
            result = execute_single_test_case(case)

            history = result["attempt_history"]
            assert len(history) == 2
            assert history[0]["attempt"] == 1
            assert history[0]["status"] == "failed"
            assert history[1]["attempt"] == 2
            assert history[1]["status"] == "passed"

    def test_attempts_count_matches_history(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [
                MagicMock(communicate=MagicMock(return_value=("", "")), returncode=1, pid=1),
                MagicMock(communicate=MagicMock(return_value=("", "")), returncode=1, pid=2),
                MagicMock(communicate=MagicMock(return_value=("", "")), returncode=0, pid=3),
            ]
            result = execute_single_test_case(case)
            assert result["attempts"] == 3
            assert len(result["attempt_history"]) == 3


class TestOutputTrimming:
    """Test output trimming for large command outputs."""

    def test_short_output_not_trimmed(self):
        short = "hello world"
        assert _trim_output(short) == short

    def test_exact_boundary_not_trimmed(self):
        exact = "x" * DEFAULT_OUTPUT_MAX_CHARS
        assert _trim_output(exact) == exact

    def test_long_output_trimmed(self):
        long_output = "a" * (DEFAULT_OUTPUT_MAX_CHARS * 2)
        trimmed = _trim_output(long_output)
        assert len(trimmed) <= DEFAULT_OUTPUT_MAX_CHARS + 200  # allow marker text
        assert "truncated" in trimmed

    def test_trimmed_contains_head_and_tail(self):
        """Trimmed output should show beginning and end of original."""
        long_output = "START_" + "m" * (DEFAULT_OUTPUT_MAX_CHARS * 2) + "_END"
        trimmed = _trim_output(long_output)
        assert "START_" in trimmed
        assert "_END" in trimmed
        assert "truncated" in trimmed

    def test_trim_preserves_structure(self):
        lines = [f"line_{i}" for i in range(DEFAULT_OUTPUT_MAX_CHARS // 5)]
        long_output = "\n".join(lines)
        trimmed = _trim_output(long_output)
        assert "line_0" in trimmed
        assert f"line_{len(lines)-1}" in trimmed
