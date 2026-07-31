"""Integration tests for the sequence (multi-step) test case feature."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli_test_framework.runners.json_runner import JSONRunner
from cli_test_framework.runners.yaml_runner import YAMLRunner
from cli_test_framework.core.test_case import TestCase, TestCaseStep


class TestSequenceLoadJSON(unittest.TestCase):
    """Test loading sequence test cases from JSON config."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def _write_config(self, config):
        path = Path(self.temp_dir.name) / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_load_sequence_case(self):
        config = {
            "test_cases": [
                {
                    "name": "seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        runner.load_test_cases()
        self.assertEqual(len(runner.test_cases), 1)
        case = runner.test_cases[0]
        self.assertEqual(case.command, "")  # no single command for sequence mode
        self.assertIsNotNone(case.steps)
        self.assertEqual(len(case.steps), 2)
        self.assertEqual(case.steps[0].command, "echo")
        self.assertEqual(case.steps[1].args, ["b"])

    def test_load_mixed_cases(self):
        """Both sequence and single-command cases coexist."""
        config = {
            "test_cases": [
                {
                    "name": "single",
                    "command": "echo",
                    "args": ["hello"],
                    "expected": {"return_code": 0},
                },
                {
                    "name": "seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                    ],
                },
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        runner.load_test_cases()
        self.assertEqual(len(runner.test_cases), 2)
        self.assertIsNotNone(runner.test_cases[0].command)
        self.assertIsNotNone(runner.test_cases[1].steps)

    def test_load_sequence_with_step_timeout(self):
        config = {
            "test_cases": [
                {
                    "name": "timeout_seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}, "timeout": 5},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        runner.load_test_cases()
        self.assertEqual(runner.test_cases[0].steps[0].timeout, 5)
        self.assertIsNone(runner.test_cases[0].steps[1].timeout)

    def test_load_sequence_missing_step_field(self):
        config = {
            "test_cases": [
                {
                    "name": "bad_seq",
                    "steps": [
                        {"command": "echo", "args": ["a"]},  # missing expected
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        with self.assertRaises(SystemExit):
            runner.load_test_cases()

    def tearDown(self):
        self.temp_dir.cleanup()


class TestSequenceLoadYAML(unittest.TestCase):
    """Test loading sequence test cases from YAML config."""

    def setUp(self):
        try:
            import yaml
            self.yaml = yaml
        except ImportError:
            self.skipTest("pyyaml not installed")
        self.temp_dir = tempfile.TemporaryDirectory()

    def _write_config(self, config):
        path = Path(self.temp_dir.name) / "config.yaml"
        path.write_text(
            self.yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
        )
        return path

    def test_load_sequence_case(self):
        config = {
            "test_cases": [
                {
                    "name": "seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = YAMLRunner(str(path), workspace=self.temp_dir.name)
        runner.load_test_cases()
        self.assertEqual(len(runner.test_cases), 1)
        self.assertIsNotNone(runner.test_cases[0].steps)
        self.assertEqual(len(runner.test_cases[0].steps), 2)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestSequenceExecution(unittest.TestCase):
    """Test sequence execution logic with mocked subprocess."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def _write_config(self, config):
        path = Path(self.temp_dir.name) / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    @patch("subprocess.Popen")
    def test_sequence_all_pass(self, mock_popen):
        mock_popen.return_value = MagicMock(
            communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
        )
        config = {
            "test_cases": [
                {
                    "name": "seq",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 1)
        self.assertEqual(mock_popen.call_count, 2)

    @patch("subprocess.Popen")
    def test_sequence_fail_stops_early(self, mock_popen):
        """Step 2 fails → step 3 should NOT execute."""
        mock_popen.side_effect = [
            MagicMock(communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1),   # step 1 pass
            MagicMock(communicate=MagicMock(return_value=("", "err")), returncode=1, pid=2),    # step 2 fail
            MagicMock(communicate=MagicMock(return_value=("no\n", "")), returncode=0, pid=3),   # step 3 should not run
        ]
        config = {
            "test_cases": [
                {
                    "name": "seq_fail",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["c"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        success = runner.run_tests()
        self.assertFalse(success)
        # Only 2 subprocess calls: step 1 + step 2 (step 3 skipped)
        self.assertEqual(mock_popen.call_count, 2)
        detail = runner.results["details"][0]
        self.assertEqual(detail["status"], "failed")
        self.assertIn("step 2", detail["message"])

    @patch("subprocess.Popen")
    def test_sequence_aggregates_output_and_duration(self, mock_popen):
        mock_popen.side_effect = [
            MagicMock(communicate=MagicMock(return_value=("out1\n", "")), returncode=0, pid=1),
            MagicMock(communicate=MagicMock(return_value=("out2\n", "")), returncode=0, pid=2),
        ]
        config = {
            "test_cases": [
                {
                    "name": "seq_agg",
                    "steps": [
                        {"command": "echo", "args": ["a"], "expected": {"return_code": 0}},
                        {"command": "echo", "args": ["b"], "expected": {"return_code": 0}},
                    ],
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        runner.run_tests()
        detail = runner.results["details"][0]
        self.assertIn("out1", detail["output"])
        self.assertIn("out2", detail["output"])
        self.assertIn("->", detail["command"])  # command chain separator
        self.assertGreaterEqual(detail["duration"], 0)

    @patch("subprocess.Popen")
    def test_single_command_backward_compat(self, mock_popen):
        """Single-command case still works as before."""
        mock_popen.return_value = MagicMock(
            communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
        )
        config = {
            "test_cases": [
                {
                    "name": "single",
                    "command": "echo",
                    "args": ["hello"],
                    "expected": {"return_code": 0},
                }
            ]
        }
        path = self._write_config(config)
        runner = JSONRunner(str(path), workspace=self.temp_dir.name)
        success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(mock_popen.call_count, 1)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestTestCaseStepDataclass(unittest.TestCase):
    """Test TestCaseStep and TestCase with steps field."""

    def test_test_case_step_creation(self):
        step = TestCaseStep(command="echo", args=["hello"], expected={"return_code": 0})
        self.assertEqual(step.command, "echo")
        self.assertEqual(step.timeout, None)

    def test_test_case_with_steps(self):
        steps = [
            TestCaseStep(command="echo", args=["a"], expected={"return_code": 0}),
            TestCaseStep(command="echo", args=["b"], expected={"return_code": 0}, timeout=5),
        ]
        case = TestCase(name="seq", steps=steps)
        self.assertEqual(case.command, "")  # default for sequence mode
        self.assertEqual(len(case.steps), 2)
        self.assertEqual(case.steps[1].timeout, 5)

    def test_test_case_to_dict_with_steps(self):
        steps = [
            TestCaseStep(command="echo", args=["a"], expected={"return_code": 0}),
            TestCaseStep(command="echo", args=["b"], expected={"return_code": 0}, retry_count=2),
        ]
        case = TestCase(name="seq", steps=steps, retry_count=3)
        d = case.to_dict()
        self.assertIn("steps", d)
        self.assertEqual(d["steps"][0]["command"], "echo")
        self.assertEqual(d["steps"][0]["retry_count"], 0)
        self.assertEqual(d["steps"][1]["retry_count"], 2)
        self.assertEqual(d["retry_count"], 3)

    def test_test_case_to_dict_without_steps(self):
        case = TestCase(name="s", command="echo", args=["x"], expected={"return_code": 0}, retry_count=5)
        d = case.to_dict()
        self.assertNotIn("steps", d)
        self.assertEqual(d["retry_count"], 5)


if __name__ == "__main__":
    unittest.main()
