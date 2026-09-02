from abc import ABC
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed, Future
from typing import List, Dict, Any, Optional, Union, Set
from collections import deque
import time
import threading
import logging
from .base_runner import BaseRunner
from .test_case import TestCase
from .process_worker import run_test_in_process

logger = logging.getLogger("symtest.core.parallel_runner")


class AtomicSemaphore:
    """
    支持原子级多令牌获取的信号量，消除逐个 acquire 导致的部分占有死锁。

    与 threading.Semaphore 不同：acquire(n) 在所有 n 个令牌可用时一次性获取，
    否则等待（支持超时），不会出现"拿了3个等1个，另一个线程也拿了3个等1个"的死锁。

    唤醒策略：按请求令牌数降序优先唤醒，避免大核数任务被小任务持续抢占导致饥饿。
    """

    def __init__(self, value: int):
        self._value = value
        self._lock = threading.Lock()
        self._waiters: list = []  # list of (required_n, threading.Event)

    def _grant_tokens(self) -> None:
        """Grant tokens to eligible waiters, largest request first (anti-starvation)."""
        if not self._waiters:
            return
        # Sort by required_n descending so large-core requests get priority
        self._waiters.sort(key=lambda x: -x[0])
        granted: list = []
        remaining: list = []
        for n, event in self._waiters:
            if self._value >= n:
                self._value -= n
                granted.append(event)
            else:
                remaining.append((n, event))
        self._waiters = remaining
        for event in granted:
            event.set()

    def acquire(self, n: int = 1, timeout: Optional[float] = None) -> bool:
        """Atomically acquire n tokens. Returns True on success, False on timeout."""
        event = threading.Event()
        with self._lock:
            # Fast path: enough tokens and no pending waiters
            if self._value >= n and not self._waiters:
                self._value -= n
                return True
            self._waiters.append((n, event))
            self._grant_tokens()

        if not event.wait(timeout=timeout):
            # Timeout cleanup – guard against race where release granted
            # tokens between event.wait() returning and lock acquisition
            with self._lock:
                if event.is_set():
                    return True
                for i, (_, e) in enumerate(self._waiters):
                    if e is event:
                        del self._waiters[i]
                        self._grant_tokens()
                        break
            return False
        return True

    def release(self, n: int = 1) -> None:
        """Release n tokens, waking eligible waiters with anti-starvation priority."""
        with self._lock:
            self._value += n
            self._grant_tokens()

