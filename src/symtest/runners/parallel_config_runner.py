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
from ..core.config_loader import parse_test_cases, execute_sequence
from ..config.inheritance_expander import resolve_inheritance, apply_variables
from ..core.test_case import TestCase
from ..core.execution import execute_single_test_case
from ..core.types import TestCaseData
from ..utils.path_resolver import PathResolver
from ..config.import_expander import expand_imports

logger = logging.getLogger("symtest.runners.parallel_config_runner")


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
        """Load test cases from config file using the injected loader."""
        if self._config_loader is None:
            raise RuntimeError(
                "config_loader must be set before loading test cases"
            )
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = self._config_loader(f)

            # Expand import references (no-op if none present)
            config = expand_imports(config, self.config_path)
            # Resolve extends inheritance (no-op if none present)
            config = resolve_inheritance(config)
            # Per-case + global variable substitution
            config = apply_variables(config, self._variables)

            self.load_setup_from_config(config)
            self.test_cases = parse_test_cases(
                config, self.workspace, self.path_resolver,
            )

            logger.info("Successfully loaded %d test cases",
                        len(self.test_cases))

            # Heuristic scheduling: longest-estimated first (topology-aware)
            if self.test_cases:
                history_cases: Dict[str, Any] = {}
                if self.history_dir:
                    from ..core.history_store import load_history
                    hist = load_history(self.history_dir)
                    history_cases = hist.get("cases", {})

                def get_estimated_time(case: TestCase) -> float:
                    if case.name in history_cases:
                        return float(
                            history_cases[case.name]["avg_duration"],
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
        except Exception as e:
            sys.exit(f"Failed to load configuration file: {str(e)}")

    # ------------------------------------------------------------------
    #  Execution
    # ------------------------------------------------------------------

    def _run_sequence(self, case: TestCase) -> Dict[str, Any]:
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

        # 2. Acquire resource tokens (thread mode only)
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
            case_data = case.to_execution_dict()

            command_preview = (
                f"{case_data['command']} {' '.join(case_data['args'])}".strip()
            )
            if self.execution_mode != "thread" or self.cpu_semaphore is None:
                logger.info(
                    "  [Worker] Executing command: %s", command_preview,
                )

            result = execute_single_test_case(
                case_data,
                str(self.workspace) if self.workspace else None,
                env=task_env,
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
