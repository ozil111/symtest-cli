"""Generic parallel config-driven test runner with injectable config loader.

The only difference between ParallelJSONRunner and ParallelYAMLRunner was the
``load`` call.  This module extracts the common scheduling / resource-management
logic into ``ParallelConfigRunner``, accepting a ``config_loader`` callable.
"""
import sys
import os
import logging
from typing import Optional, Dict, Any, Callable, BinaryIO, List

from ..core.parallel_runner import ParallelRunner, AtomicSemaphore
from ..core.config_loader import parse_test_cases
from ..core.orchestration.sequence import execute_sequence
from ..config.prepared import prepare_config
from ..core.test_case import TestCase
from ..core.orchestration.single import execute_single_test_case
from ..core.resource_manager import JointResourceManager
from ..core.system_memory import read_memory_snapshot
from ..core.types import TestCaseData
from ..utils.path_resolver import PathResolver

logger = logging.getLogger("symtest.runners.parallel_config_runner")

# 用 history 历史最大峰值估算需求时的安全系数（可由 memory_margin 覆盖）
_MEMORY_SAFETY_MARGIN = 1.2
# 提交余量保留（系统还需为其他消费者留出的提交额度）
_DEFAULT_COMMIT_RESERVE_MB = 2048
# 物理内存低水位：低于该值暂停启动新任务（已运行任务继续）
_DEFAULT_PHYSICAL_WATERMARK_MB = 2048
# 需求未知（无显式声明、无历史）case 的默认估算需求
_DEFAULT_MEMORY_DEMAND_MB = 4096
# 最小启动间隔：仅在活动任务峰值可能拥挤时错开启动
_DEFAULT_MIN_START_INTERVAL_S = 1.0


