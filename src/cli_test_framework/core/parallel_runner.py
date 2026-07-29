from abc import ABC
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Union
import time
import threading
import logging
from .base_runner import BaseRunner
from .test_case import TestCase
from .process_worker import run_test_in_process

logger = logging.getLogger("cli_test_framework.core.parallel_runner")


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
        super().__init__(config_file, workspace, **kwargs)
        self.max_workers = max_workers
        self.execution_mode = execution_mode
        self.lock = threading.Lock()  # 用于线程安全的结果更新
        
    def run_tests(self) -> bool:
        """并行运行所有测试用例"""
        try:
            self.load_test_cases()
            self._apply_test_case_filter()
            self.results["total"] = len(self.test_cases)
            
            if self.results["total"] == 0:
                logger.warning("No test cases to run.")
                return False
            
            # 执行setup任务
            self.setup_manager.setup_all()
            
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
                            str(self.workspace) if self.workspace else None
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
            logger.info("Parallel test execution completed in %.2f seconds", execution_time)
            logger.info("Passed: %d, Failed: %d", self.results["passed"], self.results["failed"])

            # Update history & regression detection
            self._update_history()

            return self.results["failed"] == 0
        finally:
            # 确保teardown总是被执行
            self.setup_manager.teardown_all()
    
    def _run_test_with_index(self, test_index: int, case: TestCase) -> Dict[str, Any]:
        """运行单个测试并返回结果（包含索引信息）"""
        logger.info("[Worker] Running test %d: %s", test_index, case.name)
        result = self.run_single_test(case)
        return result
    
    def _update_results(self, result: Dict[str, Any], test_index: int, case: TestCase) -> None:
        """线程安全地更新测试结果"""
        with self.lock:
            self._fill_hint_command(result, case.name)
            self.results["details"].append(result)
            duration = result.get("duration", 0)
            if result["status"] == "passed":
                self.results["passed"] += 1
                logger.info("✓ Test %d passed: %s (%.2fs)", test_index, case.name, duration)
            else:
                self.results["failed"] += 1
                logger.error("✗ Test %d failed: %s (%.2fs)", test_index, case.name, duration)
                if result["message"]:
                    logger.error("  Error: %s", result["message"])
    
    def run_tests_sequential(self) -> bool:
        """回退到顺序执行模式"""
        logger.info("Falling back to sequential execution...")
        return super().run_tests() 