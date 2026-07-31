import json
import os
import sys
import tempfile

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


def build_config(temp_dir):
    return {
        "test_cases": [
            {
                "name": "简单命令",
                "command": "echo hello",
                "args": [],
                "expected": {"return_code": 0, "output_contains": ["hello"]},
            },
            {
                "name": "带引号的Windows路径",
                "command": '"C:\\Program Files (x86)\\Python\\python.exe" --version',
                "args": [],
                "expected": {"return_code": 0},
            },
            {
                "name": "不带引号的Windows路径",
                "command": "C:\\Program Files (x86)\\Python\\python.exe --version",
                "args": [],
                "expected": {"return_code": 0},
            },
            {
                "name": "相对路径脚本",
                "command": "python script.py",
                "args": ["--verbose"],
                "expected": {"return_code": 0},
            },
            {
                "name": "复杂命令带参数",
                "command": "node app.js",
                "args": ["--port", "3000", "--env", "development"],
                "expected": {"return_code": 0},
            },
            {
                "name": "带空格的Unix路径",
                "command": '"/usr/local/bin/my app" --help',
                "args": [],
                "expected": {"return_code": 0},
            },
        ]
    }


def write_config(temp_dir, config):
    path = os.path.join(temp_dir, "space_path_test.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return path


def assert_loaded_cases(cases, original_config):
    assert len(cases) == len(original_config["test_cases"])
    names = [c.name for c in cases]
    assert set(names) == {c["name"] for c in original_config["test_cases"]}


def test_json_runner_loads_space_paths():
    temp_dir = tempfile.mkdtemp()
    config = build_config(temp_dir)
    config_path = write_config(temp_dir, config)

    runner = JSONRunner(config_path, temp_dir)
    runner.load_test_cases()

    assert_loaded_cases(runner.test_cases, config)


def test_parallel_runner_loads_space_paths():
    temp_dir = tempfile.mkdtemp()
    config = build_config(temp_dir)
    config_path = write_config(temp_dir, config)

    runner = ParallelJSONRunner(config_path, temp_dir, max_workers=2, execution_mode="thread")
    runner.load_test_cases()

    assert_loaded_cases(runner.test_cases, config)


def test_runner_executes_script_argument_with_spaces(tmp_path):
    script_dir = tmp_path / "tools with spaces"
    script_dir.mkdir()
    script_path = script_dir / "emit value.py"
    script_path.write_text(
        "import sys\n"
        "print('script-path-ok')\n"
        "print(sys.argv[1])\n",
        encoding="utf-8",
    )
    config = {
        "test_cases": [
            {
                "name": "script path with spaces",
                "command": f'"{sys.executable}"',
                "args": [str(script_path.relative_to(tmp_path)), "payload value"],
                "expected": {
                    "return_code": 0,
                    "output_contains": ["script-path-ok", "payload value"],
                },
            }
        ]
    }
    config_path = write_config(str(tmp_path), config)

    runner = JSONRunner(config_path, str(tmp_path))

    assert runner.run_tests()

