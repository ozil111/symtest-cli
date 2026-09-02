"""Tests for the inheritance expander module."""

from pathlib import Path
import pytest

from symtest.config.inheritance_expander import (
    resolve_inheritance,
    apply_variables,
    _deep_merge_dicts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# ---------------------------------------------------------------------------
# _deep_merge_dicts
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_scalar_overlay(self):
        """Overlay scalar wins over base."""
        assert _deep_merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

    def test_dict_recursive_merge(self):
        """Dict values are recursively merged."""
        base = {"a": {"x": 1, "y": 2}}
        overlay = {"a": {"y": 99, "z": 3}}
        assert _deep_merge_dicts(base, overlay) == {
            "a": {"x": 1, "y": 99, "z": 3},
        }

    def test_list_whole_replace(self):
        """List is whole-replaced, not extended."""
        base = {"steps": [1, 2, 3]}
        overlay = {"steps": [4, 5]}
        assert _deep_merge_dicts(base, overlay) == {"steps": [4, 5]}

    def test_new_key_added(self):
        """New keys from overlay are added."""
        base = {"a": 1}
        overlay = {"b": 2}
        assert _deep_merge_dicts(base, overlay) == {"a": 1, "b": 2}

    def test_does_not_mutate_inputs(self):
        """Original dicts are not mutated."""
        base = {"a": {"x": 1}}
        overlay = {"a": {"y": 2}}
        result = _deep_merge_dicts(base, overlay)
        assert base == {"a": {"x": 1}}
        assert overlay == {"a": {"y": 2}}
        assert result == {"a": {"x": 1, "y": 2}}


# ---------------------------------------------------------------------------
# resolve_inheritance — no extends
# ---------------------------------------------------------------------------

class TestResolveNoExtends:
    def test_no_extends_unchanged(self):
        """Config without extends is returned with abstract markers removed."""
        config = {
            "test_cases": [
                {"name": "case1", "command": "echo", "args": ["a"], "expected": {}},
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        assert result["test_cases"][0]["name"] == "case1"
        assert "abstract" not in result["test_cases"][0]

    def test_empty_cases(self):
        """Empty test_cases list is fine."""
        result = resolve_inheritance({"test_cases": []})
        assert result["test_cases"] == []

    def test_does_not_mutate_input(self):
        """Original config is not mutated."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["a"], "expected": {},
                 "abstract": True},
            ]
        }
        original_copy = config.copy()
        resolve_inheritance(config)
        assert config == original_copy


# ---------------------------------------------------------------------------
# resolve_inheritance — basic inheritance
# ---------------------------------------------------------------------------

class TestBasicInheritance:
    def test_single_extends_merges_fields(self):
        """Child with extends gets parent's fields merged."""
        config = {
            "test_cases": [
                {
                    "name": "_base",
                    "abstract": True,
                    "command": "echo",
                    "args": ["hello"],
                    "expected": {"return_code": 0},
                },
                {
                    "name": "child1",
                    "extends": "_base",
                },
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        child = result["test_cases"][0]
        assert child["name"] == "child1"
        assert child["command"] == "echo"
        assert child["args"] == ["hello"]
        assert child["expected"] == {"return_code": 0}
        assert "extends" not in child

    def test_child_overrides_parent_scalars(self):
        """Child's scalar value overrides parent's."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["base"], "expected": {}, "tags": ["a"]},
                {"name": "child", "extends": "_base", "args": ["child"],
                 "description": "overridden"},
            ]
        }
        result = resolve_inheritance(config)
        child = result["test_cases"][0]
        assert child["args"] == ["child"]
        assert child["description"] == "overridden"

    def test_child_overrides_parent_list(self):
        """Child's list replaces parent's list (not merged)."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {}, "tags": ["tag1", "tag2"]},
                {"name": "child", "extends": "_base", "tags": ["tag3"]},
            ]
        }
        result = resolve_inheritance(config)
        child = result["test_cases"][0]
        assert child["tags"] == ["tag3"]

    def test_child_merges_dict_deep(self):
        """Child's dict is deep-merged with parent's expected."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"],
                 "expected": {"return_code": 0, "output_contains": ["hello"]}},
                {"name": "child", "extends": "_base",
                 "expected": {"output_contains": ["world"]}},
            ]
        }
        result = resolve_inheritance(config)
        child = result["test_cases"][0]
        assert child["expected"]["return_code"] == 0
        assert child["expected"]["output_contains"] == ["world"]

    def test_child_not_abstract(self):
        """abstract=False is the default; not inherited from parent."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {}},
                {"name": "child", "extends": "_base"},
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        assert result["test_cases"][0]["name"] == "child"


# ---------------------------------------------------------------------------
# resolve_inheritance — chain inheritance
# ---------------------------------------------------------------------------

class TestChainInheritance:
    def test_chain_three_levels(self):
        """A → B → C: C gets merged fields from B which got them from A."""
        config = {
            "test_cases": [
                {"name": "_A", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {"return_code": 0},
                 "variables": {"v": "1"}},
                {"name": "_B", "abstract": True, "extends": "_A",
                 "expected": {"output_contains": ["b"]},
                 "variables": {"w": "2"}},
                {"name": "C", "extends": "_B",
                 "expected": {"output_contains": ["c"]},
                 "variables": {"x": "3"}},
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        c = result["test_cases"][0]
        assert c["command"] == "echo"
        assert c["args"] == ["a"]
        assert c["expected"]["return_code"] == 0  # from A, not overridden
        assert c["expected"]["output_contains"] == ["c"]  # from C (list replace)
        assert c["variables"] == {"v": "1", "w": "2", "x": "3"}


# ---------------------------------------------------------------------------
# resolve_inheritance — variables
# ---------------------------------------------------------------------------

class TestVariables:
    def test_variables_deep_merged_from_chain(self):
        """Variables are deep-merged along the extends chain."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["{k1}"], "expected": {},
                 "variables": {"k1": "v1", "shared": "base"}},
                {"name": "child", "extends": "_base",
                 "variables": {"k2": "v2", "shared": "child"}},
            ]
        }
        result = resolve_inheritance(config)
        child = result["test_cases"][0]
        assert child["variables"] == {"k1": "v1", "k2": "v2", "shared": "child"}

    def test_variables_preserved_on_case(self):
        """After resolve_inheritance, variables remain on case dict."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["{msg}"], "expected": {},
                 "variables": {"msg": "hi"}},
                {"name": "child", "extends": "_base"},
            ]
        }
        result = resolve_inheritance(config)
        assert result["test_cases"][0]["variables"] == {"msg": "hi"}


# ---------------------------------------------------------------------------
# resolve_inheritance — errors
# ---------------------------------------------------------------------------

class TestInheritanceErrors:
    def test_extends_target_not_found(self):
        """extends to a non-existent case raises ValueError."""
        config = {
            "test_cases": [
                {"name": "orphan", "extends": "nonexistent", "expected": {}},
            ]
        }
        with pytest.raises(ValueError, match="extends target not found"):
            resolve_inheritance(config)

    def test_circular_extends_two_nodes(self):
        """Circular extends (A → B → A) raises ValueError."""
        config = {
            "test_cases": [
                {"name": "A", "extends": "B", "expected": {}},
                {"name": "B", "extends": "A", "expected": {}},
            ]
        }
        with pytest.raises(ValueError, match="Circular"):
            resolve_inheritance(config)

    def test_circular_extends_self(self):
        """A case extending itself raises ValueError."""
        config = {
            "test_cases": [
                {"name": "A", "extends": "A", "expected": {}},
            ]
        }
        with pytest.raises(ValueError, match="Circular"):
            resolve_inheritance(config)


# ---------------------------------------------------------------------------
# resolve_inheritance — abstract
# ---------------------------------------------------------------------------

class TestAbstract:
    def test_abstract_without_extends_is_removed(self):
        """Standalone abstract cases (no extends referencing them) are removed."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {}},
                {"name": "real", "command": "echo", "args": ["b"], "expected": {}},
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        assert result["test_cases"][0]["name"] == "real"

    def test_abstract_parent_removed_after_inheritance(self):
        """Abstract base used by extends is removed; only child remains."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {}},
                {"name": "child", "extends": "_base"},
                {"name": "child2", "extends": "_base", "args": ["b"]},
            ]
        }
        result = resolve_inheritance(config)
        names = {c["name"] for c in result["test_cases"]}
        assert names == {"child", "child2"}
        assert len(result["test_cases"]) == 2

    def test_abstract_child_is_removed(self):
        """If a child marks itself abstract, it's still removed."""
        config = {
            "test_cases": [
                {"name": "_base", "abstract": True, "command": "echo",
                 "args": ["a"], "expected": {}},
                {"name": "_child", "extends": "_base", "abstract": True},
            ]
        }
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 0


