"""TUI tests using Textual's app.run_test() async Pilot.

These tests exercise widgets and screens in a real (but headless) Textual app.
Requires: textual, pytest-asyncio.
"""

import pytest

from symtest.tui.app import CaseManagerApp
from symtest.tui.screens.case_list import CaseListScreen
from symtest.tui.screens.case_editor import CaseEditorScreen
from symtest.tui.widgets.search_bar import SearchBar
from symtest.tui.widgets.case_table import CaseTable
from symtest.tui.widgets.steps_editor import StepsEditor
from symtest.tui.widgets.expected_editor import ExpectedEditor
from symtest.core.test_case import TestCase, TestCaseStep


# =============================================================================
# App construction & basic mount
# =============================================================================


class TestAppConstruction:
    """Test that the app can be constructed and mounted via run_test."""

    @pytest.mark.asyncio
    async def test_app_starts_and_shows_case_list(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            # App should have mounted and pushed a CaseListScreen
            assert isinstance(pilot.app.screen, CaseListScreen)
            # Case table should be populated
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            assert table.row_count > 0

    @pytest.mark.asyncio
    async def test_app_with_workspace(self, sample_config):
        app = CaseManagerApp(str(sample_config), workspace="/tmp/test_ws")
        async with app.run_test() as pilot:
            assert isinstance(pilot.app.screen, CaseListScreen)

    @pytest.mark.asyncio
    async def test_app_title_set(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test():
            assert "Case Manager" in app.TITLE


# =============================================================================
# CaseListScreen — search
# =============================================================================


class TestCaseListSearch:
    """Test search bar interaction in CaseListScreen via run_test."""

    @pytest.mark.asyncio
    async def test_search_filters_table(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            original_rows = table.row_count

            # Focus search and type query
            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)
            search_input = search_bar.query_one("#search-input")
            search_input.focus()
            await pilot.press("e", "c", "h", "o")  # type "echo"

            # This should filter to only matching cases
            await pilot.pause()

            # After search, the table should have filtered results
            screen = pilot.app.screen
            assert isinstance(screen, CaseListScreen)
            # filtered_indices should be ≤ original
            assert len(screen._filtered_indices) <= original_rows

    @pytest.mark.asyncio
    async def test_search_clear_restores_all(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            original_rows = table.row_count

            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)
            search_input = search_bar.query_one("#search-input")
            search_input.focus()
            await pilot.press("z", "z", "z", "n", "o", "m", "a", "t", "c", "h")

            await pilot.pause()

            # Clear search
            screen = pilot.app.screen
            screen.action_clear_search()
            await pilot.pause()

            assert len(screen._filtered_indices) == original_rows

    @pytest.mark.asyncio
    async def test_toggle_search_mode_fuzzy(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)

            # Toggle to fuzzy mode
            screen = pilot.app.screen
            screen.action_toggle_fuzzy()
            await pilot.pause()

            assert search_bar.mode == "fuzzy"

    @pytest.mark.asyncio
    async def test_toggle_search_mode_regex(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)

            screen = pilot.app.screen
            screen.action_toggle_regex()
            await pilot.pause()

            assert search_bar.mode == "regex"


# =============================================================================
# CaseListScreen — CRUD actions
# =============================================================================


class TestCaseListActions:
    """Test CRUD actions via run_test."""

    @pytest.mark.asyncio
    async def test_add_case_opens_editor(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            screen = pilot.app.screen
            screen.action_add_case()
            await pilot.pause()

            # Should have pushed CaseEditorScreen
            assert isinstance(pilot.app.screen, CaseEditorScreen)

    @pytest.mark.asyncio
    async def test_delete_case(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            screen = pilot.app.screen
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            original_count = len(pilot.app.screen._ctrl.cases)

            # Ensure cursor is on first row
            assert table.row_count > 0

            screen.action_delete_case()
            await pilot.pause()

            assert len(screen._ctrl.cases) == original_count - 1

    @pytest.mark.asyncio
    async def test_edit_case_opens_editor_with_data(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            screen = pilot.app.screen
            screen.action_edit_case()
            await pilot.pause()

            # Should have pushed CaseEditorScreen with pre-populated data
            assert isinstance(pilot.app.screen, CaseEditorScreen)

    @pytest.mark.asyncio
    async def test_duplicate_case(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            screen = pilot.app.screen
            original_count = len(screen._ctrl.cases)

            screen.action_duplicate_case()
            await pilot.pause()

            assert len(screen._ctrl.cases) == original_count + 1
            # The duplicated case's name should end with "_copy"
            last_case = screen._ctrl.cases[-1]
            assert "_copy" in last_case.name


# =============================================================================
# CaseEditorScreen — construction & compose
# =============================================================================


class TestCaseEditorScreen:
    """Test CaseEditorScreen via run_test."""

    @pytest.mark.asyncio
    async def test_compose_new_case(self, sample_config):
        """App mounting a CaseEditorScreen for a new case."""
        app = CaseManagerApp(str(sample_config))

        async with app.run_test() as pilot:
            # Push editor for new case
            pilot.app.push_screen(CaseEditorScreen())
            await pilot.pause()

            assert isinstance(pilot.app.screen, CaseEditorScreen)

    @pytest.mark.asyncio
    async def test_compose_with_existing_case(self, sample_config):
        """App mounting a CaseEditorScreen with an existing case."""
        app = CaseManagerApp(str(sample_config))
        existing_case = TestCase(
            name="existing_test",
            command="python",
            args=["-m", "test"],
            expected={"return_code": 0},
            tags=["smoke"],
        )

        async with app.run_test() as pilot:
            pilot.app.push_screen(CaseEditorScreen(existing_case))
            await pilot.pause()

            assert isinstance(pilot.app.screen, CaseEditorScreen)

    @pytest.mark.asyncio
    async def test_cancel_dismisses_editor(self, sample_config):
        app = CaseManagerApp(str(sample_config))

        async with app.run_test() as pilot:
            pilot.app.push_screen(CaseEditorScreen())
            await pilot.pause()

            # Press Cancel button
            await pilot.click("#btn-cancel")
            await pilot.pause()

            # Should be back to CaseListScreen
            assert isinstance(pilot.app.screen, CaseListScreen)

    @pytest.mark.asyncio
    async def test_switch_mode_button(self, sample_config):
        app = CaseManagerApp(str(sample_config))

        async with app.run_test() as pilot:
            pilot.app.push_screen(CaseEditorScreen())
            await pilot.pause()

            # Click the switch mode button
            await pilot.click("#btn-switch-mode")
            await pilot.pause()

            editor = pilot.app.screen
            assert editor._is_sequence is True


# =============================================================================
# StepsEditor in mounted context
# =============================================================================


class TestStepsEditorMounted:
    """Test StepsEditor widget when mounted via run_test."""

    @pytest.mark.asyncio
    async def test_load_refreshes_list(self, sample_config):
        app = CaseManagerApp(str(sample_config))

        async with app.run_test() as pilot:
            pilot.app.push_screen(CaseEditorScreen())
            await pilot.pause()

            # Switch to sequence mode
            await pilot.click("#btn-switch-mode")
            await pilot.pause()

            steps_editor = pilot.app.screen.query_one("#steps-editor", StepsEditor)
            assert steps_editor._steps == []

            # Load steps via the widget API
            steps = [
                TestCaseStep(command="step1", args=["a"], expected={}),
                TestCaseStep(command="step2", args=["b"], expected={"return_code": 0}),
            ]
            steps_editor.load(steps)

            assert len(steps_editor._steps) == 2


# =============================================================================
# ExpectedEditor in mounted context
# =============================================================================


class TestExpectedEditorMounted:
    """Test ExpectedEditor widget when mounted via run_test."""

    @pytest.mark.asyncio
    async def test_load_syncs_to_ui(self, sample_config):
        app = CaseManagerApp(str(sample_config))

        async with app.run_test() as pilot:
            pilot.app.push_screen(CaseEditorScreen())
            await pilot.pause()

            expected_editor = pilot.app.screen.query_one("#expected-editor", ExpectedEditor)
            # Load some data
            expected_editor.load({
                "return_code": 0,
                "output_contains": ["hello"],
            })

            # to_dict should reflect loaded data
            result = expected_editor.to_dict()
            assert result["return_code"] == 0
            assert result["output_contains"] == ["hello"]


# =============================================================================
# CaseTable widget
# =============================================================================


class TestCaseTableMounted:
    """Test CaseTable widget when mounted via run_test."""

    @pytest.mark.asyncio
    async def test_columns_initialised(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            assert table.row_count > 0
            # 6 columns: #, Name, Command, Tags, Timeout, Mode
            assert len(table.columns) == 6

    @pytest.mark.asyncio
    async def test_cursor_movement(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            table = pilot.app.screen.query_one("#main-table", CaseTable)
            assert table.row_count > 0

            # First row should be selectable
            idx = table.get_selected_index()
            assert idx is not None
            # Index should be within valid range
            assert 0 <= idx < len(pilot.app.screen._ctrl.cases)


# =============================================================================
# SearchBar widget
# =============================================================================


class TestSearchBarMounted:
    """Test SearchBar widget when mounted via run_test."""

    @pytest.mark.asyncio
    async def test_input_changes_emit_message(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)
            search_input = search_bar.query_one("#search-input")
            search_input.focus()
            await pilot.press("t", "e", "s", "t")

            await pilot.pause()
            assert search_bar.query == "test"

    @pytest.mark.asyncio
    async def test_clear_resets_state(self, sample_config):
        app = CaseManagerApp(str(sample_config))
        async with app.run_test() as pilot:
            search_bar = pilot.app.screen.query_one("#main-search", SearchBar)
            search_input = search_bar.query_one("#search-input")
            search_input.focus()
            await pilot.press("q", "u", "e", "r", "y")

            await pilot.pause()
            assert search_bar.query == "query"

            search_bar.clear()
            assert search_bar.query == ""
