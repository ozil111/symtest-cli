"""Regression tests for the comparator construction lifecycle (v2.1).

Acceptance coverage:
1. path_params are workspace-resolved BEFORE comparator construction
2. constructor-captured state (self.script / self.cwd / self.case_dir)
   contains resolved absolute paths
3. behaviour is independent of the process CWD
4. hourglass-style plugins keep working without plugin-side .resolve()
5. abstract comparator classes are never registered
6. explicit comparator_type wins over the class-name convention
7. the convention fallback strips ONLY the trailing Comparator suffix
8. built-in and workspace discovery share identical registration rules
9. unknown/misspelled comparator parameters fail loudly
10. the "options" config namespace merges into constructor kwargs with
    top-level keys taking precedence
"""
import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

from symtest.core.validation.assertions import Assertions, ValidationError
from symtest.core.validation.validator import _dispatch_file_compare
from symtest.file_comparator.base_comparator import ComparatorBase, CompareContext
from symtest.file_comparator.extractor_comparator import ExtractorComparator
from symtest.file_comparator.factory import (
    ComparatorFactory,
    _type_name_from_class,
)
from symtest.file_comparator.result import ComparisonResult
from symtest.file_comparator.script_extract_comparator import (
    ScriptExtractComparator,
)


@pytest.fixture(autouse=True)
def _clean_factory():
    ComparatorFactory.reset()
    yield
    ComparatorFactory.reset()


def _register_type(type_name, cls):
    ComparatorFactory.register_comparator(type_name, cls)


# ---------------------------------------------------------------------------
# 1–3: path_params resolved before construction, CWD-independent
# ---------------------------------------------------------------------------

