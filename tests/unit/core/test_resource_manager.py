# -*- coding: utf-8 -*-
"""Tests for the CPU+memory joint resource manager (opportunistic admission).

All admission logic is exercised with injected fake memory snapshots so the
behaviour is deterministic regardless of the host's actual memory state.

策略要点（2026-10-29 机会式准入）：

- 不为运行中任务保留完整未来峰值（无重复计账）：系统余量只需覆盖
  新任务自身需求 + 保留量；
- 提交余量与物理低水位分别检查、口径不混用；
- 最小启动间隔错开授予；
- 需求未知或结构性不可满足时跳过提交检查（不再整池独占）。
"""
import threading
import time

import pytest

from symtest.core.resource_manager import JointResourceManager
from symtest.core.system_memory import MemorySnapshot


class FakeSnapshotSource:
    """可变快照源：测试中动态修改系统余量。"""

    def __init__(self, avail_physical, commit_limit=None, avail_commit=None,
                 total_physical=None):
        self.avail_physical = avail_physical
        self.commit_limit = commit_limit
        self.avail_commit = avail_commit
        if total_physical is not None:
            self.total_physical = total_physical
        elif avail_physical is not None:
            self.total_physical = max(
                avail_physical, commit_limit or 0) + 8 * 1024 ** 3
        else:
            self.total_physical = None

    def __call__(self) -> MemorySnapshot:
        return MemorySnapshot(
            total_physical_bytes=self.total_physical,
            avail_physical_bytes=self.avail_physical,
            avail_commit_bytes=self.avail_commit
            if self.avail_commit is not None else self.avail_physical,
            commit_limit_bytes=self.commit_limit,
        )


GB = 1024 ** 3
MB = 1024 ** 2

# 与 runner 默认一致的可观测默认参数
COMMIT_RESERVE = 2 * GB
PHYSICAL_WATERMARK = 2 * GB


def make_manager(cpu_capacity=4, snapshot=None, poll=0.05,
                 commit_reserve=COMMIT_RESERVE,
                 physical_watermark=PHYSICAL_WATERMARK,
                 min_start_interval=0.0, memory_capacity=16 * GB):
    source = snapshot or FakeSnapshotSource(
        avail_physical=64 * GB, commit_limit=64 * GB,
    )
    return JointResourceManager(
        cpu_capacity=cpu_capacity,
        memory_capacity_bytes=memory_capacity,
        snapshot_fn=source,
        poll_interval=poll,
        commit_reserve_bytes=commit_reserve,
        physical_watermark_bytes=physical_watermark,
        min_start_interval=min_start_interval,
    ), source


class TestBasicAcquireRelease:
    def test_acquire_grants_when_resources_free(self):
        mgr, _ = make_manager()
        ticket = mgr.acquire(cpu=2, memory_bytes=4 * GB, label="t1")
        assert ticket.cpu == 2
        assert ticket.memory_bytes == 4 * GB
        mgr.release(ticket, "t1")

    def test_release_restores_cpu_tokens(self):
        mgr, _ = make_manager(cpu_capacity=4)
        t1 = mgr.acquire(cpu=4, memory_bytes=10 * GB)
        got = threading.Event()
        ticket_holder = {}

        def waiter():
            ticket_holder["t"] = mgr.acquire(cpu=1, memory_bytes=1 * GB)
            got.set()

        th = threading.Thread(target=waiter, daemon=True)
        th.start()
        time.sleep(0.3)
        assert not got.is_set(), "should still be blocked while cpu pool is full"
        mgr.release(t1)
        assert got.wait(timeout=5)
        mgr.release(ticket_holder["t"])

    def test_cpu_tokens_are_part_of_joint_admission(self):
        mgr, _ = make_manager(cpu_capacity=4)
        t1 = mgr.acquire(cpu=3, memory_bytes=1 * GB)
        got = threading.Event()
        holder = {}

        def waiter():
            holder["t"] = mgr.acquire(cpu=2, memory_bytes=1 * GB)
            got.set()

        th = threading.Thread(target=waiter, daemon=True)
        th.start()
        time.sleep(0.3)
        assert not got.is_set(), "CPU shortage must block joint admission"
        mgr.release(t1)
        assert got.wait(timeout=5)
        mgr.release(holder["t"])

    def test_observation_bookkeeping_tracks_active_demand(self):
        """_mem_capacity/_mem_free 仅观测记账，不参与准入。"""
        mgr, _ = make_manager(memory_capacity=16 * GB)
        assert mgr._mem_free == 16 * GB
        t1 = mgr.acquire(cpu=1, memory_bytes=6 * GB)
        assert mgr._mem_free == 10 * GB
        mgr.release(t1)
        assert mgr._mem_free == 16 * GB


