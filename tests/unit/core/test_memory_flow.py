# -*- coding: utf-8 -*-
"""Tests for the peak-memory data flow: orchestration aggregation and
history persistence (measurement backend is faked; platform-independent).
"""
import sys
from unittest.mock import patch

import pytest

from symtest.core.execution.result import ExecutionResult
from symtest.core.history_store import load_history
from symtest.core.orchestration.sequence import execute_sequence
from symtest.core.orchestration.single import execute_single_test_case
from symtest.core.test_case import ExecutionSpec, TestStep
from symtest.runners.json_runner import JSONRunner

SRC = "windows_job_commit"


def _exec_result(rc=0, peak=None, output="ok"):
    return ExecutionResult(
        name="case", command="cmd", return_code=rc, output=output,
        peak_memory_bytes=peak, peak_memory_source=SRC if peak else None,
    )


class TestSingleCommandAggregation:
    def test_retry_takes_max_peak(self):
        """retry 各 attempt 峰值取最大值。"""
        spec = ExecutionSpec(name="case", command="cmd", retry_count=1)
        peaks = [100, 300]

        def fake_execute(cmd_spec, workspace=None, env=None, **kwargs):
            assert kwargs.get("measure_memory") is True
            rc = 1 if len(peaks) > 1 else 0
            peak = peaks.pop(0)
            return _exec_result(rc=rc, peak=peak)

        with patch(
            "symtest.core.orchestration.single.execute_command",
            side_effect=fake_execute,
        ):
            result = execute_single_test_case(
                spec, expectation={"return_code": 0}, measure_memory=True,
            )
        assert result["status"] == "passed"
        assert result["peak_memory_bytes"] == 300
        assert result["peak_memory_source"] == SRC

    def test_no_measurement_keeps_legacy_shape(self):
        """无可测量（后端失败/未启用）→ 结果字典不含峰值字段。"""
        spec = ExecutionSpec(name="case", command="cmd")
        with patch(
            "symtest.core.orchestration.single.execute_command",
            return_value=_exec_result(rc=0, peak=None),
        ):
            result = execute_single_test_case(
                spec, expectation={"return_code": 0}, measure_memory=True,
            )
        assert "peak_memory_bytes" not in result
        assert "peak_memory_source" not in result

    def test_measurement_failure_does_not_affect_verdict(self):
        """峰值测量不改变通过/失败判定。"""
        spec = ExecutionSpec(name="case", command="cmd")
        with patch(
            "symtest.core.orchestration.single.execute_command",
            return_value=_exec_result(rc=2, peak=500),
        ):
            result = execute_single_test_case(
                spec, expectation={"return_code": 0}, measure_memory=True,
            )
        assert result["status"] == "failed"
        assert result["peak_memory_bytes"] == 500


class TestSequenceAggregation:
    def _step(self, command):
        return TestStep.from_flat(command=command, args=[])

    def test_sequence_takes_max_over_executed_steps(self):
        """序列峰值取实际执行步骤的最大值（不求和）。"""
        peaks = [100, 500]

        def fake_executor(step_spec, workspace=None, **kwargs):
            peak = peaks.pop(0)
            return {
                "name": step_spec.name,
                "status": "passed",
                "message": "",
                "command": "cmd",
                "output": "ok",
                "return_code": 0,
                "duration": 0.1,
                "peak_memory_bytes": peak,
                "peak_memory_source": SRC,
            }

        result = execute_sequence(
            "seq-case", [self._step("a"), self._step("b")],
            executor=fake_executor, measure_memory=True,
        )
        assert result["status"] == "passed"
        assert result["peak_memory_bytes"] == 500

    def test_step_without_measurement_does_not_zero_out(self):
        """某步无测量不影响其余步骤的聚合。"""
        peaks = [100, None, 700]

        def fake_executor(step_spec, workspace=None, **kwargs):
            peak = peaks.pop(0)
            data = {
                "name": step_spec.name, "status": "passed", "message": "",
                "command": "cmd", "output": "ok", "return_code": 0,
                "duration": 0.1,
            }
            if peak is not None:
                data["peak_memory_bytes"] = peak
                data["peak_memory_source"] = SRC
            return data

        result = execute_sequence(
            "seq-case", [self._step("a"), self._step("b"), self._step("c")],
            executor=fake_executor, measure_memory=True,
        )
        assert result["status"] == "passed"
        assert result["peak_memory_bytes"] == 700

    def test_sequence_without_measurement_keeps_legacy_shape(self):
        def fake_executor(step_spec, workspace=None, **kwargs):
            return {
                "name": step_spec.name, "status": "passed", "message": "",
                "command": "cmd", "output": "ok", "return_code": 0,
                "duration": 0.1,
            }

        result = execute_sequence(
            "seq-case", [self._step("a")],
            executor=fake_executor, measure_memory=True,
        )
        assert "peak_memory_bytes" not in result


