import json
import sys

from symtest.runners.json_runner import JSONRunner


def write_config(tmp_path, config):
    config_path = tmp_path / "cases.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_runner_executes_python_c_without_path_resolver_patch(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "test_cases": [
                {
                    "name": "python -c quoting",
                    "execution": {
                        "command": f'"{sys.executable}" -c "print(\'real-output\')"',
                        "args": [],
                    },
                    "expected": {"return_code": 0, "output_contains": ["real-output"]},
                }
            ]
        },
    )

    runner = JSONRunner(str(config_path), workspace=str(tmp_path))

    assert runner.run_tests()
    assert runner.results["passed"] == 1


def test_runner_reports_real_command_failure(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "test_cases": [
                {
                    "name": "nonzero exit",
                    "execution": {
                        "command": f'"{sys.executable}" -c "import sys; sys.exit(7)"',
                        "args": [],
                    },
                    "expected": {"return_code": 0},
                }
            ]
        },
    )

    runner = JSONRunner(str(config_path), workspace=str(tmp_path))

    assert not runner.run_tests()
    detail = runner.results["details"][0]
    assert detail["status"] == "failed"
    assert detail["return_code"] == 7
    assert runner.results["failed"] == 1


def test_runner_reports_real_command_timeout(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "test_cases": [
                {
                    "name": "timeout",
                    "execution": {
                        "command": f'"{sys.executable}" -c "import time; time.sleep(2)"',
                        "args": [],
                        "timeout": 0.2,
                    },
                    "expected": {"return_code": 0},
                }
            ]
        },
    )

    runner = JSONRunner(str(config_path), workspace=str(tmp_path))

    assert not runner.run_tests()
    detail = runner.results["details"][0]
    assert detail["status"] == "timeout"
    assert "Timeout reached" in detail["message"]


def test_sequence_stops_before_later_real_steps_after_failure(tmp_path):
    first_marker = tmp_path / "first.txt"
    third_marker = tmp_path / "third.txt"
    config_path = write_config(
        tmp_path,
        {
            "test_cases": [
                {
                    "name": "fail fast sequence",
                    "execution": {
                        "steps": [
                        {
                            "command": (
                                f'"{sys.executable}" -c '
                                f'"from pathlib import Path; Path({first_marker.as_posix()!r}).write_text(\'done\')"'
                            ),
                            "args": [],
                            "expected": {"return_code": 0},
                        },
                        {
                            "command": f'"{sys.executable}" -c "import sys; sys.exit(3)"',
                            "args": [],
                            "expected": {"return_code": 0},
                        },
                        {
                            "command": (
                                f'"{sys.executable}" -c '
                                f'"from pathlib import Path; Path({third_marker.as_posix()!r}).write_text(\'bad\')"'
                            ),
                            "args": [],
                            "expected": {"return_code": 0},
                        },
                        ],
                    },
                }
            ]
        },
    )

    runner = JSONRunner(str(config_path), workspace=str(tmp_path))

    assert not runner.run_tests()
    assert first_marker.read_text() == "done"
    assert not third_marker.exists()
    assert "step 2" in runner.results["details"][0]["message"]
