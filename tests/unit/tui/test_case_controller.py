"""Tests for CaseController — CRUD, search, tags, load, save."""

from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from symtest.core.test_case import TestCase, TestStep
from symtest.core.config_loader import parse_test_cases
from symtest.tui.controllers.case_controller import CaseController
from symtest.config.normalize import normalize_draft_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(**kwargs) -> TestCase:
    defaults = {"name": "tc", "command": "echo", "args": ["hi"],
                "expected": {}, "tags": [], "description": ""}
    defaults.update(kwargs)
    return TestCase(**defaults)


def _seq_tc(steps=None, **kwargs) -> TestCase:
    defaults = {"name": "seq_tc", "steps": steps or [],
                "description": "", "tags": []}
    defaults.update(kwargs)
    return TestCase(**defaults)


def _step(cmd="echo", args=None, expected=None) -> TestStep:
    return TestStep.from_flat(command=cmd,
                        args=args or [],
                        expected=expected or {})


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestControllerInit:
    def test_initial_state(self):
        ctrl = CaseController()
        assert ctrl.cases == []
        assert ctrl.case_count == 0
        assert ctrl.file_path is None
        assert ctrl.workspace is None
        assert ctrl.dirty is False
        assert ctrl.file_name == "(untitled)"


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


class TestControllerLoad:
    @patch("symtest.tui.controllers.case_controller.load_config")
    def test_load_single_cmd_cases(self, mock_load):
        mock_load.return_value = {
            "test_cases": [
                {"name": "tc1", "execution": {"command": "echo", "args": ["hi"]},
                 "expected": {"return_code": 0}, "tags": ["smoke"]},
                {"name": "tc2", "execution": {"command": "ls", "args": ["-la"]},
                 "expected": {}, "tags": []},
            ]
        }
        ctrl = CaseController()
        count = ctrl.load("dummy.json")
        assert count == 2
        assert ctrl.case_count == 2
        assert ctrl.file_name == "dummy.json"
        assert ctrl.dirty is False

        assert ctrl.cases[0].name == "tc1"
        assert ctrl.cases[0].command == "echo"
        assert ctrl.cases[0].tags == ["smoke"]

    @patch("symtest.tui.controllers.case_controller.load_config")
    def test_load_sequence_cases(self, mock_load):
        mock_load.return_value = {
            "test_cases": [
                {"name": "multi_step",
                 "execution": {
                     "steps": [
                         {"command": "echo", "args": ["1"], "expected": {}},
                         {"command": "echo", "args": ["2"], "expected": {}},
                     ],
                 },
                 "tags": ["seq"]},
            ]
        }
        ctrl = CaseController()
        ctrl.load("seq.json")
        assert ctrl.case_count == 1
        assert ctrl.cases[0].steps is not None
        assert len(ctrl.cases[0].steps) == 2
        assert ctrl.cases[0].steps[0].command == "echo"

    @patch("symtest.tui.controllers.case_controller.load_config")
    def test_load_preserves_setup(self, mock_load):
        mock_load.return_value = {
            "setup": {"workspace": "/tmp"},
            "test_cases": [{"name": "tc1", "execution": {"command": "echo", "args": []},
                            "expected": {}}],
        }
        ctrl = CaseController()
        ctrl.load("with_setup.json")
        # Setup is stored internally for re-serialisation
        assert ctrl._setup == {"workspace": "/tmp"}

    @patch("symtest.tui.controllers.case_controller.load_config")
    def test_load_stores_workspace(self, mock_load):
        mock_load.return_value = {"test_cases": []}
        ctrl = CaseController()
        ctrl.load("d.json", workspace="/my/workspace")
        assert ctrl.workspace == "/my/workspace"


