"""Widget for editing a test case's ``steps`` list (sequence mode).

Uses an internal ``_steps`` list so that ``load()`` / ``to_steps()`` work
even when the widget is not mounted.
"""

from __future__ import annotations

import copy
import json
from typing import Any, List

from textual.widgets import Input, TextArea, Static, Button
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.app import ComposeResult

from ...core.test_case import TestCaseStep


class StepsEditor(Vertical):
    """Editor for the ``steps`` sequence of a test case."""

    DEFAULT_CSS = """
    StepsEditor {
        height: auto;
        border: solid $primary;
        padding: 1;
    }
    StepsEditor #steps-list {
        height: auto;
        min-height: 3;
    }
    StepsEditor .step-row {
        height: auto;
        padding: 1 0;
        border-bottom: solid $panel;
    }
    StepsEditor .step-row Static {
        width: 1fr;
    }
    StepsEditor .step-header {
        color: $accent;
        padding-bottom: 1;
    }
    StepsEditor #step-editor {
        height: auto;
        margin-top: 1;
        border: solid $surface;
        padding: 1;
    }
    StepsEditor #step-confirm {
        margin-top: 1;
    }
    """

    class Changed(Message):
        """Emitted whenever steps are modified."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._steps: List[TestCaseStep] = []
        self._editing_idx: int = -1  # -1 = new step

    def compose(self) -> ComposeResult:
        yield Static("─ Steps ─", classes="label")
        yield Vertical(id="steps-list")
        yield Static("", id="step-editor-status")
        yield Static("Command:", classes="label")
        yield Input(placeholder="python", id="step-cmd")
        yield Static("Args (space-separated):", classes="label")
        yield Input(placeholder="./script.py --flag", id="step-args")
        yield Static("Expected (JSON):", classes="label")
        yield TextArea('{"return_code": 0}', id="step-expected")
        yield Static("Timeout (seconds):", classes="label")
        yield Input(placeholder="", id="step-timeout")
        yield Static("Retry count:", classes="label")
        yield Input(placeholder="0", id="step-retry-count")
        yield Horizontal(
            Button("Save Step", id="step-save", variant="primary"),
            Button("Cancel", id="step-cancel"),
            id="step-confirm",
        )
        yield Horizontal(
            Button("+ Add Step", id="step-add", variant="success"),
            id="step-actions",
        )

    def on_mount(self) -> None:
        self._refresh_list()

    # -- public API ----------------------------------------------------------

    def load(self, steps: List[TestCaseStep]) -> None:
        """Populate the editor with *steps*."""
        self._steps = copy.deepcopy(steps)
        self._editing_idx = -1
        if self.is_mounted:
            self._refresh_list()
            self._clear_edit_form()

    def to_steps(self) -> List[TestCaseStep]:
        if self.is_mounted:
            # Pull any in-progress edit from UI into steps before returning
            pass  # edits are applied immediately via buttons
        return copy.deepcopy(self._steps)

    # -- internal -----------------------------------------------------------

    def _refresh_list(self) -> None:
        container = self.query_one("#steps-list", Vertical)
        container.remove_children()
        for i, step in enumerate(self._steps):
            args_str = " ".join(step.args) if step.args else ""
            exp_preview = json.dumps(step.expected, ensure_ascii=False)
            if len(exp_preview) > 40:
                exp_preview = exp_preview[:37] + "..."
            timeout_str = f", timeout={step.timeout}s" if step.timeout else ""
            retry_str = f", retry={step.retry_count}" if step.retry_count else ""

            row = Horizontal(
                Static(f"[Step {i+1}/{len(self._steps)}]"),
                Static(f"cmd: {step.command}"),
                Static(f"args: {args_str[:30]}"),
                Static(f"exp: {exp_preview}"),
                Button("Edit", id=f"step-edit-{i}"),
                Button("Del", id=f"step-del-{i}"),
                Button("↑", id=f"step-up-{i}"),
                Button("↓", id=f"step-down-{i}"),
                classes="step-row",
            )
            container.mount(row)

    def _clear_edit_form(self) -> None:
        self._editing_idx = -1
        if not self.is_mounted:
            return
        self.query_one("#step-cmd", Input).value = ""
        self.query_one("#step-args", Input).value = ""
        self.query_one("#step-expected", TextArea).text = '{"return_code": 0}'
        self.query_one("#step-timeout", Input).value = ""
        self.query_one("#step-retry-count", Input).value = ""
        status = self.query_one("#step-editor-status", Static)
        status.update("")

    def _edit_step(self, idx: int) -> None:
        self._editing_idx = idx
        step = self._steps[idx]
        self.query_one("#step-cmd", Input).value = step.command
        self.query_one("#step-args", Input).value = " ".join(step.args)
        self.query_one("#step-expected", TextArea).text = json.dumps(
            step.expected, ensure_ascii=False
        )
        self.query_one("#step-timeout", Input).value = str(step.timeout) if step.timeout else ""
        self.query_one("#step-retry-count", Input).value = str(step.retry_count) if step.retry_count else ""
        status = self.query_one("#step-editor-status", Static)
        status.update(f"Editing Step {idx+1}")

    def _save_current_step(self) -> None:
        cmd = self.query_one("#step-cmd", Input).value.strip()
        if not cmd:
            self.notify("Command cannot be empty", severity="error")
            return

        args_text = self.query_one("#step-args", Input).value.strip()
        args = args_text.split() if args_text else []

        try:
            expected = json.loads(self.query_one("#step-expected", TextArea).text)
        except json.JSONDecodeError:
            self.notify("Expected must be valid JSON", severity="error")
            return

        timeout_text = self.query_one("#step-timeout", Input).value.strip()
        timeout = float(timeout_text) if timeout_text else None

        retry_text = self.query_one("#step-retry-count", Input).value.strip()
        retry_count = int(retry_text) if retry_text else 0

        new_step = TestCaseStep(
            command=cmd, args=args, expected=expected, timeout=timeout, retry_count=retry_count,
        )

        if self._editing_idx >= 0:
            self._steps[self._editing_idx] = new_step
        else:
            self._steps.append(new_step)

        self._clear_edit_form()
        self._refresh_list()
        self.post_message(self.Changed())

    def _delete_step(self, idx: int) -> None:
        del self._steps[idx]
        if self._editing_idx == idx:
            self._clear_edit_form()
        elif self._editing_idx > idx:
            self._editing_idx -= 1
        self._refresh_list()
        self.post_message(self.Changed())

    def _move_step(self, idx: int, direction: int) -> None:
        new_idx = idx + direction
        if 0 <= new_idx < len(self._steps):
            self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
            if self._editing_idx == idx:
                self._editing_idx = new_idx
            elif self._editing_idx == new_idx:
                self._editing_idx = idx
            self._refresh_list()
            self.post_message(self.Changed())

    # -- button handlers -----------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id)

        if bid == "step-add":
            self._clear_edit_form()

        elif bid == "step-save":
            self._save_current_step()

        elif bid == "step-cancel":
            self._clear_edit_form()

        elif bid and bid.startswith("step-edit-"):
            idx = int(bid.split("-")[-1])
            if 0 <= idx < len(self._steps):
                self._edit_step(idx)

        elif bid and bid.startswith("step-del-"):
            idx = int(bid.split("-")[-1])
            if 0 <= idx < len(self._steps):
                self._delete_step(idx)

        elif bid and bid.startswith("step-up-"):
            idx = int(bid.split("-")[-1])
            self._move_step(idx, -1)

        elif bid and bid.startswith("step-down-"):
            idx = int(bid.split("-")[-1])
            self._move_step(idx, 1)
