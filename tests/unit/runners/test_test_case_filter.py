"""Tests for the test_case_filter feature across all runner types."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from symtest.runners.json_runner import JSONRunner
from symtest.runners.yaml_runner import YAMLRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


def _make_multi_case_json(temp_dir: Path) -> Path:
    """Create a JSON config with 3 test cases: alpha, beta, gamma."""
    config = {
        "test_cases": [
            {"name": "alpha", "execution": {"command": "echo", "args": ["a"]}, "expected": {"return_code": 0}},
            {"name": "beta", "execution": {"command": "echo", "args": ["b"]}, "expected": {"return_code": 0}},
            {"name": "gamma", "execution": {"command": "echo", "args": ["c"]}, "expected": {"return_code": 0}},
        ]
    }
    path = temp_dir / "cases.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _make_multi_case_yaml(temp_dir: Path) -> Path:
    """Create a YAML config with 3 test cases: alpha, beta, gamma."""
    try:
        import yaml
    except ImportError:
        return None

    config = {
        "test_cases": [
            {"name": "alpha", "execution": {"command": "echo", "args": ["a"]}, "expected": {"return_code": 0}},
            {"name": "beta", "execution": {"command": "echo", "args": ["b"]}, "expected": {"return_code": 0}},
            {"name": "gamma", "execution": {"command": "echo", "args": ["c"]}, "expected": {"return_code": 0}},
        ]
    }
    path = temp_dir / "cases.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


class TestJSONRunnerFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_multi_case_json(Path(self.temp_dir.name))

    def test_filter_single_case(self):
        """Only the specified test case should be loaded after filter."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha"]
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("a\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(len(runner.test_cases), 1)
        self.assertEqual(runner.test_cases[0].name, "alpha")

    def test_filter_multiple_cases(self):
        """Multiple test case names should be preserved after filter."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha", "gamma"]
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(names, ["alpha", "gamma"])

    def test_filter_nonexistent_case(self):
        """Non-matching filter should result in empty test cases and return False."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["nonexistent"]
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def test_no_filter_runs_all(self):
        """Without test_case_filter, all test cases should be loaded."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(len(runner.test_cases), 3)

    def test_filter_none_runs_all(self):
        """test_case_filter=None should behave the same as no filter."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=None
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(len(runner.test_cases), 3)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestYAMLRunnerFilter(unittest.TestCase):
    def setUp(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_multi_case_yaml(Path(self.temp_dir.name))

    def test_filter_single_case(self):
        runner = YAMLRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["beta"]
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("b\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(len(runner.test_cases), 1)
        self.assertEqual(runner.test_cases[0].name, "beta")

    def test_filter_nonexistent_case(self):
        runner = YAMLRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["nonexistent"]
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestParallelJSONRunnerFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_multi_case_json(Path(self.temp_dir.name))

    def test_filter_single_case(self):
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha"], max_workers=2
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("a\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        self.assertEqual(len(runner.test_cases), 1)
        self.assertEqual(runner.test_cases[0].name, "alpha")

    def test_filter_multiple_cases(self):
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha", "gamma"], max_workers=2
        )
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = runner.run_tests()
        self.assertTrue(success)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(names, ["alpha", "gamma"])

    def test_filter_nonexistent_case(self):
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["nonexistent"], max_workers=2
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