class ParallelConfigRunner(ParallelRunner):
    """Generic parallel test runner with injectable config loader.

    Subclasses inject a ``config_loader`` instead of hardcoding
    ``json.load`` / ``yaml.safe_load``.  All scheduling (CPU-aware semaphore,
    heuristic ordering, proportional core assignment) lives here.
    """

    def __init__(self, config_file: str = "test_cases.json",
                 workspace: Optional[str] = None,
                 max_workers: Optional[int] = None,
                 execution_mode: str = "thread",
                 config_loader: Optional[Callable[[BinaryIO], Dict[str, Any]]] = None,
                 variables: Optional[Dict[str, Any]] = None,
                 **kwargs):
        # Auto-detect physical CPU cores (reserve 2 for OS)
        self.total_physical = os.cpu_count() or 4
        self.safe_capacity = max(1, self.total_physical - 2)

        if max_workers is None:
            max_workers = self.total_physical

        # 机会式内存准入参数（symtest.json run 段配置键透传；CLI 第一版
        # 不提供旗标）。必须在 super().__init__ 之前 pop——BaseRunner 不
        # 接受未知 kwargs；显式 None 同样回退内置默认值。
        def _memory_param(key, default, cast):
            value = kwargs.pop(key, None)
            return cast(default if value is None else value)

        self._memory_margin = _memory_param(
            "memory_margin", _MEMORY_SAFETY_MARGIN, float)
        self._memory_commit_reserve_mb = _memory_param(
            "memory_commit_reserve_mb", _DEFAULT_COMMIT_RESERVE_MB, int)
        self._memory_physical_watermark_mb = _memory_param(
            "memory_physical_watermark_mb", _DEFAULT_PHYSICAL_WATERMARK_MB, int)
        self._memory_default_demand_mb = _memory_param(
            "memory_default_demand_mb", _DEFAULT_MEMORY_DEMAND_MB, int)
        self._memory_min_start_interval_s = _memory_param(
            "memory_min_start_interval_s", _DEFAULT_MIN_START_INTERVAL_S, float)

        super().__init__(config_file, workspace, max_workers,
                         execution_mode, **kwargs)
        self._config_loader = config_loader
        self._variables = variables or {}
        # Backward-compatible attribute for tests that patch path_resolver
        self.path_resolver = PathResolver(self.workspace)

        # Resource pool – only meaningful in thread mode
        self.cpu_semaphore = (
            AtomicSemaphore(self.safe_capacity)
            if execution_mode == "thread" else None
        )

        # Windows 内存管理（测量 + CPU/内存联合准入）；
        # 在 load_test_cases 解析出用例后按条件启用，见
        # ``_setup_memory_management``。未启用时保持原 CPU-only 路径。
        self._memory_enabled = False
        self._memory_history: Dict[str, Any] = {}
        self._resource_manager = None

        logger.info(
            "✅ [Resource Manager] Detected %d CPUs. Pool size set to %d.",
            self.total_physical, self.safe_capacity,
        )

    # ------------------------------------------------------------------
    #  CPU allocation helpers
    # ------------------------------------------------------------------

    def _assign_relative_cpu_cores(self) -> None:
        """Assign ``cpu_cores`` proportionally based on *estimated_time*
        and *min_memory_mb* for cases without an explicit ``cpu_cores``.

        Weight = estimated_time (s) + min_memory_mb / 100.
        """
        candidates = [
            c for c in self.test_cases
            if not (c.resources and "cpu_cores" in c.resources)
        ]
        if not candidates:
            return

        def weight(case: TestCase) -> float:
            res = case.resources or {}
            est = float(res.get("estimated_time") or 0)
            mem = float(res.get("min_memory_mb") or 0)
            return est + mem / 100.0

        weights = [weight(c) for c in candidates]
        total_weight = sum(weights)

        if total_weight <= 0:
            for case in candidates:
                if not case.resources:
                    case.resources = {}
                case.resources["cpu_cores"] = 1
            return

        allocated = 0
        indexed = sorted(
            enumerate(zip(candidates, weights)),
            key=lambda x: x[1][1], reverse=True,
        )
        for rank, (_idx, (case, w)) in enumerate(indexed):
            if rank == len(indexed) - 1:
                share = max(1, self.safe_capacity - allocated)
            else:
                share = max(
                    1, int(round(self.safe_capacity * w / total_weight)),
                )
            if not case.resources:
                case.resources = {}
            case.resources["cpu_cores"] = share
            allocated += share

    # ------------------------------------------------------------------
    #  Topology-constrained LPT sort
    # ------------------------------------------------------------------

    def _topology_lpt_sort(self, get_estimated_time) -> List[TestCase]:
        """Sort cases by LPT (Longest Processing Time first) within DAG constraints.

        Cases are grouped into topological "levels". Within each level,
        cases are sorted by estimated time descending. This preserves
        dependency order while maximizing parallel resource utilization.
        """
        from collections import deque
        from typing import Dict, Set

        cases = self.test_cases
        name_to_case: Dict[str, TestCase] = {c.name: c for c in cases}

        # Compute in-degree
        in_degree: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = {}
        for c in cases:
            deps = [d for d in c.depends_on if d in name_to_case]
            in_degree[c.name] = len(deps)
            for dep in deps:
                dependents.setdefault(dep, []).append(c.name)

        # BFS to compute depth levels
        depth: Dict[str, int] = {}
        queue: deque = deque()
        for c in cases:
            if in_degree[c.name] == 0:
                depth[c.name] = 0
                queue.append(c.name)

        while queue:
            name = queue.popleft()
            for dep_name in dependents.get(name, []):
                new_depth = depth[name] + 1
                if dep_name not in depth or depth[dep_name] < new_depth:
                    depth[dep_name] = new_depth
                    # Only enqueue once all predecessors are processed
                    # (simple max-depth approach is sufficient for sorting)
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    queue.append(dep_name)

        # Fallback: ensure all cases have a depth
        for c in cases:
            if c.name not in depth:
                depth[c.name] = 0

        # Sort: depth ascending, then estimated_time descending within same depth
        result = sorted(
            cases,
            key=lambda c: (depth.get(c.name, 0), -get_estimated_time(c)),
        )
        return result

    # ------------------------------------------------------------------
    #  Test loading (format-agnostic)
    # ------------------------------------------------------------------

    def load_test_cases(self) -> None:
        """Load test cases through the shared config preparation pipeline."""
        if self._config_loader is None:
            raise RuntimeError(
                "config_loader must be set before loading test cases"
            )
        try:
            # Shared pipeline: raw-form schema validation, import expansion,
            # extends resolution, variable application, expanded-form
            # completeness validation and semantic checks (same rules as
            # ``symtest validate``).
            prepared = prepare_config(
                self.config_path,
                workspace=str(self.workspace) if self.workspace else None,
                variables=self._variables,
                file_loader=self._config_loader,
            )
            if not prepared.valid:
                details = "\n  ".join(prepared.errors)
                sys.exit(
                    f"Failed to load configuration file "
                    f"(invalid configuration, {len(prepared.errors)} error(s)):\n"
                    f"  {details}"
                )
            config = prepared.config

            self.load_setup_from_config(config)
            self.test_cases = parse_test_cases(
                config, self.workspace, self.path_resolver,
            )

            logger.info("Successfully loaded %d test cases",
                        len(self.test_cases))

            # Heuristic scheduling: longest-estimated first (topology-aware)
            history_cases: Dict[str, Any] = {}
            if self.test_cases:
                if self.history_dir:
                    from ..core.history_store import load_history
                    hist = load_history(self.history_dir)
                    history_cases = hist.get("cases", {})

                def get_estimated_time(case: TestCase) -> float:
                    if case.name in history_cases:
                        # 兼容"只有内存记录、没有耗时字段"的记录
                        # （内存峰值可在 case 失败时先行记录）。
                        return float(
                            history_cases[case.name].get("avg_duration", 0),
                        )
                    return float(
                        (case.resources or {}).get("estimated_time", 0),
                    )

                logger.info(
                    "Optimizing execution order based on estimated duration...",
                )

                has_deps = any(c.depends_on for c in self.test_cases)
                if has_deps:
                    # Topology-constrained LPT: sort within each "level" of the DAG
                    self.test_cases = self._topology_lpt_sort(get_estimated_time)
                else:
                    self.test_cases.sort(key=get_estimated_time, reverse=True)

                top_case = self.test_cases[0]
                top_est = get_estimated_time(top_case)
                source = (
                    "history" if top_case.name in history_cases else "config"
                )
                logger.info(
                    "Heaviest task: %s (Est: %.2fs, source: %s)",
                    top_case.name, top_est, source,
                )

            self._assign_relative_cpu_cores()

            # Windows 内存管理（测量 + 联合准入）：在用例解析与 history
            # 读取完成后决定是否启用。
            self._setup_memory_management(history_cases)
        except Exception as e:
            sys.exit(f"Failed to load configuration file: {str(e)}")

    # ------------------------------------------------------------------
    #  Windows memory management (measurement + joint admission)
    # ------------------------------------------------------------------

    def _setup_memory_management(self, history_cases: Dict[str, Any]) -> None:
        """按条件启用 Windows 内存管理（测量 + 机会式准入）。

        启用条件（全部满足）：

        - Windows 平台（本轮不实现 Linux cgroup）；
        - thread 模式（process 模式不接入资源调度，行为不变）；
        - 启用了 ``--history-dir`` 或有 case 显式声明 ``min_memory_mb``——
          两者都没有时不进入新的内存管理路径，行为与旧版本完全一致。

        启用后（机会式准入，2026-10-29 方案）：

        - 每个命令经 Job Object 测量进程组提交内存峰值（执行层）；
        - thread 模式经 :class:`JointResourceManager` 做 CPU+内存联合
          准入：提交余量 ≥ 新任务估算需求 + 保留量，物理内存独立
          低水位检查，仅在活动峰值可能拥挤时保持最小启动间隔；不再为运行中任务保留
          完整未来峰值，允许偶发超出内存（不保证零 OOM）；
        - 参数（安全系数 / 提交保留 / 物理水位 / 默认需求 / 启动
          间隔）由 ``symtest.json`` run 段配置键覆盖，默认值见模块
          常量。
        """
        declared_any = any(
            c.resources and "min_memory_mb" in c.resources
            for c in self.test_cases
        )
        self._memory_enabled = (
            os.name == "nt"
            and self.execution_mode == "thread"
            and (self.history_dir is not None or declared_any)
        )
        if not self._memory_enabled:
            return

        snapshot = read_memory_snapshot()
        if not snapshot.usable or not snapshot.total_physical_bytes:
            logger.warning(
                "✅ [Resource Manager] System memory snapshot unavailable; "
                "memory admission disabled (CPU-only scheduling kept).",
            )
            self._memory_enabled = False
            return

        self._memory_history = history_cases or {}
        self._resource_manager = JointResourceManager(
            cpu_capacity=self.safe_capacity,
            # 仅观测记账（活动任务估算需求之和），不参与准入
            memory_capacity_bytes=snapshot.total_physical_bytes,
            snapshot_fn=read_memory_snapshot,
            commit_reserve_bytes=self._memory_commit_reserve_mb * 1024 * 1024,
            physical_watermark_bytes=(
                self._memory_physical_watermark_mb * 1024 * 1024),
            min_start_interval=self._memory_min_start_interval_s,
        )
        logger.info(
            "✅ [Resource Manager] Opportunistic memory admission enabled "
            "(physical %.1f GiB): commit reserve %.1f GiB, physical "
            "watermark %.1f GiB, default demand %.1f GiB, safety margin "
            "%.2f, min startup interval %.1fs.",
            snapshot.total_physical_bytes / 1024 ** 3,
            self._memory_commit_reserve_mb / 1024,
            self._memory_physical_watermark_mb / 1024,
            self._memory_default_demand_mb / 1024,
            self._memory_margin,
            self._memory_min_start_interval_s,
        )

    def _estimate_memory_bytes(self, case: TestCase) -> Optional[int]:
        """估算 case 的内存需求（字节，历史提交峰值口径）。

        优先级：

        1. 显式 ``min_memory_mb``：直接作为需求（用户判断优先）；
        2. history 历史最大峰值 × 安全系数（峰值口径天然只增，
           用最大值避免偶发高峰被平均稀释后再次 OOM）；
        3. 两者皆无 → 可配置默认需求（不再整池独占；首次估算
           不准的风险明确接受，运行后更新历史）。
        """
        resources = case.resources or {}
        declared = resources.get("min_memory_mb")
        if declared:
            return int(float(declared) * 1024 * 1024)
        record = (self._memory_history or {}).get(case.name) or {}
        max_peak = record.get("max_peak_memory_bytes")
        if max_peak:
            return int(max_peak * self._memory_margin)
        return self._memory_default_demand_mb * 1024 * 1024

    # ------------------------------------------------------------------
    #  Execution
    # ------------------------------------------------------------------

    def _run_sequence(self, case: TestCase,
                      measure_memory: bool = False) -> Dict[str, Any]:
        """Run a sequence test case with fail-fast semantics."""
        return execute_sequence(
            case_name=case.name,
            steps=case.steps,
            workspace=str(self.workspace) if self.workspace else None,
            print_prefix="[Worker]",
            case_expected=case.expected if case.expected else None,
            update_baseline=self.update_baseline,
            error_analysis=self.error_analysis,
            resume=self.resume,
            env=case.env,
            case_outputs=case.outputs,
            measure_memory=measure_memory,
        )

    def run_single_test(self, case: TestCase) -> Dict[str, Any]:
        """Thread-safe, resource-aware execution of a single test case.

        In *thread* mode this uses an ``AtomicSemaphore`` to cap concurrent
        CPU core usage and sets ``OMP_NUM_THREADS`` / ``MKL_NUM_THREADS``
        environment variables accordingly.
        """
        # 1. Determine required core count
        required_cores = 1
        if case.resources and "cpu_cores" in case.resources:
            required_cores = case.resources["cpu_cores"]

        if required_cores > self.safe_capacity:
            required_cores = self.safe_capacity

        tokens_acquired = 0
        task_env = None

        # 2. 联合资源池（Windows 内存管理启用时）：CPU + 内存原子准入，
        #    内存不足排队等待（无降级）；估算来源见 _estimate_memory_bytes。
        if self._memory_enabled and self._resource_manager is not None:
            memory_bytes = self._estimate_memory_bytes(case)
            ticket = self._resource_manager.acquire(
                required_cores, memory_bytes, case.name,
            )
            try:
                task_env = {
                    "OMP_NUM_THREADS": str(ticket.cpu),
                    "MKL_NUM_THREADS": str(ticket.cpu),
                    "NPROC": str(ticket.cpu),
                }
                if case.steps:
                    return self._run_sequence(
                        case, measure_memory=True,
                    )
                spec = case.execution
                command_preview = (
                    f"{spec.command} {' '.join(spec.args)}".strip()
                )
                logger.info(
                    "  [Worker] Executing command: %s", command_preview,
                )
                result = execute_single_test_case(
                    spec,
                    str(self.workspace) if self.workspace else None,
                    env=task_env,
                    expectation=case.expected,
                    update_baseline=self.update_baseline,
                    error_analysis=self.error_analysis,
                    measure_memory=True,
                )
                if result["status"] != "passed" and result.get("message"):
                    logger.error(
                        "  [Worker] Error for %s: %s",
                        case.name, result["message"],
                    )
                return result
            finally:
                self._resource_manager.release(ticket, case.name)

        # 3. Acquire resource tokens (thread mode only)
        if self.execution_mode == "thread" and self.cpu_semaphore is not None:
            if not self.cpu_semaphore.acquire(required_cores, timeout=10.0):
                required_cores = 1
                self.cpu_semaphore.acquire(1)
                tokens_acquired = 1
            else:
                tokens_acquired = required_cores

            task_env = {
                "OMP_NUM_THREADS": str(required_cores),
                "MKL_NUM_THREADS": str(required_cores),
                "NPROC": str(required_cores),
            }

            logger.info(
                "  [Scheduler] Task '%s' acquired %d cores. Running...",
                case.name, tokens_acquired,
            )

        # 3. Execute
        if case.steps:
            result = self._run_sequence(case)
        else:
            spec = case.execution

            command_preview = (
                f"{spec.command} {' '.join(spec.args)}".strip()
            )
            if self.execution_mode != "thread" or self.cpu_semaphore is None:
                logger.info(
                    "  [Worker] Executing command: %s", command_preview,
                )

            result = execute_single_test_case(
                spec,
                str(self.workspace) if self.workspace else None,
                env=task_env,
                expectation=case.expected,
                update_baseline=self.update_baseline,
                error_analysis=self.error_analysis,
            )

            if result["output"].strip():
                logger.debug(
                    "  [Worker] Command output for %s:", case.name,
                )
                for line in result["output"].splitlines():
                    logger.debug("    %s", line)

            if result["status"] != "passed" and result.get("message"):
                logger.error(
                    "  [Worker] Error for %s: %s",
                    case.name, result["message"],
                )

        # 4. Release tokens
        if (self.execution_mode == "thread"
                and self.cpu_semaphore is not None
                and tokens_acquired > 0):
            self.cpu_semaphore.release(tokens_acquired)
            logger.info(
                "  [Scheduler] Task '%s' released %d cores.",
                case.name, tokens_acquired,
            )

        return result