class TestOpportunisticAdmission:
    def test_no_double_counting_allows_parallel_big_tasks(self):
        """机会式准入核心：两个 6 GiB 任务在 10 GiB 余量下可同时运行。

        旧策略要求系统余量覆盖「运行中任务的完整预留 + 新请求」
        （6+6=12 > 10 被拒）；新策略只检查新任务自身需求 + 保留量，
        已占用内存由系统余量自然体现，不重复计账。
        """
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=10 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        t1 = mgr.acquire(cpu=1, memory_bytes=6 * GB)
        # 6 + 2 reserve = 8 ≤ 10：第二个 6 GiB 任务在第一个运行时仍可启动
        t2 = mgr.acquire(cpu=1, memory_bytes=6 * GB)
        assert t2.memory_bytes == 6 * GB
        mgr.release(t1)
        mgr.release(t2)

    def test_commit_margin_blocks_admission(self):
        """提交余量不足（需求 + 保留量 > 余量）要拦截。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=7 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        got = threading.Event()

        def waiter():
            mgr.acquire(cpu=1, memory_bytes=6 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.4)
        assert not got.is_set(), "commit margin shortage must block"
        # 6 + 2 = 8 ≤ 9 → 放行
        source.avail_commit = 9 * GB
        assert got.wait(timeout=5)

    def test_physical_watermark_is_independent_of_demand(self):
        """物理低水位独立检查：需求很小但物理可用低于水位也要拦截。"""
        source = FakeSnapshotSource(
            avail_physical=1 * GB, avail_commit=64 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source, physical_watermark=2 * GB)
        got = threading.Event()

        def waiter():
            mgr.acquire(cpu=1, memory_bytes=256 * MB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.4)
        assert not got.is_set(), "physical watermark breach must block"
        source.avail_physical = 5 * GB
        assert got.wait(timeout=5)

    def test_physical_high_does_not_excuse_commit_shortage(self):
        """口径不混用：物理充足不能豁免提交余量不足。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=2 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source)
        got = threading.Event()

        def waiter():
            mgr.acquire(cpu=1, memory_bytes=6 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.4)
        assert not got.is_set()
        source.avail_commit = 20 * GB
        assert got.wait(timeout=5)

    def test_pressure_pauses_new_tasks_but_running_tasks_continue(self):
        """内存压力大时暂停启动新任务；已运行任务不受影响（无独占回收）。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=64 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source)
        t1 = mgr.acquire(cpu=1, memory_bytes=6 * GB)
        # 外部内存压力上升
        source.avail_commit = 1 * GB
        got = threading.Event()

        def waiter():
            mgr.acquire(cpu=1, memory_bytes=1 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.3)
        assert not got.is_set(), "memory pressure must pause new admissions"
        mgr.release(t1)  # 释放不改变外部压力，仍应等待
        time.sleep(0.2)
        assert not got.is_set()
        source.avail_commit = 64 * GB
        assert got.wait(timeout=5)

    def test_deny_reason_records_actual_judgement_path(self):
        """拒绝原因来自实际判断路径，含关键数值。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=7 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        got = threading.Event()
        holder = {}

        def waiter():
            holder["t"] = mgr.acquire(cpu=1, memory_bytes=6 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.4)
        with mgr._lock:
            reasons = [w.deny_reason for w in mgr._waiters]
        assert reasons and "commit margin" in reasons[0]
        source.avail_commit = 20 * GB
        assert got.wait(timeout=5)


