# -*- coding: utf-8 -*-
"""CPU + 内存联合资源池（编排层：何时运行、以什么资源运行）。

策略为**机会式准入**（2026-10-29 确定）：根据历史需求和当前内存压力
决定是否启动新任务，减少并行引起的内存失败；允许偶发超出内存、
分配失败或被 kill，不保证零 OOM。不再为运行中任务保留完整的未来
峰值——已经占用的内存自然体现在系统余量中，未来再次增长导致超额
的风险明确接受。

准入判据（全部满足才授予，任一不满足则排队等待）：

1. **CPU 令牌**充足（``AtomicSemaphore`` 语义不变，纳入同一把锁）；
2. **条件启动间隔**：仅在存在活动任务且活动估算峰值之和 + 新需求
   + 提交保留量超过当前提交余量时，要求距上次授予达到最小间隔。
   这只是保守的错峰信号，不作硬预留；新需求/余量未知时保守错峰；
3. **提交余量** ≥ 新任务估算需求 + ``commit_reserve_bytes``（历史
   提交峰值仅用于提交准入；需求未知或结构性不可满足时跳过该项）；
4. **物理低水位**：可用物理内存 ≥ ``physical_watermark_bytes``
   （独立的压力检查，不与任务需求量挂钩，与提交口径分开建模）。

其余语义：

- **排队而非降级**：内存不足持续等待（CPU 的"超时降级到 1 核"不
  适用于内存——降级启动正是 OOM 失败的来源）；
- **周期重评**：等待者按 ``poll_interval`` 周期唤醒重评系统快照
  （外部进程释放内存不会触发条件变量）；被启动间隔阻塞时按剩余
  间隔唤醒，避免固定轮询周期拉大实际间距；
- **大小任务共存**：大任务等待期间，余量足够的小任务可正常启动
  （按内存需求降序授予，大任务优先，防饥饿）；
- **fail-open**：快照不可用（API 失败/非 Windows）时仅保留 CPU
  令牌与启动间隔约束，告警一次；
- **压力下暂停**：内存压力大时只暂停启动新任务，已运行任务继续
  执行；
- **准入原因记录**：每次拒绝把具体原因（含关键数值）写入
  ``waiter.deny_reason`` 并记入日志，供验收按实际判断路径归因；
- **异常安全**：调用方在 ``finally`` 中 ``release``，票券一次性使用。

本模块不做任何 Win32/进程操作（原则 4）：进程组测量归 execution 层
（``execution/windows_job.py``），系统快照来自 ``system_memory``。

兼容说明：``memory_capacity_bytes`` 与 ``_mem_capacity`` / ``_mem_free``
不作为硬准入预算；活动任务估算需求之和仅用于拥挤风险判断；采集
脚本（memory-probe）据此读取"活动预留"，语义为估算需求而非预算。
"""
import logging
import threading
import time
from typing import Callable, List, Optional

from .system_memory import MemorySnapshot, read_memory_snapshot

logger = logging.getLogger("symtest.core.resource_manager")

# 默认参数（可由 runner / symtest.json 配置覆盖）
_DEFAULT_COMMIT_RESERVE_BYTES = 2 * 1024 ** 3
_DEFAULT_PHYSICAL_WATERMARK_BYTES = 2 * 1024 ** 3
_DEFAULT_MIN_START_INTERVAL = 1.0


class ResourceTicket:
    """一次成功获取的资源份额（opaque，调用方只负责原样归还）。"""

    __slots__ = ("cpu", "memory_bytes")

    def __init__(self, cpu: int, memory_bytes: int):
        self.cpu = cpu
        self.memory_bytes = memory_bytes


class _Waiter:
    """等待联合资源的排队项。"""

    __slots__ = ("cpu", "need_mem", "unknown_demand", "structurally_impossible",
                 "label", "event", "ticket", "logged", "deny_reason",
                 "interval_deadline")

    def __init__(self, cpu: int, need_mem: int, unknown_demand: bool,
                 structurally_impossible: bool, label: str):
        self.cpu = cpu
        self.need_mem = need_mem
        self.unknown_demand = unknown_demand
        self.structurally_impossible = structurally_impossible
        self.label = label
        self.event = threading.Event()
        self.ticket: Optional[ResourceTicket] = None
        self.logged = False
        self.deny_reason = ""
        self.interval_deadline: Optional[float] = None


