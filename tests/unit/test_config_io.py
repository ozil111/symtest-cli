"""Tests for config_io module (load/save/validate)."""

from pathlib import Path
import json
import tempfile
import os
import pytest

from symtest.config.config_io import (
    load_config,
    save_config,
    validate_config,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestLoadConfig:
    def test_load_json_no_imports(self):
        """Loading a JSON config without imports returns raw dict."""
        path = FIXTURES / "sub_text_tests.json"
        config = load_config(path)
        assert "test_cases" in config
        assert len(config["test_cases"]) == 2

    def test_load_with_expand(self):
        """Loading main_config with expand=True inlines imports."""
        path = FIXTURES / "main_config.json"
        config = load_config(path, expand=True)
        assert len(config["test_cases"]) == 5

    def test_load_without_expand(self):
        """Loading with expand=False preserves import entries."""
        path = FIXTURES / "main_config.json"
        config = load_config(path, expand=False)
        # Should have import entries, not expanded
        has_import = any("import" in tc for tc in config["test_cases"])
        assert has_import

    def test_load_nonexistent_file(self):
        """Loading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(Path("nonexistent.json"))


class TestSaveConfig:
    def test_save_and_load_json(self):
        """Round-trip save/load for JSON."""
        config = {
            "test_cases": [
                {"name": "tc1", "command": "echo", "args": ["hi"],
                 "expected": {"return_code": 0}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_config.json"
            save_config(config, path)
            assert path.exists()

            loaded = load_config(path, expand=False)
            assert loaded["test_cases"][0]["name"] == "tc1"

    def test_save_and_load_yaml(self):
        """Round-trip save/load for YAML."""
        config = {
            "test_cases": [
                {"name": "tc1", "command": "echo", "args": ["hi"],
                 "expected": {"return_code": 0}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_config.yaml"
            save_config(config, path)
            assert path.exists()

            loaded = load_config(path, expand=False)
            assert loaded["test_cases"][0]["name"] == "tc1"

    def test_save_unsupported_extension(self):
        """Unsupported extension raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_config.txt"
            with pytest.raises(ValueError, match="Unsupported output format"):
                save_config({"test_cases": []}, path)


class TestValidateConfig:
    def test_valid_config_passes(self):
        """A valid config with all required fields passes validation."""
        result = validate_config(FIXTURES / "sub_text_tests.json")
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["summary"]["cases"] == 2

    def test_valid_config_with_imports(self):
        """Config with valid imports passes validation."""
        result = validate_config(FIXTURES / "main_config.json")
        assert result["valid"] is True

    def test_missing_required_fields(self):
        """Cases missing required fields are reported."""
        result = validate_config(FIXTURES / "missing_fields.json")
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        # First case should be missing 'expected'
        assert any("expected" in err for err in result["errors"])

    def test_import_target_not_found(self):
        """Non-existent import targets are reported."""
        bad_config_path = FIXTURES / "main_config.json"
        # Create a temp config that imports a nonexistent file
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            config = {
                "test_cases": [
                    {"import": "nonexistent.json"}
                ]
            }
            path = tmpdir_path / "bad_main.json"
            save_config(config, path)
            result = validate_config(path)
            assert result["valid"] is False
            assert any("not found" in err for err in result["errors"])

    def test_circular_import_detected(self):
        """Circular imports are detected."""
        result = validate_config(FIXTURES / "circular_config_a.json")
        assert result["valid"] is False
        assert any("Circular" in err for err in result["errors"])

    def test_files_loaded_summary(self):
        """Summary includes file count for configs with imports."""
        result = validate_config(FIXTURES / "main_config.json")
        assert result["summary"]["files"] == 3  # main + 2 sub-files
        assert result["summary"]["cases"] == 5


class TestValidateConfigWarnings:
    """Warning-level checks: reported but do not affect ``valid``."""

    def _write_config(self, tmpdir, config):
        path = Path(tmpdir) / "config.json"
        save_config(config, path)
        return path

    def test_missing_baseline_warns_but_stays_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "tc", "command": "echo", "args": ["hi"],
                    "expected": {
                        "compare_files": [
                            {"actual": "out.txt", "baseline": "missing_base.txt"}
                        ]
                    },
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is True
            assert any("baseline file not found" in w for w in result["warnings"])

    def test_existing_baseline_no_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "base.txt").write_text("ref\n", encoding="utf-8")
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "tc", "command": "echo", "args": ["hi"],
                    "expected": {
                        "compare_files": [{"actual": "out.txt", "baseline": "base.txt"}]
                    },
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["warnings"] == []

    def test_command_not_on_path_warns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "tc", "command": "definitely-not-a-real-cmd-xyz123",
                    "args": [], "expected": {"return_code": 0},
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is True
            assert any("not found on PATH" in w for w in result["warnings"])

    def test_builtin_command_no_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "tc", "command": "echo", "args": ["hi"],
                    "expected": {"return_code": 0},
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["warnings"] == []

    def test_placeholders_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "tc", "command": "{solver}", "args": ["run"],
                    "expected": {
                        "compare_files": [
                            {"actual": "out.txt", "baseline": "{baseline_dir}/x.txt"}
                        ]
                    },
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["warnings"] == []

    def test_sequence_case_warnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [{
                    "name": "seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "not-a-real-cmd-xyz", "args": [], "expected": {"return_code": 0}},
                    ],
                    "expected": {
                        "compare_files": [{"actual": "o.txt", "baseline": "gone.txt"}]
                    },
                }]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is True
            assert any("step 1" in w and "not found on PATH" in w for w in result["warnings"])
            assert any("baseline file not found" in w for w in result["warnings"])

    def test_syntax_error_report_includes_warnings_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not valid json", encoding="utf-8")
            result = validate_config(bad)
            assert result["valid"] is False
            assert result["warnings"] == []


