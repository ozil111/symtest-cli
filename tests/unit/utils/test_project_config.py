"""Unit tests for project-level default configuration (.symtest/symtest.json).

Covers loading/validation of the project config, the three-level merge
(command line > project config > built-in defaults), report path
resolution, and the ``symtest run`` parser/entry integration.
"""

import argparse
import json
from argparse import Namespace

import pytest

from symtest import cli
from symtest.utils.project_config import (
    DEFAULT_CONFIG_FILE,
    PROJECT_CONFIG_RELATIVE_PATH,
    ProjectConfigError,
    load_project_config,
    merge_project_config,
    resolve_path,
)


def write_project_config(workspace, data):
    path = workspace / PROJECT_CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_args(**overrides):
    values = {
        "config_file": None,
        "workspace": None,
        "parallel": None,
        "workers": None,
        "execution_mode": None,
        "output_format": "none",
        "test_case": None,
        "tag": None,
        "var": [],
        "verbose": False,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


# =========================================================================
# load_project_config — file presence and robustness
# =========================================================================


class TestLoadProjectConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_project_config(tmp_path) == {}

    def test_invalid_json_warns_and_returns_empty(self, tmp_path, caplog):
        path = tmp_path / PROJECT_CONFIG_RELATIVE_PATH
        path.parent.mkdir()
        path.write_text("{ not json", encoding="utf-8")

        assert load_project_config(tmp_path) == {}
        assert "Ignoring unreadable project config" in caplog.text

    def test_non_object_top_level_warns_and_returns_empty(self, tmp_path, caplog):
        write_project_config(tmp_path, ["run"])

        assert load_project_config(tmp_path) == {}
        assert "top level must be a JSON object" in caplog.text

    def test_valid_config_is_loaded(self, tmp_path):
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.yaml", "with_deps": True, "workers": 3},
            "report": {"html": "report.html"},
        })
        config = load_project_config(tmp_path)

        assert config == {
            "run": {"config_file": "cases.yaml", "with_deps": True, "workers": 3},
            "report": {"html": "report.html"},
        }

    def test_unknown_section_warns_and_is_ignored(self, tmp_path, caplog):
        write_project_config(tmp_path, {"run": {}, "report": {}, "extra": {"a": 1}})

        config = load_project_config(tmp_path)
        assert set(config) == {"run", "report"}
        assert "Unknown section 'extra'" in caplog.text

    def test_unknown_key_warns_and_is_ignored(self, tmp_path, caplog):
        write_project_config(tmp_path, {"run": {"with_deps": True, "wiht_deps": True}})

        config = load_project_config(tmp_path)
        assert config["run"] == {"with_deps": True}
        assert "Unknown key 'run.wiht_deps'" in caplog.text

    def test_wrong_typed_key_warns_and_is_ignored(self, tmp_path, caplog):
        write_project_config(tmp_path, {"run": {"workers": "four", "parallel": 1}})

        config = load_project_config(tmp_path)
        assert "workers" not in config["run"]
        assert "parallel" not in config["run"]
        assert "Ignoring 'run.workers'" in caplog.text

    def test_non_object_section_warns_and_is_ignored(self, tmp_path, caplog):
        write_project_config(tmp_path, {"run": True})

        assert load_project_config(tmp_path) == {}
        assert "'run' section must be an object" in caplog.text


# =========================================================================
# load_project_config(explicit_path=...) — strict mode for --defaults
# =========================================================================


