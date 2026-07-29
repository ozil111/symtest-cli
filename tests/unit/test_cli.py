import sys
import json
from argparse import Namespace
from unittest.mock import patch

import pytest

from cli_test_framework import cli


class DummyRunner:
    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.results = {
            "total": 2,
            "passed": 1,
            "failed": 1,
            "details": [
                {"name": "ok", "status": "passed"},
                {"name": "bad", "status": "failed", "message": "boom"},
            ],
        }

    def run_tests(self):
        return self.init_kwargs.get("success", False)


def make_args(config_file, **overrides):
    values = {
        "config_file": str(config_file),
        "workspace": None,
        "parallel": False,
        "workers": None,
        "execution_mode": "thread",
        "output_format": "text",
        "test_case": None,
        "tag": None,
        "verbose": False,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


# =========================================================================
# _format_results_html
# =========================================================================


class TestFormatResultsHtml:
    """Test the _format_results_html helper."""

    def test_basic_html_structure(self):
        results = {"total": 2, "passed": 1, "failed": 1}
        html = cli._format_results_html(results, "Hello & <World>")
        assert "<!DOCTYPE html>" in html
        assert "Total: 2" in html
        assert "Passed:" in html
        assert "Failed:" in html
        assert "50.0%" in html
        assert "Hello &amp; &lt;World&gt;" in html  # escaped

    def test_all_passed(self):
        results = {"total": 3, "passed": 3, "failed": 0}
        html = cli._format_results_html(results, "all good")
        assert "100.0%" in html

    def test_all_failed(self):
        results = {"total": 2, "passed": 0, "failed": 2}
        html = cli._format_results_html(results, "all bad")
        assert "0.0%" in html

    def test_zero_total(self):
        results = {"total": 0, "passed": 0, "failed": 0}
        html = cli._format_results_html(results, "empty")
        assert "0.0%" in html


# =========================================================================
# run_tests — basic paths
# =========================================================================


def test_run_tests_rejects_missing_config(caplog):
    success = cli.run_tests(make_args("missing.json"))

    assert not success
    assert "Configuration file not found" in caplog.text


def test_run_tests_rejects_unsupported_config_format(tmp_path, caplog):
    config = tmp_path / "cases.toml"
    config.write_text("", encoding="utf-8")

    success = cli.run_tests(make_args(config))

    assert not success
    assert "Unsupported configuration file format" in caplog.text


def test_run_tests_uses_json_runner_and_prints_totals(tmp_path, monkeypatch, caplog):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class PassingRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", PassingRunner)

    success = cli.run_tests(make_args(config, verbose=True, test_case=["ok"]))

    log_text = caplog.text
    assert success
    assert "Total Tests: 2" in log_text
    assert "Passed: 1" in log_text
    assert "bad" in log_text
    assert "boom" in log_text


def test_run_tests_uses_parallel_runner(tmp_path, monkeypatch):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")
    captured = {}

    class PassingParallelRunner(DummyRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.update(kwargs)

        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "ParallelJSONRunner", PassingParallelRunner)

    success = cli.run_tests(
        make_args(config, parallel=True, workers=3, execution_mode="process")
    )

    assert success
    assert captured["max_workers"] == 3
    assert captured["execution_mode"] == "process"


# =========================================================================
# run_tests — YAML runner
# =========================================================================


def test_run_tests_uses_yaml_runner(tmp_path, monkeypatch, caplog):
    config = tmp_path / "cases.yaml"
    config.write_text("test_cases: []", encoding="utf-8")

    class PassingYAMLRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "YAMLRunner", PassingYAMLRunner)

    success = cli.run_tests(make_args(config))

    assert success


def test_run_tests_uses_yaml_runner_yml_extension(tmp_path, monkeypatch):
    config = tmp_path / "cases.yml"
    config.write_text("test_cases: []", encoding="utf-8")

    class PassingYAMLRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "YAMLRunner", PassingYAMLRunner)

    success = cli.run_tests(make_args(config))

    assert success


def test_run_tests_parallel_yaml_runner(tmp_path, monkeypatch):
    config = tmp_path / "cases.yaml"
    config.write_text("test_cases: []", encoding="utf-8")
    captured = {}

    class PassingParallelYAMLRunner(DummyRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.update(kwargs)

        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "ParallelYAMLRunner", PassingParallelYAMLRunner)

    success = cli.run_tests(make_args(config, parallel=True, workers=2))

    assert success
    assert captured["max_workers"] == 2


