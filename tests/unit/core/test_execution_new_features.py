"""Tests for new execution features: retry history, flaky, output trimming."""
import subprocess
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from cli_test_framework.core.execution import (
    execute_single_test_case,
    validate_result,
    _build_next_action_hint,
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


class TestAssertionResults:
    """assertion_results should be populated on both success and failure."""

    @pytest.fixture
    def case(self):
        return {
            "name": "test_case",
            "command": "echo",
            "args": ["hello"],
            "expected": {"return_code": 0, "output_contains": ["hello", "world"]},
            "description": None,
            "timeout": None,
            "resources": None,
            "retry_count": 0,
        }

    def test_success_populates_assertion_results(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("hello world\n", "")),
                returncode=0,
                pid=1,
            )
            result = execute_single_test_case(case)
            assert result["status"] == "passed"
            ar = result["assertion_results"]
            assert len(ar) == 3  # return_code + 2x output_contains
            assert all(entry["passed"] for entry in ar)
            assert ar[0]["assertion"] == "return_code"
            assert [e["assertion"] for e in ar[1:]] == ["output_contains"] * 2

    def test_failure_marks_individual_assertions(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("hello\n", "")),
                returncode=0,
                pid=1,
            )
            result = execute_single_test_case(case)
            assert result["status"] == "failed"
            ar = result["assertion_results"]
            # return_code passed, 'hello' found, 'world' missing
            assert ar[0]["passed"] is True
            assert ar[1]["passed"] is True
            assert ar[2]["passed"] is False
            assert ar[2]["text"] == "world"
            assert "message" in ar[2]

    def test_validate_result_returns_assertion_results_on_success(self):
        mini = {
            "name": "t", "status": "failed", "message": "", "command": "c",
            "output": "abc", "return_code": 0, "duration": 0.0,
        }
        ar = validate_result(
            {"return_code": 0, "output_contains": ["abc"]}, mini,
        )
        assert ar == [
            {"assertion": "return_code", "passed": True},
            {"assertion": "output_contains", "passed": True, "text": "abc"},
        ]


class TestNextActionHint:
    """Failed results carry a structured next_action_hint."""

    @pytest.fixture
    def case(self):
        return {
            "name": "hint_case",
            "command": "echo",
            "args": ["x"],
            "expected": {"return_code": 0},
            "description": None,
            "timeout": None,
            "resources": None,
            "retry_count": 0,
        }

    def test_hint_mapping(self):
        assert _build_next_action_hint(None) is None
        assert _build_next_action_hint("file_compare")["action"] == "update_baseline"
        assert _build_next_action_hint("file_compare", update_baseline=True)["action"] == "investigate"
        assert _build_next_action_hint("return_code")["action"] == "update_expected"
        assert _build_next_action_hint("output_contains")["action"] == "update_expected"
        assert _build_next_action_hint("output_matches")["action"] == "update_expected"
        assert _build_next_action_hint("timeout")["action"] == "increase_timeout"
        assert _build_next_action_hint("execution_error")["action"] == "investigate"
        assert _build_next_action_hint("something_else")["action"] == "investigate"

    def test_assertion_failure_attaches_hint(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("", "")),
                returncode=3,
                pid=1,
            )
            result = execute_single_test_case(case)
            assert result["status"] == "failed"
            hint = result["next_action_hint"]
            assert hint["action"] == "update_expected"
            assert hint["command"] is None  # filled by the runner layer
            assert hint["reason"]

    def test_execution_error_attaches_hint(self, case):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("no such cmd")):
            result = execute_single_test_case(case)
            assert result["status"] == "failed"
            assert result["failure_kind"] == "execution_error"
            assert result["next_action_hint"]["action"] == "investigate"

    def test_timeout_attaches_hint(self, case):
        case["timeout"] = 1
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="echo", timeout=1),
            ("partial", ""),
        ]
        mock_proc.pid = 99999
        mock_proc.kill = MagicMock()
        with patch("subprocess.Popen", return_value=mock_proc):
            result = execute_single_test_case(case)
            assert result["status"] == "timeout"
            assert result["next_action_hint"]["action"] == "increase_timeout"
            # PID 99999 is harmless even if killpg() is called;
            # mock_proc.kill is also safe. Assertions above verify
            # the result format remains correct.

    def test_passed_case_has_no_hint(self, case):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("", "")),
                returncode=0,
                pid=1,
            )
            result = execute_single_test_case(case)
            assert result["status"] == "passed"
            assert result["next_action_hint"] is None


class TestRunnerHintCommandFilling:
    """Runners fill the concrete cli-test command into next_action_hint."""

    def _make_failed_result(self, action):
        return {
            "name": "case_a",
            "status": "failed",
            "next_action_hint": {"action": action, "command": None, "reason": "r"},
        }

    def test_update_baseline_command(self):
        from cli_test_framework.runners.json_runner import JSONRunner

        runner = JSONRunner(config_file="cfg.json")
        result = self._make_failed_result("update_baseline")
        runner._fill_hint_command(result, "case_a")
        cmd = result["next_action_hint"]["command"]
        assert cmd == (
            f'cli-test run "{runner.config_path}" --update-baseline -t "case_a"'
        )

    def test_rerun_command_for_other_actions(self):
        from cli_test_framework.runners.json_runner import JSONRunner

        runner = JSONRunner(config_file="cfg.json")
        result = self._make_failed_result("update_expected")
        runner._fill_hint_command(result, "case_a")
        cmd = result["next_action_hint"]["command"]
        assert cmd == f'cli-test run "{runner.config_path}" -t "case_a"'

    def test_existing_command_not_overwritten(self):
        from cli_test_framework.runners.json_runner import JSONRunner

        runner = JSONRunner(config_file="cfg.json")
        result = self._make_failed_result("update_baseline")
        result["next_action_hint"]["command"] = "custom"
        runner._fill_hint_command(result, "case_a")
        assert result["next_action_hint"]["command"] == "custom"

    def test_no_hint_is_noop(self):
        from cli_test_framework.runners.json_runner import JSONRunner

        runner = JSONRunner(config_file="cfg.json")
        result = {"name": "ok", "status": "passed", "next_action_hint": None}
        runner._fill_hint_command(result, "ok")  # should not raise
        assert result["next_action_hint"] is None