class JointResourceManager:
    """CPU + 内存联合资源池（仅线程模式使用）。"""

    def __init__(
        self,
        cpu_capacity: int,
        memory_capacity_bytes: Optional[int] = None,
        snapshot_fn: Callable[[], MemorySnapshot] = read_memory_snapshot,
        poll_interval: float = 5.0,
        commit_reserve_bytes: int = _DEFAULT_COMMIT_RESERVE_BYTES,
        physical_watermark_bytes: int = _DEFAULT_PHYSICAL_WATERMARK_BYTES,
        min_start_interval: float = _DEFAULT_MIN_START_INTERVAL,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self._cpu_capacity = max(1, cpu_capacity)
        # 活动估算需求用于启动间隔判断，不作为硬预留（见模块 docstring 兼容说明）
        self._mem_capacity = memory_capacity_bytes or 0
        self._reserved_demand = 0
        self._cpu_free = self._cpu_capacity
        self._snapshot_fn = snapshot_fn
        self._poll_interval = poll_interval
        self._commit_reserve_bytes = max(0, int(commit_reserve_bytes))
        self._physical_watermark_bytes = max(0, int(physical_watermark_bytes))
        self._min_start_interval = max(0.0, float(min_start_interval))
        self._time_fn = time_fn
        self._last_grant_time: Optional[float] = None
        self._lock = threading.Lock()
        self._waiters: List[_Waiter] = []
        self._snapshot_warned = False
        snap = self._snapshot_fn()
        if (snap.total_physical_bytes is not None
                and self._physical_watermark_bytes > 0
                and self._physical_watermark_bytes >= snap.total_physical_bytes):
            raise ValueError(
                "memory_physical_watermark_mb must be less than total physical "
                "memory (set it to 0 to disable the physical watermark)"
            )

    @property
    def _mem_free(self) -> int:
        """观测用：容量减去活动任务估算需求之和（钳制到 ≥ 0）。"""
        return max(0, self._mem_capacity - self._reserved_demand)

    # ------------------------------------------------------------------
    # 获取 / 释放
    # ------------------------------------------------------------------

    def acquire(self, cpu: int, memory_bytes: Optional[int],
                label: str = "") -> ResourceTicket:
        """获取 CPU + 内存准入；不满足时排队等待（无超时降级）。

        :param cpu: 需要的 CPU 令牌数（自动钳制到池容量）。
        :param memory_bytes: 估算内存需求（字节，历史提交峰值口径）；
            ``None`` 表示需求未知——跳过提交余量检查，物理水位与
            启动间隔仍生效。
        :param label: 日志用的任务名。
        """
        cpu = max(1, min(int(cpu), self._cpu_capacity))

        unknown_demand = memory_bytes is None
        need_mem = 0 if unknown_demand else max(0, int(memory_bytes))

        # 结构性不可满足检查：需求加保留量超过系统提交上限时，无论等多久
        # 动态余量都不可能满足（如 pagefile 过小导致 CommitLimit 低于
        # 请求）——警告并跳过提交检查（物理水位与启动间隔仍生效），
        # 交由用例自身的失败暴露问题，而不是永久排队。
        structurally_impossible = False
        if not unknown_demand:
            snap = self._snapshot_fn()
            if (snap.commit_limit_bytes is not None
                    and need_mem + self._commit_reserve_bytes
                    > snap.commit_limit_bytes):
                structurally_impossible = True
                logger.warning(
                    "  [Scheduler] Task '%s' requests %.1f GiB plus %.1f GiB reserve, exceeding "
                    "the system commit limit (%s); commit admission check "
                    "skipped — failure, if any, is left to the case itself.",
                    label, need_mem / 1024 ** 3, self._commit_reserve_bytes / 1024 ** 3,
                    ("%.1f GiB" % (snap.commit_limit_bytes / 1024 ** 3))
                    if snap.commit_limit_bytes else "unknown",
                )

        waiter = _Waiter(cpu, need_mem, unknown_demand,
                         structurally_impossible, label)
        polls = 0
        while True:
            with self._lock:
                ticket = self._try_grant_locked(waiter)
                if ticket is not None:
                    logger.info(
                        "  [Scheduler] Task '%s' admitted: %d cpu + %.1f GiB "
                        "est. demand. Running...",
                        label, ticket.cpu, ticket.memory_bytes / 1024 ** 3,
                    )
                    return ticket
                if not waiter.logged:
                    waiter.logged = True
                    logger.info(
                        "  [Scheduler] Task '%s' waiting (cpu=%d, mem=%.1f "
                        "GiB): %s.",
                        label, waiter.cpu, waiter.need_mem / 1024 ** 3,
                        waiter.deny_reason,
                    )
                    self._waiters.append(waiter)
            # release 唤醒（event set）；超时唤醒用于重评系统内存快照
            # （外部内存释放不触发本池的任何信号）。被启动间隔阻塞时
            # 按剩余间隔唤醒，让实际间距接近配置值。
            timeout = self._poll_interval
            if waiter.interval_deadline is not None:
                timeout = max(0.02, min(
                    timeout, waiter.interval_deadline - self._time_fn()))
            if waiter.event.wait(timeout=timeout):
                assert waiter.ticket is not None
                logger.info(
                    "  [Scheduler] Task '%s' admitted: %d cpu + %.1f GiB "
                    "est. demand. Running...",
                    label, waiter.ticket.cpu,
                    waiter.ticket.memory_bytes / 1024 ** 3,
                )
                return waiter.ticket
            polls += 1
            # 心跳：等待中的任务每 12 个轮询周期（默认 60s）提醒一次，
            # 避免长时间排队静默无感（排队原因是外部内存占用时属正常
            # 行为，由用户决定是否继续等待）。
            if polls % 12 == 0:
                logger.info(
                    "  [Scheduler] Task '%s' still waiting (cpu=%d, "
                    "mem=%.1f GiB, waited ~%ds): %s.",
                    label, waiter.cpu, waiter.need_mem / 1024 ** 3,
                    polls * self._poll_interval, waiter.deny_reason,
                )
            # 超时：循环重试（重评池令牌 + 系统快照 + 启动间隔）

    def release(self, ticket: ResourceTicket, label: str = "") -> None:
        """归还资源并唤醒可满足的等待者。"""
        with self._lock:
            self._cpu_free = min(self._cpu_capacity,
                                 self._cpu_free + ticket.cpu)
            self._reserved_demand = max(0, self._reserved_demand
                                        - ticket.memory_bytes)
            logger.info(
                "  [Scheduler] Task '%s' released %d cpu + %.1f GiB est. "
                "demand.",
                label, ticket.cpu, ticket.memory_bytes / 1024 ** 3,
            )
            self._grant_eligible_locked()

    # ------------------------------------------------------------------
    # 内部：持有锁的授予逻辑
    # ------------------------------------------------------------------

    def _try_grant_locked(self, waiter: _Waiter) -> Optional[ResourceTicket]:
        """尝试给单个 waiter 授予准入；成功则记录并返回票券。

        拒绝时把具体原因（含关键数值）写入 ``waiter.deny_reason``，
        供日志与采集脚本按实际判断路径归因。
        """
        # release() may have granted this waiter just after Event.wait timed
        # out. Consume the existing ticket instead of granting twice.
        if waiter.ticket is not None:
            return waiter.ticket
        waiter.interval_deadline = None

        now = self._time_fn()

        if self._cpu_free < waiter.cpu:
            waiter.deny_reason = (
                "cpu tokens exhausted (%d free < %d needed)"
                % (self._cpu_free, waiter.cpu)
            )
            return None

        snap = self._snapshot_fn()
        if not snap.usable:
            # fail-open：快照不可用（API 失败/非 Windows）时仅保留
            # CPU 令牌与启动间隔约束，告警一次。
            if not self._snapshot_warned:
                self._snapshot_warned = True
                logger.warning(
                    "  [Scheduler] System memory snapshot unavailable; "
                    "memory admission check disabled (cpu tokens + "
                    "startup interval only).",
                )
        else:
            # 提交口径准入：历史提交峰值只用于提交余量检查；需求未知
            # 或结构性不可满足时跳过（等待无意义）。
            if not waiter.unknown_demand and not waiter.structurally_impossible:
                required = waiter.need_mem + self._commit_reserve_bytes
                if (snap.avail_commit_bytes is not None
                        and snap.avail_commit_bytes < required):
                    waiter.deny_reason = (
                        "commit margin short: need %.1f GiB + reserve "
                        "%.1f GiB > available %.1f GiB"
                        % (waiter.need_mem / 1024 ** 3,
                           self._commit_reserve_bytes / 1024 ** 3,
                           snap.avail_commit_bytes / 1024 ** 3)
                    )
                    return None
            # 物理口径：独立低水位检查，不与任务需求量挂钩。
            if (snap.avail_physical_bytes is not None
                    and snap.avail_physical_bytes
                    < self._physical_watermark_bytes):
                waiter.deny_reason = (
                    "available physical memory %.1f GiB below watermark "
                    "%.1f GiB"
                    % (snap.avail_physical_bytes / 1024 ** 3,
                       self._physical_watermark_bytes / 1024 ** 3)
                )
                return None

        # Full active peaks are a conservative spacing signal, never a hard
        # reservation: current allocations are already reflected in headroom.
        # Missing demand/headroom retains spacing while tasks are active.
        crowding_risk = self._cpu_free < self._cpu_capacity and (
            not snap.usable or snap.avail_commit_bytes is None
            or waiter.unknown_demand
            or self._reserved_demand + waiter.need_mem
            + self._commit_reserve_bytes > snap.avail_commit_bytes
        )
        if (crowding_risk and self._min_start_interval > 0
                and self._last_grant_time is not None
                and now - self._last_grant_time < self._min_start_interval):
            waiter.interval_deadline = (self._last_grant_time
                                        + self._min_start_interval)
            waiter.deny_reason = (
                "peak crowding risk: minimum startup interval %.1fs not elapsed since last "
                "admission" % self._min_start_interval
            )
            return None

        # 授予
        self._cpu_free -= waiter.cpu
        self._reserved_demand += waiter.need_mem
        self._last_grant_time = now
        waiter.ticket = ResourceTicket(waiter.cpu, waiter.need_mem)
        if waiter in self._waiters:
            self._waiters.remove(waiter)
        return waiter.ticket

    def _grant_eligible_locked(self) -> None:
        """唤醒所有当前可满足的等待者（内存需求降序，大任务优先）。"""
        if not self._waiters:
            return
        for waiter in sorted(self._waiters, key=lambda w: -w.need_mem):
            ticket = self._try_grant_locked(waiter)
            if ticket is not None:
                waiter.event.set()
