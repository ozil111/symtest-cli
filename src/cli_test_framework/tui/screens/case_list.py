"""Main screen: case table + search bar + status."""

from __future__ import annotations

from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual.containers import Horizontal, Container
from textual.binding import Binding

from ..controllers.case_controller import CaseController
from ..widgets.case_table import CaseTable
from ..widgets.search_bar import SearchBar
from .case_editor import CaseEditorScreen


class CaseListScreen(Screen):
    """Primary TUI screen showing the test case table."""

    BINDINGS = [
        Binding("/", "focus_search", "Search", show=True),
        Binding("escape", "clear_search", "Clear search", show=True),
        Binding("a", "add_case", "Add", show=True),
        Binding("e", "edit_case", "Edit", show=True),
        Binding("d", "delete_case", "Delete", show=True),
        Binding("u", "duplicate_case", "Dup", show=True),
        Binding("r", "run_case", "Run", show=True),
        Binding("f6", "save_file", "Save", show=True),
        Binding("ctrl+s", "save_file", "Save", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "next_match", "Next", show=False),
        Binding("shift+enter", "prev_match", "Prev", show=False),
        Binding("up", "cursor_up", "", show=False),
        Binding("down", "cursor_down", "", show=False),
        Binding("alt+f", "toggle_fuzzy", "", show=False),
        Binding("alt+r", "toggle_regex", "", show=False),
        Binding("alt+s", "toggle_substring", "", show=False),
    ]

    DEFAULT_CSS = """
    CaseListScreen {
        align: center middle;
    }
    CaseListScreen #status-bar {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    CaseListScreen #status-bar Static {
        width: 1fr;
    }
    """

    def __init__(self, controller: CaseController):
        super().__init__()
        self._ctrl = controller
        self._filtered_indices: list[int] = list(range(len(controller.cases)))
        self._cur_match: int = 0
        self._current_tag: str | None = None

    def compose(self):
        yield Header()
        yield SearchBar(id="main-search")
        yield CaseTable(id="main-table")
        yield Container(
            Horizontal(
                Static(f"File: {self._ctrl.file_name}", id="status-file"),
                Static(f"{self._ctrl.case_count} cases", id="status-count"),
                Static("Tag: All", id="status-tag"),
                Static("", id="status-dirty"),
                id="status-inner",
            ),
            id="status-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()
        self._update_status()

    # -- table refresh -------------------------------------------------------

    def _refresh_table(self) -> None:
        table = self.query_one("#main-table", CaseTable)
        table.refresh_rows(self._ctrl.cases, self._filtered_indices)

    def _update_status(self) -> None:
        self.query_one("#status-count", Static).update(
            f"{len(self._filtered_indices)}/{self._ctrl.case_count} cases"
        )
        tag_label = self.query_one("#status-tag", Static)
        tag_label.update(f"Tag: {self._current_tag or 'All'}")
        dirty = self._ctrl.dirty
        self.query_one("#status-dirty", Static).update(
            "[MODIFIED]" if dirty else ""
        )

    # -- search handling -----------------------------------------------------

    def on_search_bar_search_changed(self, event: SearchBar.SearchChanged) -> None:
        sb = self.query_one("#main-search", SearchBar)
        self._filtered_indices = self._ctrl.search(
            event.query, event.mode, self._current_tag
        )
        self._cur_match = 0
        sb.set_match_count(len(self._filtered_indices), 0)
        self._refresh_table()
        self._update_status()
        # Select first match
        if self._filtered_indices:
            table = self.query_one("#main-table", CaseTable)
            table.select_row_by_index(self._filtered_indices[0])
            self._cur_match = 1
            sb.set_match_count(len(self._filtered_indices), 1)

    def on_search_bar_search_navigated(self, event: SearchBar.SearchNavigated) -> None:
        sb = self.query_one("#main-search", SearchBar)
        table = self.query_one("#main-table", CaseTable)
        if event.delta > 0:
            table.select_next_match()
        else:
            table.select_prev_match()
        # Update current match display
        if self._filtered_indices and table.cursor_coordinate.row < len(self._filtered_indices):
            self._cur_match = table.cursor_coordinate.row + 1
            sb.set_match_count(len(self._filtered_indices), self._cur_match)

    # -- actions -------------------------------------------------------------

    def action_focus_search(self) -> None:
        sb = self.query_one("#main-search", SearchBar)
        sb.query_one("#search-input").focus()

    def action_clear_search(self) -> None:
        self.query_one("#main-search", SearchBar).clear()
        self._filtered_indices = list(range(len(self._ctrl.cases)))
        self._refresh_table()
        self._update_status()

    def action_add_case(self) -> None:
        self.app.push_screen(
            CaseEditorScreen(),
            callback=self._on_editor_done,
        )

    def action_edit_case(self) -> None:
        idx = self._get_current_case_index()
        if idx is None:
            self.notify("No case selected", severity="warning")
            return
        case = self._ctrl.get_case(idx)
        self.app.push_screen(
            CaseEditorScreen(case),
            callback=lambda msg: self._on_editor_done(msg, original_idx=idx),
        )

    def action_delete_case(self) -> None:
        idx = self._get_current_case_index()
        if idx is None:
            self.notify("No case selected", severity="warning")
            return
        case_name = self._ctrl.get_case(idx).name
        self._ctrl.delete_case(idx)
        self.notify(f"Deleted: {case_name}")
        self._refresh_filtered()
        self._update_status()

    def action_duplicate_case(self) -> None:
        idx = self._get_current_case_index()
        if idx is None:
            self.notify("No case selected", severity="warning")
            return
        new_idx = self._ctrl.duplicate_case(idx)
        self.notify(f"Duplicated as: {self._ctrl.get_case(new_idx).name}")
        self._refresh_filtered()
        self._update_status()

    def action_run_case(self) -> None:
        idx = self._get_current_case_index()
        if idx is None:
            self.notify("No case selected", severity="warning")
            return
        case = self._ctrl.get_case(idx)
        self.notify(f"Running: {case.name}...")
        try:
            result = self._ctrl.run_case(idx)
            status_icon = "[OK]" if result["status"] == "passed" else "[FAIL]"
            # Build rich status line with new result fields
            parts = [f"{status_icon} {case.name}"]
            parts.append(f"rc={result.get('return_code')}")
            parts.append(f"{result.get('duration', 0):.2f}s")
            # Failure kind
            if result.get("failure_kind"):
                parts.append(f"kind={result['failure_kind']}")
            # Flaky / attempts
            if result.get("flaky"):
                parts.append(f"flaky ({result.get('attempts', 1)} attempts)")
            elif result.get("attempts", 1) > 1:
                parts.append(f"{result['attempts']} attempts")
            # Failed step (sequence)
            if result.get("failed_step"):
                parts.append(f"step={result['failed_step']}")
            self.notify(
                " | ".join(parts),
                severity="information" if result["status"] == "passed" else "error",
            )
            # Show error message separately for failed cases
            if result["status"] != "passed" and result.get("message"):
                self.notify(f"[ERROR] {result['message']}", severity="error")
            # Show baseline updates
            if result.get("baseline_updated"):
                for bu in result["baseline_updated"]:
                    self.notify(f"[BASELINE UPDATED] {bu}", severity="information")
        except Exception as e:
            self.notify(f"Run error: {e}", severity="error")

    def action_save_file(self) -> None:
        try:
            self._ctrl.save()
            self.notify(f"Saved to {self._ctrl.file_name}")
            self._update_status()
        except Exception as e:
            self.notify(f"Save error: {e}", severity="error")

    def action_toggle_fuzzy(self) -> None:
        self.query_one("#main-search", SearchBar).action_toggle_fuzzy()

    def action_toggle_regex(self) -> None:
        self.query_one("#main-search", SearchBar).action_toggle_regex()

    def action_toggle_substring(self) -> None:
        self.query_one("#main-search", SearchBar).action_toggle_substring()

    # -- helpers -------------------------------------------------------------

    def _get_current_case_index(self) -> int | None:
        table = self.query_one("#main-table", CaseTable)
        return table.get_selected_index()

    def _refresh_filtered(self) -> None:
        sb = self.query_one("#main-search", SearchBar)
        self._filtered_indices = self._ctrl.search(
            sb.query, sb.mode, self._current_tag
        )
        self._refresh_table()
        self._update_status()

    def _on_editor_done(self, msg, original_idx=None) -> None:
        if isinstance(msg, CaseEditorScreen.Saved):
            if original_idx is not None:
                self._ctrl.update_case(original_idx, msg.case)
            else:
                self._ctrl.add_case(msg.case)
            self._refresh_filtered()
            self._update_status()
