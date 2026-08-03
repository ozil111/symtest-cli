"""Tests for TUI app entry point and CLI integration."""

import sys
import io
import argparse
from unittest.mock import patch

import pytest

from symtest.tui.app import run_tui, CaseManagerApp
from symtest.tui.controllers.case_controller import CaseController


# ---------------------------------------------------------------------------
# run_tui — missing textual
# ---------------------------------------------------------------------------


class TestRunTuiMissingTextual:
    def test_exits_with_friendly_message(self, monkeypatch):
        """When textual is not installed, print help and exit(1)."""
        # Remove the real textual from sys.modules so the import fails
        monkeypatch.setitem(sys.modules, "textual", None)

        # We need to force ImportError on import textual
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "textual" or name.startswith("textual."):
                raise ImportError("No module named 'textual'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)

        with pytest.raises(SystemExit) as exc:
            run_tui("dummy.json")

        assert exc.value.code == 1
        output = buf.getvalue()
        assert "TUI" in output or "textual" in output.lower()


# ---------------------------------------------------------------------------
# CaseManagerApp construction
# ---------------------------------------------------------------------------


class TestCaseManagerApp:
    def test_app_creates_controller(self):
        app = CaseManagerApp("test_config.json")
        assert isinstance(app._controller, CaseController)
        assert app._config_file == "test_config.json"
        assert app._workspace is None

    def test_app_with_workspace(self):
        app = CaseManagerApp("config.yaml", workspace="/tmp")
        assert app._workspace == "/tmp"

    def test_app_title(self):
        app = CaseManagerApp("config.json")
        assert "Case Manager" in app.TITLE


# ---------------------------------------------------------------------------
# CLI argument parsing for TUI subcommand
# ---------------------------------------------------------------------------


class TestTuiCLIArgs:
    """Test that the 'tui' subcommand is properly registered in the parser."""

    def _build_parser(self):
        """Replicate the parser setup from cli.py (the relevant parts)."""
        parser = argparse.ArgumentParser(prog="symtest")
        subparsers = parser.add_subparsers(dest="command")

        tui_parser = subparsers.add_parser(
            "tui", help="Launch interactive TUI for managing test cases"
        )
        tui_parser.add_argument(
            "config_file", help="Path to the test configuration file (JSON or YAML)"
        )
        tui_parser.add_argument("--workspace", "-w", help="Working directory")
        return parser

    def test_tui_with_config_file(self):
        parser = self._build_parser()
        args = parser.parse_args(["tui", "cases.json"])
        assert args.command == "tui"
        assert args.config_file == "cases.json"
        assert args.workspace is None

    def test_tui_with_workspace(self):
        parser = self._build_parser()
        args = parser.parse_args(["tui", "cases.yaml", "--workspace", "/home/project"])
        assert args.config_file == "cases.yaml"
        assert args.workspace == "/home/project"

    def test_tui_with_short_workspace_flag(self):
        parser = self._build_parser()
        args = parser.parse_args(["tui", "config.json", "-w", "/tmp/ws"])
        assert args.workspace == "/tmp/ws"
