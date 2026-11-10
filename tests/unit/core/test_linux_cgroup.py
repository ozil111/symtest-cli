# -*- coding: utf-8 -*-
"""Tests for the Linux cgroup v2 process-group measurement backend.

核心手段：**假 cgroup 树**——monkeypatch ``_own_cgroup_dir`` 指向
tmp_path 伪造树、``_new_group_name`` 返回确定名、缓存的能力探测结果，
用普通文件模拟内核行为（cgroup.procs 记录、memory.peak 高水位），
命令真实执行。执行器全链路测试中由命令自身写 memory.peak 模拟内核
记账。探针的正向结论（有委派权限的真实环境）无法在假树上伪造，
由只读/缺控制器两个负向分支 + 真机降级路径覆盖。
"""
import os
import subprocess
import sys
import time

import pytest

from symtest.core.execution import linux_cgroup
from symtest.core.execution.executor import execute_command
from symtest.core.execution.linux_cgroup import CgroupHandle
from symtest.core.test_case import ExecutionSpec

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux cgroup v2 tests",
)


def _fake_tree(monkeypatch, tmp_path, group_name="symtest-fixed"):
    """搭假 cgroup 树并注入后端；返回 (root, group_dir)。

    同时把能力探测缓存置 True：executor 经 facade 调用 is_supported，
    假树环境必须按"可用"进入测量路径。
    """
    root = tmp_path / "cgroup2"
    root.mkdir()
    monkeypatch.setattr(linux_cgroup, "_own_cgroup_dir", lambda: root)
    monkeypatch.setattr(linux_cgroup, "_new_group_name",
                        lambda: group_name)
    monkeypatch.setattr(linux_cgroup, "_supported_cache", True)
    # 假树里普通文件会阻塞 rmdir（真 cgroupfs 伪文件不会），缩短
    # close 的重试窗口避免测试空转
    monkeypatch.setattr(linux_cgroup, "_CLOSE_RETRY_S", 0.2)
    group_dir = root / group_name
    return root, group_dir


def _py(code: str) -> list:
    return [sys.executable, "-c", code]


class TestStartInCgroup:
    def test_command_runs_and_migrates_itself(self, monkeypatch, tmp_path):
        """shell 先把自身 pid 写入 cgroup.procs 再 exec 命令。"""
        root, group_dir = _fake_tree(monkeypatch, tmp_path)
        process, handle = linux_cgroup.start_in_cgroup(
            _py("print('hi')"), cwd=None, env=None)
        out, _ = process.communicate(timeout=30)
        assert out.strip() == "hi"
        assert handle.path == group_dir
        assert handle.pid == process.pid
        # 迁移记录存在：pid 与命令进程一致（exec 保留 pid）
        recorded = (group_dir / "cgroup.procs").read_text().split()
        assert str(process.pid) in recorded
        assert group_dir.is_dir()

    def test_mkdir_failure_raises_cgroup_error(self, monkeypatch, tmp_path):
        """无法创建组目录（无委派权限）→ CgroupError，调用方回退。"""
        root = tmp_path / "cgroup2"
        root.mkdir()
        root.chmod(0o555)  # 去掉写权限
        monkeypatch.setattr(linux_cgroup, "_own_cgroup_dir", lambda: root)
        try:
            with pytest.raises(linux_cgroup.CgroupError):
                linux_cgroup.start_in_cgroup(_py("print(1)"))
        finally:
            root.chmod(0o755)

    def test_no_cgroup_v2_raises(self, monkeypatch):
        monkeypatch.setattr(linux_cgroup, "_own_cgroup_dir", lambda: None)
        with pytest.raises(linux_cgroup.CgroupError):
            linux_cgroup.start_in_cgroup(_py("print(1)"))


class TestWaitComplete:
    def test_empty_procs_file_drains(self, monkeypatch, tmp_path):
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        (group_dir / "cgroup.procs").write_text("", encoding="utf-8")
        handle = CgroupHandle(group_dir, pid=999999)
        assert linux_cgroup.wait_complete(handle, 200) is True

    def test_live_pid_times_out(self, monkeypatch, tmp_path):
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        sleeper = subprocess.Popen(["sleep", "30"])
        try:
            (group_dir / "cgroup.procs").write_text(
                str(sleeper.pid), encoding="utf-8")
            handle = CgroupHandle(group_dir, pid=sleeper.pid)
            assert linux_cgroup.wait_complete(handle, 300) is False
        finally:
            sleeper.kill()
            sleeper.wait()

    def test_dead_pid_left_in_file_still_drains(self, monkeypatch, tmp_path):
        """无 reaper 环境残留已退出 pid 的记录：全部不存活即排空。"""
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        dead = subprocess.Popen(["true"])
        dead.wait()
        (group_dir / "cgroup.procs").write_text(
            str(dead.pid), encoding="utf-8")
        handle = CgroupHandle(group_dir, pid=dead.pid)
        assert linux_cgroup.wait_complete(handle, 5000) is True