def test_run_tests_parallel_unsupported_format(tmp_path, caplog):
    config = tmp_path / "cases.toml"
    config.write_text("", encoding="utf-8")

    success = cli.run_tests(make_args(config, parallel=True))

    assert not success
    assert "Unsupported configuration file format for parallel mode" in caplog.text


# =========================================================================
# run_tests — output formats
# =========================================================================


def test_run_tests_output_json(tmp_path, monkeypatch, capsys):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class PassingRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", PassingRunner)

    success = cli.run_tests(make_args(config, output_format="json"))

    assert success
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["total"] == 2
    assert parsed["passed"] == 1
    assert parsed["failed"] == 1


def test_run_tests_output_html(tmp_path, monkeypatch, capsys):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class PassingRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", PassingRunner)

    success = cli.run_tests(make_args(config, output_format="html"))

    assert success
    captured = capsys.readouterr()
    assert "<!DOCTYPE html>" in captured.out
    assert "Total:" in captured.out
    assert "Passed:" in captured.out


# =========================================================================
# run_tests — JUnit XML
# =========================================================================


def test_run_tests_junit_xml(tmp_path, monkeypatch, caplog):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")
    junit_path = tmp_path / "report.xml"

    class PassingRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", PassingRunner)

    success = cli.run_tests(make_args(config, junit_xml=str(junit_path)))

    assert success
    assert "JUnit XML report written to" in caplog.text
    assert junit_path.exists()


def test_run_tests_junit_xml_with_failures(tmp_path, monkeypatch):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")
    junit_path = tmp_path / "report.xml"

    class FailingRunner(DummyRunner):
        def run_tests(self):
            return False

    monkeypatch.setattr(cli, "JSONRunner", FailingRunner)

    success = cli.run_tests(make_args(config, junit_xml=str(junit_path)))

    assert not success
    assert junit_path.exists()


# =========================================================================
# run_tests — workspace resolution
# =========================================================================


def test_run_tests_resolves_config_relative_to_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = workspace / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class PassingRunner(DummyRunner):
        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", PassingRunner)

    success = cli.run_tests(
        make_args("cases.json", workspace=str(workspace))
    )

    assert success


# =========================================================================
# run_tests — exception path
# =========================================================================


def test_run_tests_exception_caught(tmp_path, monkeypatch, caplog):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class CrashingRunner(DummyRunner):
        def run_tests(self):
            raise RuntimeError("boom!")

    monkeypatch.setattr(cli, "JSONRunner", CrashingRunner)

    success = cli.run_tests(make_args(config))

    assert not success
    assert "Error running tests" in caplog.text
    assert "boom" in caplog.text


def test_run_tests_exception_with_debug(tmp_path, monkeypatch, caplog, capsys):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")

    class CrashingRunner(DummyRunner):
        def run_tests(self):
            raise RuntimeError("debug_boom!")

    monkeypatch.setattr(cli, "JSONRunner", CrashingRunner)

    success = cli.run_tests(make_args(config, debug=True))

    assert not success
    captured = capsys.readouterr()
    assert "Traceback" in (captured.err + captured.out) or "Error running tests" in caplog.text


# =========================================================================
# run_tests — variables
# =========================================================================


def test_run_tests_passes_variables_to_runner(tmp_path, monkeypatch):
    config = tmp_path / "cases.json"
    config.write_text('{"test_cases": []}', encoding="utf-8")
    captured = {}

    class VarRunner(DummyRunner):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.update(kwargs)

        def run_tests(self):
            return True

    monkeypatch.setattr(cli, "JSONRunner", VarRunner)

    cli.run_tests(make_args(config, var=["solver=/opt/solver"]))

    assert captured.get("variables") == {"solver": "/opt/solver"}


# =========================================================================
# run_validate
# =========================================================================


