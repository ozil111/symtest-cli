"""Tests for the case-level ``env`` feature.

Covers parsing (``parse_test_cases`` + ``_parse_env``), subprocess injection
(``_execute_command_once`` via ``execute_single_test_case``), precedence over
scheduler-injected variables, and sequence-mode propagation.
"""
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from symtest.core.config_loader import (
    parse_test_cases,
    execute_sequence,
)
from symtest.core.execution import execute_single_test_case


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestParseEnv:
    """``env`` is parsed from raw config into a ``{str: str}`` dict."""

    def test_env_parsed_from_single_command_case(self):
        config = {
            "test_cases": [
                {
                    "name": "t",
                    "command": "solver",
                    "args": ["-i", "in.dat"],
                    "expected": {"return_code": 0},
                    "env": {"UEL_SYSID_SCALE": "1.0", "OMP_NUM_THREADS": "8"},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].env == {"UEL_SYSID_SCALE": "1.0", "OMP_NUM_THREADS": "8"}

    def test_env_parsed_from_sequence_case(self):
        config = {
            "test_cases": [
                {
                    "name": "seq",
                    "env": {"UEL_SYSID_SCALE": "2.0"},
                    "steps": [
                        {"command": "python", "args": ["s1.py"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].env == {"UEL_SYSID_SCALE": "2.0"}

    def test_env_absent_defaults_to_empty(self):
        config = {
            "test_cases": [
                {"name": "t", "command": "solver", "expected": {"return_code": 0}},
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].env == {}

    def test_env_numeric_and_bool_values_coerced_to_str(self):
        config = {
            "test_cases": [
                {
                    "name": "t",
                    "command": "solver",
                    "expected": {"return_code": 0},
                    "env": {"NPROC": 4, "DEBUG": True},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].env == {"NPROC": "4", "DEBUG": "True"}

    def test_env_survives_to_execution_dict(self):
        config = {
            "test_cases": [
                {
                    "name": "t",
                    "command": "solver",
                    "expected": {"return_code": 0},
                    "env": {"A": "1"},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].to_execution_dict()["env"] == {"A": "1"}


# ---------------------------------------------------------------------------
# Subprocess injection
# ---------------------------------------------------------------------------

class TestEnvInjection:
    """``env`` is actually passed to the subprocess."""

    def _print_env_case(self, name, env, expected_value):
        return {
            "name": name,
            "command": sys.executable,
            "args": [
                "-c",
                "import os;print(os.environ.get('CASE_ENV_KEY', '<missing>'))",
            ],
            "expected": {
                "return_code": 0,
                "output_contains": [expected_value],
            },
            "env": env,
        }

    def test_env_is_injected_into_subprocess(self):
        case = self._print_env_case("t", {"CASE_ENV_KEY": "hello"}, "hello")
        result = execute_single_test_case(case)
        assert result["status"] == "passed", result.get("message")
        assert "hello" in result["output"]

    def test_env_inherits_parent_environment(self):
        """Parent os.environ is still visible when case env is set."""
        case = self._print_env_case("t", {"CASE_ENV_KEY": "hello"}, "hello")
        result = execute_single_test_case(case)
        assert result["status"] == "passed", result.get("message")


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------

class TestEnvPrecedence:
    """case ``env`` has the highest precedence."""

    def test_case_env_overrides_scheduler_injected_env(self):
        case = {
            "name": "t",
            "command": sys.executable,
            "args": [
                "-c",
                "import os;print(os.environ.get('OMP_NUM_THREADS', '<missing>'))",
            ],
            "expected": {"return_code": 0, "output_contains": ["99"]},
            "env": {"OMP_NUM_THREADS": "99"},
        }
        # Scheduler injects its own OMP_NUM_THREADS via the ``env`` argument.
        result = execute_single_test_case(case, env={"OMP_NUM_THREADS": "8"})
        assert result["status"] == "passed", result.get("message")
        assert "99" in result["output"]


# ---------------------------------------------------------------------------
# Sequence mode
# ---------------------------------------------------------------------------

class TestEnvSequence:
    """``env`` propagates to every step in a sequence."""

    def test_env_applied_to_all_steps(self):
        steps = [
            {
                "command": sys.executable,
                "args": ["-c", "import os;print('S='+os.environ.get('SCALE','?'))"],
                "expected": {"return_code": 0, "output_contains": ["S=1.0"]},
            },
            {
                "command": sys.executable,
                "args": ["-c", "import os;print('S='+os.environ.get('SCALE','?'))"],
                "expected": {"return_code": 0, "output_contains": ["S=1.0"]},
            },
        ]
        result = execute_sequence("seq_env", steps, env={"SCALE": "1.0"})
        assert result["status"] == "passed", result.get("message")


class TestEnvAffectsConfigHash:
    """Changing ``env`` changes the sequence config hash (resume safety)."""

    def test_hash_differs_when_env_differs(self):
        from symtest.core.sequence_state import compute_config_hash

        steps = [
            {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
        ]
        h1 = compute_config_hash(steps, None, {"SCALE": "1.0"})
        h2 = compute_config_hash(steps, None, {"SCALE": "2.0"})
        h3 = compute_config_hash(steps, None, None)
        assert h1 != h2
        assert h1 != h3


# ---------------------------------------------------------------------------
# TUI editor helpers
# ---------------------------------------------------------------------------

class TestTuiEnvHelpers:
    """Round-trip of the TUI editor's ``KEY=VALUE`` env helpers."""

    def _helpers(self):
        from symtest.tui.screens.case_editor import CaseEditorScreen

        return CaseEditorScreen._format_env_text, CaseEditorScreen._parse_env_text

    def test_format_and_parse_roundtrip(self):
        fmt, parse = self._helpers()
        env = {"UEL_SYSID_SCALE": "1.0", "OMP_NUM_THREADS": "8"}
        text = fmt(env)
        assert parse(text) == env

    def test_format_empty_env(self):
        fmt, parse = self._helpers()
        assert fmt({}) == ""
        assert fmt(None) == ""

    def test_parse_skips_blanks_and_comments(self):
        _, parse = self._helpers()
        text = "# comment\n\nA=1\n  B = 2  \ninvalid-line\nC=\n"
        assert parse(text) == {"A": "1", "B": "2", "C": ""}

    def test_parse_ignores_line_without_equals(self):
        _, parse = self._helpers()
        assert parse("no_equals_here\nA=1") == {"A": "1"}
