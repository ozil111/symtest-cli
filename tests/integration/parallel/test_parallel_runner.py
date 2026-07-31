import json
import os
import sys
import tempfile
import time
import unittest

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


class TestParallelRunner(unittest.TestCase):
    """并行运行器测试类"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "test_config.json")

        test_config = {
            "test_cases": [
                {
                    "name": "测试1",
                    "command": "echo",
                    "args": ["test1"],
                    "expected": {"return_code": 0, "output_contains": ["test1"]},
                },
                {
                    "name": "测试2",
                    "command": "echo",
                    "args": ["test2"],
                    "expected": {"return_code": 0, "output_contains": ["test2"]},
                },
                {
                    "name": "测试3",
                    "command": "echo",
                    "args": ["test3"],
                    "expected": {"return_code": 0, "output_contains": ["test3"]},
                },
                {
                    "name": "测试4",
                    "command": "echo",
                    "args": ["test4"],
                    "expected": {"return_code": 0, "output_contains": ["test4"]},
                },
            ]
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_parallel_vs_sequential_performance(self):
        sequential_runner = JSONRunner(self.config_file, self.temp_dir)
        start_time = time.time()
        seq_success = sequential_runner.run_tests()
        seq_time = time.time() - start_time

        parallel_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        start_time = time.time()
        par_success = parallel_runner.run_tests()
        par_time = time.time() - start_time

        self.assertTrue(seq_success)
        self.assertTrue(par_success)
        self.assertEqual(sequential_runner.results["total"], parallel_runner.results["total"])
        self.assertEqual(sequential_runner.results["passed"], parallel_runner.results["passed"])
        self.assertGreater(seq_time, 0)
        self.assertGreater(par_time, 0)

    def test_thread_vs_process_mode(self):
        thread_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        thread_success = thread_runner.run_tests()

        process_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="process"
        )
        process_success = process_runner.run_tests()

        self.assertTrue(thread_success)
        self.assertTrue(process_success)
        self.assertEqual(thread_runner.results["passed"], process_runner.results["passed"])

    def test_max_workers_configuration(self):
        for max_workers in [1, 2, 4]:
            with self.subTest(max_workers=max_workers):
                runner = ParallelJSONRunner(
                    self.config_file, self.temp_dir, max_workers=max_workers, execution_mode="thread"
                )
                success = runner.run_tests()
                self.assertTrue(success)
                self.assertEqual(runner.results["passed"], 4)

    def test_fallback_to_sequential(self):
        runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        success = runner.run_tests_sequential()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 4)

    def test_parallel_reports_real_failures(self):
        config_file = os.path.join(self.temp_dir, "failure_config.json")
        test_config = {
            "test_cases": [
                {
                    "name": "pass",
                    "command": f'"{sys.executable}" -c "print(\'ok\')"',
                    "args": [],
                    "expected": {"return_code": 0, "output_contains": ["ok"]},
                },
                {
                    "name": "fail",
                    "command": f'"{sys.executable}" -c "import sys; sys.exit(5)"',
                    "args": [],
                    "expected": {"return_code": 0},
                },
            ]
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)

        runner = ParallelJSONRunner(
            config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )

        success = runner.run_tests()

        self.assertFalse(success)
        self.assertEqual(runner.results["passed"], 1)
        self.assertEqual(runner.results["failed"], 1)
        failed = [d for d in runner.results["details"] if d["status"] != "passed"]
        self.assertEqual(failed[0]["return_code"], 5)


if __name__ == "__main__":
    unittest.main()

