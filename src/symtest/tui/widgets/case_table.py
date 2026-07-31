"""DataTable wrapper for displaying test cases."""

from __future__ import annotations

from textual.widgets import DataTable
from textual.coordinate import Coordinate

from ...core.test_case import TestCase


class CaseTable(DataTable):
    """DataTable pre-configured for test case display."""

    DEFAULT_CSS = """
    CaseTable {
        height: 1fr;
        min-height: 5;
    }
    """

    COLUMNS = ("#", "Name", "Command", "Tags", "Timeout", "Mode")

    def __init__(self, *args, **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, *args, **kwargs)
        self._case_indices: list[int] = []
        self._all_tags: list[str] = []
        self._filtered_tag: str | None = None

    def on_mount(self) -> None:
        for col in self.COLUMNS:
            self.add_column(col, key=col.lower())

    # -- public API ----------------------------------------------------------

    def refresh_rows(self, cases: list[TestCase], indices: list[int]) -> None:
        """Clear table and repopulate with the cases at *indices*."""
        self.clear()
        self._case_indices = list(indices)
        for i, ci in enumerate(indices):
            tc = cases[ci]
            mode = "seq" if tc.steps else "cmd"
            tags = ",".join(tc.tags) if tc.tags else "-"
            timeout = str(tc.timeout) if tc.timeout else "-"
            self.add_row(
                str(i + 1),
                tc.name,
                self._truncate(tc.command, 30),
                tags,
                timeout,
                mode,
                key=str(ci),
            )

    def get_selected_index(self) -> int | None:
        """Return the case index of the currently selected row."""
        if self.row_count == 0:
            return None
        row_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        if row_key is not None:
            return int(str(row_key.row_key.value))
        return None

    def select_row_by_index(self, case_index: int) -> None:
        """Move cursor to the row corresponding to *case_index*."""
        try:
            row_key = self._row_key_for_case(case_index)
            if row_key is not None:
                self.move_cursor(row=row_key)
        except Exception:
            pass

    def select_next_match(self) -> int | None:
        """Move down one row; return new selected case index."""
        if self.row_count == 0:
            return None
        cr = self.cursor_coordinate
        new_row = min(cr.row + 1, self.row_count - 1)
        self.move_cursor(row=new_row)
        return self.get_selected_index()

    def select_prev_match(self) -> int | None:
        """Move up one row; return new selected case index."""
        if self.row_count == 0:
            return None
        cr = self.cursor_coordinate
        new_row = max(cr.row - 1, 0)
        self.move_cursor(row=new_row)
        return self.get_selected_index()

    # -- tag filter ----------------------------------------------------------

    def set_all_tags(self, tags: list[str]) -> None:
        self._all_tags = list(tags)

    @property
    def filtered_tag(self) -> str | None:
        return self._filtered_tag

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 2] + ".."

    def _row_key_for_case(self, case_index: int) -> object | None:
        """Find the row key for a given *case_index*."""
        for i in range(self.row_count):
            key = self.coordinate_to_cell_key(Coordinate(i, 0))
            if key is not None and str(key.row_key.value) == str(case_index):
                return key.row_key
        return None
