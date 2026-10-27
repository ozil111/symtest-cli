"""Acceptance tests for the unified config preparation pipeline.

Covers the user-feedback scenarios that motivated the refactor:

- structural errors (empty config, typo'd fields, negative retry_count,
  mixed execution forms) must fail **before execution**, identically for
  ``validate`` and ``run``;
- templates / inheritance cases may be incomplete in the raw file, but the
  *expanded* case must be complete;
- errors imported from sub-config files are located to file + field;
- legal template, inheritance, sequence and plugin-style configs keep working.
"""

import json
import sys
from pathlib import Path

import pytest

from symtest.config.config_io import load_config, validate_config
from symtest.config.prepared import prepare_config, ConfigValidationError
from symtest.config.config_schema import (
    get_config_schema,
    get_expanded_config_schema,
)


def _write(tmp_path, config, name="config.json"):
    path = tmp_path / name
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _valid_single_case(name="t"):
    return {
        "name": name,
        "execution": {"command": "echo", "args": ["hi"]},
        "expected": {"return_code": 0},
    }


# ---------------------------------------------------------------------------
# Structural errors rejected before execution
# ---------------------------------------------------------------------------

class TestStructuralErrors:
    @pytest.mark.parametrize("location", ["top", "default_channel", "channels"])
    def test_nonfinite_policy_requires_boolean(self, tmp_path, location):
        spec = {"type": "csv", "actual": "a.csv", "baseline": "b.csv"}
        policy = {"allow_nonfinite": "false"}
        if location == "top":
            spec.update(policy)
        elif location == "channels":
            spec[location] = {"S11": policy}
        else:
            spec[location] = policy
        case = _valid_single_case()
        case["expected"]["compare_files"] = [spec]
        path = _write(tmp_path, {"test_cases": [case]})
        report = validate_config(path, workspace=str(tmp_path))
        assert not report["valid"]
        assert any("allow_nonfinite" in e and "boolean" in e for e in report["errors"])
        with pytest.raises(ConfigValidationError, match="allow_nonfinite"):
            load_config(path, workspace=str(tmp_path))

    def test_empty_config_object(self, tmp_path):
        """``{}`` (no test_cases) must be invalid."""
        report = validate_config(_write(tmp_path, {}), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("test_cases" in e for e in report["errors"])

    def test_assertion_field_typo(self, tmp_path):
        """``return_cod`` (typo) must be caught by the strict schema."""
        cfg = {
            "test_cases": [{
                "name": "t",
                "execution": {"command": "echo", "args": ["hi"]},
                "expected": {"return_cod": 0},
            }]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("return_cod" in e for e in report["errors"])

    def test_unknown_case_level_field(self, tmp_path):
        cfg = {"test_cases": [{**_valid_single_case(), "cmd": "echo"}]}
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("cmd" in e for e in report["errors"])

    def test_negative_retry_count(self, tmp_path):
        cfg = {
            "test_cases": [{
                "name": "t",
                "execution": {"command": "echo", "args": [], "retry_count": -1},
                "expected": {"return_code": 0},
            }]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("retry_count" in e for e in report["errors"])

    def test_mixed_execution_forms(self, tmp_path):
        """command/args and steps declared together must be rejected."""
        cfg = {
            "test_cases": [{
                "name": "t",
                "execution": {
                    "command": "echo",
                    "args": ["hi"],
                    "steps": [
                        {"command": "echo", "args": ["a"],
                         "expected": {"return_code": 0}},
                    ],
                },
                "expected": {"return_code": 0},
            }]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        # dispatch sends it to the sequence form, which rejects command/args
        assert any("'command'" in e or "command" in e for e in report["errors"])

    def test_missing_execution_on_plain_case(self, tmp_path):
        cfg = {"test_cases": [{"name": "t", "expected": {}}]}
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("'execution'" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Template / inheritance completeness
# ---------------------------------------------------------------------------

class TestInheritanceCompleteness:
    @pytest.mark.parametrize("sequence", [False, True])
    @pytest.mark.parametrize("overlay", [
        {"timeout": 10}, {"env": {"SOLVER": "test"}},
    ])
    def test_partial_execution_inherits_command_or_steps(self, tmp_path, sequence, overlay):
        from symtest.runners.json_runner import JSONRunner
        from symtest.runners.parallel_json_runner import ParallelJSONRunner

        execution = {"command": "echo", "args": ["base"]}
        if sequence:
            execution = {"steps": [{**execution, "expected": {"return_code": 0}}]}
        cfg = _write(tmp_path, {"test_cases": [
            {"name": "base", "abstract": True, "execution": execution,
             "expected": {"return_code": 0}},
            {"name": "child", "extends": "base", "execution": overlay},
        ]})
        report = validate_config(cfg, workspace=str(tmp_path))
        assert report["valid"], report["errors"]
        prepared = load_config(cfg, workspace=str(tmp_path))
        assert prepared["test_cases"][0]["execution"] == {**execution, **overlay}
        for runner_cls in (JSONRunner, ParallelJSONRunner):
            runner = runner_cls(str(cfg), workspace=str(tmp_path))
            runner.load_test_cases()
            assert [case.name for case in runner.test_cases] == ["child"]

    def test_partial_template_and_child_complete_each_other(self, tmp_path):
        cfg = _write(tmp_path, {"test_cases": [
            {"name": "base", "abstract": True,
             "execution": {"command": "echo", "timeout": 10}, "expected": {}},
            {"name": "child", "extends": "base", "execution": {"args": ["child"]}},
        ]})
        prepared = prepare_config(cfg, workspace=str(tmp_path))
        assert prepared.valid, prepared.errors
        assert prepared.config["test_cases"][0]["execution"] == {
            "command": "echo", "timeout": 10, "args": ["child"],
        }

    @pytest.mark.parametrize("execution", [
        {"timeout": 10}, {"retry_count": -1}, {"argz": []},
        {"args": "wrong type"},
        {"command": "echo", "steps": [{"command": "echo", "args": [], "expected": {}}]},
    ])
    def test_partial_execution_does_not_bypass_constraints(self, tmp_path, execution):
        cfg = _write(tmp_path, {"test_cases": [
            {"name": "base", "abstract": True, "expected": {}},
            {"name": "child", "extends": "base", "execution": execution},
        ]})
        report = validate_config(cfg, workspace=str(tmp_path))
        assert not report["valid"]
        assert any("execution" in error for error in report["errors"])

    def test_abstract_template_may_lack_execution(self, tmp_path):
        """Raw form: templates are allowed to omit required fields."""
        cfg = {
            "test_cases": [
                {"name": "_base", "abstract": True,
                 "expected": {"return_code": 0}},
            ]
        }
        # Raw validation passes; the (removed) template does not reach the
        # expanded stage, so the config is valid.
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert report["valid"]

    def test_incomplete_after_inheritance_fails(self, tmp_path):
        """Child inheriting an execution-less base must fail (user bug #3)."""
        cfg = {
            "test_cases": [
                {"name": "_base", "abstract": True,
                 "expected": {"return_code": 0}},
                {"name": "child", "extends": "_base"},
            ]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert not report["valid"]
        assert any("execution" in e and "child" in e for e in report["errors"])

    def test_complete_after_inheritance_passes(self, tmp_path):
        cfg = {
            "test_cases": [
                {"name": "_base", "abstract": True,
                 "execution": {"command": "echo", "args": ["a"]},
                 "expected": {"return_code": 0}},
                {"name": "child", "extends": "_base"},
            ]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert report["valid"]
        assert report["summary"]["cases"] == 1  # abstract base not counted

    def test_valid_sequence_case_without_case_level_expected(self, tmp_path):
        cfg = {
            "test_cases": [{
                "name": "seq",
                "execution": {
                    "steps": [
                        {"command": "echo", "args": ["a"],
                         "expected": {"return_code": 0}},
                    ],
                },
            }]
        }
        report = validate_config(_write(tmp_path, cfg), workspace=str(tmp_path))
        assert report["valid"]


# ---------------------------------------------------------------------------
# Import error localization
# ---------------------------------------------------------------------------

class TestImportLocalization:
    @pytest.mark.parametrize("content", ["test_cases: [\n", 'test_cases: "\\q"\n'])
    def test_imported_yaml_syntax_error_is_reported(self, tmp_path, content):
        pytest.importorskip("yaml")
        from symtest.runners.json_runner import JSONRunner

        sub_path = tmp_path / "broken.yaml"
        sub_path.write_text(content, encoding="utf-8")
        cfg = _write(tmp_path, {"test_cases": [{"import": "broken.yaml"}]})
        report = validate_config(cfg, workspace=str(tmp_path))
        assert not report["valid"]
        assert any(str(sub_path) in e and str(cfg) in e for e in report["errors"])
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(cfg, workspace=str(tmp_path))
        assert exc_info.value.errors == report["errors"]
        runner = JSONRunner(str(cfg), workspace=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            runner.load_test_cases()
        for error in report["errors"]:
            assert error in str(exc_info.value.code)

    def test_error_in_imported_file_names_file_and_field(self, tmp_path):
        sub = {
            "test_cases": [{
                "name": "sub_case",
                "execution": {"command": "echo", "args": ["hi"]},
                "expected": {"return_cod": 0},  # typo in the *imported* file
            }]
        }
        sub_path = tmp_path / "sub.json"
        sub_path.write_text(json.dumps(sub), encoding="utf-8")

        main = {"test_cases": [{"import": "sub.json"}]}
        main_path = _write(tmp_path, main, name="main.json")

        report = validate_config(main_path, workspace=str(tmp_path))
        assert not report["valid"]
        assert any(
            str(sub_path) in e and "return_cod" in e
            for e in report["errors"]
        ), report["errors"]

    def test_import_entry_with_tags_is_valid(self, tmp_path):
        """import-level tag injection stays schema-legal."""
        sub = {"test_cases": [_valid_single_case("sub_case")]}
        (tmp_path / "sub.json").write_text(json.dumps(sub), encoding="utf-8")
        main = {"test_cases": [{"import": "sub.json", "tags": ["smoke"]}]}
        report = validate_config(
            _write(tmp_path, main, name="main.json"), workspace=str(tmp_path),
        )
        assert report["valid"], report["errors"]

    def test_invalid_imported_file_skipped_but_localized(self, tmp_path):
        sub = {"test_cases": [{"name": "bad"}]}  # missing execution/expected
        sub_path = tmp_path / "bad.json"
        sub_path.write_text(json.dumps(sub), encoding="utf-8")
        main = {"test_cases": [{"import": "bad.json"}]}
        report = validate_config(
            _write(tmp_path, main, name="main.json"), workspace=str(tmp_path),
        )
        assert not report["valid"]
        assert any(str(sub_path) in e for e in report["errors"])


# ---------------------------------------------------------------------------
# run / validate consistency + execution gating
# ---------------------------------------------------------------------------

class TestRunValidateConsistency:
    def _invalid_config(self):
        return {
            "test_cases": [{
                "name": "t",
                "execution": {"command": sys.executable,
                              "args": ["-c", "open('marker.txt', 'w')"]},
                "expected": {"return_cod": 0},  # typo
            }]
        }

    def test_invalid_config_never_executes_command(self, tmp_path):
        from symtest.runners.json_runner import JSONRunner

        cfg = _write(tmp_path, self._invalid_config())
        runner = JSONRunner(str(cfg), workspace=str(tmp_path))
        with pytest.raises(SystemExit):
            runner.run_tests()
        # the command must not have run
        assert not (tmp_path / "marker.txt").exists()

    def test_run_reports_same_errors_as_validate(self, tmp_path):
        from symtest.runners.json_runner import JSONRunner

        cfg = _write(tmp_path, self._invalid_config())
        report = validate_config(cfg, workspace=str(tmp_path))
        assert not report["valid"]

        runner = JSONRunner(str(cfg), workspace=str(tmp_path))
        with pytest.raises(SystemExit) as exc_info:
            runner.load_test_cases()
        exit_text = str(exc_info.value.code)
        for err in report["errors"]:
            assert err in exit_text, err

    def test_load_config_raises_with_diagnostics(self, tmp_path):
        cfg = _write(tmp_path, self._invalid_config())
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(cfg)
        assert any("return_cod" in line for line in exc_info.value.errors)

    def test_valid_config_runs_and_creates_marker(self, tmp_path):
        from symtest.runners.json_runner import JSONRunner

        cfg = _write(tmp_path, {
            "test_cases": [{
                "name": "t",
                "execution": {"command": sys.executable,
                              "args": ["-c", "open('marker.txt', 'w').close()"]},
                "expected": {"return_code": 0},
            }]
        })
        runner = JSONRunner(str(cfg), workspace=str(tmp_path))
        assert runner.run_tests() is True
        assert (tmp_path / "marker.txt").exists()


# ---------------------------------------------------------------------------
# Variables / placeholders survive the pipeline
# ---------------------------------------------------------------------------

class TestVariablesPipeline:
    def test_prepare_config_substitutes_variables(self, tmp_path):
        cfg = {
            "test_cases": [{
                "name": "t",
                "execution": {"command": "{solver}", "args": ["--version"]},
                "expected": {"return_code": 0},
                "variables": {"solver": "echo"},
            }]
        }
        prepared = prepare_config(
            _write(tmp_path, cfg), workspace=str(tmp_path),
        )
        assert prepared.valid, prepared.errors
        case = prepared.config["test_cases"][0]
        assert case["execution"]["command"] == "echo"
        assert "variables" not in case  # consumed by the pipeline

    def test_global_variables_overlay(self, tmp_path):
        cfg = {
            "test_cases": [{
                "name": "t",
                "execution": {"command": "{solver}", "args": ["--version"]},
                "expected": {"return_code": 0},
                "variables": {"solver": "python"},
            }]
        }
        prepared = prepare_config(
            _write(tmp_path, cfg), workspace=str(tmp_path),
            variables={"solver": "echo"},
        )
        assert prepared.valid
        assert prepared.config["test_cases"][0]["execution"]["command"] == "echo"


# ---------------------------------------------------------------------------
# Schema contract self-tests (branch fixes from the review)
# ---------------------------------------------------------------------------

class TestSchemaContract:
    @pytest.mark.parametrize("schema_fn", [get_config_schema, get_expanded_config_schema])
    @pytest.mark.parametrize("location", ["top", "default_channel", "channels"])
    @pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}, False, True])
    def test_nonfinite_policy_type(self, schema_fn, location, value):
        from jsonschema import Draft202012Validator

        spec = {"type": "script_extract", "script": "extract.py"}
        policy = {"allow_nonfinite": value}
        if location == "top":
            spec.update(policy)
        elif location == "channels":
            spec[location] = {"S11": policy}
        else:
            spec[location] = policy
        case = _valid_single_case()
        case["expected"]["compare_files"] = [spec]
        errors = list(Draft202012Validator(schema_fn()).iter_errors({"test_cases": [case]}))
        assert bool(errors) is (type(value) is not bool)
        if errors:
            assert any("allow_nonfinite" in e.json_path for e in errors)

    def test_single_case_forces_command_form(self):
        defs = get_config_schema()["$defs"]
        execution = defs["singleCase"]["allOf"][1]["properties"]["execution"]
        assert execution["$ref"] == "#/$defs/partialCommandExecution"

    def test_sequence_case_forces_steps_form(self):
        """sequenceCase must not accept the command shorthand (review bug)."""
        defs = get_config_schema()["$defs"]
        execution = defs["sequenceCase"]["allOf"][1]["properties"]["execution"]
        assert execution["$ref"] == "#/$defs/stepsExecution"

    def test_import_ref_allows_tags(self):
        defs = get_config_schema()["$defs"]
        assert "tags" in defs["importRef"]["properties"]

    def test_raw_relaxation_for_template_and_heir(self):
        allof = get_config_schema()["$defs"]["singleCase"]["allOf"]
        cond = allof[0]
        assert cond["then"]["required"] == ["name"]
        assert cond["else"]["required"] == ["name", "execution", "expected"]
        # relaxation triggers on extends OR abstract: true
        assert {"required": ["extends"]} in cond["if"]["anyOf"]

    def test_expanded_schema_rejects_template_markers(self):
        import jsonschema

        schema = get_expanded_config_schema()
        case = {
            "name": "t",
            "execution": {"command": "echo", "args": []},
            "expected": {},
            "variables": {"a": "b"},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"test_cases": [case]}, schema)

    def test_expanded_schema_accepts_complete_case(self):
        import jsonschema

        schema = get_expanded_config_schema()
        jsonschema.validate(
            {"test_cases": [_valid_single_case()]}, schema,
        )

    def test_schemas_are_json_serializable(self):
        json.dumps(get_config_schema())
        json.dumps(get_expanded_config_schema())
