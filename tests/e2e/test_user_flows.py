import json
import os
import sys
import tempfile
from unittest import SkipTest

from symtest.runners.json_runner import JSONRunner
from symtest.runners.yaml_runner import YAMLRunner


def test_json_runner_end_to_end():
    """基本 JSONRunner 流程，含 setup 环境变量"""
    temp_dir = tempfile.mkdtemp()
    config = {
        "setup": {"environment_variables": {"E2E_ENV": "json_e2e"}},
        "test_cases": [
            {
                "name": "echo with env",
                "command": f'"{sys.executable}" -c "import os; print(os.environ.get(\'E2E_ENV\'))"',
                "args": [],
                "expected": {"return_code": 0, "output_contains": ["json_e2e"]},
            },
            {
                "name": "simple echo",
                "command": f'"{sys.executable}" -c "print(\'hello-e2e\')"',
                "args": [],
                "expected": {"return_code": 0, "output_contains": ["hello-e2e"]},
            },
        ],
    }
    config_path = os.path.join(temp_dir, "e2e.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    runner = JSONRunner(config_path, workspace=temp_dir)
    success = runner.run_tests()

    assert success
    assert runner.results["total"] == 2
    assert runner.results["passed"] == 2


def test_yaml_runner_end_to_end():
    """基本 YAMLRunner 流程"""
    import importlib

    try:
        yaml = importlib.import_module("yaml")
    except ImportError:
        raise SkipTest("pyyaml not installed")
    temp_dir = tempfile.mkdtemp()
    config = {
        "setup": {"environment_variables": {"E2E_ENV": "yaml_e2e"}},
        "test_cases": [
            {
                "name": "yaml echo",
                "command": f'"{sys.executable}" -c "import os; print(os.environ.get(\'E2E_ENV\'))"',
                "args": [],
                "expected": {"return_code": 0, "output_contains": ["yaml_e2e"]},
            }
        ],
    }

    yaml_path = os.path.join(temp_dir, "e2e.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True)

    runner = YAMLRunner(yaml_path, workspace=temp_dir)
    success = runner.run_tests()

    assert success
    assert runner.results["total"] == 1
    assert runner.results["passed"] == 1

