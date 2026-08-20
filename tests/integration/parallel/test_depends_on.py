"""Integration tests for the depends_on DAG scheduling feature."""
import json
import os
import sys
import tempfile
import time
import unittest

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


class TestDependsOn(unittest.TestCase):
    """depends_on DAG 调度测试"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _write_config(self, test_cases):
        config_file = os.path.join(self.temp_dir, "test_config.json")
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({"test_cases": test_cases}, f, ensure_ascii=False, indent=2)
        return config_file

    def test_no_deps_runs_all_in_parallel(self):
        """无依赖时行为与原来一致"""
        config_file = self._write_config([
            {
                "name": "A", "command": "echo", "args": ["A"],
                "expected": {"return_code": 0, "output_contains": ["A"]},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="thread")
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 2)
        self.assertEqual(runner.results["failed"], 0)

    def test_simple_chain_sequential_runner(self):
        """顺序 runner: A → B (B depends_on A)"""
        config_file = self._write_config([
            {
                "name": "A", "command": "echo", "args": ["hello"],
                "expected": {"return_code": 0, "output_contains": ["hello"]},
            },
            {
                "name": "B", "command": "echo", "args": ["world"],
                "expected": {"return_code": 0, "output_contains": ["world"]},
                "depends_on": ["A"],
            },
        ])
        runner = JSONRunner(config_file, self.temp_dir)
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 2)

    def test_simple_chain_parallel_runner(self):
        """并行 runner: A → B (B depends_on A)"""
        config_file = self._write_config([
            {
                "name": "A", "command": "echo", "args": ["hello"],
                "expected": {"return_code": 0, "output_contains": ["hello"]},
            },
            {
                "name": "B", "command": "echo", "args": ["world"],
                "expected": {"return_code": 0, "output_contains": ["world"]},
                "depends_on": ["A"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="thread")
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 2)

    def test_parallel_deps(self):
        """A, B 并行 → C depends_on [A, B]"""
        config_file = self._write_config([
            {
                "name": "A", "command": "echo", "args": ["A"],
                "expected": {"return_code": 0, "output_contains": ["A"]},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
            },
            {
                "name": "C", "command": "echo", "args": ["C"],
                "expected": {"return_code": 0, "output_contains": ["C"]},
                "depends_on": ["A", "B"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=4, execution_mode="thread")
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 3)

    def test_dep_failure_skips_downstream(self):
        """A 失败 → B (depends_on A) 被 skip"""
        config_file = self._write_config([
            {
                "name": "A",
                "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
                "args": [],
                "expected": {"return_code": 0},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
                "depends_on": ["A"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="thread")
        success = runner.run_tests()
        self.assertFalse(success)  # A failed
        self.assertEqual(runner.results["failed"], 1)

        details = {d["name"]: d for d in runner.results["details"]}
        self.assertEqual(details["A"]["status"], "failed")
        self.assertEqual(details["B"]["status"], "skipped")
        self.assertIn("A", details["B"]["message"])

    def test_cascade_skip(self):
        """A 失败 → B skip → C (depends_on B) 也 skip"""
        config_file = self._write_config([
            {
                "name": "A",
                "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
                "args": [],
                "expected": {"return_code": 0},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
                "depends_on": ["A"],
            },
            {
                "name": "C", "command": "echo", "args": ["C"],
                "expected": {"return_code": 0, "output_contains": ["C"]},
                "depends_on": ["B"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="thread")
        success = runner.run_tests()
        self.assertFalse(success)

        details = {d["name"]: d for d in runner.results["details"]}
        self.assertEqual(details["A"]["status"], "failed")
        self.assertEqual(details["B"]["status"], "skipped")
        self.assertEqual(details["C"]["status"], "skipped")

    def test_xfailed_dep_satisfies_downstream(self):
        """xfailed 的依赖视为满足，下游正常执行"""
        config_file = self._write_config([
            {
                "name": "A",
                "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
                "args": [],
                "expected": {"return_code": 0},
                "expected_failure": True,
                "xfail_reason": "known issue",
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
                "depends_on": ["A"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="thread")
        success = runner.run_tests()
        self.assertTrue(success)  # A xfailed, B passed
        self.assertEqual(runner.results["xfailed"], 1)
        self.assertEqual(runner.results["passed"], 1)

        details = {d["name"]: d for d in runner.results["details"]}
        self.assertEqual(details["A"]["status"], "xfailed")
        self.assertEqual(details["B"]["status"], "passed")

    def test_process_mode_with_deps(self):
        """进程模式下 DAG 调度也能正常工作"""
        config_file = self._write_config([
            {
                "name": "A", "command": "echo", "args": ["A"],
                "expected": {"return_code": 0, "output_contains": ["A"]},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
                "depends_on": ["A"],
            },
        ])
        runner = ParallelJSONRunner(config_file, self.temp_dir, max_workers=2, execution_mode="process")
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 2)

    def test_dep_failure_sequential_runner(self):
        """顺序 runner: A 失败 → B skip"""
        config_file = self._write_config([
            {
                "name": "A",
                "command": f'"{sys.executable}" -c "import sys; sys.exit(1)"',
                "args": [],
                "expected": {"return_code": 0},
            },
            {
                "name": "B", "command": "echo", "args": ["B"],
                "expected": {"return_code": 0, "output_contains": ["B"]},
                "depends_on": ["A"],
            },
        ])
        runner = JSONRunner(config_file, self.temp_dir)
        success = runner.run_tests()
        self.assertFalse(success)

        details = {d["name"]: d for d in runner.results["details"]}
        self.assertEqual(details["A"]["status"], "failed")
        self.assertEqual(details["B"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
