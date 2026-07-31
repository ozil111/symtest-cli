"""Unit tests for cli_test_framework.core.config_loader — substitute_placeholders, parse_test_cases."""

from unittest.mock import patch

import pytest

from cli_test_framework.core.config_loader import (
    substitute_placeholders,
    parse_test_cases,
    execute_sequence,
)


# ---------------------------------------------------------------------------
# Basic substitution
# ---------------------------------------------------------------------------

class TestSubstitutePlaceholders:
    """Tests for the substitute_placeholders utility."""

    def test_no_variables_returns_unchanged(self):
        config = {"command": "{solver}", "args": ["--input", "{model}"]}
        result = substitute_placeholders(config, None)
        assert result == config

    def test_empty_variables_returns_unchanged(self):
        config = {"command": "{solver}", "args": ["--input", "{model}"]}
        result = substitute_placeholders(config, {})
        assert result == config

    def test_simple_string_substitution(self):
        config = {"command": "{solver}"}
        result = substitute_placeholders(config, {"solver": "/usr/bin/solver"})
        assert result["command"] == "/usr/bin/solver"

    def test_multiple_placeholders_in_one_string(self):
        config = {"command": "{solver} --input {model}"}
        result = substitute_placeholders(
            config, {"solver": "/usr/bin/solver", "model": "./data.dat"},
        )
        assert result["command"] == "/usr/bin/solver --input ./data.dat"

    def test_placeholder_in_list(self):
        config = {"args": ["--solver", "{solver}", "--input", "{model}"]}
        result = substitute_placeholders(
            config, {"solver": "/usr/bin/solver", "model": "./data.dat"},
        )
        assert result["args"] == ["--solver", "/usr/bin/solver", "--input", "./data.dat"]

    def test_placeholder_in_nested_dict(self):
        config = {
            "test_cases": [
                {
                    "name": "test-{tag}",
                    "command": "{solver}",
                    "args": ["{model}"],
                    "expected": {"return_code": 0},
                }
            ]
        }
        result = substitute_placeholders(
            config, {"solver": "/usr/bin/solver", "model": "./data.dat", "tag": "alpha"},
        )
        case = result["test_cases"][0]
        assert case["name"] == "test-alpha"
        assert case["command"] == "/usr/bin/solver"
        assert case["args"] == ["./data.dat"]

    def test_unmatched_placeholder_preserved(self):
        """Unmatched {xxx} should be kept as-is (safe for regex patterns like {2})."""
        config = {"expected": {"output_matches": r"\d{2,4}"}}
        result = substitute_placeholders(config, {"solver": "/bin/solver"})
        assert result["expected"]["output_matches"] == r"\d{2,4}"

    def test_partial_match_preserved(self):
        """Only entirely matching keys are substituted; partial matches stay."""
        config = {"command": "{solver_extra}"}
        result = substitute_placeholders(config, {"solver": "/bin/solver"})
        assert result["command"] == "{solver_extra}"

    def test_non_string_values_unchanged(self):
        config = {"timeout": 60, "priority": 3.5, "enabled": True, "data": None}
        result = substitute_placeholders(config, {"timeout": "999"})
        assert result["timeout"] == 60
        assert result["priority"] == 3.5
        assert result["enabled"] is True
        assert result["data"] is None

    def test_original_config_not_mutated(self):
        original = {"command": "{solver}", "args": ["{model}"]}
        result = substitute_placeholders(
            original, {"solver": "/usr/bin/solver", "model": "./data.dat"},
        )
        # Original should be unchanged
        assert original["command"] == "{solver}"
        assert original["args"] == ["{model}"]
        # Result should have substitutions
        assert result["command"] == "/usr/bin/solver"
        assert result["args"] == ["./data.dat"]

    def test_variable_value_converted_to_str(self):
        """Non-string variable values should be converted via str()."""
        config = {"command": "{count} {flag}"}
        result = substitute_placeholders(config, {"count": 42, "flag": True})
        assert result["command"] == "42 True"


# ---------------------------------------------------------------------------
# Integration-style: full config dict with placeholders
# ---------------------------------------------------------------------------