class TestMinStartInterval:
    def test_second_grant_waits_for_interval(self):
        """授予间保持最小启动间隔（错开启动）。"""
        mgr, _ = make_manager(min_start_interval=0.5)
        t1 = mgr.acquire(cpu=1, memory_bytes=1 * GB)
        got = threading.Event()
        holder = {}

        def waiter():
            holder["t"] = mgr.acquire(cpu=1, memory_bytes=1 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        start = time.monotonic()
        assert got.wait(timeout=5), "interval-blocked waiter must wake after interval"
        elapsed = time.monotonic() - start
        assert elapsed >= 0.4, (
            "second grant must respect the minimum startup interval "
            "(got %.2fs)" % elapsed
        )
        mgr.release(t1)
        mgr.release(holder["t"])

    def test_zero_interval_disables_spacing(self):
        mgr, _ = make_manager(min_start_interval=0.0)
        t1 = mgr.acquire(cpu=1, memory_bytes=1 * GB)
        t2 = mgr.acquire(cpu=1, memory_bytes=1 * GB)
        mgr.release(t1)
        mgr.release(t2)


class TestUnknownAndImpossibleDemand:
    def test_demand_plus_reserve_exceeds_commit_limit(self, caplog):
        source = FakeSnapshotSource(
            avail_physical=12 * GB, avail_commit=8 * GB, commit_limit=8 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        ticket = mgr.acquire(cpu=1, memory_bytes=7 * GB, label="reserve")
        assert ticket.memory_bytes == 7 * GB
        assert "plus 2.0 GiB reserve" in caplog.text
        mgr.release(ticket)

    @pytest.mark.parametrize("watermark", [2 * GB, 3 * GB])
    def test_impossible_physical_watermark_rejected(self, watermark):
        source = FakeSnapshotSource(avail_physical=GB, total_physical=2 * GB)
        with pytest.raises(ValueError, match="memory_physical_watermark_mb"):
            make_manager(snapshot=source, physical_watermark=watermark)

    def test_zero_watermark_allowed_on_small_machine(self):
        source = FakeSnapshotSource(avail_physical=GB, total_physical=2 * GB)
        mgr, _ = make_manager(snapshot=source, physical_watermark=0,
                              commit_reserve=0)
        ticket = mgr.acquire(1, GB)
        mgr.release(ticket)

    def test_unknown_demand_skips_commit_check(self):
        """需求未知（None）→ 跳过提交检查（不再整池独占等待）。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=3 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source)
        t1 = mgr.acquire(cpu=1, memory_bytes=256 * MB)
        # 需求未知：即使提交余量 3 GiB 不足以覆盖 4 GiB + 保留量，
        # 也应立即放行（跳过提交检查；物理水位仍生效）
        t2 = mgr.acquire(cpu=1, memory_bytes=None)
        assert t2.memory_bytes == 0
        mgr.release(t1)
        mgr.release(t2)

    def test_structurally_impossible_skips_commit_check(self):
        """需求超过系统提交上限 → 结构性不可满足 → 跳过提交检查放行。"""
        source = FakeSnapshotSource(
            avail_physical=5 * GB, commit_limit=8 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        # 需求 9 GiB > 提交上限 8 GiB：等待无意义 → 放行
        ticket = mgr.acquire(cpu=1, memory_bytes=9 * GB, label="impossible")
        assert ticket.memory_bytes == 9 * GB
        mgr.release(ticket)

    def test_structurally_impossible_still_respects_watermark(self):
        """结构性不可满足只豁免提交检查；物理水位仍生效。"""
        source = FakeSnapshotSource(
            avail_physical=1 * GB, commit_limit=8 * GB,
        )
        mgr, _ = make_manager(snapshot=source, physical_watermark=2 * GB)
        got = threading.Event()

        def waiter():
            mgr.acquire(cpu=1, memory_bytes=9 * GB)
            got.set()

        threading.Thread(target=waiter, daemon=True).start()
        time.sleep(0.3)
        assert not got.is_set(), "physical watermark must still apply"
        source.avail_physical = 5 * GB
        assert got.wait(timeout=5)


class TestSnapshotRobustness:
    def test_snapshot_unusable_fails_open(self):
        """快照不可用 → fail-open（仅 CPU 令牌 + 启动间隔），不能永久阻塞。"""
        source = FakeSnapshotSource(avail_physical=None)
        mgr, _ = make_manager(snapshot=source)
        ticket = mgr.acquire(cpu=1, memory_bytes=6 * GB)
        assert ticket.memory_bytes == 6 * GB
        mgr.release(ticket)

    def test_small_task_runs_while_big_task_waits(self):
        """大任务等待提交余量期间，余量足够的小任务可正常启动。"""
        source = FakeSnapshotSource(
            avail_physical=64 * GB, avail_commit=5 * GB, commit_limit=64 * GB,
        )
        mgr, _ = make_manager(snapshot=source, commit_reserve=2 * GB)
        t1 = mgr.acquire(cpu=1, memory_bytes=256 * MB)
        big_got = threading.Event()
        small_got = threading.Event()
        holder = {}

        def big_waiter():
            holder["big"] = mgr.acquire(cpu=1, memory_bytes=6 * GB)
            big_got.set()

        def small_waiter():
            holder["small"] = mgr.acquire(cpu=1, memory_bytes=2 * GB)
            small_got.set()

        threading.Thread(target=big_waiter, daemon=True).start()
        time.sleep(0.2)
        threading.Thread(target=small_waiter, daemon=True).start()
        # 大任务需 6+2=8 > 余量 5：排队；小任务需 2+2=4 ≤ 5：可运行
        assert small_got.wait(timeout=5)
        assert not big_got.is_set()
        # 外部内存释放（系统快照变化）后大任务放行
        source.avail_commit = 20 * GB
        assert big_got.wait(timeout=5)
        mgr.release(t1)
        mgr.release(holder["small"])
        mgr.release(holder["big"])


class TestExceptionSafety:
    def test_timeout_racing_with_release_grants_waiter_only_once(self, monkeypatch):
        source = FakeSnapshotSource(avail_physical=300)
        mgr, _ = make_manager(cpu_capacity=3, memory_capacity=300,
                              commit_reserve=0, physical_watermark=0,
                              snapshot=source)
        held = mgr.acquire(1, 100)
        source.avail_physical = 0

        class TimeoutRaceEvent:
            def set(self):
                pass

            def wait(self, timeout):
                # Simulate release granting the ticket after wait timed out,
                # before acquire has reacquired the manager lock.
                source.avail_physical = 1000
                mgr.release(held)
                return False

        monkeypatch.setattr(threading, "Event", TimeoutRaceEvent)
        ticket = mgr.acquire(1, 100)
        assert (mgr._cpu_free, mgr._mem_free) == (2, 200)
        mgr.release(ticket)
        assert (mgr._cpu_free, mgr._mem_free) == (3, 300)

    def test_release_in_finally_pattern_survives_execution_error(self):
        """调用方 try/finally 模式：执行异常后释放，CPU 池不泄漏。"""
        mgr, _ = make_manager(cpu_capacity=2)
        ticket = mgr.acquire(cpu=2, memory_bytes=1 * GB)
        try:
            raise RuntimeError("case execution failed")
        except RuntimeError:
            pass
        finally:
            mgr.release(ticket)
        t2 = mgr.acquire(cpu=2, memory_bytes=1 * GB)
        mgr.release(t2)