class TestPathParamsResolvedBeforeConstruction:
    def test_script_extract_ctor_state_is_workspace_resolved(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "cases" / "case01").mkdir(parents=True)

        cmp = ComparatorFactory.create_comparator(
            "script_extract",
            workspace=str(tmp_path),
            script="scripts/extract.py",
            cwd="cases/case01",
        )
        assert isinstance(cmp, ScriptExtractComparator)
        # Constructor-captured state already holds ABSOLUTE paths.
        assert cmp.script == str(tmp_path / "scripts" / "extract.py")
        assert cmp.cwd == str(tmp_path / "cases" / "case01")

    def test_resolution_independent_of_process_cwd(self, tmp_path, monkeypatch):
        (tmp_path / "scripts").mkdir()
        other_cwd = tmp_path / "unrelated"
        other_cwd.mkdir()
        monkeypatch.chdir(other_cwd)  # process CWD must not matter

        workspace = tmp_path / "ws"
        workspace.mkdir()
        cmp = ComparatorFactory.create_comparator(
            "script_extract",
            workspace=str(workspace),
            script="scripts/extract.py",
        )
        assert cmp.script == str(workspace / "scripts" / "extract.py")

    def test_resolved_script_actually_executes_from_other_cwd(
            self, tmp_path, monkeypatch):
        """End-to-end: a workspace-relative script/cwd executes correctly even
        when the process CWD is somewhere unrelated."""
        ws = tmp_path / "ws"
        (ws / "scripts").mkdir(parents=True)
        (ws / "cases" / "case01").mkdir(parents=True)
        script = ws / "scripts" / "extract.py"
        script.write_text(textwrap.dedent("""
            import json
            print(json.dumps({"channels": {
                "A": {"expected": [1.0], "actual": [1.0]}
            }}))
        """), encoding="utf-8")

        monkeypatch.chdir(tmp_path)  # CWD is NOT the workspace
        cmp = ComparatorFactory.create_comparator(
            "script_extract",
            workspace=str(ws),
            script="scripts/extract.py",
            cwd="cases/case01",
        )
        result = cmp.compare(CompareContext())
        assert result.error is None
        assert result.identical is True

    def test_script_comparator_ctor_state_is_workspace_resolved(self, tmp_path):
        cmp = ComparatorFactory.create_comparator(
            "script",
            workspace=str(tmp_path),
            script="scripts/analyze.py",
            cwd="cases/case01",
        )
        assert cmp.script == str(tmp_path / "scripts" / "analyze.py")
        assert cmp.cwd == str(tmp_path / "cases" / "case01")

    def test_hourglass_plugin_ctor_state_is_workspace_resolved(
            self, tmp_path, monkeypatch):
        """The example plugin receives workspace-resolved script/case_dir in
        constructor state — proving removal of plugin-side Path.resolve() is
        safe now that the framework resolves before construction."""
        plugin_file = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "examples" / "plugins" / "hourglass_tangent_comparator.py"
        )
        spec = importlib.util.spec_from_file_location(
            "hourglass_lifecycle_test", str(plugin_file)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = module.HourglassTangentComparator

        monkeypatch.setitem(
            ComparatorFactory._comparators, "hourglass_tangent", cls
        )
        cmp = ComparatorFactory.create_comparator(
            "hourglass_tangent",
            workspace=str(tmp_path),
            script="case/analyze_tangent.py",
            case_dir="case/case01",
        )
        assert cls.path_params == ("script", "case_dir")
        assert cmp.script == str(tmp_path / "case" / "analyze_tangent.py")
        assert cmp.case_dir == str(tmp_path / "case" / "case01")

    def test_absolute_paths_not_touched(self, tmp_path):
        absolute = str(tmp_path / "scripts" / "extract.py")
        cmp = ComparatorFactory.create_comparator(
            "script_extract", workspace=str(tmp_path / "other"),
            script=absolute,
        )
        assert cmp.script == absolute


# ---------------------------------------------------------------------------
# 5–8: discovery / registration rules
# ---------------------------------------------------------------------------

class TestDiscoveryRules:
    def test_abstract_classes_not_registered(self):
        ComparatorFactory._load_comparators()
        available = ComparatorFactory.get_available_comparators()
        # Abstract lane bases must never appear as instantiable types.
        assert "extractor" not in available
        assert "file" not in available
        assert "comparatorbase" not in available

    def test_explicit_comparator_type_wins(self, tmp_path):
        plugin = tmp_path / "win_comparator.py"
        plugin.write_text(textwrap.dedent("""
            from symtest.file_comparator.base_comparator import ComparatorBase
            from symtest.file_comparator.result import ComparisonResult

            class WinComparator(ComparatorBase):
                comparator_type = "my_explicit_name"
                def compare(self, ctx):
                    return ComparisonResult()
        """), encoding="utf-8")
        ComparatorFactory.set_plugin_dirs([tmp_path])
        assert "my_explicit_name" in ComparatorFactory.get_available_comparators()
        # Convention-derived name must NOT exist alongside the explicit one
        assert "win" not in ComparatorFactory.get_available_comparators()

    def test_suffix_only_convention_fallback(self):
        # Only the trailing "Comparator" suffix is stripped.
        assert _type_name_from_class("TextComparator") == "text"
        assert _type_name_from_class("H5Comparator") == "h5"
        assert _type_name_from_class("HourglassTangentComparator") == "hourglasstangent"
        # 'comparator' occurring earlier in the name is preserved
        assert _type_name_from_class("XComparatorComparator") == "xcomparator"

    def test_invalid_explicit_comparator_type_falls_back(self, tmp_path):
        plugin = tmp_path / "bad_type_comparator.py"
        plugin.write_text(textwrap.dedent("""
            from symtest.file_comparator.base_comparator import ComparatorBase
            from symtest.file_comparator.result import ComparisonResult

            class BadTypeComparator(ComparatorBase):
                comparator_type = 123  # invalid: not a string
                def compare(self, ctx):
                    return ComparisonResult()
        """), encoding="utf-8")
        ComparatorFactory.set_plugin_dirs([tmp_path])
        # Falls back to the class-name convention instead of registering garbage
        assert "badtype" in ComparatorFactory.get_available_comparators()
        assert "123" not in ComparatorFactory.get_available_comparators()

    def test_builtin_and_workspace_share_registration_rules(self, tmp_path):
        """The same class registered through both discovery paths yields the
        same type name and both honour abstract filtering."""
        # Built-in path: abstract ExtractorComparator is skipped
        ComparatorFactory._load_comparators()
        assert "extractor" not in ComparatorFactory.get_available_comparators()

        # Workspace path: an abstract class in a plugin dir is skipped too
        plugin = tmp_path / "abstract_plugin_comparator.py"
        plugin.write_text(textwrap.dedent("""
            from symtest.file_comparator.extractor_comparator import (
                ExtractorComparator,
            )

            class StillAbstract(ExtractorComparator):
                '''Does not implement extract() — stays abstract.'''
        """), encoding="utf-8")
        ComparatorFactory.set_plugin_dirs([tmp_path])
        assert "stillabstract" not in ComparatorFactory.get_available_comparators()

    def test_registration_helper_returns_type_name(self):
        class HelperCheckedComparator(ComparatorBase):
            def compare(self, ctx):
                return ComparisonResult()

        name = ComparatorFactory._register_comparator_class(
            HelperCheckedComparator, HelperCheckedComparator.__module__,
        )
        assert name == "helperchecked"


# ---------------------------------------------------------------------------
# 11: unknown comparator TYPE fails loudly (no silent fallback)
# ---------------------------------------------------------------------------

class TestUnknownTypeFailsLoudly:
    def test_unknown_type_raises_with_available_types(self):
        """A typo'd 'type' (e.g. 'cvs') must raise, naming the available types —
        never silently degrade to another comparator."""
        ComparatorFactory._load_comparators()
        with pytest.raises(ValueError, match="Unknown comparator type 'cvs'"):
            ComparatorFactory.get_comparator_class("cvs")

    def test_unknown_type_create_comparator_raises(self):
        with pytest.raises(ValueError, match="Available types"):
            ComparatorFactory.create_comparator("cvs")

    def test_auto_and_text_still_resolve_to_text(self):
        """'auto'/'text' keep their documented TextComparator mapping;
        'auto' is normally resolved from the extension upstream."""
        from symtest.file_comparator.text_comparator import TextComparator
        assert ComparatorFactory.get_comparator_class("auto") is TextComparator
        assert ComparatorFactory.get_comparator_class("text") is TextComparator

    def test_unknown_type_via_assertions_is_validation_error(self):
        """Through the assertion layer an unknown type surfaces as a
        ValidationError (failure_kind=file_compare), not a wrong pass."""
        with pytest.raises(ValidationError, match="Unknown comparator type"):
            Assertions.compare_files("a.bin", "b.bin", file_type="cvs")

    def test_registration_helper_skips_foreign_and_abstract(self):
        class ForeignComparator(ComparatorBase):
            def compare(self, ctx):
                return ComparisonResult()

        # Foreign module classes are skipped
        assert ComparatorFactory._register_comparator_class(
            ForeignComparator, "some.other.module",
        ) is None
        # Abstract classes are skipped
        assert ComparatorFactory._register_comparator_class(
            ExtractorComparator, ExtractorComparator.__module__,
        ) is None


# ---------------------------------------------------------------------------
# 9: strict configuration
# ---------------------------------------------------------------------------

class TestStrictConfiguration:
    def test_unknown_param_fails_loudly_at_factory(self, tmp_path):
        with pytest.raises(TypeError) as exc_info:
            ComparatorFactory.create_comparator(
                "script_extract",
                workspace=str(tmp_path),
                script="s.py",
                timeut=600,  # typo of 'timeout'
            )
        message = str(exc_info.value)
        assert "ScriptExtractComparator" in message
        assert "timeut" in message
        assert "timeout" in message  # supported params are listed

    def test_unknown_param_fails_loudly_via_assertion(self, tmp_path):
        (tmp_path / "a.txt").write_text("same\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("same\n", encoding="utf-8")
        with pytest.raises(ValidationError) as exc_info:
            Assertions.compare_files(
                "a.txt", "b.txt", workspace=str(tmp_path),
                file_type="text", rtol=1e-5,  # text comparator has no rtol
            )
        assert "TextComparator" in str(exc_info.value)

    def test_declared_params_still_work(self, tmp_path):
        cmp = ComparatorFactory.create_comparator(
            "script_extract",
            workspace=str(tmp_path),
            script="s.py",
            timeout=42,
            channels={"A": {"atol": 1.0}},
            default_channel={"rtol": 1e-3},
        )
        assert cmp.timeout == 42
        assert cmp.channel_specs == {"A": {"atol": 1.0}}
        assert cmp.default_spec == {"rtol": 1e-3}


# ---------------------------------------------------------------------------
# Autonomous comparators without two-file inputs (no fake "" paths)
# ---------------------------------------------------------------------------

class TestNoFileInputs:
    def test_autonomous_result_has_none_file_paths(self):
        """Autonomous comparators must not fake file1=""/file2="" — absent
        inputs stay None through construction, str() and serialization."""
        class NoFileComparator(ComparatorBase):
            def compare(self, ctx):
                return self._analyze()

            def _analyze(self):
                result = ComparisonResult()
                result.identical = True
                result.error_stats = {"energy_ratio": 0.98}
                return result

        result = NoFileComparator().compare(CompareContext())
        assert result.file1 is None
        assert result.file2 is None
        # No obsolete two-file worldview leakage into string rendering
        assert "None" not in str(result)
        # Serialization carries explicit nulls, not empty strings
        d = result.to_dict()
        assert d["file1"] is None
        assert d["file2"] is None

    def test_script_comparator_without_files(self, tmp_path):
        (tmp_path / "s.py").write_text("print('PASS')\n", encoding="utf-8")
        cmp = ComparatorFactory.create_comparator(
            "script", workspace=str(tmp_path), script="s.py",
        )
        result = cmp.compare(CompareContext())
        assert result.identical is True
        assert result.file1 is None
        assert result.file2 is None
        assert result.to_dict()["file1"] is None


# ---------------------------------------------------------------------------
# 10: "options" namespace merge
# ---------------------------------------------------------------------------

class TestOptionsNamespace:
    def test_options_merged_with_top_level_precedence(self, tmp_path, monkeypatch):
        captured = {}

        class OptionsProbe(ComparatorBase):
            def __init__(self, from_options="", from_top="", timeout=0):
                super().__init__()
                self.from_options = from_options
                self.from_top = from_top
                self.timeout = timeout

            def compare(self, ctx):
                captured.update(
                    from_options=self.from_options,
                    from_top=self.from_top,
                    timeout=self.timeout,
                )
                result = ComparisonResult()
                result.identical = True
                return result

        monkeypatch.setitem(
            ComparatorFactory._comparators, "optionsprobe", OptionsProbe
        )
        spec = {
            "type": "optionsprobe",
            "options": {
                "from_options": "opt",
                "from_top": "should_be_overridden",
                "timeout": 7,
            },
            "from_top": "top_wins",
        }
        result = _dispatch_file_compare(spec, str(tmp_path), Assertions())
        assert result["passed"] is True
        assert captured["from_options"] == "opt"
        assert captured["from_top"] == "top_wins"  # top-level precedence
        assert captured["timeout"] == 7

    def test_invalid_options_type_fails_loudly(self):
        spec = {
            "type": "text",
            "actual": "a.txt",
            "baseline": "b.txt",
            "options": "not-a-dict",
        }
        with pytest.raises(ValidationError) as exc_info:
            _dispatch_file_compare(spec, None, Assertions())
        assert "'options'" in str(exc_info.value)