class TestControllerSave:
    @patch("symtest.tui.controllers.case_controller.load_config")
    @patch("symtest.tui.controllers.case_controller.save_config")
    def test_save_writes_cases(self, mock_save, mock_load):
        mock_load.return_value = {
            "test_cases": [
                {"name": "tc1", "execution": {"command": "echo", "args": []},
                 "expected": {}, "tags": []},
            ]
        }
        ctrl = CaseController()
        ctrl.load("dummy.json")
        mock_save.reset_mock()

        ctrl.add_case(_tc(name="new_case"))
        ctrl.save()

        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        config_dict = args[0]
        assert len(config_dict["test_cases"]) == 2
        assert ctrl.dirty is False

    @patch("symtest.tui.controllers.case_controller.load_config")
    @patch("symtest.tui.controllers.case_controller.save_config")
    def test_save_as_new_path(self, mock_save, mock_load):
        mock_load.return_value = {"test_cases": []}
        ctrl = CaseController()
        ctrl.load("original.json")
        mock_save.reset_mock()

        ctrl.save_as("new_path.json")
        mock_save.assert_called_once()
        assert ctrl.file_name == "new_path.json"

    def test_save_without_file_path_raises(self):
        ctrl = CaseController()
        with pytest.raises(ValueError, match="No file path"):
            ctrl.save()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestControllerCRUD:
    @pytest.fixture
    def ctrl(self):
        c = CaseController()
        c._cases = [
            _tc(name="tc0"),
            _tc(name="tc1"),
            _tc(name="tc2"),
        ]
        c._dirty = False
        return c

    def test_get_case(self, ctrl):
        assert ctrl.get_case(1).name == "tc1"

    def test_get_case_out_of_range_raises(self, ctrl):
        with pytest.raises(IndexError):
            ctrl.get_case(10)

    def test_add_case(self, ctrl):
        idx = ctrl.add_case(_tc(name="new"))
        assert idx == 3
        assert ctrl.case_count == 4
        assert ctrl.dirty is True

    def test_update_case(self, ctrl):
        new_tc = _tc(name="updated")
        ctrl.update_case(1, new_tc)
        assert ctrl.cases[1].name == "updated"
        assert ctrl.dirty is True

    def test_delete_case(self, ctrl):
        ctrl.delete_case(1)
        assert ctrl.case_count == 2
        assert ctrl.cases[0].name == "tc0"
        assert ctrl.cases[1].name == "tc2"
        assert ctrl.dirty is True

    def test_duplicate_case(self, ctrl):
        new_idx = ctrl.duplicate_case(0)
        assert ctrl.case_count == 4
        assert ctrl.cases[new_idx].name == "tc0_copy"
        # Should be a deep copy, not the same object
        assert ctrl.cases[new_idx] is not ctrl.cases[0]
        assert ctrl.dirty is True

    def test_move_case_forward(self, ctrl):
        ctrl.move_case(0, 2)
        assert [tc.name for tc in ctrl.cases] == ["tc1", "tc2", "tc0"]

    def test_move_case_backward(self, ctrl):
        ctrl.move_case(2, 0)
        assert [tc.name for tc in ctrl.cases] == ["tc2", "tc0", "tc1"]

    def test_move_case_noop(self, ctrl):
        ctrl.move_case(1, 1)
        assert [tc.name for tc in ctrl.cases] == ["tc0", "tc1", "tc2"]
        # No-op should NOT set dirty
        assert ctrl.dirty is False

    def test_swap_cases(self, ctrl):
        ctrl.swap_cases(0, 2)
        assert [tc.name for tc in ctrl.cases] == ["tc2", "tc1", "tc0"]
        assert ctrl.dirty is True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestControllerSearch:
    @pytest.fixture
    def ctrl(self):
        c = CaseController()
        c._cases = [
            _tc(name="alpha", command="echo", args=["a"], tags=["smoke"],
                description="first test"),
            _tc(name="beta", command="python", args=["-c", "pass"],
                tags=["regression"], description="second test"),
            _tc(name="gamma", command="echo", args=["g"],
                tags=["smoke", "slow"], description=""),
        ]
        return c

    def test_substring_search(self, ctrl):
        indices = ctrl.search("echo")
        assert indices == [0, 2]

    def test_substring_search_in_name(self, ctrl):
        indices = ctrl.search("alpha")
        assert indices == [0]

    def test_substring_search_in_description(self, ctrl):
        indices = ctrl.search("first")
        assert indices == [0]

    def test_substring_search_no_match(self, ctrl):
        indices = ctrl.search("nonexistent")
        assert indices == []

    def test_fuzzy_search(self, ctrl):
        indices = ctrl.search("alpha", mode="fuzzy")
        assert 0 in indices

    def test_regex_search(self, ctrl):
        indices = ctrl.search(r"^echo$", mode="regex")
        assert indices == [0, 2]

    def test_search_with_tag_filter(self, ctrl):
        indices = ctrl.search("echo", tag="slow")
        assert indices == [2]

    def test_search_tag_filter_no_match(self, ctrl):
        indices = ctrl.search("echo", tag="regression")
        assert indices == []

    def test_empty_query_matches_all(self, ctrl):
        indices = ctrl.search("")
        assert len(indices) == 3

    def test_invalid_regex_returns_empty(self, ctrl):
        indices = ctrl.search("[unclosed", mode="regex")
        # Invalid regex causes each _regex_match to return False
        assert indices == []


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


