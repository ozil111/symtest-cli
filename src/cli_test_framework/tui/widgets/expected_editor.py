"""Widget for editing a test case's ``expected`` dict.

Provides structured inputs for known keys (return_code, output_contains,
output_matches, compare_files) and a free-form area for custom key-value pairs.

Uses an internal ``_data`` dict so that ``load()`` / ``to_dict()`` work
even when the widget is not mounted (e.g. in tests).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

from textual.widgets import Input, TextArea, Static
from textual.containers import Vertical
from textual.message import Message


class ExpectedEditor(Vertical):
    """Nested-dict editor for the ``expected`` field of a test case."""

    DEFAULT_CSS = """
    ExpectedEditor {
        height: auto;
        border: solid $primary;
        padding: 1;
    }
    ExpectedEditor Static.label {
        color: $text-muted;
        height: 1;
        margin-top: 1;
    }
    ExpectedEditor #expected-return-code {
        width: 10;
    }
    ExpectedEditor #expected-output-contains {
        height: 3;
    }
    ExpectedEditor #expected-custom {
        height: 4;
    }
    """

    class Changed(Message):
        """Emitted whenever the expected dict is modified."""

    _KNOWN_KEYS = {"return_code", "output_contains", "output_matches", "compare_files"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data: Dict[str, Any] = {}

    def compose(self):
        yield Static("─ Expected ─", classes="label")
        yield Static("return_code:", classes="label")
        yield Input(placeholder="0", id="expected-return-code")
        yield Static("output_contains (one per line):", classes="label")
        yield TextArea("", id="expected-output-contains")
        yield Static("output_matches (regex):", classes="label")
        yield Input(placeholder=".*", id="expected-output-matches")
        yield Static(
            "compare_files (one JSON per line: {actual, baseline, type, start_line?, end_line?, start_column?, end_column?}):",
            classes="label",
        )
        yield TextArea("", id="expected-compare-files")
        yield Static("Custom key-value pairs (key=value, one per line):", classes="label")
        yield TextArea("", id="expected-custom")

    def on_mount(self) -> None:
        """Populate UI from internal data on mount."""
        self._sync_to_ui()

    # -- public API ----------------------------------------------------------

    def load(self, expected: Dict[str, Any]) -> None:
        """Populate the editor from an *expected* dict."""
        self._data = copy.deepcopy(expected)
        if self.is_mounted:
            self._sync_to_ui()

    def to_dict(self) -> Dict[str, Any]:
        """Reconstruct the expected dict from the current widget values."""
        if self.is_mounted:
            self._sync_from_ui()
        return copy.deepcopy(self._data)

    # -- internal sync -------------------------------------------------------

    def _sync_to_ui(self) -> None:
        """Push internal ``_data`` into the widget children."""
        rc = self._data.get("return_code")
        self.query_one("#expected-return-code", Input).value = str(rc) if rc is not None else ""

        oc = self._data.get("output_contains", [])
        self.query_one("#expected-output-contains", TextArea).text = "\n".join(oc)

        om = self._data.get("output_matches", "")
        self.query_one("#expected-output-matches", Input).value = om

        cf = self._data.get("compare_files", [])
        cf_lines = [json.dumps(item, ensure_ascii=False) for item in cf]
        self.query_one("#expected-compare-files", TextArea).text = "\n".join(cf_lines)

        custom_lines = [
            f"{k}={json.dumps(v, ensure_ascii=False)}"
            for k, v in self._data.items()
            if k not in self._KNOWN_KEYS
        ]
        self.query_one("#expected-custom", TextArea).text = "\n".join(custom_lines)

    def _sync_from_ui(self) -> None:
        """Pull widget children values into ``_data``."""
        self._data = {}

        rc_text = self.query_one("#expected-return-code", Input).value.strip()
        if rc_text:
            try:
                self._data["return_code"] = int(rc_text)
            except ValueError:
                self._data["return_code"] = rc_text

        oc_text = self.query_one("#expected-output-contains", TextArea).text.strip()
        if oc_text:
            self._data["output_contains"] = [
                line for line in oc_text.splitlines() if line.strip()
            ]

        om_text = self.query_one("#expected-output-matches", Input).value.strip()
        if om_text:
            self._data["output_matches"] = om_text

        cf_text = self.query_one("#expected-compare-files", TextArea).text.strip()
        if cf_text:
            cf_list = []
            for line in cf_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    cf_list.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            if cf_list:
                self._data["compare_files"] = cf_list

        custom_text = self.query_one("#expected-custom", TextArea).text.strip()
        if custom_text:
            for line in custom_text.splitlines():
                line = line.strip()
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                try:
                    self._data[key] = json.loads(value.strip())
                except (json.JSONDecodeError, ValueError):
                    self._data[key] = value.strip()
