import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from symtest.core.setup import BaseSetup, EnvironmentSetup, SetupManager
from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner
from symtest.runners.yaml_runner import YAMLRunner


class TestBaseSetup(unittest.TestCase):
    """测试BaseSetup基类"""

    def test_abstract_methods(self):
        """测试抽象方法"""
        with self.assertRaises(TypeError):
            BaseSetup()

    def test_get_name(self):
        """测试获取setup名称"""

        class TestSetup(BaseSetup):
            def setup(self):
                pass

            def teardown(self):
                pass

        test_setup = TestSetup()
        self.assertEqual(test_setup.get_name(), "TestSetup")


class TestEnvironmentSetup(unittest.TestCase):
    """测试EnvironmentSetup插件"""

    def setUp(self):
        self.original_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_setup_new_environment_variables(self):
        config = {
            "environment_variables": {
                "TEST_VAR1": "value1",
                "TEST_VAR2": "value2",
            }
        }

        env_setup = EnvironmentSetup(config)
        env_setup.setup()

        self.assertEqual(os.environ.get("TEST_VAR1"), "value1")
        self.assertEqual(os.environ.get("TEST_VAR2"), "value2")

    def test_setup_overwrite_existing_variables(self):
        os.environ["EXISTING_VAR"] = "original_value"
        config = {"environment_variables": {"EXISTING_VAR": "new_value"}}

        env_setup = EnvironmentSetup(config)
        env_setup.setup()

        self.assertEqual(os.environ.get("EXISTING_VAR"), "new_value")

    def test_teardown_restore_original_variables(self):
        os.environ["EXISTING_VAR"] = "original_value"
        config = {
            "environment_variables": {
                "EXISTING_VAR": "new_value",
                "NEW_VAR": "new_var_value",
            }
        }

        env_setup = EnvironmentSetup(config)
        env_setup.setup()
        self.assertEqual(os.environ.get("EXISTING_VAR"), "new_value")
        self.assertEqual(os.environ.get("NEW_VAR"), "new_var_value")

        env_setup.teardown()
        self.assertEqual(os.environ.get("EXISTING_VAR"), "original_value")
        self.assertIsNone(os.environ.get("NEW_VAR"))

    def test_empty_config(self):
        env_setup = EnvironmentSetup({})
        env_setup.setup()
        env_setup.teardown()

    def test_none_config(self):
        env_setup = EnvironmentSetup()
        env_setup.setup()
        env_setup.teardown()


class TestSetupManager(unittest.TestCase):
    """测试SetupManager"""

    def setUp(self):
        self.manager = SetupManager()
        self.original_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_add_setup(self):
        env_setup = EnvironmentSetup({"environment_variables": {"TEST": "value"}})
        self.manager.add_setup(env_setup)

        self.assertEqual(len(self.manager.setups), 1)
        self.assertEqual(self.manager.setups[0], env_setup)

    def test_setup_all(self):
        config = {"environment_variables": {"TEST_VAR": "test_value"}}
        env_setup = EnvironmentSetup(config)
        self.manager.add_setup(env_setup)

        self.manager.setup_all()
        self.assertEqual(os.environ.get("TEST_VAR"), "test_value")

    def test_teardown_all(self):
        config = {"environment_variables": {"TEST_VAR": "test_value"}}
        env_setup = EnvironmentSetup(config)
        self.manager.add_setup(env_setup)

        self.manager.setup_all()
        self.assertEqual(os.environ.get("TEST_VAR"), "test_value")

        self.manager.teardown_all()
        self.assertIsNone(os.environ.get("TEST_VAR"))

    def test_multiple_setups_execution_order(self):
        execution_order = []

        class TestSetup1(BaseSetup):
            def setup(self):
                execution_order.append("setup1")

            def teardown(self):
                execution_order.append("teardown1")

        class TestSetup2(BaseSetup):
            def setup(self):
                execution_order.append("setup2")

            def teardown(self):
                execution_order.append("teardown2")

        self.manager.add_setup(TestSetup1())
        self.manager.add_setup(TestSetup2())

        self.manager.setup_all()
        self.assertEqual(execution_order, ["setup1", "setup2"])

        execution_order.clear()
        self.manager.teardown_all()
        self.assertEqual(execution_order, ["teardown2", "teardown1"])

    def test_empty_manager(self):
        self.manager.setup_all()
        self.manager.teardown_all()


class TestRunnerIntegration(unittest.TestCase):
    """测试runner与setup模块的集成"""

    def setUp(self):
        self.original_env = dict(os.environ)
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def create_test_config_file(self, config_data, filename="test_config.json"):
        config_path = os.path.join(self.temp_dir, filename)
        with open(config_path, "w") as f:
            json.dump(config_data, f)
        return config_path

    def test_json_runner_with_setup(self):
        config = {
            "setup": {
                "environment_variables": {
                    "TEST_ENV": "test_value",
                }
            },
            "test_cases": [
                {
                    "name": "Test env var",
                    "execution": {
                        "command": "python",
                        "args": ["-c", "import os; print(os.environ.get('TEST_ENV', 'NOT_SET'))"],
                    },
                    "expected": {"return_code": 0, "output_contains": ["test_value"]},
                }
            ],
        }

        config_path = self.create_test_config_file(config)
        runner = JSONRunner(config_path, workspace=self.temp_dir)

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(
                communicate=MagicMock(return_value=("test_value\n", "")), returncode=0, pid=1
            )
            self.assertIsNone(os.environ.get("TEST_ENV"))
            result = runner.run_tests()
            self.assertTrue(result)
            self.assertIsNone(os.environ.get("TEST_ENV"))

    def test_setup_configuration_loading(self):
        config = {
            "setup": {
                "environment_variables": {
                    "VAR1": "value1",
                    "VAR2": "value2",
                }
            },
            "test_cases": [],
        }

        config_path = self.create_test_config_file(config)
        runner = JSONRunner(config_path, workspace=self.temp_dir)
        runner.load_test_cases()

        self.assertEqual(len(runner.setup_manager.setups), 1)
        self.assertIsInstance(runner.setup_manager.setups[0], EnvironmentSetup)

    def test_yaml_runner_with_setup(self):
        import yaml

        config = {
            "setup": {"environment_variables": {"YAML_TEST_ENV": "yaml_value"}},
            "test_cases": [
                {
                    "name": "Test YAML env var",
                    "execution": {"command": "echo", "args": ["test"]},
                    "expected": {"return_code": 0},
                }
            ],
        }

        yaml_path = os.path.join(self.temp_dir, "test_config.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(config, f)

        runner = YAMLRunner(yaml_path, workspace=self.temp_dir)
        runner.load_test_cases()

        self.assertEqual(len(runner.setup_manager.setups), 1)
        self.assertIsInstance(runner.setup_manager.setups[0], EnvironmentSetup)

    def test_parallel_runner_with_setup(self):
        config = {
            "setup": {"environment_variables": {"PARALLEL_TEST_ENV": "parallel_value"}},
            "test_cases": [
                {
                    "name": "Test parallel env var",
                    "execution": {"command": "echo", "args": ["test"]},
                    "expected": {"return_code": 0},
                }
            ],
        }

        config_path = self.create_test_config_file(config)
        runner = ParallelJSONRunner(config_path, workspace=self.temp_dir, max_workers=2)
        runner.load_test_cases()

        self.assertEqual(len(runner.setup_manager.setups), 1)
        self.assertIsInstance(runner.setup_manager.setups[0], EnvironmentSetup)


if __name__ == "__main__":
    unittest.main()