class TestQueryPeak:
    def test_reads_memory_peak(self, monkeypatch, tmp_path):
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        (group_dir / "memory.peak").write_text("5368709120\n",
                                               encoding="utf-8")
        handle = CgroupHandle(group_dir, pid=1)
        assert linux_cgroup.query_peak_bytes(handle) == 5368709120

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        handle = CgroupHandle(group_dir, pid=1)
        assert linux_cgroup.query_peak_bytes(handle) is None

    def test_zero_peak_returns_none(self, monkeypatch, tmp_path):
        """不得以 0 伪装成功。"""
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        (group_dir / "memory.peak").write_text("0\n", encoding="utf-8")
        handle = CgroupHandle(group_dir, pid=1)
        assert linux_cgroup.query_peak_bytes(handle) is None


class TestTerminateAndClose:
    def test_terminate_kills_group_members(self, monkeypatch, tmp_path):
        """组内 pid 被 SIGKILL（覆盖 setsid 逃逸进程组的后代）。"""
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        orphan = subprocess.Popen(  # 新会话：killpg 无效，靠名单击杀
            ["sleep", "60"], start_new_session=True)
        try:
            (group_dir / "cgroup.procs").write_text(
                str(orphan.pid), encoding="utf-8")
            handle = CgroupHandle(group_dir, pid=999999)
            linux_cgroup.terminate(handle)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if orphan.poll() is not None:
                    break
                time.sleep(0.05)
            assert orphan.poll() is not None
        finally:
            if orphan.poll() is None:
                orphan.kill()
                orphan.wait()

    def test_close_removes_empty_group(self, monkeypatch, tmp_path):
        """空组（无成员、无子组）目录被移除（真 cgroupfs 伪文件不阻塞）。"""
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        linux_cgroup.close_group(CgroupHandle(group_dir, pid=1))
        assert not group_dir.exists()

    def test_close_leaves_group_with_live_member(self, monkeypatch, tmp_path,
                                                 caplog):
        """组内仍有存活进程：保留目录并告警，不强杀。"""
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        group_dir.mkdir()
        sleeper = subprocess.Popen(["sleep", "30"])
        try:
            (group_dir / "cgroup.procs").write_text(
                str(sleeper.pid), encoding="utf-8")
            with caplog.at_level("WARNING"):
                linux_cgroup.close_group(CgroupHandle(group_dir, pid=1))
            assert group_dir.exists()
            assert "left in place" in caplog.text
        finally:
            sleeper.kill()
            sleeper.wait()


class TestProbeSupport:
    """探针负向分支可确定性复现；正向结论需真实委派环境。"""

    def test_probe_without_memory_controller(self, monkeypatch, tmp_path):
        """子组无 memory.peak 且无法启用控制器 → 不支持。"""
        root, _ = _fake_tree(monkeypatch, tmp_path)
        (root / "cgroup.controllers").write_text("cpu pids\n",
                                                 encoding="utf-8")
        assert linux_cgroup._probe_support() is False

    def test_probe_readonly_base(self, monkeypatch, tmp_path):
        """mkdir 被拒（本机真实降级路径的确定性复现）→ 不支持。"""
        root, _ = _fake_tree(monkeypatch, tmp_path)
        root.chmod(0o555)
        try:
            assert linux_cgroup._probe_support() is False
        finally:
            root.chmod(0o755)

    def test_try_enable_memory_controller_success(self, tmp_path):
        root = tmp_path / "cg"
        root.mkdir()
        (root / "cgroup.controllers").write_text(
            "cpu memory pids\n", encoding="utf-8")
        (root / "cgroup.subtree_control").write_text(
            "cpu\n", encoding="utf-8")
        assert linux_cgroup._try_enable_memory_controller(root) is True

    def test_try_enable_memory_controller_readonly(self, tmp_path):
        """subtree_control 不可写 → False。"""
        root = tmp_path / "cg"
        root.mkdir()
        (root / "cgroup.controllers").write_text(
            "cpu memory pids\n", encoding="utf-8")
        subtree = root / "cgroup.subtree_control"
        subtree.write_text("cpu\n", encoding="utf-8")
        subtree.chmod(0o444)
        try:
            assert linux_cgroup._try_enable_memory_controller(root) is False
        finally:
            subtree.chmod(0o644)

    def test_try_enable_memory_controller_missing(self, tmp_path):
        root = tmp_path / "cg"
        root.mkdir()
        assert linux_cgroup._try_enable_memory_controller(root) is False

    def test_is_supported_uses_process_cache(self, monkeypatch):
        monkeypatch.setattr(linux_cgroup, "_supported_cache", None)
        calls = []
        monkeypatch.setattr(
            linux_cgroup, "_probe_support",
            lambda: calls.append(1) or True,
        )
        assert linux_cgroup.is_supported() is True
        assert linux_cgroup.is_supported() is True
        assert len(calls) == 1  # 第二次命中缓存

    def test_real_machine_degrades_without_delegation(self, monkeypatch):
        """无委派权限的真机（如 /sys/fs/cgroup 只读）：is_supported 返回
        False。有委派权限的机器上正向结论由真实验收覆盖。"""
        own = linux_cgroup._own_cgroup_dir()  # 未打桩：真实目录
        monkeypatch.setattr(linux_cgroup, "_supported_cache", None)
        result = linux_cgroup.is_supported()
        if own is None or not os.access(own, os.W_OK | os.X_OK):
            assert result is False