# ---------------------------------------------------------------------------
# resolve_inheritance — fixtures
# ---------------------------------------------------------------------------

class TestResolveFixtures:
    def test_fixture_basic_inheritance(self):
        """Test with inheritance_base.json fixture."""
        from symtest.config.import_expander import _load_raw_config

        path = FIXTURES / "inheritance_base.json"
        config = _load_raw_config(path)
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 2
        names = {c["name"] for c in result["test_cases"]}
        assert names == {"child_echo_hello", "child_echo_custom"}

        hello = [c for c in result["test_cases"]
                 if c["name"] == "child_echo_hello"][0]
        assert hello["execution"]["command"] == "echo"
        assert hello["execution"]["args"] == ["{msg}"]
        assert hello["variables"] == {"msg": "hello"}
        assert hello["expected"] == {"output_contains": ["{msg}"]}

        custom = [c for c in result["test_cases"]
                  if c["name"] == "child_echo_custom"][0]
        assert custom["variables"] == {"msg": "world"}
        # expected deep-merged: parent's output_contains + child's return_code
        assert custom["expected"]["return_code"] == 0
        assert custom["expected"]["output_contains"] == ["{msg}"]

    def test_fixture_chain_inheritance(self):
        """Test with inheritance_chain.json fixture."""
        from symtest.config.import_expander import _load_raw_config

        path = FIXTURES / "inheritance_chain.json"
        config = _load_raw_config(path)
        result = resolve_inheritance(config)
        assert len(result["test_cases"]) == 1
        c = result["test_cases"][0]
        assert c["name"] == "C_concrete"
        # variables deep-merged: A→B→C, C wins shared
        assert c["variables"] == {
            "a": "1", "b": "2", "c": "3", "shared": "from_c",
        }
        # expected deep-merged: A (empty) → B output_contains
        assert c["expected"]["output_contains"] == ["step_b"]
        # args from C (overrides A)
        assert c["execution"]["args"] == ["print('{a} {b} {c}')"]
        assert c["execution"]["command"] == "python"  # from A