class TestPlaceholderInTestCases:
    """End-to-end style tests with realistic config dicts."""

    def test_full_json_config_with_steps(self):
        config = {
            "test_cases": [
                {
                    "name": "Multi-step with placeholders",
                    "steps": [
                        {
                            "command": "{solver}",
                            "args": ["--parse", "{input}"],
                            "expected": {"return_code": 0},
                        },
                        {
                            "command": "{solver}",
                            "args": ["--solve", "{input}"],
                            "expected": {"output_contains": ["Optimal"]},
                        },
                    ],
                }
            ]
        }
        result = substitute_placeholders(
            config, {"solver": "/opt/solver", "input": "model.dat"},
        )
        steps = result["test_cases"][0]["steps"]
        assert steps[0]["command"] == "/opt/solver"
        assert steps[0]["args"] == ["--parse", "model.dat"]
        assert steps[1]["command"] == "/opt/solver"
        assert steps[1]["args"] == ["--solve", "model.dat"]


# ---------------------------------------------------------------------------
# parse_test_cases — retry_count
# ---------------------------------------------------------------------------

class TestParseRetryCount:
    """Tests for ``retry_count`` parsing in ``parse_test_cases``."""

    def test_single_command_retry_count(self):
        config = {
            "test_cases": [
                {
                    "name": "retry-case",
                    "command": "echo",
                    "args": ["ok"],
                    "expected": {"return_code": 0},
                    "retry_count": 3,
                }
            ]
        }
        cases = parse_test_cases(config)
        assert len(cases) == 1
        assert cases[0].retry_count == 3

    def test_single_command_default_retry_count(self):
        """Without ``retry_count``, it defaults to 0."""
        config = {
            "test_cases": [
                {
                    "name": "no-retry",
                    "command": "echo",
                    "args": ["ok"],
                    "expected": {"return_code": 0},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].retry_count == 0

    def test_step_retry_count(self):
        config = {
            "test_cases": [
                {
                    "name": "step-case",
                    "steps": [
                        {
                            "command": "echo",
                            "args": ["s1"],
                            "expected": {"return_code": 0},
                        },
                        {
                            "command": "echo",
                            "args": ["s2"],
                            "expected": {"return_code": 0},
                            "retry_count": 2,
                        },
                    ],
                }
            ]
        }
        cases = parse_test_cases(config)
        assert len(cases) == 1
        steps = cases[0].steps
        assert len(steps) == 2
        assert steps[0].retry_count == 0  # default
        assert steps[1].retry_count == 2

    def test_step_default_retry_count(self):
        config = {
            "test_cases": [
                {
                    "name": "step-no-retry",
                    "steps": [
                        {
                            "command": "echo",
                            "args": ["s1"],
                            "expected": {"return_code": 0},
                        }
                    ],
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].steps[0].retry_count == 0


# ---------------------------------------------------------------------------
# parse_test_cases — case-level expected in sequence mode
# ---------------------------------------------------------------------------

class TestParseCaseLevelExpected:
    """Tests for case-level ``expected`` in sequence-mode ``parse_test_cases``."""

    def test_sequence_case_expected_is_preserved(self):
        config = {
            "test_cases": [
                {
                    "name": "case-with-expected",
                    "steps": [
                        {"command": "echo", "args": ["s1"], "expected": {"return_code": 0}},
                    ],
                    "expected": {
                        "compare_files": [
                            {"actual": "out.csv", "baseline": "ref.csv", "type": "csv"},
                        ],
                    },
                }
            ]
        }
        cases = parse_test_cases(config)
        assert len(cases) == 1
        assert cases[0].name == "case-with-expected"
        case_expected = cases[0].expected
        assert "compare_files" in case_expected
        assert len(case_expected["compare_files"]) == 1
        assert case_expected["compare_files"][0]["actual"] == "out.csv"

    def test_sequence_case_without_expected_defaults_to_empty_dict(self):
        config = {
            "test_cases": [
                {
                    "name": "no-expected",
                    "steps": [
                        {"command": "echo", "args": ["s1"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].expected == {}

    def test_sequence_case_expected_includes_return_code(self):
        config = {
            "test_cases": [
                {
                    "name": "case-rc",
                    "steps": [
                        {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
                    ],
                    "expected": {"return_code": 0},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].expected == {"return_code": 0}


# ---------------------------------------------------------------------------
# execute_sequence — case-level expected assertions
# ---------------------------------------------------------------------------

def _passed_result(name="step", output="ok\n"):
    return {
        "name": name,
        "status": "passed",
        "message": "",
        "command": "cmd",
        "output": output,
        "return_code": 0,
        "duration": 0.1,
    }


def _failed_result(name="step"):
    return {
        "name": name,
        "status": "failed",
        "message": "bad return code",
        "command": "cmd",
        "output": "err\n",
        "return_code": 2,
        "duration": 0.2,
    }


class TestExecuteSequenceCaseExpected:
    """Tests for case-level ``expected`` in ``execute_sequence``."""

    def test_all_steps_pass_and_case_expected_passes(self):
        steps = [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["two"], "expected": {"return_code": 0}},
        ]
        case_expected = {"output_contains": ["one"]}

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "one\n"),
                _passed_result("s2", "two\n"),
            ]
            result = execute_sequence(
                case_name="case-expected-pass",
                steps=steps,
                case_expected=case_expected,
            )

        assert result["status"] == "passed"
        assert executor.call_count == 2

    def test_all_steps_pass_but_case_expected_fails(self):
        steps = [
            {"command": "echo", "args": ["hello"], "expected": {"return_code": 0}},
        ]
        case_expected = {"output_contains": ["MISSING_TEXT"]}

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "hello world\n")
            result = execute_sequence(
                case_name="case-expected-fail",
                steps=steps,
                case_expected=case_expected,
            )

        assert result["status"] == "failed"
        assert "Case-level assertion failed" in result["message"]

    def test_step_fails_case_expected_not_executed(self):
        steps = [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "tool", "args": ["fail"], "expected": {"return_code": 0}},
        ]
        case_expected = {"output_contains": ["SHOULD_NOT_RUN"]}

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "one\n"),
                _failed_result("s2"),
            ]
            result = execute_sequence(
                case_name="step-fails-first",
                steps=steps,
                case_expected=case_expected,
            )

        assert result["status"] == "failed"
        assert "Case-level assertion" not in result["message"]
        # When a step fails, case_expected is not a real step
        assert "Failed at step 2/2" in result["message"]

    def test_no_case_expected_backward_compatible(self):
        steps = [
            {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
        ]

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "ok\n")
            result = execute_sequence(
                case_name="no-case-expected",
                steps=steps,
            )

        assert result["status"] == "passed"
        assert executor.call_count == 1

    def test_empty_case_expected_does_nothing(self):
        steps = [
            {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
        ]

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "ok\n")
            result = execute_sequence(
                case_name="empty-expected",
                steps=steps,
                case_expected={},
            )

        assert result["status"] == "passed"
        assert executor.call_count == 1

    def test_error_message_step_count_with_case_expected(self):
        """When case_expected exists, total steps = len(steps) + 1."""
        steps = [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["two"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["three"], "expected": {"return_code": 0}},
        ]
        case_expected = {"output_contains": ["MISSING"]}

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.side_effect = [
                _passed_result("s1", "one\n"),
                _passed_result("s2", "two\n"),
                _passed_result("s3", "three\n"),
            ]
            result = execute_sequence(
                case_name="step-count-test",
                steps=steps,
                case_expected=case_expected,
            )

        # 3 steps + 1 synthetic = 4 total; case-level is step 4
        assert result["status"] == "failed"
        assert "Failed at step 4/4" in result["message"]

    def test_case_expected_with_return_code(self):
        steps = [
            {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
        ]
        # The combined result's return_code comes from last step (0)
        # and case_expected.return_code also expects 0 → pass
        case_expected = {"return_code": 0}

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "ok\n")
            result = execute_sequence(
                case_name="case-return-code",
                steps=steps,
                case_expected=case_expected,
            )

        assert result["status"] == "passed"

    def test_case_expected_compare_files_invoked(self):
        steps = [
            {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
        ]
        case_expected = {
            "compare_files": [
                {"actual": "a.txt", "baseline": "b.txt", "type": "text"}
            ],
        }

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "ok\n")
            with patch(
                "cli_test_framework.core.execution.validate_result"
            ) as mock_validate:
                result = execute_sequence(
                    case_name="case-compare-files",
                    steps=steps,
                    case_expected=case_expected,
                )

        # validate_result should be called once with the case_expected
        mock_validate.assert_called_once()
        assert result["status"] == "passed"

    def test_case_expected_compare_files_fails(self):
        steps = [
            {"command": "echo", "args": ["ok"], "expected": {"return_code": 0}},
        ]
        case_expected = {
            "compare_files": [
                {"actual": "a.txt", "baseline": "b.txt", "type": "text"}
            ],
        }

        with patch(
            "cli_test_framework.core.config_loader.execute_single_test_case"
        ) as executor:
            executor.return_value = _passed_result("s1", "ok\n")
            with patch(
                "cli_test_framework.core.execution.validate_result",
                side_effect=AssertionError("Files differ"),
            ):
                result = execute_sequence(
                    case_name="case-compare-fail",
                    steps=steps,
                    case_expected=case_expected,
                )

        assert result["status"] == "failed"
        assert "Case-level assertion failed" in result["message"]
        assert "Files differ" in result["message"]
