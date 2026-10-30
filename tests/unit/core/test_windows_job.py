# -*- coding: utf-8 -*-
"""Tests for Windows Job Object process-group measurement.

Real-subprocess tests (Windows only): grandchild peak capture, group kill on
timeout, drain wait, and graceful fallback when the job backend fails.
"""
import sys
import time
from unittest.mock import Mock, patch

import pytest

from symtest.core.execution import windows_job
from symtest.core.execution.executor import execute_command
from symtest.core.test_case import ExecutionSpec

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Job Object tests",
)


def _py(code: str) -> ExecutionSpec:
    return ExecutionSpec(name="job-case", command=sys.executable,
                         args=["-c", code])


class TestPeakMeasurement:
    def test_peak_includes_grandchild_allocation(self):
        """父进程派生子进程分配 100MB —— 峰值必须覆盖后代进程。"""
        child_alloc = "buf=bytearray(100*1024*1024);time.sleep(0.5)"
        spec = _py(
            "import subprocess,sys,time;"
            "p=subprocess.Popen([sys.executable,'-c',%r]);"
            "p.wait();print('done')" % child_alloc
        )
        result = execute_command(spec, measure_memory=True)
        assert result.return_code == 0
        assert result.error is None
        assert result.peak_memory_source == windows_job.PEAK_SOURCE
        assert result.peak_memory_bytes is not None
        assert result.peak_memory_bytes > 80 * 1024 * 1024

    def test_measure_off_leaves_peak_unknown(self):
        result = execute_command(_py("print('x')"), measure_memory=False)
        assert result.return_code == 0
        # 未测量：None 而不是 0
        assert result.peak_memory_bytes is None
        assert result.peak_memory_source is None

    def test_measurement_does_not_change_verdict(self):
        """测量路径下的返回码 / 输出语义与普通路径一致。"""
        spec = _py("import sys; print('out'); sys.exit(3)")
        result = execute_command(spec, measure_memory=True)
        assert result.return_code == 3
        assert "out" in result.output


class TestGroupKill:
    def test_timeout_terminates_process_group(self):
        """父 + 子进程都要在超时后被 Job 终止（无孤儿、communicate 返回）。"""
        spec = _py(
            "import subprocess,sys,time;"
            "p=subprocess.Popen([sys.executable,'-c','time.sleep(120)']);"
            "time.sleep(120)"
        )
        spec.timeout = 3
        t0 = time.time()
        result = execute_command(spec, measure_memory=True)
        elapsed = time.time() - t0
        assert result.timed_out is True
        # 整组被杀：管道 EOF 使 communicate 快速返回
        assert elapsed < 30
        # 超时路径同样有峰值测量
        assert result.peak_memory_bytes is not None


class TestDrainAndHandles:
    def test_descendant_wait_uses_only_remaining_command_budget(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("out", "")
        wait = Mock(return_value=True)
        with patch.multiple(
            windows_job,
            start_in_job=Mock(return_value=(process, 123)),
            wait_job_complete=wait,
            query_peak_memory_bytes=Mock(return_value=100),
            close_job=Mock(),
        ), patch(
            "symtest.core.execution.executor.time.perf_counter",
            side_effect=[0, 10, 11.5, 12],
        ):
            spec = _py("pass")
            spec.timeout = 2
            result = execute_command(spec, measure_memory=True)
        process.communicate.assert_called_once_with(timeout=2)
        wait.assert_called_once_with(123, 500)
        assert not result.timed_out
        assert result.error is None

    def test_redirected_descendant_finishes_beyond_old_grace(self, tmp_path):
        marker = tmp_path / "finished.txt"
        child = (
            "import time; from pathlib import Path; time.sleep(6); "
            f"Path({str(marker)!r}).write_text('done')"
        )
        spec = _py(
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}], "
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        )
        spec.timeout = 20
        result = execute_command(spec, measure_memory=True)
        assert result.error is None
        assert not result.timed_out
        assert result.return_code == 0
        assert marker.read_text() == "done"
        assert result.peak_memory_bytes is not None

    def test_redirected_descendant_shares_command_deadline(self):
        spec = _py(
            "import subprocess,sys,time; time.sleep(1); "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], "
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        )
        spec.timeout = 2
        started = time.perf_counter()
        result = execute_command(spec, measure_memory=True)
        elapsed = time.perf_counter() - started
        assert result.error is None
        assert result.timed_out
        assert result.return_code is None
        assert result.peak_memory_bytes is not None
        assert elapsed < 10, "descendant timeout must terminate promptly"

    def test_wait_job_complete_drains_after_exit(self):
        proc, job = windows_job.start_in_job(
            [sys.executable, "-c", "print('hi')"], cwd=None, env=None,
        )
        try:
            proc.communicate(timeout=30)
            # 进程已退出：排空应立即成立（Job 信号语义不适用于成员退出，
            # 实现必须走进程数轮询）
            assert windows_job.wait_job_complete(job, 2000) is True
            assert windows_job.query_peak_memory_bytes(job) is not None
        finally:
            windows_job.close_job(job)

    def test_query_peak_after_close_returns_none(self):
        proc, job = windows_job.start_in_job(
            [sys.executable, "-c", "print('hi')"], cwd=None, env=None,
        )
        proc.communicate(timeout=30)
        windows_job.close_job(job)
        # 句柄已关闭：查询失败返回 None（不抛异常、不返回 0）
        assert windows_job.query_peak_memory_bytes(job) is None


class TestFallback:
    def test_job_backend_failure_falls_back_to_plain_subprocess(self):
        """Job 后端失败 → 回退普通 Popen，执行不受影响、峰值未知。"""
        spec = _py("print('fallback')")

        def _boom(*args, **kwargs):
            raise windows_job.JobError("simulated backend failure")

        with patch.object(windows_job, "start_in_job", side_effect=_boom):
            result = execute_command(spec, measure_memory=True)
        assert result.return_code == 0
        assert "fallback" in result.output
        assert result.peak_memory_bytes is None
        assert result.error is None