class TestConfigSchema:
    """The exported JSON Schema is the machine-readable config contract."""

    def test_schema_structure(self):
        from symtest.config.config_schema import get_config_schema

        schema = get_config_schema()
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["type"] == "object"
        assert "test_cases" in schema["required"]
        for defname in ("expected", "compareSpec", "resources", "step",
                        "singleCase", "sequenceCase", "importRef"):
            assert defname in schema["$defs"], f"missing $defs.{defname}"

    def test_schema_is_json_serializable(self):
        from symtest.config.config_schema import get_config_schema

        json.dumps(get_config_schema())  # must not raise

    def test_get_config_schema_returns_independent_copy(self):
        from symtest.config.config_schema import get_config_schema

        mutated = get_config_schema()
        mutated["title"] = "mutated"
        assert get_config_schema()["title"] != "mutated"

    def test_required_fields_match_validate_config(self):
        """singleCase/step required fields must match validate_config's checks."""
        from symtest.config.config_schema import get_config_schema

        defs = get_config_schema()["$defs"]
        # singleCase now uses allOf with if/then for conditional required
        # (extends present → only name required; else → name, command, args, expected)
        single_allof = defs["singleCase"]["allOf"]
        else_section = single_allof[0]["else"]
        assert else_section["required"] == ["name", "command", "args", "expected"]
        assert defs["step"]["required"] == ["command", "args", "expected"]

        # sequenceCase also uses allOf
        seq_allof = defs["sequenceCase"]["allOf"]
        seq_else = seq_allof[0]["else"]
        assert seq_else["required"] == ["name", "steps"]


class TestValidateInheritance:
    """validate_config should detect extends-related errors."""

    def _write_config(self, tmpdir, config):
        path = Path(tmpdir) / "config.json"
        save_config(config, path)
        return path

    def test_extends_target_not_found_reported(self):
        """extends to a nonexistent case is an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [
                    {"name": "orphan", "extends": "nonexistent"},
                ]
            })
            result = validate_config(path)
            assert result["valid"] is False
            assert any("extends target" in err and "not found" in err
                       for err in result["errors"])

    def test_circular_extends_reported(self):
        """Circular extends chain is an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [
                    {"name": "A", "extends": "B"},
                    {"name": "B", "extends": "A"},
                ]
            })
            result = validate_config(path)
            assert result["valid"] is False
            assert any("Circular extends" in err for err in result["errors"])

    def test_valid_inheritance_does_not_count_abstract(self):
        """Abstract cases are not counted in case summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [
                    {"name": "_base", "abstract": True, "command": "echo",
                     "args": ["a"], "expected": {}},
                    {"name": "child1", "extends": "_base"},
                    {"name": "child2", "extends": "_base"},
                ]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is True
            assert result["summary"]["cases"] == 2  # only children

    def test_extends_case_skips_required_field_checks(self):
        """Cases with extends should not be flagged for missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [
                    {"name": "_base", "abstract": True, "command": "echo",
                     "args": ["a"], "expected": {}},
                    {"name": "child", "extends": "_base"},
                    # child has no command/args/expected but inherits them
                ]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is True

    def test_duplicate_case_name_reported(self):
        """Duplicate case names across files should be flagged (ambiguous extends)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_config(tmpdir, {
                "test_cases": [
                    {"name": "same", "command": "echo", "args": ["1"],
                     "expected": {}},
                    {"name": "same", "command": "echo", "args": ["2"],
                     "expected": {}},
                ]
            })
            result = validate_config(path, workspace=tmpdir)
            assert result["valid"] is False
            assert any("Duplicate case name" in err for err in result["errors"])