class TestHistoryPersistence:
    def _make_runner(self, tmp_path):
        config = tmp_path / "test_cases.json"
        config.write_text("{}", encoding="utf-8")
        return JSONRunner(
            str(config), workspace=str(tmp_path), history_dir="hist",
        )

    def test_peak_recorded_for_failed_case(self, tmp_path):
        """失败 case 的有效峰值也记录（保护下次调度）。"""
        runner = self._make_runner(tmp_path)
        runner.results["details"] = [
            {"name": "failed-case", "status": "failed", "duration": 1.0,
             "peak_memory_bytes": 500, "peak_memory_source": SRC},
        ]
        runner._update_history()
        hist = load_history(runner.history_dir)
        rec = hist["cases"]["failed-case"]
        assert rec["last_peak_memory_bytes"] == 500
        assert rec["max_peak_memory_bytes"] == 500
        assert rec["peak_memory_count"] == 1
        assert rec["peak_memory_source"] == SRC
        # 失败 case 不记录耗时
        assert "avg_duration" not in rec

    def test_passed_case_records_both_duration_and_peak(self, tmp_path):
        runner = self._make_runner(tmp_path)
        runner.results["details"] = [
            {"name": "ok-case", "status": "passed", "duration": 2.0,
             "peak_memory_bytes": 500, "peak_memory_source": SRC},
        ]
        runner._update_history()
        hist = load_history(runner.history_dir)
        rec = hist["cases"]["ok-case"]
        assert rec["avg_duration"] == 2.0
        assert rec["max_peak_memory_bytes"] == 500

    def test_case_without_measurement_unchanged(self, tmp_path):
        runner = self._make_runner(tmp_path)
        runner.results["details"] = [
            {"name": "plain-case", "status": "passed", "duration": 2.0},
        ]
        runner._update_history()
        hist = load_history(runner.history_dir)
        rec = hist["cases"]["plain-case"]
        assert "max_peak_memory_bytes" not in rec
        assert rec["avg_duration"] == 2.0

    def test_update_history_flag_clears_memory_records(self, tmp_path):
        """--update-history 清除整条记录（耗时 + 内存）。"""
        runner = self._make_runner(tmp_path)
        runner.update_history = True
        runner.results["details"] = [
            {"name": "c", "status": "passed", "duration": 2.0,
             "peak_memory_bytes": 500, "peak_memory_source": SRC},
        ]
        runner._update_history()
        hist = load_history(runner.history_dir)
        assert "c" in hist["cases"]  # 本次运行重新记录
        assert hist["cases"]["c"]["max_peak_memory_bytes"] == 500


class TestMemoryOnlyHistoryCompat:
    @pytest.mark.parametrize("mode", ["thread", "process"])
    @pytest.mark.parametrize("history_dir", [None, "hist"])
    def test_empty_parallel_configuration_loads(self, tmp_path, mode, history_dir):
        from symtest.runners.parallel_json_runner import ParallelJSONRunner

        config = tmp_path / "empty.json"
        config.write_text('{"test_cases": []}', encoding="utf-8")
        runner = ParallelJSONRunner(
            str(config), workspace=str(tmp_path), execution_mode=mode,
            history_dir=history_dir,
        )
        runner.load_test_cases()
        assert runner.test_cases == []

    def test_lpt_estimation_tolerates_memory_only_records(self, tmp_path):
        """只有内存记录的 case 参与 LPT 排序时按 0 耗时处理，不抛错。"""
        from symtest.core.history_store import load_history, update_case_memory
        from symtest.runners.parallel_json_runner import ParallelJSONRunner

        config = tmp_path / "test_cases.json"
        import json
        config.write_text(json.dumps({
            "test_cases": [
                {"name": "mem-only",
                 "execution": {"command": sys.executable, "args": ["-c", "print(1)"]},
                 "expected": {"return_code": 0}},
            ]
        }), encoding="utf-8")

        runner = ParallelJSONRunner(
            str(config), workspace=str(tmp_path), history_dir="hist",
        )
        # 预置只有内存记录的 history
        hist = load_history(runner.history_dir)
        update_case_memory(hist, "mem-only", 500 * 1024 ** 2, SRC)
        from symtest.core.history_store import save_history
        save_history(runner.history_dir, hist)

        runner.load_test_cases()  # 不应抛 KeyError
        assert len(runner.test_cases) == 1