# ---------------------------------------------------------------------------
# apply_variables
# ---------------------------------------------------------------------------

class TestApplyVariables:
    def test_no_variables_no_global(self):
        """Config without variables field passes through unchanged."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["hello"],
                 "expected": {}},
            ]
        }
        result = apply_variables(config)
        assert result["test_cases"][0]["args"] == ["hello"]
        assert "variables" not in result["test_cases"][0]

    def test_case_variables_substituted(self):
        """Per-case variables are substituted."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["{msg}"],
                 "expected": {"output_contains": ["{msg}"]},
                 "variables": {"msg": "hello"}},
            ]
        }
        result = apply_variables(config)
        c = result["test_cases"][0]
        assert c["args"] == ["hello"]
        assert c["expected"]["output_contains"] == ["hello"]
        assert "variables" not in c

    def test_global_variables_applied(self):
        """Global variables substitute placeholders across all cases."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "{solver}", "args": ["{path}"],
                 "expected": {}},
            ]
        }
        result = apply_variables(config, {"solver": "python", "path": "/tmp"})
        c = result["test_cases"][0]
        assert c["command"] == "python"
        assert c["args"] == ["/tmp"]

    def test_global_overlays_case_variables(self):
        """Global --var takes precedence over case variables."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["{msg}"],
                 "expected": {},
                 "variables": {"msg": "case_value"}},
            ]
        }
        result = apply_variables(config, {"msg": "global_value"})
        c = result["test_cases"][0]
        assert c["args"] == ["global_value"]

    def test_setup_with_global_variables(self):
        """setup dict is substituted with global variables only."""
        config = {
            "setup": {"solver_path": "{solver}"},
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["a"],
                 "expected": {}},
            ]
        }
        result = apply_variables(config, {"solver": "/usr/bin/python"})
        assert result["setup"]["solver_path"] == "/usr/bin/python"

    def test_variables_consumed(self):
        """After apply_variables, 'variables' key is removed from each case."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["{msg}"],
                 "expected": {},
                 "variables": {"msg": "test"}},
            ]
        }
        result = apply_variables(config)
        assert "variables" not in result["test_cases"][0]

    def test_partial_match_left_unchanged(self):
        """Placeholders not in variables are left as-is."""
        config = {
            "test_cases": [
                {"name": "c1", "command": "echo", "args": ["{msg} {other}"],
                 "expected": {},
                 "variables": {"msg": "hello"}},
            ]
        }
        result = apply_variables(config)
        c = result["test_cases"][0]
        assert c["args"] == ["hello {other}"]
