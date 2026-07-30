"""Unit tests for built-in ScriptComparator."""
import os
import sys
from pathlib import Path

import pytest

from cli_test_framework.file_comparator.script_comparator import ScriptComparator


_FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.fixture
def mock_pass():
    return str(_FIXTURES / "mock_pass_script.py")


@pytest.fixture
def mock_fail():
    return str(_FIXTURES / "mock_fail_script.py")


class TestScriptComparatorPass:
    def test_exit_code_zero_is_pass(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass)
        result = cmp.compare_files()
        assert result.identical is True
        assert "PASS" in (result.command_output or "")

    def test_pass_pattern_match(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass, pass_pattern=r"PASS")
        result = cmp.compare_files()
        assert result.identical is True

    def test_pass_pattern_no_match_is_fail(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass, pass_pattern=r"NO_MATCH")
        result = cmp.compare_files()
        assert result.identical is False
        assert any("pass_pattern_missing" == d.diff_type for d in result.differences)


class TestScriptComparatorFail:
    def test_nonzero_exit_is_fail(self, mock_fail):
        cmp = ScriptComparator(script=mock_fail)
        result = cmp.compare_files()
        assert result.identical is False
        assert any("exit_code_mismatch" == d.diff_type for d in result.differences)

    def test_fail_pattern_override(self, mock_fail):
        """fail_pattern match forces fail regardless of exit code."""
        cmp = ScriptComparator(script=mock_fail, fail_pattern=r"MISMATCH")
        result = cmp.compare_files()
        assert result.identical is False
        assert any("fail_pattern_match" == d.diff_type for d in result.differences)

    def test_fail_pattern_ignores_pass(self, mock_pass):
        """fail_pattern forces fail even when exit code is 0."""
        cmp = ScriptComparator(
            script=mock_pass, fail_pattern=r"PASS",
        )
        result = cmp.compare_files()
        assert result.identical is False
        assert any("fail_pattern_match" == d.diff_type for d in result.differences)


class TestScriptComparatorEdge:
    def test_command_output_captured(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass)
        result = cmp.compare_files()
        assert result.command_output is not None
        assert "PASS" in result.command_output

    def test_args_forwarded(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass, args=["alpha", "beta"])
        result = cmp.compare_files()
        assert result.identical is True

    def test_file_args_forwarded(self, mock_pass):
        cmp = ScriptComparator(script=mock_pass)
        result = cmp.compare_files(file1="f1.txt", file2="f2.txt")
        assert result.identical is True
        assert "f1.txt" in (result.command_output or "")
