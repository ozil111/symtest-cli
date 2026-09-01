"""Tests for new config_loader features: output slimming, step_results."""
from unittest.mock import patch

import pytest

from symtest.core.orchestration.sequence import execute_sequence
from symtest.core.validation.assertions import ValidationError
from symtest.core.validation.result import ValidationResult


def _passed_result(name, output="ok\n"):
    return {"name": name, "status": "passed", "message": "", "command": "cmd",
            "output": output, "return_code": 0, "duration": 0.1}


def _failed_result(name, output="fail\n", message="error"):
    return {"name": name, "status": "failed", "message": message, "command": "cmd",
            "output": output, "return_code": 1, "duration": 0.1, "failure_kind": "return_code"}


class TestSequenceOutputSliming:
    """Test that sequence failures produce slim output."""

    def test_passed_sequence_keeps_combined_output(self):
        steps = [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["two"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "one\n"),
                _passed_result("s2", "two\n"),
            ]
            result = execute_sequence("seq_pass", steps)
            assert result["status"] == "passed"
            assert "one" in result["output"]
            assert "two" in result["output"]

    def test_failed_step_only_keeps_failed_step_output(self):
        steps = [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["two"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "step_one_output_long_string\n"),
                _failed_result("s2", "step_two_failed_error_detail\n", "step 2 failed"),
            ]
            result = execute_sequence("seq_fail", steps)
            assert result["status"] == "failed"
            # Should only contain failed step's output, not step 1's
            assert "step_one_output" not in result["output"]
            assert "step_two_failed" in result["output"]
            assert result["failed_step"] == 2

    def test_case_level_failure_has_empty_output(self):
        steps = [
            {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "long_output_from_step\n"),
            ]
            result = execute_sequence(
                "case_fail",
                steps,
                case_expected={"return_code": 1},  # will fail
            )
            assert result["status"] == "failed"
            # Case-level failure → output should be empty
            assert result["output"] == ""

    def test_step_results_present_on_pass(self):
        steps = [
            {"command": "e1", "args": ["a"], "expected": {"return_code": 0}},
            {"command": "e2", "args": ["b"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1"),
                _passed_result("s2"),
            ]
            result = execute_sequence("case", steps)
            assert "step_results" in result
            assert len(result["step_results"]) == 2
            assert result["step_results"][0]["step"] == 1
            assert result["step_results"][0]["status"] == "passed"
            assert result["step_results"][1]["step"] == 2
            assert result["step_results"][1]["status"] == "passed"

    def test_step_results_truncates_on_failure(self):
        steps = [
            {"command": "e1", "args": ["a"], "expected": {"return_code": 0}},
            {"command": "e2", "args": ["b"], "expected": {"return_code": 0}},
            {"command": "e3", "args": ["c"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1"),
                _failed_result("s2"),
            ]
            result = execute_sequence("case", steps)
            # step 3 never executed, step_results only has 2 entries
            assert len(result["step_results"]) == 2
            assert result["step_results"][0]["status"] == "passed"
            assert result["step_results"][1]["status"] == "failed"


class TestSequenceStructuredDiagnostics:
    """Sequence results propagate assertion_results / next_action_hint."""

    def test_failed_step_propagates_hint_and_assertions(self):
        failed = _failed_result("s2")
        failed["assertion_results"] = [
            {"assertion": "return_code", "passed": False, "message": "rc mismatch"}
        ]
        failed["next_action_hint"] = {
            "action": "update_expected", "command": None, "reason": "r",
        }
        steps = [
            {"command": "e1", "args": ["a"], "expected": {"return_code": 0}},
            {"command": "e2", "args": ["b"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [_passed_result("s1"), failed]
            result = execute_sequence("case", steps)
            assert result["status"] == "failed"
            assert result["assertion_results"] == failed["assertion_results"]
            assert result["next_action_hint"] == failed["next_action_hint"]

    def test_case_level_failure_builds_hint(self):
        steps = [
            {"command": "echo", "args": ["x"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [_passed_result("s1")]
            with patch(
                "symtest.core.orchestration.sequence.validate_result"
            ) as mock_validate:
                mock_validate.side_effect = ValidationError(
                    "compare failed",
                    failure_kind="file_compare",
                    compare_failures=[{"actual": "a.csv", "baseline": "b.csv"}],
                    assertion_results=[{"assertion": "compare_files", "passed": False}],
                )
                result = execute_sequence(
                    "case",
                    steps,
                    case_expected={"compare_files": [{"actual": "a.csv", "baseline": "b.csv"}]},
                )
            assert result["status"] == "failed"
            assert result["assertion_results"] == [
                {"assertion": "compare_files", "passed": False}
            ]
            assert result["next_action_hint"]["action"] == "update_baseline"

    def test_passed_sequence_uses_case_level_assertion_results(self):
        steps = [
            {"command": "echo", "args": ["x"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [_passed_result("s1")]
            with patch(
                "symtest.core.orchestration.sequence.validate_result"
            ) as mock_validate:
                mock_validate.return_value = ValidationResult(
                    passed=True,
                    assertion_results=[{"assertion": "return_code", "passed": True}],
                )
                result = execute_sequence(
                    "case",
                    steps,
                    case_expected={"return_code": 0},
                )
            assert result["status"] == "passed"
            assert result["assertion_results"] == [
                {"assertion": "return_code", "passed": True}
            ]
            assert result["next_action_hint"] is None


class TestSequenceExpectedEcho:
    """Test that failure_kind and compare_failures are propagated from case-level failures."""

    def test_case_level_compare_failure_kind(self):
        steps = [
            {"command": "echo", "args": ["x"], "expected": {"return_code": 0}},
        ]
        with patch(
            "symtest.core.orchestration.sequence.execute_single_test_case"
        ) as executor:
            executor.side_effect = [_passed_result("s1")]
            # validate_result is imported locally inside execute_sequence as
            #   from .execution import validate_result
            with patch(
                "symtest.core.orchestration.sequence.validate_result"
            ) as mock_validate:
                mock_validate.side_effect = ValidationError(
                    "compare failed",
                    failure_kind="file_compare",
                    compare_failures=[{"actual": "a.csv", "baseline": "b.csv"}],
                )
                result = execute_sequence(
                    "case",
                    steps,
                    case_expected={"compare_files": [{"actual": "a.csv", "baseline": "b.csv"}]},
                )
            assert result["status"] == "failed"
            assert result["failure_kind"] == "file_compare"
            assert len(result["compare_failures"]) == 1
