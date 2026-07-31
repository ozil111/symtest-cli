"""Tests for TUI widget data models — StepsEditor._steps, ExpectedEditor._data.

These tests exercise the internal data layer of widgets without requiring
the Textual app to be running.  ``load()`` / ``to_steps()`` / ``to_dict()``
work against the internal state even when the widget is not mounted.
"""

import copy
import pytest

from cli_test_framework.core.test_case import TestCaseStep
from cli_test_framework.tui.widgets.steps_editor import StepsEditor
from cli_test_framework.tui.widgets.expected_editor import ExpectedEditor


def _step(cmd="echo", args=None, expected=None, timeout=None, retry_count=0):
    return TestCaseStep(
        command=cmd,
        args=args or [],
        expected=expected or {},
        timeout=timeout,
        retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# StepsEditor data layer
# ---------------------------------------------------------------------------


class TestStepsEditorData:
    """Test StepsEditor._steps and its load/to_steps methods (no mount)."""

    def test_initial_state_empty(self):
        editor = StepsEditor()
        assert editor._steps == []
        assert editor.to_steps() == []

    def test_load_and_to_steps_roundtrip(self):
        editor = StepsEditor()
        original = [
            _step("echo", ["hello"], {"return_code": 0}),
            _step("python", ["-c", "print(1)"], {"output_contains": ["1"]}),
        ]
        editor.load(original)
        result = editor.to_steps()
        assert len(result) == 2
        assert result[0].command == "echo"
        assert result[0].args == ["hello"]
        assert result[1].command == "python"

    def test_load_creates_deep_copy(self):
        editor = StepsEditor()
        original = [_step("echo", ["hello"])]
        editor.load(original)
        # Modify original — should not affect editor
        original[0].args.append("world")
        assert editor.to_steps()[0].args == ["hello"]

    def test_to_steps_creates_deep_copy(self):
        editor = StepsEditor()
        editor.load([_step("echo", ["hello"])])
        result = editor.to_steps()
        result[0].args.append("world")
        assert editor._steps[0].args == ["hello"]

    def test_empty_steps_list(self):
        editor = StepsEditor()
        editor.load([])
        assert editor.to_steps() == []

    def test_steps_with_timeout(self):
        editor = StepsEditor()
        editor.load([_step("sleep", timeout=10.0)])
        result = editor.to_steps()
        assert result[0].timeout == 10.0

    def test_steps_with_retry_count(self):
        editor = StepsEditor()
        editor.load([_step("flaky", retry_count=3)])
        result = editor.to_steps()
        assert result[0].retry_count == 3

    def test_steps_default_retry_count(self):
        editor = StepsEditor()
        editor.load([_step("stable")])
        result = editor.to_steps()
        assert result[0].retry_count == 0

    def test_steps_with_empty_args(self):
        editor = StepsEditor()
        editor.load([_step("echo")])
        result = editor.to_steps()
        assert result[0].args == []

    def test_editing_idx_initial(self):
        editor = StepsEditor()
        assert editor._editing_idx == -1

    def test_load_resets_editing_idx(self):
        editor = StepsEditor()
        editor._editing_idx = 3
        editor.load([_step("echo")])
        assert editor._editing_idx == -1


# ---------------------------------------------------------------------------
# ExpectedEditor data layer
# ---------------------------------------------------------------------------


class TestExpectedEditorData:
    """Test ExpectedEditor._data and its load/to_dict methods (no mount)."""

    def test_initial_state_empty(self):
        editor = ExpectedEditor()
        assert editor._data == {}
        assert editor.to_dict() == {}

    def test_load_and_to_dict_roundtrip(self):
        editor = ExpectedEditor()
        original = {
            "return_code": 0,
            "output_contains": ["hello", "world"],
            "output_matches": r"\d+",
        }
        editor.load(original)
        result = editor.to_dict()
        assert result == original

    def test_load_creates_deep_copy(self):
        editor = ExpectedEditor()
        original = {"output_contains": ["hello"]}
        editor.load(original)
        original["output_contains"].append("world")
        assert editor.to_dict()["output_contains"] == ["hello"]

    def test_to_dict_creates_deep_copy(self):
        editor = ExpectedEditor()
        editor.load({"return_code": 0})
        result = editor.to_dict()
        result["extra"] = "should_not_persist"
        assert "extra" not in editor._data

    def test_load_complex_expected(self):
        editor = ExpectedEditor()
        original = {
            "return_code": 1,
            "output_contains": ["ok"],
            "output_matches": r"^done$",
            "compare_files": [
                {"actual": "a.txt", "baseline": "b.txt", "type": "text"},
            ],
        }
        editor.load(original)
        result = editor.to_dict()
        assert result["return_code"] == 1
        assert result["compare_files"][0]["type"] == "text"

    def test_load_empty_dict(self):
        editor = ExpectedEditor()
        editor.load({})
        assert editor.to_dict() == {}

    def test_load_custom_keys(self):
        editor = ExpectedEditor()
        original = {
            "return_code": 0,
            "custom_key": "custom_value",
            "nested": {"a": 1},
        }
        editor.load(original)
        result = editor.to_dict()
        assert result["custom_key"] == "custom_value"
        assert result["nested"] == {"a": 1}

    def test_load_multiple_times_overwrites(self):
        editor = ExpectedEditor()
        editor.load({"return_code": 0})
        editor.load({"return_code": 1})
        assert editor.to_dict() == {"return_code": 1}

    def test_to_dict_when_not_mounted_does_not_sync(self):
        """When not mounted, to_dict returns the internal _data as-is."""
        editor = ExpectedEditor()
        editor._data = {"return_code": 42}
        result = editor.to_dict()
        assert result["return_code"] == 42