class TestControllerTags:
    def test_get_all_tags(self):
        ctrl = CaseController()
        ctrl._cases = [
            _tc(name="a", tags=["smoke", "fast"]),
            _tc(name="b", tags=["slow"]),
            _tc(name="c", tags=["smoke", "regression"]),
        ]
        tags = ctrl.get_all_tags()
        assert tags == ["fast", "regression", "slow", "smoke"]

    def test_get_all_tags_empty(self):
        ctrl = CaseController()
        ctrl._cases = []
        assert ctrl.get_all_tags() == []

    def test_get_all_tags_no_tags(self):
        ctrl = CaseController()
        ctrl._cases = [_tc(name="a", tags=[])]
        assert ctrl.get_all_tags() == []


# ---------------------------------------------------------------------------
# Create Empty Case
# ---------------------------------------------------------------------------


class TestCreateEmptyCase:
    def test_single_mode(self):
        tc = CaseController.create_empty_case("single")
        assert tc.name == "new_case"
        assert tc.command == ""
        assert tc.args == []
        assert tc.expected == {}
        assert tc.steps is None

    def test_sequence_mode(self):
        tc = CaseController.create_empty_case("sequence")
        assert tc.name == "new_case"
        assert tc.steps == []
        assert tc.command == ""

    def test_default_is_single(self):
        tc = CaseController.create_empty_case()
        assert tc.steps is None
        assert tc.command == ""


# ---------------------------------------------------------------------------
# Dirty flag
# ---------------------------------------------------------------------------


class TestDirtyFlag:
    def test_load_resets_dirty(self):
        ctrl = CaseController()
        ctrl._dirty = True
        with patch("symtest.tui.controllers.case_controller.load_config",
                   return_value={"test_cases": []}):
            ctrl.load("dummy.json")
        assert ctrl.dirty is False

    def test_save_resets_dirty(self):
        ctrl = CaseController()
        ctrl._file_path = Path("/tmp/test.json")
        ctrl._dirty = True
        with patch("symtest.tui.controllers.case_controller.save_config"):
            ctrl.save()
        assert ctrl.dirty is False


# ---------------------------------------------------------------------------
# Parse from dict (static method)
# ---------------------------------------------------------------------------


class TestParseFromDict:
    """TUI 宽松形态自处理（原则 6）：draft 先 normalize 再走严格 parser。"""

    def test_single_cmd_case(self):
        result = parse_test_cases(normalize_draft_config({"test_cases": [
            {"name": "simple", "execution": {"command": "echo", "args": ["hello"]},
             "expected": {"return_code": 0}, "tags": ["demo"]},
        ]}))
        assert len(result) == 1
        tc = result[0]
        assert tc.name == "simple"
        assert tc.command == "echo"
        assert tc.steps is None
        assert tc.tags == ["demo"]

    def test_sequence_case(self):
        result = parse_test_cases(normalize_draft_config({"test_cases": [
            {"name": "seq",
             "execution": {
                 "steps": [
                     {"command": "step1", "args": ["a"], "expected": {}},
                     {"command": "step2", "args": ["b"], "expected": {"return_code": 1}},
                 ],
             }},
        ]}))
        assert len(result) == 1
        tc = result[0]
        assert tc.name == "seq"
        assert tc.steps is not None
        assert len(tc.steps) == 2
        assert tc.steps[1].command == "step2"
        assert tc.steps[1].expected == {"return_code": 1}

    def test_missing_fields_get_defaults(self):
        result = parse_test_cases(normalize_draft_config({"test_cases": [
            {"name": "minimal"},
        ]}))
        tc = result[0]
        assert tc.command == ""
        assert tc.args == []
        assert tc.expected == {}
        assert tc.tags == []
        assert tc.description == ""

    def test_empty_list(self):
        assert parse_test_cases({"test_cases": []}) == []

    def test_step_timeout(self):
        result = parse_test_cases(normalize_draft_config({"test_cases": [
            {"name": "with_timeout",
             "execution": {
                 "steps": [{"command": "sleep", "args": ["10"], "expected": {},
                            "timeout": 30.0}],
             }},
        ]}))
        tc = result[0]
        assert tc.steps[0].timeout == 30.0

    def test_strict_parser_rejects_incomplete_case(self):
        """core parser 无宽松模式：半成品未经 normalize 直接解析即报错。"""
        with pytest.raises(ValueError):
            parse_test_cases({"test_cases": [{"name": "minimal"}]})
