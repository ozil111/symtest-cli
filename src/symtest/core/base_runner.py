import time
import logging
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from .test_case import TestCase
from .assertions import Assertions
from .setup import SetupManager, EnvironmentSetup
from .execution import execute_single_test_case
from .history_store import load_history, update_case, check_regression, save_history, reset_cases
from .last_run_store import update_last_run, get_last_failed_names
from ..file_comparator.factory import ComparatorFactory

logger = logging.getLogger("symtest.core.base_runner")

class BaseRunner(ABC):
    def __init__(self, config_file: str, workspace: Optional[str] = None,
                 test_case_filter: Optional[List[str]] = None,
                 test_case_tag_filter: Optional[List[str]] = None,
                 history_dir: Optional[str] = None,
                 regression_threshold: float = 1.5,
                 update_baseline: bool = False,
                 update_history: bool = False,
                 error_analysis: bool = False,
                 last_failed: bool = False,
                 resume: bool = False,
                 plugin_dirs: Optional[List[str]] = None):
        if workspace:
            self.workspace = Path(workspace)
        else:
            self.workspace = Path.cwd()
        config_path = Path(config_file)
        if config_path.is_absolute():
            self.config_path = config_path
        else:
            self.config_path = self.workspace / config_path
        self.test_cases: List[TestCase] = []
        self.test_case_filter: Optional[List[str]] = test_case_filter
        self.test_case_tag_filter: Optional[List[str]] = test_case_tag_filter
        if history_dir:
            self.history_dir = str((self.workspace / history_dir).resolve())
        else:
            self.history_dir = None
        self.regression_threshold = regression_threshold
        self.update_baseline = update_baseline
        self.update_history = update_history
        self.error_analysis = error_analysis
        self.last_failed = last_failed
        self.resume = resume

        # --- workspace plugin directories ---
        resolved_plugin_dirs: List[str] = list(plugin_dirs) if plugin_dirs else []
        default_plugin_dir = self.workspace / "comparators"
        if default_plugin_dir.is_dir() and str(default_plugin_dir.resolve()) not in resolved_plugin_dirs:
            resolved_plugin_dirs.append(str(default_plugin_dir.resolve()))
        ComparatorFactory.set_plugin_dirs(resolved_plugin_dirs)
        self.results: Dict[str, Any] = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "xfailed": 0,
            "xpassed": 0,
            "updated": 0,
            "details": []
        }
        self.assertions = Assertions()
        self.setup_manager = SetupManager()

    @abstractmethod
    def load_test_cases(self) -> None:
        """Load test cases from configuration file"""
        pass
    
    def load_setup_from_config(self, config: Dict[str, Any]) -> None:
        """从配置文件加载setup配置"""
        setup_config = config.get("setup", {})
        
        # 处理环境变量设置
        if "environment_variables" in setup_config:
            env_setup = EnvironmentSetup({"environment_variables": setup_config["environment_variables"]})
            self.setup_manager.add_setup(env_setup)
        
        # 这里可以扩展支持其他类型的setup插件
        # 例如：
        # if "custom_setups" in setup_config:
        #     for custom_setup_config in setup_config["custom_setups"]:
        #         # 动态加载自定义setup插件
        #         pass

    def _apply_test_case_filter(self) -> None:
        """根据 test_case_filter / test_case_tag_filter / --last-failed 过滤测试用例"""
        if self.last_failed and not self.test_case_filter:
            ws = str(self.workspace) if self.workspace else str(Path.cwd())
            failed_names = get_last_failed_names(ws)
            if failed_names:
                logger.info(
                    "--last-failed: filtering to %d previously failed case(s): %s",
                    len(failed_names), ", ".join(failed_names),
                )
                self.test_case_filter = (
                    (self.test_case_filter or []) + failed_names
                )
            else:
                logger.info("--last-failed: no previously failed cases found; running all.")

        if self.test_case_filter or self.test_case_tag_filter:
            original_count = len(self.test_cases)
            self.test_cases = [
                tc for tc in self.test_cases
                if (not self.test_case_filter or tc.name in self.test_case_filter)
                and (not self.test_case_tag_filter
                     or set(tc.tags or []) & set(self.test_case_tag_filter))
            ]
            filtered_out = original_count - len(self.test_cases)
            if filtered_out > 0:
                logger.info("Filtered out %d test case(s). Running %d specified case(s).",
                            filtered_out, len(self.test_cases))
            if not self.test_cases:
                logger.warning("No matching test cases found for: names=%s, tags=%s",
                               self.test_case_filter, self.test_case_tag_filter)

    def run_tests(self) -> bool:
        """Run all test cases and return whether all tests passed"""
        try:
            self.load_test_cases()
            self._apply_test_case_filter()
            self.results["total"] = len(self.test_cases)
            
            if self.results["total"] == 0:
                logger.warning("No test cases to run.")
                return False
            
            # 执行setup任务
            self.setup_manager.setup_all()
            
            total_start_time = time.time()
            
            # ── Topological sort for depends_on ──
            ordered_cases = self._topological_order()
            
            logger.info("Starting test execution... Total tests: %d", self.results["total"])
            logger.info("=" * 50)
            
            for i, case in enumerate(ordered_cases, 1):
                logger.info("Running test %d/%d: %s", i, self.results["total"], case.name)
                
                # Check if dependencies failed → skip
                if hasattr(case, 'depends_on') and case.depends_on:
                    dep_failed = any(
                        d["status"] not in ("passed", "xfailed")
                        for d in self.results["details"]
                        if d["name"] in case.depends_on
                    )
                    if dep_failed:
                        failed_dep = next(
                            d["name"] for d in self.results["details"]
                            if d["name"] in case.depends_on
                            and d["status"] not in ("passed", "xfailed")
                        )
                        skip_result = {
                            "name": case.name,
                            "status": "skipped",
                            "message": f"Skipped: dependency '{failed_dep}' failed",
                            "output": "",
                            "command": case.command if case.command
                                       else " -> ".join(
                                           f"{s.command} {' '.join(s.args)}".strip()
                                           for s in (case.steps or [])
                                       ),
                            "return_code": None,
                            "duration": 0,
                            "expected": case.expected if case.expected else None,
                            "description": case.description or None,
                            "tags": case.tags or [],
                        }
                        self._fill_hint_command(skip_result, case.name)
                        self.results["details"].append(skip_result)
                        logger.warning("⊘ Test %d skipped: %s", i, case.name)
                        logger.warning("  Reason: %s", skip_result["message"])
                        continue
                
                result = self.run_single_test(case)
                
                # Apply xfail status mapping before counting
                self._apply_xfail_status(result, case)

                # ── Echo expected / description / tags ──
                result["expected"] = case.expected if case.expected else None
                result["description"] = case.description or None
                result["tags"] = case.tags or []
                self._fill_hint_command(result, case.name)

                self.results["details"].append(result)
                duration = result.get("duration", 0)
                status = result["status"]
                if status == "passed":
                    self.results["passed"] += 1
                    # Check for baseline updates
                    if result.get("baseline_updated"):
                        self.results["updated"] += 1
                        logger.info("✓ Test passed (baseline updated): %s (%.2fs)", case.name, duration)
                    elif result.get("flaky"):
                        logger.info("✓ Test passed (flaky, %d attempts): %s (%.2fs)",
                                    result.get("attempts", 1), case.name, duration)
                    else:
                        logger.info("✓ Test passed: %s (%.2fs)", case.name, duration)
                elif status == "xfailed":
                    self.results["xfailed"] += 1
                    attempt_info = f" ({result.get('attempts', 1)} attempts)" if result.get("attempts", 1) > 1 else ""
                    logger.info("✓ Test xfailed (expected)%s: %s (%.2fs)", attempt_info, case.name, duration)
                    if result.get("message"):
                        logger.info("  Reason: %s", result.get("xfail_reason", ""))
                        logger.info("  Detail: %s", result["message"])
                elif status == "xpassed":
                    self.results["xpassed"] += 1
                    self.results["failed"] += 1
                    logger.error("✗ Test xpassed (unexpected!): %s (%.2fs)", case.name, duration)
                    if result.get("message"):
                        logger.error("  Error: %s", result["message"])
                    logger.warning("  [XPass] Marked as expected_failure but passed — remove the xfail marker.")
                else:
                    self.results["failed"] += 1
                    if result.get("flaky"):
                        logger.error("✗ Test failed (%d attempts): %s (%.2fs)",
                                     result.get("attempts", 1), case.name, duration)
                    else:
                        logger.error("✗ Test failed: %s (%.2fs)", case.name, duration)
                    if result["message"]:
                        logger.error("  Error: %s", result["message"])
                    
            total_duration = time.time() - total_start_time
            skipped = sum(1 for d in self.results["details"] if d["status"] == "skipped")
            logger.info("=" * 50)
            logger.info(
                "Test execution completed in %.2fs. "
                "Passed: %d, Failed: %d, XFailed: %d, XPassed: %d, Skipped: %d",
                total_duration,
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

    def _topological_order(self) -> List[TestCase]:
        """Return test cases in topological order respecting ``depends_on``.

        Cases without dependencies keep their original relative order.
        Cases with dependencies are placed after all their dependencies.
        Uses Kahn's algorithm with stable ordering for determinism.
        """
        cases = self.test_cases
        has_deps = any(c.depends_on for c in cases)
        if not has_deps:
            return list(cases)

        name_to_case: Dict[str, TestCase] = {c.name: c for c in cases}

        # in_degree and dependents
        in_degree: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = {}
        for c in cases:
            deps = [d for d in c.depends_on if d in name_to_case]
            in_degree[c.name] = len(deps)
            for dep in deps:
                dependents.setdefault(dep, []).append(c.name)

        # Kahn: start with zero in-degree cases in original order
        result: List[TestCase] = []
        ready: deque = deque(c for c in cases if in_degree[c.name] == 0)

        while ready:
            case = ready.popleft()
            result.append(case)
            for dep_name in dependents.get(case.name, []):
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    ready.append(name_to_case[dep_name])

        # If any case remains (shouldn't happen after cycle validation),
        # append them in original order as fallback
        seen: Set[str] = {c.name for c in result}
        for c in cases:
            if c.name not in seen:
                result.append(c)

        return result

    def _fill_hint_command(self, result: Dict[str, Any], case_name: str) -> None:
        """Fill in the concrete CLI command inside ``next_action_hint``.

        The execution layer attaches the hint with ``command=None`` because it
        does not know the config file path; the runner does.
        """
        hint = result.get("next_action_hint")
        if not hint or hint.get("command"):
            return
        config = str(self.config_path)
        if hint.get("action") == "update_baseline":
            hint["command"] = (
                f'symtest run "{config}" --update-baseline -t "{case_name}"'
            )
        else:
            hint["command"] = f'symtest run "{config}" -t "{case_name}"'

    def _apply_xfail_status(self, result: Dict[str, Any], case: "TestCase") -> None:
        """Apply xfail (expected failure) status mapping to a test result.

        When ``case.expected_failure`` is True:
        - ``passed`` → ``xpassed`` (unexpected pass; counts as a suite failure)
        - any non-passed status → ``xfailed`` (expected failure; not a failure)

        The ``xfail_reason`` from the case is attached to the result dict so the
        report can display it.
        """
        if not getattr(case, "expected_failure", False):
            return
        xfail_reason = getattr(case, "xfail_reason", "") or ""
        result["xfail_reason"] = xfail_reason
        result["xfail_quiet"] = getattr(case, "xfail_quiet", False)
        if result.get("status") == "passed":
            result["status"] = "xpassed"
        else:
            result["status"] = "xfailed"

    def _save_last_run(self) -> None:
        """Persist per-case status for ``--last-failed`` support."""
        ws = str(self.workspace) if self.workspace else str(Path.cwd())
        update_last_run(ws, self.results["details"])

    def _update_history(self) -> None:
        """Update .symtest history with successful run results and check for regressions."""
        if not self.history_dir:
            return
        history = load_history(self.history_dir)

        if self.update_history:
            run_names = {r["name"] for r in self.results["details"]}
            cleared = reset_cases(history, run_names)
            if cleared:
                logger.info(
                    "History reset: cleared %d case(s) before recording this run",
                    cleared,
                )
                self.results["history_reset"] = True
                self.results["history_cleared"] = cleared

        for result in self.results["details"]:
            # Only record successful cases in history; skip failed ones
            if result["status"] != "passed":
                continue
            duration = result.get("duration", 0)
            # Check regression BEFORE updating (compare against old avg)
            warning = check_regression(history, result["name"], duration, self.regression_threshold)
            if warning:
                logger.warning(warning)
            update_case(history, result["name"], duration)
        save_history(self.history_dir, history)

    def _run_sequence(self, case: TestCase) -> Dict[str, Any]:
        """Run a sequence test case with multiple steps (fail-fast)."""
        from .config_loader import execute_sequence
        return execute_sequence(
            case_name=case.name,
            steps=case.steps,
            workspace=str(self.workspace) if self.workspace else None,
            case_expected=case.expected if case.expected else None,
            resume=self.resume,
            env=case.env,
        )

    @abstractmethod
    def run_single_test(self, case: TestCase) -> Dict[str, str]:
        """Run a single test case and return the result"""
        pass