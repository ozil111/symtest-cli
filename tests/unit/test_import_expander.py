"""Tests for the import expander module (方案 B – config splitting)."""

from pathlib import Path
import pytest

from symtest.config.import_expander import expand_imports, _load_raw_config

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_expand_no_imports():
    """Config without 'import' entries is returned unchanged."""
    config = {
        "test_cases": [
            {"name": "case1", "command": "echo", "args": ["a"], "expected": {}},
        ]
    }
    result = expand_imports(config, Path("dummy.json"))
    assert result["test_cases"] == config["test_cases"]


def test_expand_single_import():
    """A single import entry is expanded and cases are inlined."""
    main_path = FIXTURES / "main_config.json"
    config = _load_raw_config(main_path)
    result = expand_imports(config, main_path)

    # Should have: 1 inline + 2 from JSON + 2 from YAML = 5 cases
    assert len(result["test_cases"]) == 5

    names = {tc["name"] for tc in result["test_cases"]}
    assert "main_inline_case" in names
    assert "text_identical" in names
    assert "text_diff" in names
    assert "json_exact" in names
    assert "json_steps" in names


def test_import_paths_resolved_relative_to_config():
    """Import paths are resolved relative to the config file's parent dir."""
    main_path = FIXTURES / "main_config.json"
    config = _load_raw_config(main_path)
    result = expand_imports(config, main_path)

    # The imported cases should be resolved correctly
    names = {tc["name"] for tc in result["test_cases"]}
    assert names == {"main_inline_case", "text_identical", "text_diff",
                     "json_exact", "json_steps"}


def test_import_file_not_found():
    """Missing import file raises FileNotFoundError."""
    config = {"test_cases": [{"import": "nonexistent.json"}]}
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        expand_imports(config, Path("dummy.json"))


def test_circular_import_detected():
    """Circular imports raise RuntimeError."""
    a_path = (FIXTURES / "circular_config_a.json").resolve()
    config = _load_raw_config(a_path)
    with pytest.raises(RuntimeError, match="Circular import"):
        expand_imports(config, a_path)


def test_yaml_import_from_json():
    """A JSON main config can import YAML sub-files."""
    main_path = FIXTURES / "main_config.json"
    config = _load_raw_config(main_path)
    result = expand_imports(config, main_path)

    # Find the YAML-imported cases
    yaml_cases = [tc for tc in result["test_cases"]
                  if tc["name"] in ("json_exact", "json_steps")]
    assert len(yaml_cases) == 2

    # json_steps should be a sequence
    json_steps = next(tc for tc in result["test_cases"] if tc["name"] == "json_steps")
    assert "steps" in json_steps["execution"]
    assert len(json_steps["execution"]["steps"]) == 2


def test_setup_merge():
    """Setup from main and sub files are merged; sub values override main."""
    main_path = FIXTURES / "setup_main.json"
    config = _load_raw_config(main_path)
    result = expand_imports(config, main_path)

    assert "setup" in result
    env = result["setup"]["environment_variables"]
    assert env["BASE"] == "from_main"
    assert env["SUB_KEY"] == "from_sub"
    assert env["OVERRIDE_ME"] == "from_sub"  # sub overrides main


def test_setup_preserved_without_imports():
    """Setup is preserved when there are no imports."""
    config = {
        "setup": {"environment_variables": {"KEY": "val"}},
        "test_cases": [
            {"name": "c", "command": "echo", "args": ["x"], "expected": {}},
        ],
    }
    result = expand_imports(config, Path("dummy.json"))
    assert result["setup"] == config["setup"]
    assert result["test_cases"] == config["test_cases"]


def test_empty_test_cases():
    """Config with empty test_cases list works."""
    result = expand_imports({"test_cases": []}, Path("dummy.json"))
    assert result["test_cases"] == []


def test_deeply_nested_import():
    """Three-level deep import chain expands correctly."""
    # main -> A -> B; B has 1 case
    main = {
        "test_cases": [{"import": "sub_text_tests.json"}],
    }
    result = expand_imports(main, FIXTURES / "main_config.json")
    assert len(result["test_cases"]) == 2  # 2 cases in sub_text_tests.json
    names = {tc["name"] for tc in result["test_cases"]}
    assert names == {"text_identical", "text_diff"}
