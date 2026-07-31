"""Textual App entry point for the TUI manager.

Usage::

    from symtest.tui.app import run_tui
    run_tui("test_cases.json", workspace="/path/to/project")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding

from .controllers.case_controller import CaseController
from .screens.case_list import CaseListScreen


class CaseManagerApp(App):
    """Terminal UI for browsing / editing / running test cases."""

    TITLE = "CLI Test Framework - Case Manager"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("q", "quit", "Quit", show=True, priority=True),
    ]

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, config_file: str, workspace: Optional[str] = None,
                 update_baseline: bool = False,
                 history_dir: Optional[str] = None,
                 update_history: bool = False):
        super().__init__()
        self._config_file = config_file
        self._workspace = workspace
        self._controller = CaseController()
        self._controller.update_baseline = update_baseline
        self._controller.history_dir = history_dir
        self._controller.update_history = update_history

    def on_mount(self) -> None:
        try:
            count = self._controller.load(self._config_file, self._workspace)
            self.notify(f"Loaded {count} test cases from {Path(self._config_file).name}")
        except Exception as e:
            self.notify(f"Failed to load config: {e}", severity="error")

        self.push_screen(CaseListScreen(self._controller))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_tui(config_file: str, workspace: Optional[str] = None,
            update_baseline: bool = False,
            history_dir: Optional[str] = None,
            update_history: bool = False) -> None:
    """Launch the TUI manager.

    Safe to call without installing textual — raises :exc:`ImportError`
    with a friendly message if textual is not available.
    """
    try:
        import textual  # noqa: F401 — verify textual is importable
    except ImportError:
        import sys

        print(
            "TUI 功能需要安装 textual。请运行：\n"
            "  pip install symtest[tui]\n"
            "或：\n"
            "  pip install textual"
        )
        sys.exit(1)

    app = CaseManagerApp(config_file, workspace,
                         update_baseline=update_baseline,
                         history_dir=history_dir,
                         update_history=update_history)
    app.run()