class TestRunValidate:
    """Test cli.run_validate."""

    def test_missing_config(self, caplog):
        success = cli.run_validate(make_args("missing.json"))
        assert not success
        assert "Configuration file not found" in caplog.text

    def test_valid_config(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "config.json"
        config.write_text('{"test_cases": [{"name": "t1", "command": "echo"}]}')

        monkeypatch.setattr(
            "cli_test_framework.config.config_io.validate_config",
            lambda cf, ws: {
                "valid": True,
                "summary": {"cases": 1, "files": 1, "files_loaded": ["config.json"]},
                "errors": [],
            },
        )

        success = cli.run_validate(make_args(config))
        assert success
        captured = capsys.readouterr()
        assert "Loaded 1 test cases" in captured.out
        assert "All required fields" in captured.out

    def test_invalid_config_with_errors(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "config.json"
        config.write_text('{}')

        monkeypatch.setattr(
            "cli_test_framework.config.config_io.validate_config",
            lambda cf, ws: {
                "valid": False,
                "summary": {"cases": 0, "files": 0},
                "errors": ["Missing test_cases", "Invalid format"],
            },
        )

        success = cli.run_validate(make_args(config))
        assert not success
        captured = capsys.readouterr()
        assert "Missing test_cases" in captured.out

    def test_warnings_shown_in_text_output(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "config.json"
        config.write_text('{}')

        monkeypatch.setattr(
            "cli_test_framework.config.config_io.validate_config",
            lambda cf, ws: {
                "valid": True,
                "summary": {"cases": 1, "files": 1},
                "errors": [],
                "warnings": ["case 'tc': baseline file not found: 'b.txt'"],
            },
        )

        success = cli.run_validate(make_args(config))
        assert success  # warnings do not affect validity
        captured = capsys.readouterr()
        assert "[WARN]" in captured.out
        assert "baseline file not found" in captured.out

    def test_with_workspace(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        config = workspace / "config.json"
        config.write_text('{}')

        validate_config_called = []

        def fake_validate(cf, ws):
            validate_config_called.append((cf, ws))
            return {"valid": True, "summary": {"cases": 0, "files": 0}, "errors": []}

        monkeypatch.setattr(
            "cli_test_framework.config.config_io.validate_config",
            fake_validate,
        )

        success = cli.run_validate(make_args("config.json", workspace=str(workspace)))
        assert success
        assert validate_config_called[0][1] == str(workspace)


# =========================================================================
# run_schema
# =========================================================================


class TestRunSchema:
    """Test cli.run_schema."""

    def test_prints_valid_json_schema(self, capsys):
        cli.run_schema()
        captured = capsys.readouterr()
        schema = json.loads(captured.out)
        assert schema["title"] == "cli-test configuration"
        assert "$defs" in schema
        assert schema["$schema"].startswith("https://json-schema.org/")

    def test_main_schema_dispatch(self, monkeypatch):
        called = []

        def fake_schema():
            called.append("schema")

        monkeypatch.setattr(cli, "run_schema", fake_schema)
        monkeypatch.setattr("sys.argv", ["cli-test", "schema"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert "schema" in called

    def test_schema_subcommand_parser(self):
        parser = cli.create_parser()
        args = parser.parse_args(["schema"])
        assert args.command == "schema"


# =========================================================================
# run_compare
# =========================================================================


class TestRunCompare:
    """Test cli.run_compare."""

    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            "cli_test_framework.commands.compare.run_comparison",
            lambda args: 0,
        )
        args = Namespace(file1="a.txt", file2="b.txt")
        success = cli.run_compare(args)
        assert success is True

    def test_failure(self, monkeypatch):
        monkeypatch.setattr(
            "cli_test_framework.commands.compare.run_comparison",
            lambda args: 1,
        )
        args = Namespace(file1="a.txt", file2="b.txt")
        success = cli.run_compare(args)
        assert success is False

    def test_exit_code_nonzero(self, monkeypatch):
        monkeypatch.setattr(
            "cli_test_framework.commands.compare.run_comparison",
            lambda args: 2,
        )
        args = Namespace(file1="a.txt", file2="b.txt")
        success = cli.run_compare(args)
        assert success is False


# =========================================================================
# main dispatch
# =========================================================================


class TestMainDispatch:
    """Test cli.main() dispatch to subcommands."""

    def test_main_run(self, monkeypatch):
        called = []

        def fake_run(args):
            called.append("run")
            return True

        monkeypatch.setattr(cli, "run_tests", fake_run)
        monkeypatch.setattr("sys.argv", ["cli-test", "run", "cases.json"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert "run" in called

    def test_main_run_failure(self, monkeypatch):
        def fake_run(args):
            return False

        monkeypatch.setattr(cli, "run_tests", fake_run)
        monkeypatch.setattr("sys.argv", ["cli-test", "run", "cases.json"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1

    def test_main_tui(self, monkeypatch):
        called = []

        def fake_tui(args):
            called.append("tui")

        monkeypatch.setattr(cli, "run_tui", fake_tui)
        monkeypatch.setattr("sys.argv", ["cli-test", "tui", "cases.json"])

        cli.main()
        assert "tui" in called

    def test_main_validate_success(self, monkeypatch):
        def fake_validate(args):
            return True

        monkeypatch.setattr(cli, "run_validate", fake_validate)
        monkeypatch.setattr("sys.argv", ["cli-test", "validate", "config.json"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0

    def test_main_validate_failure(self, monkeypatch):
        def fake_validate(args):
            return False

        monkeypatch.setattr(cli, "run_validate", fake_validate)
        monkeypatch.setattr("sys.argv", ["cli-test", "validate", "config.json"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1

    def test_main_compare_success(self, monkeypatch):
        def fake_compare(args):
            return True

        monkeypatch.setattr(cli, "run_compare", fake_compare)
        monkeypatch.setattr("sys.argv", ["cli-test", "compare", "a.txt", "b.txt"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0

    def test_main_compare_failure(self, monkeypatch):
        def fake_compare(args):
            return False

        monkeypatch.setattr(cli, "run_compare", fake_compare)
        monkeypatch.setattr("sys.argv", ["cli-test", "compare", "a.txt", "b.txt"])

        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1


def test_main_exits_nonzero_without_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cli-test"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


# =========================================================================
# _parse_vars
# =========================================================================


def test_parse_vars_single():
    result = cli._parse_vars(["solver=/opt/solver"])
    assert result == {"solver": "/opt/solver"}


def test_parse_vars_multiple():
    result = cli._parse_vars(["solver=/opt/solver", "model=./data.dat"])
    assert result == {"solver": "/opt/solver", "model": "./data.dat"}


def test_parse_vars_empty():
    result = cli._parse_vars([])
    assert result == {}


def test_parse_vars_invalid_warns(caplog):
    result = cli._parse_vars(["bad_entry"])
    assert result == {}
    assert "Ignoring invalid --var" in caplog.text


def test_parse_vars_key_with_spaces():
    result = cli._parse_vars([" solver = /opt/solver "])
    assert result == {"solver": "/opt/solver"}


def test_parse_vars_value_contains_equals():
    result = cli._parse_vars(["key=val=with=equals"])
    assert result == {"key": "val=with=equals"}


# =========================================================================
# create_parser
# =========================================================================


class TestCreateParser:
    """Test that the argument parser is correctly configured."""

    def test_run_subcommand_accepts_all_args(self):
        parser = cli.create_parser()
        args = parser.parse_args([
            "run", "config.json",
            "--workspace", "/path",
            "--parallel",
            "--workers", "4",
            "--execution-mode", "process",
            "--output-format", "html",
            "--test-case", "tc1",
            "--tag", "smoke",
            "--history-dir", "/tmp/history",
            "--regression-threshold", "2.0",
            "--verbose",
            "--debug",
            "--junit-xml", "report.xml",
            "--var", "key=value",
        ])
        assert args.command == "run"
        assert args.config_file == "config.json"
        assert args.workspace == "/path"
        assert args.parallel is True
        assert args.workers == 4
        assert args.execution_mode == "process"
        assert args.output_format == "html"
        assert args.test_case == ["tc1"]
        assert args.tag == ["smoke"]
        assert args.history_dir == "/tmp/history"
        assert args.regression_threshold == 2.0
        assert args.verbose is True
        assert args.debug is True
        assert args.junit_xml == "report.xml"
        assert args.var == ["key=value"]

    def test_validate_subcommand(self):
        parser = cli.create_parser()
        args = parser.parse_args(["validate", "config.json", "--workspace", "/ws"])
        assert args.command == "validate"
        assert args.config_file == "config.json"
        assert args.workspace == "/ws"

    def test_compare_subcommand(self):
        parser = cli.create_parser()
        args = parser.parse_args([
            "compare", "a.txt", "b.txt",
            "--start-line", "5",
            "--end-line", "10",
            "--output-format", "json",
            "--verbose",
        ])
        assert args.command == "compare"
        assert args.file1 == "a.txt"
        assert args.file2 == "b.txt"
        assert args.start_line == 5
        assert args.end_line == 10
        assert args.output_format == "json"
        assert args.verbose is True

