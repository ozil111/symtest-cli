import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from symtest.runners.json_runner import JSONRunner
from symtest.runners.yaml_runner import YAMLRunner


class TestJSONRunner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config = {
            "test_cases": [
                {
                    "name": "simple",
                    "execution": {"command": "echo", "args": ["ok"]},
                    "expected": {"return_code": 0},
                }
            ]
        }
        self.config_path = Path(self.temp_dir.name) / "json_config.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.runner = JSONRunner(str(self.config_path), workspace=self.temp_dir.name)

    def test_load_test_cases(self):
        self.runner.load_test_cases()
        self.assertGreater(len(self.runner.test_cases), 0, "No test cases loaded")

    def test_run_tests(self):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = self.runner.run_tests()
        self.assertTrue(success, "Some tests failed")

    def tearDown(self):
        self.temp_dir.cleanup()


class TestYAMLRunner(unittest.TestCase):
    def setUp(self):
        import importlib

        try:
            self.yaml = importlib.import_module("yaml")
        except ImportError:
            self.skipTest("pyyaml not installed")

        self.temp_dir = tempfile.TemporaryDirectory()
        config = {
            "test_cases": [
                {
                    "name": "simple",
                    "execution": {"command": "echo", "args": ["ok"]},
                    "expected": {"return_code": 0},
                }
            ]
        }
        self.config_path = Path(self.temp_dir.name) / "yaml_config.yaml"
        self.config_path.write_text(
            self.yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
        )
        self.runner = YAMLRunner(str(self.config_path), workspace=self.temp_dir.name)

    def test_load_test_cases(self):
        self.runner.load_test_cases()
        self.assertGreater(len(self.runner.test_cases), 0, "No test cases loaded")

    def test_run_tests(self):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("ok\n", "")), returncode=0, pid=1
            )
            success = self.runner.run_tests()
        self.assertTrue(success, "Some tests failed")

    def tearDown(self):
        self.temp_dir.cleanup()


class TestPlaceholderSubstitution(unittest.TestCase):
    """Integration test: verify that variables flow through runner's load_test_cases."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config = {
            "test_cases": [
                {
                    "name": "placeholder-test",
                    "execution": {
                        "command": "{solver}",
                        "args": ["--input", "{flag}"],
                    },
                    "expected": {"return_code": 0},
                }
            ]
        }
        self.config_path = Path(self.temp_dir.name) / "placeholder_config.json"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def test_placeholders_substituted_in_loaded_cases(self):
        # Use an absolute path valid on the current platform: on Windows,
        # Python 3.13+ no longer treats '/usr/bin/solver' (rooted, no drive)
        # as absolute, which would make split_command resolve it against workspace.
        solver = "/usr/bin/solver" if os.name != "nt" else "C:\\tools\\solver.exe"
        runner = JSONRunner(
            str(self.config_path),
            workspace=self.temp_dir.name,
            variables={"solver": solver, "flag": "--verbose"},
        )
        runner.load_test_cases()

        self.assertEqual(len(runner.test_cases), 1)
        case = runner.test_cases[0]
        self.assertIn(solver, case.command)
        self.assertIn("--verbose", case.args)
        self.assertNotIn("{solver}", case.command)
        self.assertNotIn("{flag}", case.args)

    def test_no_variables_still_works(self):
        """Without variables, placeholders should remain as-is."""
        runner = JSONRunner(
            str(self.config_path),
            workspace=self.temp_dir.name,
        )
        runner.load_test_cases()

        self.assertEqual(len(runner.test_cases), 1)
        case = runner.test_cases[0]
        self.assertIn("{solver}", case.command)
        self.assertIn("{flag}", case.args)

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()