def write_explicit_defaults(workspace, data, name=".symtest/validation.json"):
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadProjectConfigExplicit:
    def test_valid_explicit_file_is_loaded(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {
            "run": {"config_file": "validation_cases.json", "workers": 1},
            "report": {"text": "reports/validation.txt"},
        })

        config = load_project_config(tmp_path, explicit_path=str(path))

        assert config == {
            "run": {"config_file": "validation_cases.json", "workers": 1},
            "report": {"text": "reports/validation.txt"},
        }

    def test_relative_path_resolved_against_workspace(self, tmp_path):
        write_explicit_defaults(tmp_path, {"run": {"config_file": "cases.json"}})

        config = load_project_config(tmp_path, explicit_path=".symtest/validation.json")

        assert config["run"]["config_file"] == "cases.json"

    def test_absolute_path_used_as_is(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {"run": {"config_file": "cases.json"}})

        config = load_project_config(tmp_path, explicit_path=str(path.resolve()))

        assert config["run"]["config_file"] == "cases.json"

    def test_explicit_file_replaces_default_file(self, tmp_path):
        # Conflicting values: the explicit file must win and the default
        # .symtest/symtest.json must NOT be merged in.
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json", "workers": 8, "parallel": True},
        })
        write_explicit_defaults(tmp_path, {
            "run": {"config_file": "validation_cases.json", "workers": 1},
        })

        config = load_project_config(tmp_path, explicit_path=".symtest/validation.json")

        assert config["run"] == {"config_file": "validation_cases.json", "workers": 1}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="not found"):
            load_project_config(tmp_path, explicit_path=".symtest/absent.json")

    def test_broken_json_raises(self, tmp_path):
        path = tmp_path / ".symtest" / "broken.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")

        with pytest.raises(ProjectConfigError, match="cannot read"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_non_object_top_level_raises(self, tmp_path):
        path = write_explicit_defaults(tmp_path, ["run"])

        with pytest.raises(ProjectConfigError, match="top level must be a JSON object"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_unknown_section_raises(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {"run": {}, "report": {}, "extra": {}})

        with pytest.raises(ProjectConfigError, match="unknown section"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_unknown_key_raises(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {
            "run": {"with_deps": True, "wiht_deps": True},
        })

        with pytest.raises(ProjectConfigError, match="unknown key 'run.wiht_deps'"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_wrong_typed_key_raises(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {"run": {"workers": "four"}})

        with pytest.raises(ProjectConfigError, match="'run.workers' expects int"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_non_object_section_raises(self, tmp_path):
        path = write_explicit_defaults(tmp_path, {"run": True})

        with pytest.raises(ProjectConfigError, match="'run' section must be an object"):
            load_project_config(tmp_path, explicit_path=str(path))

    def test_default_file_keeps_lenient_behaviour(self, tmp_path, caplog):
        # Without explicit_path the default file stays lenient (broken file
        # → warning + empty dict, no exception).
        path = tmp_path / PROJECT_CONFIG_RELATIVE_PATH
        path.parent.mkdir()
        path.write_text("{ not json", encoding="utf-8")

        assert load_project_config(tmp_path) == {}
        assert "Ignoring unreadable project config" in caplog.text


# =========================================================================
# merge_project_config — three-level priority
# =========================================================================


class TestMergeProjectConfig:
    def test_builtin_defaults_when_no_config(self):
        args = merge_project_config(make_args(), {}, None)

        assert args.config_file == DEFAULT_CONFIG_FILE
        assert args.parallel is False
        assert args.workers is None
        assert args.execution_mode == "thread"
        assert args.regression_threshold == 1.5
        assert args.with_deps is False
        assert args.error_analysis is False
        assert args.error_analysis_all is False
        assert args.text_report is None
        assert args.html_report is None
        assert args.junit_xml is None

    def test_project_config_wins_over_builtin(self):
        config = {
            "run": {"config_file": "cases.yaml", "parallel": True, "workers": 2,
                    "with_deps": True, "error_analysis_all": True},
            "report": {"text": "report.txt", "html": "report.html"},
        }
        args = merge_project_config(make_args(), config, None)

        assert args.config_file == "cases.yaml"
        assert args.parallel is True
        assert args.workers == 2
        assert args.with_deps is True
        assert args.error_analysis_all is True
        assert args.text_report == "report.txt"
        assert args.html_report == "report.html"

    def test_command_line_wins_over_project_config(self):
        config = {"run": {"config_file": "cases.yaml", "parallel": True,
                          "error_analysis_all": True},
                  "report": {"html": "from_config.html"}}
        args = merge_project_config(
            make_args(config_file="explicit.json", parallel=False, html_report="cli.html"),
            config, None,
        )

        assert args.config_file == "explicit.json"
        assert args.parallel is False
        assert args.error_analysis_all is True  # not set on CLI → config value
        assert args.html_report == "cli.html"

    def test_explicit_cli_off_beats_config_on(self):
        config = {"run": {"with_deps": True}}
        args = merge_project_config(make_args(with_deps=False), config, None)

        assert args.with_deps is False

    def test_missing_attributes_receive_defaults(self):
        # External callers may construct minimal Namespace objects.
        args = merge_project_config(Namespace(), {}, None)

        assert args.config_file == DEFAULT_CONFIG_FILE
        assert args.execution_mode == "thread"
        assert args.regression_threshold == 1.5


# =========================================================================
# resolve_path — workspace-relative report paths
# =========================================================================


class TestResolvePath:
    def test_none_passes_through(self, tmp_path):
        assert resolve_path(None, tmp_path) is None

    def test_relative_resolved_against_workspace(self, tmp_path):
        assert resolve_path("report.html", tmp_path) == str(tmp_path / "report.html")

    def test_absolute_unchanged(self, tmp_path):
        absolute = str(tmp_path / "elsewhere.html")
        assert resolve_path(absolute, tmp_path) == absolute


# =========================================================================
# run parser — new optional arguments
# =========================================================================


class TestRunParser:
    def _parse(self, argv):
        return cli.create_parser().parse_args(["run"] + argv)

    def test_config_file_is_optional(self):
        args = self._parse([])
        assert args.config_file is None

    def test_config_file_positional_still_works(self):
        args = self._parse(["cases.json"])
        assert args.config_file == "cases.json"

    def test_boolean_flags_default_to_none(self):
        args = self._parse(["cases.json"])
        assert args.parallel is None
        assert args.with_deps is None
        assert args.error_analysis is None
        assert args.error_analysis_all is None

    def test_no_prefix_flags_override(self):
        args = self._parse(["cases.json", "--no-with-deps", "--no-parallel",
                            "--no-error-analysis-all"])
        assert args.with_deps is False
        assert args.parallel is False
        assert args.error_analysis_all is False

    def test_text_report_and_no_config(self):
        args = self._parse(["cases.json", "--text-report", "out.txt", "--no-config"])
        assert args.text_report == "out.txt"
        assert args.no_config is True

    def test_defaults_flag_parses(self):
        args = self._parse(["--defaults", ".symtest/validation.json"])
        assert args.defaults == ".symtest/validation.json"
        assert args.no_config is False

    def test_defaults_defaults_to_none(self):
        args = self._parse(["cases.json"])
        assert args.defaults is None

    def test_defaults_and_no_config_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._parse(["--defaults", ".symtest/validation.json", "--no-config"])


# =========================================================================
# run_tests — end-to-end integration
# =========================================================================


class DummyRunner:
    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs
        self.results = {
            "total": 2,
            "passed": 2,
            "failed": 0,
            "details": [
                {"name": "a", "status": "passed"},
                {"name": "b", "status": "passed"},
            ],
        }

    def run_tests(self):
        return True


class TestRunTestsProjectConfig:
    def _run(self, tmp_path, monkeypatch, **arg_overrides):
        config = tmp_path / "cases.json"
        config.write_text('{"test_cases": []}', encoding="utf-8")
        captured = {}

        class CapturingRunner(DummyRunner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.update(kwargs)

        monkeypatch.setattr("symtest.commands.run.JSONRunner", CapturingRunner)
        result = cli.run_tests(make_args(workspace=str(tmp_path), **arg_overrides))
        return result, captured

    def test_omitted_config_file_uses_project_config(self, tmp_path, monkeypatch):
        write_project_config(tmp_path, {"run": {"config_file": "cases.json"}})

        result, _ = self._run(tmp_path, monkeypatch)

        assert result
        # cases.json in workspace is used → runner ran without error.

    def test_omitted_config_file_without_project_config_falls_back(self, tmp_path,
                                                                   monkeypatch, caplog):
        result, _ = self._run(tmp_path, monkeypatch)

        assert not result
        assert "Configuration file not found" in caplog.text
        assert DEFAULT_CONFIG_FILE in caplog.text

    def test_project_options_reach_runner(self, tmp_path, monkeypatch):
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json", "error_analysis": True,
                    "error_analysis_all": True, "with_deps": True},
        })

        result, captured = self._run(tmp_path, monkeypatch)

        assert result
        assert captured["error_analysis"] is True
        assert captured["error_analysis_all"] is True
        assert captured["with_deps"] is True

    def test_cli_overrides_project_config(self, tmp_path, monkeypatch):
        write_project_config(tmp_path, {"run": {"config_file": "cases.json",
                                                "error_analysis_all": True}})

        result, captured = self._run(tmp_path, monkeypatch, with_deps=None)

        # with_deps absent everywhere → builtin False; error_analysis_all from config.
        assert result
        assert captured["with_deps"] is False
        assert captured["error_analysis_all"] is True

    def test_text_report_written_from_project_config(self, tmp_path, monkeypatch):
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json"},
            "report": {"text": "test_report.txt"},
        })

        result, _ = self._run(tmp_path, monkeypatch)

        assert result
        report = tmp_path / "test_report.txt"
        assert report.exists()
        assert "Total Tests: 2" in report.read_text(encoding="utf-8")

    def test_text_report_relative_to_workspace(self, tmp_path, monkeypatch):
        (tmp_path / "cases.json").write_text('{"test_cases": []}', encoding="utf-8")
        write_project_config(tmp_path, {"run": {"config_file": "cases.json"}})

        result, _ = self._run(tmp_path, monkeypatch, text_report="reports/out.txt")

        assert result
        assert (tmp_path / "reports" / "out.txt").exists()

    def test_html_report_from_project_config(self, tmp_path, monkeypatch, caplog):
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json"},
            "report": {"html": "test_report.html"},
        })

        result, _ = self._run(tmp_path, monkeypatch)

        assert result
        assert (tmp_path / "test_report.html").exists()
        assert "HTML report written to" in caplog.text

    def test_no_config_skips_project_file(self, tmp_path, monkeypatch, caplog):
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json", "error_analysis_all": True},
        })

        # --no-config: config file from project config is NOT used → builtin
        # fallback test_cases.json, which does not exist → failure.
        result, captured = self._run(tmp_path, monkeypatch, no_config=True)

        assert not result
        assert "Configuration file not found" in caplog.text
        assert "error_analysis_all" not in captured

    def test_no_config_with_explicit_config_file(self, tmp_path, monkeypatch):
        write_project_config(tmp_path, {"run": {"error_analysis_all": True}})

        result, captured = self._run(tmp_path, monkeypatch,
                                     config_file="cases.json", no_config=True)

        assert result
        # Project config value must not leak through --no-config.
        assert captured["error_analysis_all"] is False

    def test_project_config_used_with_workspace(self, tmp_path, monkeypatch):
        # Config file lives in a subdirectory used as --workspace.
        workspace = tmp_path / "proj"
        workspace.mkdir()
        write_project_config(workspace, {"run": {"config_file": "cases.json"}})
        (workspace / "cases.json").write_text('{"test_cases": []}', encoding="utf-8")

        captured = {}

        class CapturingRunner(DummyRunner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.update(kwargs)

        monkeypatch.setattr("symtest.commands.run.JSONRunner", CapturingRunner)
        result = cli.run_tests(make_args(workspace=str(workspace)))

        assert result
        assert captured["config_file"] == str((workspace / "cases.json").resolve())


class TestRunTestsDefaults:
    """``--defaults FILE``: explicit defaults file replaces the default one."""

    def _run(self, tmp_path, monkeypatch, **arg_overrides):
        config = tmp_path / "cases.json"
        config.write_text('{"test_cases": []}', encoding="utf-8")
        captured = {}

        class CapturingRunner(DummyRunner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.update(kwargs)

        monkeypatch.setattr("symtest.commands.run.JSONRunner", CapturingRunner)
        result = cli.run_tests(make_args(workspace=str(tmp_path), **arg_overrides))
        return result, captured

    def test_defaults_file_options_reach_runner(self, tmp_path, monkeypatch):
        (tmp_path / "validation_cases.json").write_text(
            '{"test_cases": []}', encoding="utf-8")
        write_explicit_defaults(tmp_path, {
            "run": {"config_file": "validation_cases.json", "workers": 1,
                    "error_analysis_all": True},
        })

        result, captured = self._run(tmp_path, monkeypatch,
                                     defaults=".symtest/validation.json", parallel=False)

        assert result
        assert captured["config_file"] == str(
            (tmp_path / "validation_cases.json").resolve())
        assert captured["error_analysis_all"] is True

    def test_defaults_file_replaces_default_project_config(self, tmp_path, monkeypatch):
        # Both files exist with conflicting values: only the explicit one counts.
        write_project_config(tmp_path, {
            "run": {"config_file": "cases.json", "error_analysis_all": True},
        })
        write_explicit_defaults(tmp_path, {
            "run": {"config_file": "cases.json", "error_analysis_all": False},
        })

        result, captured = self._run(tmp_path, monkeypatch,
                                     defaults=".symtest/validation.json")

        assert result
        assert captured["error_analysis_all"] is False

    def test_cli_overrides_defaults_file(self, tmp_path, monkeypatch):
        write_explicit_defaults(tmp_path, {
            "run": {"config_file": "cases.json", "error_analysis_all": True},
        })

        result, captured = self._run(tmp_path, monkeypatch,
                                     defaults=".symtest/validation.json",
                                     error_analysis_all=False)

        assert result
        assert captured["error_analysis_all"] is False

    def test_missing_defaults_file_aborts_run(self, tmp_path, monkeypatch, caplog):
        captured = {}

        class CapturingRunner(DummyRunner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.update(kwargs)

        monkeypatch.setattr("symtest.commands.run.JSONRunner", CapturingRunner)
        result = cli.run_tests(make_args(
            workspace=str(tmp_path), defaults=".symtest/absent.json"))

        assert not result
        assert "not found" in caplog.text
        assert not captured  # runner never constructed

    def test_broken_defaults_file_aborts_run(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / ".symtest" / "broken.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")

        result, _ = self._run(tmp_path, monkeypatch, defaults=".symtest/broken.json")

        assert not result
        assert "cannot read defaults file" in caplog.text

    def test_defaults_file_report_paths_resolve_against_workspace(
            self, tmp_path, monkeypatch):
        write_explicit_defaults(tmp_path, {
            "run": {"config_file": "cases.json"},
            "report": {"text": "reports/validation/test_report.txt"},
        })

        result, _ = self._run(tmp_path, monkeypatch,
                              defaults=".symtest/validation.json")

        assert result
        report = tmp_path / "reports" / "validation" / "test_report.txt"
        assert report.exists()


# =========================================================================
# error_analysis_all implication (existing behavior, guarded by merge)
# =========================================================================


def test_error_analysis_all_implies_error_analysis(tmp_path, monkeypatch):
    (tmp_path / "cases.json").write_text('{"test_cases": []}', encoding="utf-8")
    write_project_config(tmp_path, {"run": {"config_file": "cases.json",
                                            "error_analysis_all": True}})
    captured = {}

    class CapturingRunner(DummyRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.update(kwargs)

    monkeypatch.setattr("symtest.commands.run.JSONRunner", CapturingRunner)

    assert cli.run_tests(make_args(workspace=str(tmp_path)))
    assert captured["error_analysis"] is True
    assert captured["error_analysis_all"] is True


# =========================================================================
# argparse.BooleanOptionalAction is used intentionally (3.9+)
# =========================================================================


def test_boolean_optional_action_available():
    assert hasattr(argparse, "BooleanOptionalAction")
