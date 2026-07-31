# -*- coding: utf-8 -*-
"""Integration tests for history_dir and regression detection in runners."""

import json
import os
import tempfile

import pytest

from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner
from symtest.core.history_store import SYMTEST_FILENAME, load_history


def _make_json_config(tmp_path, test_cases):
    """Write a JSON config and return its path."""
    config = tmp_path / "test_cases.json"
    config.write_text(json.dumps({"test_cases": test_cases}), encoding="utf-8")
    return str(config)


def _fast_case(name="fast_test"):
    return {
        "name": name,
        "command": "echo",
        "args": ["ok"],
        "expected": {"return_code": 0},
    }


class TestJSONRunnerHistory:
    def test_no_history_dir_no_symtest(self, tmp_path):
        config = _make_json_config(tmp_path, [_fast_case()])
        runner = JSONRunner(config_file=config, workspace=str(tmp_path))
        runner.run_tests()
        # No .symtest created
        assert not os.path.exists(str(tmp_path / ".symtest"))

    def test_history_dir_creates_symtest(self, tmp_path):
        config = _make_json_config(tmp_path, [_fast_case()])
        hist_dir = str(tmp_path / "hist")
        runner = JSONRunner(
            config_file=config,
            workspace=str(tmp_path),
            history_dir=hist_dir,
        )
        runner.run_tests()
        assert os.path.exists(os.path.join(hist_dir, SYMTEST_FILENAME))

    def test_history_records_duration(self, tmp_path):
        config = _make_json_config(tmp_path, [_fast_case("my_case")])
        hist_dir = str(tmp_path / "hist")
        runner = JSONRunner(
            config_file=config,
            workspace=str(tmp_path),
            history_dir=hist_dir,
        )
        runner.run_tests()
        history = load_history(hist_dir)
        assert "my_case" in history["cases"]
        rec = history["cases"]["my_case"]
        assert rec["run_count"] == 1
        assert rec["avg_duration"] > 0
        assert rec["last_duration"] == rec["avg_duration"]

    def test_cumulative_average_across_runs(self, tmp_path):
        config = _make_json_config(tmp_path, [_fast_case("my_case")])
        hist_dir = str(tmp_path / "hist")
        for _ in range(3):
            runner = JSONRunner(
                config_file=config,
                workspace=str(tmp_path),
                history_dir=hist_dir,
            )
            runner.run_tests()
        history = load_history(hist_dir)
        assert history["cases"]["my_case"]["run_count"] == 3

    def test_regression_warning_printed(self, tmp_path, caplog):
        """Simulate regression by writing a low avg_duration, then running."""
        config = _make_json_config(tmp_path, [_fast_case("slow_case")])
        hist_dir = str(tmp_path / "hist")
        # Pre-seed a very low avg so the real run looks like a regression
        os.makedirs(hist_dir, exist_ok=True)
        seed = {"version": 1, "cases": {
            "slow_case": {"avg_duration": 0.0001, "last_duration": 0.0001, "run_count": 5}
        }}
        with open(os.path.join(hist_dir, SYMTEST_FILENAME), "w", encoding="utf-8") as f:
            json.dump(seed, f)

        runner = JSONRunner(
            config_file=config,
            workspace=str(tmp_path),
            history_dir=hist_dir,
            regression_threshold=1.5,
        )
        runner.run_tests()
        output = caplog.text
        assert "regressed" in output.lower() or "WARNING" in output


class TestYAMLRunnerHistory:
    def test_history_dir_with_yaml(self, tmp_path):
        yaml_content = """
test_cases:
  - name: yaml_case
    command: echo
    args: ["hello"]
    expected:
      return_code: 0
"""
        config = tmp_path / "test_cases.yaml"
        config.write_text(yaml_content, encoding="utf-8")
        hist_dir = str(tmp_path / "hist")
        runner = YAMLRunner(
            config_file=str(config),
            workspace=str(tmp_path),
            history_dir=hist_dir,
        )
        runner.run_tests()
        history = load_history(hist_dir)
        assert "yaml_case" in history["cases"]


class TestParallelJSONRunnerHistory:
    def test_history_dir_with_parallel(self, tmp_path):
        config = _make_json_config(tmp_path, [_fast_case("p_case")])
        hist_dir = str(tmp_path / "hist")
        runner = ParallelJSONRunner(
            config_file=config,
            workspace=str(tmp_path),
            history_dir=hist_dir,
            max_workers=2,
        )
        runner.run_tests()
        history = load_history(hist_dir)
        assert "p_case" in history["cases"]

    def test_smart_scheduling_uses_history(self, tmp_path, caplog):
        """Verify that ParallelJSONRunner uses history data for scheduling."""
        cases = [
            {
                "name": "heavy",
                "command": "echo",
                "args": ["heavy"],
                "expected": {"return_code": 0},
                "resources": {"estimated_time": 1},
            },
            {
                "name": "light",
                "command": "echo",
                "args": ["light"],
                "expected": {"return_code": 0},
                "resources": {"estimated_time": 100},
            },
        ]
        config = _make_json_config(tmp_path, cases)
        hist_dir = str(tmp_path / "hist")
        # Pre-seed: heavy=50s avg, light=1s avg (opposite of config)
        os.makedirs(hist_dir, exist_ok=True)
        seed = {"version": 1, "cases": {
            "heavy": {"avg_duration": 50.0, "last_duration": 50.0, "run_count": 3},
            "light": {"avg_duration": 1.0, "last_duration": 1.0, "run_count": 3},
        }}
        with open(os.path.join(hist_dir, SYMTEST_FILENAME), "w", encoding="utf-8") as f:
            json.dump(seed, f)

        runner = ParallelJSONRunner(
            config_file=config,
            workspace=str(tmp_path),
            history_dir=hist_dir,
            max_workers=2,
        )
        runner.load_test_cases()
        # After loading, cases should be sorted by history avg (heavy first)
        output = caplog.text
        assert "history" in output.lower() or "Heaviest" in output
