"""Screen for editing a single test case (both single-cmd and sequence modes)."""

from __future__ import annotations

from textual import on
from textual.screen import Screen
from textual.widgets import Input, TextArea, Static, Button, Header, Footer, Label
from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
from textual.message import Message

from ...core.test_case import TestCase
from ..widgets.expected_editor import ExpectedEditor
from ..widgets.steps_editor import StepsEditor


class CaseEditorScreen(Screen):
    """Full-screen form for creating / editing a test case."""

    DEFAULT_CSS = """
    CaseEditorScreen {
        align: center middle;
    }
    CaseEditorScreen #editor-container {
        width: 90%;
        height: 90%;
        border: solid $primary;
        padding: 1 2;
    }
    CaseEditorScreen #editor-fields {
        height: 1fr;
    }
    CaseEditorScreen #editor-footer {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    CaseEditorScreen Input {
        width: 100%;
        margin-bottom: 1;
    }
    CaseEditorScreen Label {
        margin-top: 1;
    }
    CaseEditorScreen #case-tags {
        width: 100%;
    }
    CaseEditorScreen #case-description {
        height: 3;
        margin-bottom: 1;
    }
    CaseEditorScreen #case-timeout {
        width: 15;
    }
    CaseEditorScreen #mode-indicator {
        color: $accent;
        text-style: bold;
    }
    """

    class Saved(Message):
        """Emitted when user saves, carrying the TestCase."""

        def __init__(self, case: TestCase):
            super().__init__()
            self.case = case

    class Cancelled(Message):
        """Emitted when user cancels editing."""

    def __init__(self, case: TestCase | None = None):
        super().__init__()
        self._case: TestCase | None = case
        self._is_sequence = case is not None and case.steps is not None

    def compose(self):
        yield Header()
        yield Vertical(
            ScrollableContainer(
                Label("Name:", id="name-label"),
                Input(placeholder="test_case_name", id="case-name"),
                Label("Mode:", id="mode-label"),
                Static("Single Command", id="mode-indicator"),
                Label("Command:", id="cmd-label"),
                Input(placeholder="python", id="case-command"),
                Label("Args (space-separated):", id="args-label"),
                Input(placeholder="./script.py --flag", id="case-args"),
                Label("Tags (comma-separated):", id="tags-label"),
                Input(placeholder="tag1, tag2", id="case-tags"),
                Label("Description:", id="desc-label"),
                TextArea("", id="case-description"),
                Label("Timeout (seconds):", id="timeout-label"),
                Input(placeholder="", id="case-timeout"),
                Label("Retry count:", id="retry-label"),
                Input(placeholder="0", id="case-retry-count"),
                ExpectedEditor(id="expected-editor"),
                StepsEditor(id="steps-editor"),
                id="editor-fields",
            ),
            Horizontal(
                Button("Save", id="btn-save", variant="primary"),
                Button("Cancel", id="btn-cancel"),
                Button("Switch to Sequence", id="btn-switch-mode"),
                id="editor-footer",
            ),
            id="editor-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        if self._case is None:
            self._case = TestCase(name="new_case", command="", args=[], expected={}, tags=[])
            self._is_sequence = False
        else:
            self._is_sequence = self._case.steps is not None

        self._populate_form()
        self._update_mode_visibility()

    # -- populate / collect --------------------------------------------------

    def _populate_form(self) -> None:
        if self._case is None:
            return
        tc = self._case

        self.query_one("#case-name", Input).value = tc.name
        self.query_one("#case-command", Input).value = tc.command
        self.query_one("#case-args", Input).value = " ".join(tc.args) if tc.args else ""
        self.query_one("#case-tags", Input).value = ",".join(tc.tags) if tc.tags else ""
        self.query_one("#case-description", TextArea).text = tc.description or ""
        self.query_one("#case-timeout", Input).value = str(tc.timeout) if tc.timeout else ""
        self.query_one("#case-retry-count", Input).value = str(tc.retry_count) if tc.retry_count else ""

        self.query_one("#expected-editor", ExpectedEditor).load(tc.expected or {})

        if self._is_sequence and tc.steps:
            self.query_one("#steps-editor", StepsEditor).load(tc.steps)

        self.query_one("#mode-indicator", Static).update(
            "Sequence Mode" if self._is_sequence else "Single Command"
        )
        switch_btn = self.query_one("#btn-switch-mode", Button)
        switch_btn.label = "Switch to Sequence" if not self._is_sequence else "Switch to Single"

    def _collect_case(self) -> TestCase:
        name = self.query_one("#case-name", Input).value.strip() or "unnamed"
        tags_text = self.query_one("#case-tags", Input).value
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]

        timeout_text = self.query_one("#case-timeout", Input).value.strip()
        timeout = float(timeout_text) if timeout_text else None

        retry_text = self.query_one("#case-retry-count", Input).value.strip()
        retry_count = int(retry_text) if retry_text else 0

        description = self.query_one("#case-description", TextArea).text.strip()

        if self._is_sequence:
            steps = self.query_one("#steps-editor", StepsEditor).to_steps()
            expected = self.query_one("#expected-editor", ExpectedEditor).to_dict()
            return TestCase(
                name=name,
                steps=steps,
                expected=expected,
                description=description or "",
                timeout=timeout,
                resources=self._case.resources if self._case else None,
                tags=tags,
                retry_count=retry_count,
            )
        else:
            command = self.query_one("#case-command", Input).value.strip()
            args_text = self.query_one("#case-args", Input).value.strip()
            args = args_text.split() if args_text else []
            expected = self.query_one("#expected-editor", ExpectedEditor).to_dict()

            return TestCase(
                name=name,
                command=command,
                args=args,
                expected=expected,
                description=description or "",
                timeout=timeout,
                resources=self._case.resources if self._case else None,
                tags=tags,
                retry_count=retry_count,
            )

    def _update_mode_visibility(self) -> None:
        """Show/hide fields based on current mode."""
        cmd_label = self.query_one("#cmd-label", Label)
        args_label = self.query_one("#args-label", Label)
        cmd_input = self.query_one("#case-command", Input)
        args_input = self.query_one("#case-args", Input)
        expected = self.query_one("#expected-editor", ExpectedEditor)
        steps = self.query_one("#steps-editor", StepsEditor)
        mode_label = self.query_one("#mode-label", Label)
        mode_indicator = self.query_one("#mode-indicator", Static)
        switch_btn = self.query_one("#btn-switch-mode", Button)

        if self._is_sequence:
            mode_label.display = True
            mode_indicator.display = True
            cmd_label.display = False
            args_label.display = False
            cmd_input.display = False
            args_input.display = False
            expected.display = True
            steps.display = True
            switch_btn.label = "Switch to Single"
        else:
            mode_label.display = False
            mode_indicator.display = True
            cmd_label.display = True
            args_label.display = True
            cmd_input.display = True
            args_input.display = True
            expected.display = True
            steps.display = False
            switch_btn.label = "Switch to Sequence"

    # -- button handlers -----------------------------------------------------

    @on(Button.Pressed, "#btn-save")
    def _on_save(self) -> None:
        try:
            case = self._collect_case()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
            return
        self.post_message(self.Saved(case))
        self.dismiss()

    @on(Button.Pressed, "#btn-cancel")
    def _on_cancel(self) -> None:
        self.post_message(self.Cancelled())
        self.dismiss()

    @on(Button.Pressed, "#btn-switch-mode")
    def _on_switch_mode(self) -> None:
        self._is_sequence = not self._is_sequence
        mode_label = self.query_one("#mode-indicator", Static)
        mode_label.update("Sequence Mode" if self._is_sequence else "Single Command")
        self._update_mode_visibility()