class TestExecutorIntegration:
    """execute_command 全链路：假树 + 确定组名，命令自写 memory.peak
    模拟内核记账，验证峰值读取与结果传播。"""

    def _peak_writing_spec(self, peak_bytes):
        code = (
            "import os; "
            f"open(os.environ['PEAK_FILE'], 'w').write({str(peak_bytes)!r}); "
            "print('done')"
        )
        return ExecutionSpec(
            name="cg-case", command=sys.executable, args=["-c", code],
        )

    def test_peak_recorded_with_linux_source(self, monkeypatch, tmp_path):
        root, group_dir = _fake_tree(monkeypatch, tmp_path)
        spec = self._peak_writing_spec(5368709120)
        result = execute_command(
            spec, measure_memory=True,
            env={"PEAK_FILE": str(group_dir / "memory.peak")},
        )
        assert result.error is None
        assert result.return_code == 0
        assert "done" in result.output
        assert result.peak_memory_bytes == 5368709120
        assert result.peak_memory_source == linux_cgroup.PEAK_SOURCE
        # 注：假树里 cgroup.procs/memory.peak 是普通文件，会阻塞 rmdir
        # （真 cgroupfs 伪文件不阻塞），因此不在此断言目录移除。

    def test_measure_off_leaves_peak_unknown(self, monkeypatch, tmp_path):
        root, group_dir = _fake_tree(monkeypatch, tmp_path)
        # 未测量时不创建组目录：peak 文件指向 tmp_path 避免命令写失败
        spec = self._peak_writing_spec(1)
        result = execute_command(
            spec, measure_memory=False,
            env={"PEAK_FILE": str(tmp_path / "memory.peak")},
        )
        assert result.return_code == 0
        assert result.peak_memory_bytes is None
        assert result.peak_memory_source is None
        assert not group_dir.exists()

    def test_timeout_terminates_and_records_peak(
            self, monkeypatch, tmp_path):
        """超时：整组终止、timed_out 置位、峰值照常读取。"""
        root, group_dir = _fake_tree(monkeypatch, tmp_path)
        code = (
            "import os,subprocess,sys,time; "
            "open(os.environ['PEAK_FILE'],'w').write('1048576'); "
            "subprocess.Popen(['sleep','60']); "
            "time.sleep(60)"
        )
        spec = ExecutionSpec(
            name="cg-timeout", command=sys.executable, args=["-c", code],
        )
        spec.timeout = 3
        t0 = time.perf_counter()
        result = execute_command(
            spec, measure_memory=True,
            env={"PEAK_FILE": str(group_dir / "memory.peak")},
        )
        elapsed = time.perf_counter() - t0
        assert result.timed_out is True
        assert elapsed < 30  # 整组被杀，不死等
        assert result.peak_memory_bytes == 1048576

    def test_measurement_does_not_change_verdict(self, monkeypatch, tmp_path):
        root, group_dir = _fake_tree(monkeypatch, tmp_path)
        spec = ExecutionSpec(
            name="cg-rc", command=sys.executable,
            args=["-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        )
        result = execute_command(
            spec, measure_memory=True,
            env={"PEAK_FILE": str(group_dir / "memory.peak")},
        )
        assert result.return_code == 3
        assert result.stdout == "out\n"
        assert result.stderr == "err\n"

    def test_migration_failure_falls_back_to_plain_subprocess(
            self, monkeypatch, tmp_path, caplog):
        _, group_dir = _fake_tree(monkeypatch, tmp_path)
        mkdir = type(group_dir).mkdir

        def mkdir_with_unwritable_procs(path, *args, **kwargs):
            mkdir(path, *args, **kwargs)
            if path == group_dir:
                mkdir(path / "cgroup.procs")  # 重定向到目录一定失败（包括 root）。

        monkeypatch.setattr(type(group_dir), "mkdir", mkdir_with_unwritable_procs)
        marker = tmp_path / "runs"
        spec = ExecutionSpec(
            name="cg-fallback", command=sys.executable,
            args=["-c", "import sys; open(sys.argv[1], 'a').write('run\\n')", str(marker)],
        )
        result = execute_command(spec, measure_memory=True)
        assert result.return_code == 0
        assert marker.read_text(encoding="utf-8") == "run\n"
        assert "cannot migrate process to cgroup" in caplog.text
        assert result.peak_memory_bytes is None
        assert result.error is None


class TestSourceContract:
    def test_peak_source_matches_history_dispatch_key(self):
        """linux_cgroup.PEAK_SOURCE 与 history_store 的分派键保持一致。"""
        from symtest.core.history_store import LINUX_PEAK_SOURCE
        assert linux_cgroup.PEAK_SOURCE == LINUX_PEAK_SOURCE
