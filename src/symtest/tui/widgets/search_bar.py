"""Search bar widget with multi-mode search (substring / fuzzy / regex).

Emits :class:`SearchChanged` when the query text or mode changes, and
:class:`SearchNavigated` when the user cycles through matches.
"""

from __future__ import annotations

from textual import on
from textual.widgets import Input, Static
from textual.containers import Horizontal
from textual.message import Message


class SearchBar(Horizontal):
    """A search bar with mode toggle and result count."""

    DEFAULT_CSS = """
    SearchBar {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    SearchBar #search-input {
        width: 40;
    }
    SearchBar #search-mode {
        width: 12;
        padding: 0 1;
        color: $text-muted;
    }
    SearchBar #search-count {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    # Maps keyboard modifiers to modes
    _MODES = {
        0: "substring",
        2: "regex",   # Alt pressed
        4: "fuzzy",   # Ctrl pressed → fuzzy mode
    }

    class SearchChanged(Message):
        """Emitted when search query or mode changes."""

        def __init__(self, query: str, mode: str):
            super().__init__()
            self.query = query
            self.mode = mode

    class SearchNavigated(Message):
        """Emitted to jump to match N."""

        def __init__(self, delta: int):
            super().__init__()
            self.delta = delta

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = ""
        self._mode: str = "substring"
        self._match_count = 0
        self._history: list[str] = []
        self._history_idx = -1

    def compose(self):
        yield Input(placeholder="Search...", id="search-input")
        yield Static("[子串]", id="search-mode")
        yield Static("", id="search-count")

    # -- mode toggle via key bindings ----------------------------------------

    def _handle_mode_toggle(self, mode: str, label: str) -> None:
        if self._mode != mode:
            self._mode = mode
            self.query_one("#search-mode", Static).update(label)
            self.post_message(self.SearchChanged(self._query, self._mode))

    def action_toggle_substring(self) -> None:
        self._handle_mode_toggle("substring", "[子串]")

    def action_toggle_fuzzy(self) -> None:
        self._handle_mode_toggle("fuzzy", "[模糊]")

    def action_toggle_regex(self) -> None:
        self._handle_mode_toggle("regex", "[正则]")

    # -- input handling ------------------------------------------------------

    @on(Input.Changed, "#search-input")
    def _on_input_changed(self, event: Input.Changed) -> None:
        self._query = event.value.strip()
        self.post_message(self.SearchChanged(self._query, self._mode))

    @on(Input.Submitted, "#search-input")
    def _on_input_submitted(self, _event: Input.Submitted) -> None:
        # Add to history (dedup, keep last 10)
        if self._query and (not self._history or self._history[-1] != self._query):
            self._history.append(self._query)
            if len(self._history) > 10:
                self._history.pop(0)
        self._history_idx = -1
        self.post_message(self.SearchNavigated(1))

    # -- public API ----------------------------------------------------------

    def set_match_count(self, total: int, current: int = 0) -> None:
        """Update the match counter display."""
        self._match_count = total
        label = f"{current}/{total}" if total > 0 else ""
        self.query_one("#search-count", Static).update(label)

    def clear(self) -> None:
        """Reset search bar."""
        inp = self.query_one("#search-input", Input)
        inp.clear()
        self._query = ""
        self._match_count = 0
        self.query_one("#search-count", Static).update("")

    def history_previous(self) -> None:
        """Cycle to previous history entry."""
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        text = self._history[self._history_idx]
        inp = self.query_one("#search-input", Input)
        inp.value = text
        self._query = text
        self.post_message(self.SearchChanged(self._query, self._mode))

    def history_next(self) -> None:
        if not self._history or self._history_idx == -1:
            return
        self._history_idx += 1
        if self._history_idx >= len(self._history):
            self._history_idx = -1
            inp = self.query_one("#search-input", Input)
            inp.value = ""
            self._query = ""
        else:
            text = self._history[self._history_idx]
            inp = self.query_one("#search-input", Input)
            inp.value = text
            self._query = text
        self.post_message(self.SearchChanged(self._query, self._mode))

    @property
    def query(self) -> str:
        return self._query

    @property
    def mode(self) -> str:
        return self._mode