class ParallelRunner(BaseRunner):
    """并行测试运行器基类，支持多线程和多进程执行"""
    
    def __init__(self, config_file: str, workspace: Optional[str] = None, 
                 max_workers: Optional[int] = None, 
                 execution_mode: str = "thread",
                 error_analysis: bool = False,
                 **kwargs):
        """
        初始化并行运行器
        
        Args:
            config_file: 配置文件路径
            workspace: 工作目录
            max_workers: 最大并发数，默认为CPU核心数
            execution_mode: 执行模式，'thread'(线程) 或 'process'(进程)
            **kwargs: 透传给 BaseRunner 的额外参数
                (test_case_filter, test_case_tag_filter, history_dir, regression_threshold)
        """
        error_analysis_all = kwargs.get('error_analysis_all', False)
        super().__init__(config_file, workspace, **kwargs)
        self.max_workers = max_workers
        self.execution_mode = execution_mode
        self.error_analysis = error_analysis or error_analysis_all
        self.lock = threading.Lock()  # 用于线程安全的结果更新
        
    def run_tests(self) -> bool:
        """并行运行所有测试用例（DAG 依赖调度）"""
        try:
            self.load_test_cases()
            self._apply_test_case_filter()
            self.results["total"] = len(self.test_cases)
            
            if self.results["total"] == 0:
                logger.warning("No test cases to run.")
                return False
            
            # 执行setup任务
            self.setup_manager.setup_all()
            
            # ── Build dependency graph ──
            has_deps = any(case.depends_on for case in self.test_cases)
            
            if not has_deps:
                # Fast path: no dependencies, use original flat submission
                return self._run_tests_flat()
            
            logger.info("Starting DAG-scheduled parallel execution... Total tests: %d", self.results["total"])
            logger.info("Execution mode: %s, Max workers: %s", self.execution_mode, self.max_workers or "auto")
            logger.info("=" * 50)
            
            start_time = time.time()
            
            if self.execution_mode == "process":
                executor_class = ProcessPoolExecutor
            else:
                executor_class = ThreadPoolExecutor
            
            with executor_class(max_workers=self.max_workers) as executor:
                self._run_dag(executor)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            logger.info("=" * 50)
            logger.info(
                "Parallel test execution completed in %.2f seconds", execution_time,
            )
            skipped = sum(1 for d in self.results["details"] if d["status"] == "skipped")
            logger.info(
                "Passed: %d, Failed: %d, XFailed: %d, XPassed: %d, Skipped: %d",
                self.results["passed"], self.results["failed"],
                self.results["xfailed"], self.results["xpassed"], skipped,
            )

            # Update history & regression detection
            self._update_history()

            # Save last-run state for --last-failed
            self._save_last_run()

            # Exit-code rule: failed + xpassed > 0 → non-zero
            return self.results["failed"] == 0 and self.results["xpassed"] == 0
        finally:
            # 确保teardown总是被执行
            self.setup_manager.teardown_all()
    
    def _run_tests_flat(self) -> bool:
        """Original flat submission (no depends_on), kept for backward compat."""
        logger.info("Starting parallel test execution... Total tests: %d", self.results["total"])
        logger.info("Execution mode: %s, Max workers: %s", self.execution_mode, self.max_workers or "auto")
        logger.info("=" * 50)
        
        start_time = time.time()
        
        if self.execution_mode == "process":
            executor_class = ProcessPoolExecutor
        else:
            executor_class = ThreadPoolExecutor
            
        with executor_class(max_workers=self.max_workers) as executor:
            # 提交所有测试任务
            if self.execution_mode == "process":
                # 进程模式：使用独立的工作器函数
                future_to_case = {
                    executor.submit(
                        run_test_in_process, 
                        i, 
                        {
                            "name": case.name,
                            "command": case.command,
                            "args": case.args,
                            "expected": case.expected,
                            "timeout": case.timeout,
                            "resources": case.resources,
                            "retry_count": case.retry_count,
                            "steps": [
                                {
                                    "command": s.command,
                                    "args": s.args,
                                    "expected": s.expected,
                                    "timeout": s.timeout,
                                    "retry_count": s.retry_count,
                                }
                                for s in case.steps
                            ] if case.steps else None,
                        },
                        str(self.workspace) if self.workspace else None,
                        update_baseline=self.update_baseline,
                        error_analysis=self.error_analysis,
                        resume=self.resume,
                    ): (i, case) 
                    for i, case in enumerate(self.test_cases, 1)
                }
            else:
                # 线程模式：使用实例方法
                future_to_case = {
                    executor.submit(self._run_test_with_index, i, case): (i, case) 
                    for i, case in enumerate(self.test_cases, 1)
                }
            
            # 收集结果
            for future in as_completed(future_to_case):
                test_index, case = future_to_case[future]
                try:
                    result = future.result()
                    self._update_results(result, test_index, case)
                except Exception as exc:
                    error_result = {
                        "name": case.name,
                        "status": "failed",
                        "message": f"Test execution failed: {str(exc)}",
                        "output": "",
                        "command": "",
                        "return_code": None
                    }
                    self._update_results(error_result, test_index, case)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        logger.info("=" * 50)
        logger.info(
            "Parallel test execution completed in %.2f seconds", execution_time,
        )
        logger.info(
            "Passed: %d, Failed: %d, XFailed: %d, XPassed: %d",
            self.results["passed"], self.results["failed"],
            self.results["xfailed"], self.results["xpassed"],
        )

        # Update history & regression detection
        self._update_history()

        # Save last-run state for --last-failed
        self._save_last_run()

        # Exit-code rule: failed + xpassed > 0 → non-zero
        return self.results["failed"] == 0 and self.results["xpassed"] == 0

    def _run_dag(self, executor) -> None:
        """DAG-scheduled execution: Kahn topology + ready queue with completion callbacks."""
        cases = self.test_cases
        name_to_case: Dict[str, TestCase] = {c.name: c for c in cases}
        name_to_index: Dict[str, int] = {c.name: i for i, c in enumerate(cases, 1)}

        # Build adjacency: dependents[dep] = [cases that depend on dep]
        dependents: Dict[str, List[str]] = {}
        for c in cases:
            for dep in c.depends_on:
                if dep in name_to_case:
                    dependents.setdefault(dep, []).append(c.name)

        # in-degree: how many unfinished dependencies each case has
        in_degree: Dict[str, int] = {}
        for c in cases:
            deps = [d for d in c.depends_on if d in name_to_case]
            in_degree[c.name] = len(deps)

        # Track: processed case names (result recorded) and dep status
        processed: Set[str] = set()
        dep_results: Dict[str, bool] = {}  # True = dep satisfied

        # Active futures
        active_futures: Dict[Future, TestCase] = {}
        total = len(cases)

        def _submit(case: TestCase) -> None:
            idx = name_to_index.get(case.name, 0)
            if self.execution_mode == "process":
                future = executor.submit(
                    run_test_in_process,
                    idx,
                    {
                        "name": case.name,
                        "command": case.command,
                        "args": case.args,
                        "expected": case.expected,
                        "timeout": case.timeout,
                        "resources": case.resources,
                        "retry_count": case.retry_count,
                        "steps": [
                            {
                                "command": s.command,
                                "args": s.args,
                                "expected": s.expected,
                                "timeout": s.timeout,
                                "retry_count": s.retry_count,
                            }
                            for s in case.steps
                        ] if case.steps else None,
                    },
                    str(self.workspace) if self.workspace else None,
                    update_baseline=self.update_baseline,
                    error_analysis=self.error_analysis,
                    resume=self.resume,
                )
            else:
                future = executor.submit(self._run_test_with_index, idx, case)
            active_futures[future] = case

        def _on_case_completed(case: TestCase, result: Dict[str, Any]) -> None:
            """Process one completed case: record result, notify dependents, cascade skips."""
            processed.add(case.name)

            self._update_results(result, name_to_index.get(case.name, 0), case)

            effective_status = result["status"]
            dep_satisfied = effective_status in ("passed", "xfailed")
            dep_results[case.name] = dep_satisfied

            if not dep_satisfied:
                # Cascade skip to all direct dependents
                for dep_name in dependents.get(case.name, []):
                    if dep_name not in processed:
                        _cascade_skip(dep_name, case.name)
                return

            # Satisfied: decrement in-degree for each dependent
            for dep_name in dependents.get(case.name, []):
                if dep_name in processed:
                    continue
                dep_case = name_to_case[dep_name]
                in_degree[dep_name] -= 1
                if in_degree[dep_name] <= 0:
                    # Verify ALL dependencies are satisfied
                    all_satisfied = all(
                        dep_results.get(d, False)
                        for d in dep_case.depends_on
                        if d in name_to_case
                    )
                    if all_satisfied:
                        _submit(dep_case)

        def _cascade_skip(case_name: str, failed_by: str) -> None:
            """BFS cascade: mark case_name and all transitive dependents as skipped."""
            queue: deque = deque([case_name])
            while queue:
                current = queue.popleft()
                if current in processed:
                    continue
                processed.add(current)

                case = name_to_case.get(current)
                idx = name_to_index.get(current, 0)

                skip_result = {
                    "name": current,
                    "status": "skipped",
                    "message": f"Skipped: dependency '{failed_by}' failed",
                    "output": "",
                    "command": _case_command_str(case),
                    "return_code": None,
                    "duration": 0,
                }
                self._update_results_skipped(skip_result, idx, current)

                for dep_name in dependents.get(current, []):
                    if dep_name not in processed:
                        queue.append(dep_name)

        def _case_command_str(case: Optional[TestCase]) -> str:
            if case is None:
                return ""
            if case.command:
                return case.command
            if case.steps:
                return " -> ".join(
                    f"{s.command} {' '.join(s.args)}".strip()
                    for s in case.steps
                )
            return ""

        # Submit all cases with zero in-degree
        for c in cases:
            if in_degree[c.name] == 0:
                _submit(c)

        # Main loop: process futures one at a time
        while len(processed) < total:
            if not active_futures:
                break  # All submitted, all done
            for future in as_completed(list(active_futures.keys())):
                case = active_futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "name": case.name,
                        "status": "failed",
                        "message": f"Test execution failed: {str(exc)}",
                        "output": "",
                        "command": _case_command_str(case),
                        "return_code": None,
                    }
                _on_case_completed(case, result)
                break  # Process one future, then re-check queue

    def _update_results_skipped(self, result: Dict[str, Any], test_index: int, case_name: str) -> None:
        """Thread-safe result update for skipped cases (no xfail processing)."""
        with self.lock:
            self._fill_hint_command(result, case_name)
            self.results["details"].append(result)
            logger.warning("⊘ Test %d skipped: %s", test_index, case_name)
            if result.get("message"):
                logger.warning("  Reason: %s", result["message"])
    
    def _run_test_with_index(self, test_index: int, case: TestCase) -> Dict[str, Any]:
        """运行单个测试并返回结果（包含索引信息）"""
        logger.info("[Worker] Running test %d: %s", test_index, case.name)
        result = self.run_single_test(case)
        return result
    
    def _update_results(self, result: Dict[str, Any], test_index: int, case: TestCase) -> None:
        """线程安全地更新测试结果"""
        with self.lock:
            # Apply xfail status mapping before counting
            self._apply_xfail_status(result, case)

            self._fill_hint_command(result, case.name)
            self.results["details"].append(result)
            duration = result.get("duration", 0)
            status = result["status"]
            if status == "passed":
                self.results["passed"] += 1
                logger.info("✓ Test %d passed: %s (%.2fs)", test_index, case.name, duration)
            elif status == "xfailed":
                self.results["xfailed"] += 1
                logger.info("✓ Test %d xfailed (expected): %s (%.2fs)", test_index, case.name, duration)
                if result.get("message"):
                    logger.info("  Detail: %s", result["message"])
            elif status == "xpassed":
                self.results["xpassed"] += 1
                self.results["failed"] += 1
                logger.error("✗ Test %d xpassed (unexpected!): %s (%.2fs)", test_index, case.name, duration)
                if result.get("message"):
                    logger.error("  Error: %s", result["message"])
                logger.warning("  [XPass] Marked as expected_failure but passed — remove the xfail marker.")
            else:
                self.results["failed"] += 1
                logger.error("✗ Test %d failed: %s (%.2fs)", test_index, case.name, duration)
                if result["message"]:
                    logger.error("  Error: %s", result["message"])
    
    def run_tests_sequential(self) -> bool:
        """回退到顺序执行模式"""
        logger.info("Falling back to sequential execution...")
        return super().run_tests() 