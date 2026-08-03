"""Tests for the test_case_tag_filter feature across all runner types."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from symtest.runners.json_runner import JSONRunner
from symtest.runners.yaml_runner import YAMLRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


def _make_tagged_cases_json(temp_dir: Path) -> Path:
    """Create a JSON config with 4 test cases that have different tags."""
    config = {
        "test_cases": [
            {
                "name": "alpha",
                "command": "echo", "args": ["a"],
                "tags": ["smoke", "fast"],
                "expected": {"return_code": 0},
            },
            {
                "name": "beta",
                "command": "echo", "args": ["b"],
                "tags": ["smoke"],
                "expected": {"return_code": 0},
            },
            {
                "name": "gamma",
                "command": "echo", "args": ["c"],
                "tags": ["regression", "slow"],
                "expected": {"return_code": 0},
            },
            {
                "name": "delta",
                "command": "echo", "args": ["d"],
                "tags": ["fast", "regression"],
                "expected": {"return_code": 0},
            },
        ]
    }
    path = temp_dir / "tagged_cases.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _make_tagged_cases_yaml(temp_dir: Path) -> Path:
    """Create a YAML config with 4 test cases that have different tags."""
    try:
        import yaml
    except ImportError:
        return None

    config = {
        "test_cases": [
            {
                "name": "alpha",
                "command": "echo", "args": ["a"],
                "tags": ["smoke", "fast"],
                "expected": {"return_code": 0},
            },
            {
                "name": "beta",
                "command": "echo", "args": ["b"],
                "tags": ["smoke"],
                "expected": {"return_code": 0},
            },
            {
                "name": "gamma",
                "command": "echo", "args": ["c"],
                "tags": ["regression", "slow"],
                "expected": {"return_code": 0},
            },
            {
                "name": "delta",
                "command": "echo", "args": ["d"],
                "tags": ["fast", "regression"],
                "expected": {"return_code": 0},
            },
        ]
    }
    path = temp_dir / "tagged_cases.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


class TestJSONRunnerTagFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_tagged_cases_json(Path(self.temp_dir.name))

    def _run_with_mock(self, runner):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")),
                returncode=0, pid=1,
            )
            return runner.run_tests()

    def test_filter_single_tag(self):
        """Only test cases with 'smoke' tag should be kept."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["smoke"],
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(set(names), {"alpha", "beta"})

    def test_filter_multiple_tags(self):
        """Cases matching any of the tags (OR logic) should be kept."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["smoke", "regression"],
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(set(names), {"alpha", "beta", "gamma", "delta"})

    def test_filter_nonexistent_tag(self):
        """Non-matching tag should result in empty test cases."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["nonexistent"],
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def test_filter_partial_match_tag(self):
        """Only cases with 'slow' tag."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["slow"],
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(set(names), {"gamma"})

    def test_tag_and_name_filter_combined(self):
        """Tag filter and name filter combined (AND logic)."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha", "gamma"],
            test_case_tag_filter=["fast"],
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        # alpha has 'fast' tag, gamma does not → only alpha
        self.assertEqual(names, ["alpha"])

    def test_tag_and_name_filter_no_intersection(self):
        """When tag matches but name doesn't, result is empty."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["delta"],
            test_case_tag_filter=["slow"],
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def test_no_tag_filter_runs_all(self):
        """Without tag filter, all cases should be loaded."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
        )
        self._run_with_mock(runner)
        self.assertEqual(len(runner.test_cases), 4)

    def test_tag_filter_none_runs_all(self):
        """test_case_tag_filter=None should behave the same as no filter."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=None,
        )
        self._run_with_mock(runner)
        self.assertEqual(len(runner.test_cases), 4)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestJSONRunnerTagFilter_NoTags(unittest.TestCase):
    """Test tag filtering on cases without any tags defined."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config = {
            "test_cases": [
                {"name": "no_tag_case", "command": "echo", "args": ["x"],
                 "expected": {"return_code": 0}},
            ]
        }
        path = Path(self.temp_dir.name) / "no_tags.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.config_path = path

    def test_tag_filter_ignores_cases_without_tags(self):
        """Cases without tags should not match any tag filter."""
        runner = JSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["smoke"],
        )
        success = runner.run_tests()
        self.assertFalse(success)
        self.assertEqual(len(runner.test_cases), 0)

    def tearDown(self):
        self.temp_dir.cleanup()


class TestParallelJSONRunnerTagFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = _make_tagged_cases_json(Path(self.temp_dir.name))

    def _run_with_mock(self, runner):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")),
                returncode=0, pid=1,
            )
            return runner.run_tests()

    def test_tag_filter_parallel(self):
        """Tag filter works in parallel runner."""
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_tag_filter=["smoke"], max_workers=2,
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(set(names), {"alpha", "beta"})

    def test_tag_and_name_filter_parallel(self):
        """Combined tag + name filter in parallel runner."""
        runner = ParallelJSONRunner(
            str(self.config_path), workspace=self.temp_dir.name,
            test_case_filter=["alpha", "gamma"],
            test_case_tag_filter=["slow"], max_workers=2,
        )
        self._run_with_mock(runner)
        names = [tc.name for tc in runner.test_cases]
        self.assertEqual(names, ["gamma"])

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
