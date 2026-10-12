"""Tests for --with-deps dependency expansion and dropped-dependency warning."""

import json
import tempfile
import unittest
from pathlib import Path

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


def _make_dep_chain_json(temp_dir: Path) -> Path:
    """Create a config with chain A <- B <- C plus independent D."""
    config = {
        "test_cases": [
            {"name": "A", "execution": {"command": "echo", "args": ["a"]},
             "expected": {"return_code": 0}},
            {"name": "B", "execution": {"command": "echo", "args": ["b"]},
             "scheduling": {"depends_on": ["A"]},
             "expected": {"return_code": 0}},
            {"name": "C", "execution": {"command": "echo", "args": ["c"]},
             "scheduling": {"depends_on": ["B"]},
             "expected": {"return_code": 0}},
            {"name": "D", "execution": {"command": "echo", "args": ["d"]},
             "expected": {"return_code": 0}},
        ]
    }
    path = temp_dir / "dep_chain.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class TestWithDeps(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_dep_chain_json(Path(self.temp_dir.name))

    def _filter(self, runner):
        runner.load_test_cases()
        runner._apply_test_case_filter()
        return [tc.name for tc in runner.test_cases]

    def test_default_keeps_existing_behavior(self):
        """Without with_deps, filtering stays name-exact (A drops silently)."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["C"],
        )
        self.assertEqual(self._filter(runner), ["C"])

    def test_with_deps_expands_transitive_closure(self):
        """with_deps pulls in the full dependency chain A <- B."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["C"], with_deps=True,
        )
        self.assertEqual(self._filter(runner), ["A", "B", "C"])

    def test_with_deps_partial_selection(self):
        """Deps already selected are not duplicated."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["A", "C"], with_deps=True,
        )
        self.assertEqual(self._filter(runner), ["A", "B", "C"])

    def test_with_deps_noop_without_filter(self):
        """with_deps without a name filter changes nothing (full run)."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            with_deps=True,
        )
        self.assertEqual(self._filter(runner), ["A", "B", "C", "D"])

    def test_parallel_with_deps_expansion(self):
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["C"], with_deps=True, max_workers=2,
        )
        self.assertEqual(self._filter(runner), ["A", "B", "C"])

    def test_dropped_dependency_warns(self):
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["C"],
        )
        runner.load_test_cases()
        with self.assertLogs("symtest.core.base_runner", level="WARNING") as logs:
            runner._apply_test_case_filter()
        self.assertTrue(
            any("depends on" in msg and "IGNORED" in msg for msg in logs.output)
        )

    def test_no_warning_when_deps_selected(self):
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["A", "B", "C"],
        )
        runner.load_test_cases()
        with self.assertLogs("symtest.core.base_runner", level="INFO") as logs:
            runner._apply_test_case_filter()
        self.assertFalse(any("WARNING" in msg for msg in logs.output))

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
