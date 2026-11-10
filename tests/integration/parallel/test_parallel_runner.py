import json
import os
import sys
import tempfile
import time
import unittest

import pytest

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


class TestParallelRunner(unittest.TestCase):
    """并行运行器测试类"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "test_config.json")

        test_config = {
            "test_cases": [
                {
                    "name": "测试1",
                    "execution": {"command": "echo", "args": ["test1"]},
                    "expected": {"return_code": 0, "output_contains": ["test1"]},
                },
                {
                    "name": "测试2",
                    "execution": {"command": "echo", "args": ["test2"]},
                    "expected": {"return_code": 0, "output_contains": ["test2"]},
                },
                {
                    "name": "测试3",
                    "execution": {"command": "echo", "args": ["test3"]},
                    "expected": {"return_code": 0, "output_contains": ["test3"]},
                },
                {
                    "name": "测试4",
                    "execution": {"command": "echo", "args": ["test4"]},
                    "expected": {"return_code": 0, "output_contains": ["test4"]},
                },
            ]
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_parallel_vs_sequential_performance(self):
        sequential_runner = JSONRunner(self.config_file, self.temp_dir)
        start_time = time.time()
        seq_success = sequential_runner.run_tests()
        seq_time = time.time() - start_time

        parallel_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        start_time = time.time()
        par_success = parallel_runner.run_tests()
        par_time = time.time() - start_time

        self.assertTrue(seq_success)
        self.assertTrue(par_success)
        self.assertEqual(sequential_runner.results["total"], parallel_runner.results["total"])
        self.assertEqual(sequential_runner.results["passed"], parallel_runner.results["passed"])
        self.assertGreater(seq_time, 0)
        self.assertGreater(par_time, 0)

    def test_thread_vs_process_mode(self):
        thread_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        thread_success = thread_runner.run_tests()

        process_runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="process"
        )
        process_success = process_runner.run_tests()

        self.assertTrue(thread_success)
        self.assertTrue(process_success)
        self.assertEqual(thread_runner.results["passed"], process_runner.results["passed"])

    def test_process_mode_discovers_workspace_plugins(self):
        """Process workers discover workspace plugins via the pool initializer
        (explicit initargs — the framework never writes os.environ)."""
        comparators_dir = os.path.join(self.temp_dir, "comparators")
        os.makedirs(comparators_dir)
        plugin_code = (
            "from symtest.file_comparator.base_comparator import ComparatorBase\n"
            "from symtest.file_comparator.result import ComparisonResult\n"
            "\n"
            "class AlwaysPassComparator(ComparatorBase):\n"
            "    def compare(self, ctx):\n"
            "        result = ComparisonResult(\n"
            "            file1=str(ctx.baseline or ''),\n"
            "            file2=str(ctx.actual or ''),\n"
            "        )\n"
            "        result.identical = True\n"
            "        return result\n"
        )
        with open(os.path.join(comparators_dir, "always_pass_comparator.py"),
                  "w", encoding="utf-8") as f:
            f.write(plugin_code)

        # Contents deliberately differ: the plugin always passes, so the case
        # only succeeds if the WORKER actually registered the plugin type.
        file_a = os.path.join(self.temp_dir, "a.txt")
        file_b = os.path.join(self.temp_dir, "b.txt")
        for path, content in ((file_a, "AAA"), (file_b, "BBB")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        config_file = os.path.join(self.temp_dir, "plugin_config.json")
        test_config = {
            "test_cases": [
                {
                    "name": "plugin_case",
                    "execution": {
                        "command": f'"{sys.executable}" -c "print(\'ok\')"',
                        "args": [],
                    },
                    "expected": {
                        "return_code": 0,
                        "compare_files": [
                            {
                                "actual": "b.txt",
                                "baseline": "a.txt",
                                "type": "alwayspass",
                            }
                        ],
                    },
                }
            ]
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)

        runner = ParallelJSONRunner(
            config_file, self.temp_dir, max_workers=2, execution_mode="process"
        )
        success = runner.run_tests()

        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 1)

    def test_max_workers_configuration(self):
        for max_workers in [1, 2, 4]:
            with self.subTest(max_workers=max_workers):
                runner = ParallelJSONRunner(
                    self.config_file, self.temp_dir, max_workers=max_workers, execution_mode="thread"
                )
                success = runner.run_tests()
                self.assertTrue(success)
                self.assertEqual(runner.results["passed"], 4)

    def test_fallback_to_sequential(self):
        runner = ParallelJSONRunner(
            self.config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )
        success = runner.run_tests_sequential()
        self.assertTrue(success)
        self.assertEqual(runner.results["passed"], 4)

    def test_parallel_reports_real_failures(self):
        config_file = os.path.join(self.temp_dir, "failure_config.json")
        test_config = {
            "test_cases": [
                {
                    "name": "pass",
                    "execution": {
                        "command": f'"{sys.executable}" -c "print(\'ok\')"',
                        "args": [],
                    },
                    "expected": {"return_code": 0, "output_contains": ["ok"]},
                },
                {
                    "name": "fail",
                    "execution": {
                        "command": f'"{sys.executable}" -c "import sys; sys.exit(5)"',
                        "args": [],
                    },
                    "expected": {"return_code": 0},
                },
            ]
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f, ensure_ascii=False, indent=2)

        runner = ParallelJSONRunner(
            config_file, self.temp_dir, max_workers=2, execution_mode="thread"
        )

        success = runner.run_tests()

        self.assertFalse(success)
        self.assertEqual(runner.results["passed"], 1)
        self.assertEqual(runner.results["failed"], 1)
        failed = [d for d in runner.results["details"] if d["status"] != "passed"]
        self.assertEqual(failed[0]["return_code"], 5)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Windows memory management (measurement + joint admission)
# ---------------------------------------------------------------------------

GB = 1024 ** 3


def _write_config(path, cases):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"test_cases": cases}, f, ensure_ascii=False, indent=2)


def _sleep_case(name, seconds=2, mem_mb=None):
    case = {
        "name": name,
        "execution": {
            "command": sys.executable,
            "args": ["-c",
                     "import time;time.sleep(%d);print('%s')" % (seconds, name)],
        },
        "expected": {"return_code": 0, "output_contains": [name]},
        "scheduling": {"resources": {"cpu_cores": 1}},
    }
    if mem_mb is not None:
        case["scheduling"]["resources"]["min_memory_mb"] = mem_mb
    return case


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
class TestWindowsMemoryManagement:
    def test_short_case_batch_has_no_per_case_startup_delay(self, tmp_path, monkeypatch):
        """A dozen tiny cases must not incur eleven one-second launch gaps."""
        from symtest.core.system_memory import MemorySnapshot

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            lambda: MemorySnapshot(16 * GB, 12 * GB, 12 * GB, 32 * GB),
        )
        config = tmp_path / "cases.json"
        _write_config(config, [
            _sleep_case("tiny%d" % i, seconds=0, mem_mb=16) for i in range(12)
        ])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=4, execution_mode="thread",
        )
        start = time.perf_counter()
        assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["passed"] == 12
        assert time.perf_counter() - start < 8

    def test_commit_reserve_over_limit_runs_and_records_peak(
            self, tmp_path, monkeypatch, caplog):
        """需求本身可满足但加保留量超上限：完整执行并更新 history。"""
        from symtest.core.system_memory import MemorySnapshot
        from symtest.core.history_store import load_history

        reads = 0

        def snapshot():
            nonlocal reads
            reads += 1
            # Bound a regression to permanent polling without leaking workers.
            if reads > 5:
                raise AssertionError("unsatisfiable commit demand kept polling")
            return MemorySnapshot(16 * GB, 12 * GB, 8 * GB, 8 * GB)

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot", snapshot,
        )
        config = tmp_path / "cases.json"
        _write_config(config, [_sleep_case("reserve", seconds=0, mem_mb=7 * 1024)])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=2, execution_mode="thread",
            history_dir="hist", memory_commit_reserve_mb=2048,
            memory_min_start_interval_s=0,
        )
        assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["passed"] == 1
        assert "plus 2.0 GiB reserve" in caplog.text
        record = load_history(str(tmp_path / "hist"))["cases"]["reserve"]
        assert record["max_peak_memory_bytes"] > 0
        assert record["peak_memory_source"] == "windows_job_commit"

    @pytest.mark.parametrize("watermark_mb", [2048, 3072])
    def test_impossible_watermark_fails_before_execution(
            self, tmp_path, monkeypatch, watermark_mb):
        from symtest.core.system_memory import MemorySnapshot

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            lambda: MemorySnapshot(2 * GB, GB, 16 * GB, 16 * GB),
        )
        config = tmp_path / "cases.json"
        _write_config(config, [_sleep_case("never_started", seconds=0, mem_mb=256)])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=2, execution_mode="thread",
            history_dir="hist", memory_physical_watermark_mb=watermark_mb,
        )
        monkeypatch.setattr(
            runner, "run_single_test",
            lambda case: pytest.fail("invalid watermark must prevent execution"),
        )
        with pytest.raises(SystemExit, match="memory_physical_watermark_mb"):
            runner.run_tests()
        from symtest.core.history_store import load_history
        assert not load_history(str(tmp_path / "hist")).get("cases")

    @pytest.mark.parametrize("watermark_mb", [0, 512])
    def test_small_machine_runs_with_valid_watermark(
            self, tmp_path, monkeypatch, watermark_mb):
        from symtest.core.system_memory import MemorySnapshot

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            lambda: MemorySnapshot(2 * GB, GB, 16 * GB, 16 * GB),
        )
        config = tmp_path / "cases.json"
        _write_config(config, [_sleep_case("small", seconds=0, mem_mb=256)])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=2, execution_mode="thread",
            memory_physical_watermark_mb=watermark_mb,
        )
        assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["details"][0]["peak_memory_bytes"] > 0

    def test_peaks_measured_and_recorded(self):
        """启用内存管理（thread + Windows + history）→ 结果与 history 均有峰值。"""
        temp_dir = tempfile.mkdtemp()
        try:
            config_file = os.path.join(temp_dir, "mem_config.json")
            _write_config(config_file, [
                _sleep_case("m0", seconds=0, mem_mb=256),
                _sleep_case("m1", seconds=0, mem_mb=256),
            ])
            runner = ParallelJSONRunner(
                config_file, temp_dir, max_workers=2, execution_mode="thread",
                history_dir="hist",
            )
            assert runner.run_tests()
            for detail in runner.results["details"]:
                assert detail["peak_memory_bytes"] > 0
                assert detail["peak_memory_source"] == "windows_job_commit"

            from symtest.core.history_store import load_history
            hist = load_history(os.path.join(temp_dir, "hist"))
            for name in ("m0", "m1"):
                rec = hist["cases"][name]
                assert rec["max_peak_memory_bytes"] > 0
                assert rec["peak_memory_source"] == "windows_job_commit"
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_memory_management_disabled_without_history_and_declaration(self):
        """无 history 且未声明内存 → 不进入内存管理路径（旧行为）。"""
        temp_dir = tempfile.mkdtemp()
        try:
            config_file = os.path.join(temp_dir, "plain_config.json")
            _write_config(config_file, [
                _sleep_case("p0", seconds=0),
            ])
            runner = ParallelJSONRunner(
                config_file, temp_dir, max_workers=2, execution_mode="thread",
            )
            assert runner.run_tests()
            assert not runner._memory_enabled
            for detail in runner.results["details"]:
                assert "peak_memory_bytes" not in detail
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_memory_admission_caps_concurrency(self, monkeypatch):
        """机会式准入：提交余量不足时第三个任务排队，已运行任务继续。

        快照按「基础余量 − 活动任务估算需求」动态模拟真实系统的提交
        余量消耗。三个 40 GiB 用例、100 GiB 基础余量：前两个可并发
        （40+2 ≤ 100−40），第三个需 42 ≤ 20 不满足 → 等待，前两个
        释放后放行。全部通过，最大并发 ≤ 2。
        """
        from symtest.core.resource_manager import JointResourceManager
        from symtest.core.system_memory import MemorySnapshot

        state = {"demand": 0, "active": 0, "max_active": 0}
        clock = time.perf_counter

        def fake_snapshot():
            return MemorySnapshot(
                total_physical_bytes=100 * GB,
                avail_physical_bytes=100 * GB,
                avail_commit_bytes=100 * GB - state["demand"],
                commit_limit_bytes=100 * GB,
            )

        class TrackingManager(JointResourceManager):
            def acquire(self, *args, **kwargs):
                ticket = super().acquire(*args, **kwargs)
                state["demand"] += ticket.memory_bytes
                state["active"] += 1
                state["max_active"] = max(state["max_active"],
                                           state["active"])
                return ticket

            def release(self, ticket, label=""):
                state["demand"] -= ticket.memory_bytes
                state["active"] -= 1
                super().release(ticket, label)

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.JointResourceManager",
            TrackingManager,
        )

        temp_dir = tempfile.mkdtemp()
        try:
            config_file = os.path.join(temp_dir, "queue_config.json")
            _write_config(config_file, [
                _sleep_case("q0", seconds=2, mem_mb=40 * 1024),
                _sleep_case("q1", seconds=2, mem_mb=40 * 1024),
                _sleep_case("q2", seconds=2, mem_mb=40 * 1024),
            ])
            runner = ParallelJSONRunner(
                config_file, temp_dir, max_workers=3, execution_mode="thread",
                history_dir="hist",
            )
            start = clock()
            assert runner.run_tests()
            elapsed = clock() - start
            assert runner._memory_enabled
            assert runner.results["passed"] == 3
            # 提交余量不足 → 不能 3 个全并发（无重复计账下前两个可并发）
            assert state["max_active"] <= 2, (
                "memory admission failed to cap concurrency: %d concurrent"
                % state["max_active"]
            )
            assert state["max_active"] >= 1
            assert elapsed < 60
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.parametrize("headroom_gb", [80, 1000])
    def test_memory_admission_allows_parallel_when_abundant(self, monkeypatch, headroom_gb):
        """余量充足时不重复计账：三个 40 GiB 任务全部并发（回归防护）。"""
        from symtest.core.resource_manager import JointResourceManager
        from symtest.core.system_memory import MemorySnapshot

        # GitHub Windows runner 只有 4 vCPU（safe_capacity = 4-2 = 2），
        # CPU 令牌不足以支撑 3 并发；固定核数使断言与宿主机无关。
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        fake = MemorySnapshot(
            total_physical_bytes=1000 * GB,
            avail_physical_bytes=1000 * GB,
            avail_commit_bytes=headroom_gb * GB,
            commit_limit_bytes=1000 * GB,
        )
        state = {"active": 0, "max_active": 0, "grants": []}
        clock = time.perf_counter

        class TrackingManager(JointResourceManager):
            def acquire(self, *args, **kwargs):
                ticket = super().acquire(*args, **kwargs)
                state["active"] += 1
                state["max_active"] = max(state["max_active"],
                                           state["active"])
                state["grants"].append(clock())
                return ticket

            def release(self, ticket, label=""):
                state["active"] -= 1
                super().release(ticket, label)

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            lambda: fake,
        )
        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.JointResourceManager",
            TrackingManager,
        )

        temp_dir = tempfile.mkdtemp()
        try:
            config_file = os.path.join(temp_dir, "abundant_config.json")
            _write_config(config_file, [
                # sleep 3s：第三个任务因 1s 启动间隔最早 ~2s 准入，需要
                # 第一个任务（~3s 结束）仍存活才能观察到 3 并发。
                _sleep_case("a0", seconds=3, mem_mb=40 * 1024),
                _sleep_case("a1", seconds=3, mem_mb=40 * 1024),
                _sleep_case("a2", seconds=3, mem_mb=40 * 1024),
            ])
            runner = ParallelJSONRunner(
                config_file, temp_dir, max_workers=3, execution_mode="thread",
                history_dir="hist",
            )
            assert runner.run_tests()
            assert runner._memory_enabled
            assert runner.results["passed"] == 3
            # 旧策略会把 3×40 GiB 预留判为超容量而串行；机会式准入在
            # 余量充足时必须放行并发
            assert state["max_active"] == 3, (
                "admission must not double-count active reservations: "
                "max concurrent = %d" % state["max_active"]
            )
            grants = sorted(state["grants"])
            if headroom_gb == 80:
                # Individual demand fits, overlapping full peaks do not:
                # stagger grants without turning the estimate into a hard cap.
                for earlier, later in zip(grants, grants[1:]):
                    assert later - earlier >= 0.9
            else:
                assert grants[-1] - grants[0] < 0.9
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)




# ---------------------------------------------------------------------------
# Linux memory management (cgroup v2 measurement + joint admission)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "linux", reason="Linux cgroup v2 tests")
class TestLinuxMemoryManagement:
    """Linux 内存准入集成测试：假快照 + 假 cgroup 树驱动全链路。

    假树里 cgroup.procs/memory.peak 是普通文件，由命令自身写
    memory.peak 模拟内核记账；真 cgroupfs 行为由委派环境验收。
    """

    def _fake_snapshot(self, monkeypatch):
        from symtest.core.system_memory import MemorySnapshot

        monkeypatch.setattr(
            "symtest.runners.parallel_config_runner.read_memory_snapshot",
            lambda: MemorySnapshot(16 * GB, 12 * GB, 12 * GB, 16 * GB),
        )

    def _fake_cgroup_tree(self, monkeypatch, tmp_path):
        from symtest.core.execution import linux_cgroup

        root = tmp_path / "cgroup2"
        root.mkdir()
        monkeypatch.setattr(linux_cgroup, "_own_cgroup_dir", lambda: root)
        monkeypatch.setattr(linux_cgroup, "_supported_cache", True)
        monkeypatch.setattr(linux_cgroup, "_CLOSE_RETRY_S", 0.2)
        return root

    def test_admission_and_linux_peak_history_full_chain(
            self, tmp_path, monkeypatch, caplog):
        """准入开启 → 命令进组执行 → 峰值写回 linux 隔离字段。"""
        import logging as _logging

        from symtest.core.history_store import load_history

        root = self._fake_cgroup_tree(monkeypatch, tmp_path)
        self._fake_snapshot(monkeypatch)
        group_dir = root / "symtest-fixed"
        case = {
            "name": "peak-case",
            "execution": {
                "command": sys.executable,
                "args": ["-c",
                         "import os; "
                         "open(os.environ['PEAK_FILE'],'w').write"
                         "('524288000'); print('peak-case')"],
                "env": {"PEAK_FILE": str(group_dir / "memory.peak")},
            },
            "expected": {"return_code": 0,
                         "output_contains": ["peak-case"]},
            "scheduling": {"resources": {"min_memory_mb": 16}},
        }
        from symtest.core.execution import linux_cgroup
        monkeypatch.setattr(linux_cgroup, "_new_group_name",
                            lambda: "symtest-fixed")
        config = tmp_path / "cases.json"
        _write_config(config, [case])
        with caplog.at_level(_logging.INFO):
            runner = ParallelJSONRunner(
                str(config), str(tmp_path), max_workers=2,
                execution_mode="thread", history_dir="hist",
            )
            assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["passed"] == 1
        record = load_history(str(tmp_path / "hist"))["cases"]["peak-case"]
        assert record["max_peak_memory_bytes_linux"] == 524288000
        assert record["last_peak_memory_bytes_linux"] == 524288000
        assert record["peak_memory_count_linux"] == 1
        # 隔离：不写 Windows 平铺字段
        assert "max_peak_memory_bytes" not in record
        assert "peak_memory_source" not in record
        assert "cgroup v2 whole-group peak measurement enabled" in caplog.text

    def test_degraded_without_cgroup_still_admits(
            self, tmp_path, monkeypatch, caplog):
        """无 cgroup 权限：准入仍启用（默认/手动需求），history 无峰值，
        且明确提示无法学习整组峰值。"""
        from symtest.core.execution import linux_cgroup
        from symtest.core.history_store import load_history

        self._fake_snapshot(monkeypatch)
        monkeypatch.setattr(linux_cgroup, "_supported_cache", False)
        config = tmp_path / "cases.json"
        _write_config(config, [_sleep_case("degraded", seconds=0, mem_mb=16)])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=2,
            execution_mode="thread", history_dir="hist",
        )
        assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["passed"] == 1
        assert "cannot learn per-case whole-group memory peaks" in caplog.text
        record = load_history(str(tmp_path / "hist"))["cases"]["degraded"]
        assert "max_peak_memory_bytes_linux" not in record
        assert "max_peak_memory_bytes" not in record

    def test_short_case_batch_has_no_per_case_startup_delay(
            self, tmp_path, monkeypatch):
        """无拥挤风险时连续小任务不引入逐个 1s 启动间隔（对齐 Windows）。"""
        import itertools

        from symtest.core.execution import linux_cgroup

        root = self._fake_cgroup_tree(monkeypatch, tmp_path)
        counter = itertools.count()
        monkeypatch.setattr(linux_cgroup, "_new_group_name",
                            lambda: "symtest-fixed-%d" % next(counter))
        self._fake_snapshot(monkeypatch)
        config = tmp_path / "cases.json"
        _write_config(config, [
            _sleep_case("tiny%d" % i, seconds=0, mem_mb=16)
            for i in range(12)
        ])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=4,
            execution_mode="thread",
        )
        start = time.perf_counter()
        assert runner.run_tests()
        assert runner._memory_enabled
        assert runner.results["passed"] == 12
        assert time.perf_counter() - start < 8

    def test_linux_history_peak_feeds_next_admission(
            self, tmp_path, monkeypatch):
        """写入 history 的 linux 峰值参与下一轮需求估算（× 安全系数）。"""
        from symtest.core.execution import linux_cgroup
        from symtest.core.history_store import (
            LINUX_PEAK_SOURCE, load_history, save_history, update_case_memory,
        )

        self._fake_cgroup_tree(monkeypatch, tmp_path)
        self._fake_snapshot(monkeypatch)
        config = tmp_path / "cases.json"
        _write_config(config, [_sleep_case("reuse", seconds=0)])
        runner = ParallelJSONRunner(
            str(config), str(tmp_path), max_workers=2,
            execution_mode="thread", history_dir="hist",
        )
        hist = load_history(runner.history_dir)
        update_case_memory(hist, "reuse", 10 * GB, LINUX_PEAK_SOURCE)
        save_history(runner.history_dir, hist)

        runner.load_test_cases()
        est = runner._estimate_memory_bytes(runner.test_cases[0])
        assert est == int(10 * GB * runner._memory_margin)
