"""单用例编排（原则 4）：组合 Executor 与 Validator + retry policy。

自 1.3 ``core/execution.py::execute_single_test_case`` /
``_execute_command_once`` 搬迁：retry 循环、attempt_history / flaky 聚合
逐位保持（现有 retry/flaky 测试是回归门）；变化只有职责归位：

- subprocess 执行交给 ``execution.executor.execute_command``；
- 判定交给 ``validation.validator.validate_result``（只读）；
- ``--update-baseline`` 写盘改为本层独立 accept 步骤
  （``accept.apply_baseline_accept``）；
- ``next_action_hint`` 由 ``reporting.diagnosis`` 生成（原则 5）。

兼容性：``case`` 接受 ``ExecutionSpec`` 或旧 dict 形态（读取
name/command/args/timeout/retry_count/env[/expected]），dict 支持在
Phase 3 Schema v2 落地后移除。
"""
import logging
import time
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Union

from ..execution.executor import DEFAULT_OUTPUT_MAX_CHARS, _spec_get, execute_command
from ..result import TestResult
from ..types import TestResultData
from ..validation.validator import _trim_compare_failures, validate_result
from ..validation.assertions import ValidationError
from .accept import apply_baseline_accept
from ...reporting.diagnosis import build_next_action_hint

logger = logging.getLogger("symtest.core.orchestration.single")


def _resolve_expectation(
    case: Any,
    expectation: Optional[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """期望规格解析：显式参数优先；旧 dict 形态回落到 ``case["expected"]``。"""
    if expectation is not None:
        return expectation
    if isinstance(case, Mapping):
        return case.get("expected") or {}
    return {}


def _execute_command_once(
    case: Any,
    expectation: Mapping[str, Any],
    workspace: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
    output_max_chars: int = DEFAULT_OUTPUT_MAX_CHARS,
) -> TestResultData:
    """Compose one attempt: execute → validate → (optional) baseline accept."""
    start_time = time.perf_counter()

    exec_result = execute_command(
        case, workspace, env, output_max_chars=output_max_chars,
    )

    result = TestResult(
        name=exec_result.name,
        command=exec_result.command,
        output=exec_result.output,
        stdout=exec_result.stdout,
        stderr=exec_result.stderr,
        return_code=exec_result.return_code,
    )

    if exec_result.error is not None:
        result.message = f"Execution error: {exec_result.error}"
        result.failure_kind = "execution_error"
        result.next_action_hint = build_next_action_hint("execution_error")
    elif exec_result.timed_out:
        result.status = "timeout"
        result.failure_kind = "timeout"
        result.message = (
            f"Timeout reached! Killed after {exec_result.timeout_limit} seconds."
        )
        result.next_action_hint = build_next_action_hint("timeout")
    else:
        try:
            vr = validate_result(
                expectation or {}, exec_result, workspace,
                error_analysis=error_analysis,
            )
        except ValidationError as exc:
            result.message = str(exc)
            result.failure_kind = exc.failure_kind
            result.compare_failures = _trim_compare_failures(exc.compare_failures)
            result.baseline_updated = list(exc.baseline_updated)
            result.assertion_results = list(exc.assertion_results)
            result.next_action_hint = build_next_action_hint(
                exc.failure_kind, update_baseline=update_baseline,
            )
        except AssertionError as exc:
            # Legacy AssertionError catch for backward compatibility
            result.message = str(exc)
            result.failure_kind = result.failure_kind or "unknown"
            result.next_action_hint = build_next_action_hint(result.failure_kind)
        except Exception as exc:
            result.message = f"Execution error: {str(exc)}"
            result.failure_kind = "execution_error"
            result.next_action_hint = build_next_action_hint("execution_error")
        else:
            if vr.passed:
                result.status = "passed"
                result.assertion_results = vr.assertion_results
            else:
                result.message = vr.message
                result.failure_kind = vr.failure_kind
                result.compare_failures = _trim_compare_failures(vr.compare_failures)
                result.assertion_results = vr.assertion_results
                result.next_action_hint = build_next_action_hint(
                    vr.failure_kind, update_baseline=update_baseline,
                )
                # ── accept 步骤（原则 3：写盘在编排层，不在 Validator） ──
                if update_baseline and vr.failure_kind == "file_compare":
                    accepted = apply_baseline_accept(vr, workspace)
                    if accepted is not None:
                        result.status = "passed"
                        result.message = ""
                        result.failure_kind = None
                        result.compare_failures = []
                        result.assertion_results = accepted
                        result.next_action_hint = None

    result.duration = time.perf_counter() - start_time
    return result.to_dict()


def execute_single_test_case(
    case: Any,
    workspace: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    *,
    expectation: Optional[Mapping[str, Any]] = None,
    update_baseline: bool = False,
    error_analysis: bool = False,
    output_max_chars: int = DEFAULT_OUTPUT_MAX_CHARS,
) -> TestResultData:
    """
    Stateless execution of a single test case with optional retry.

    Args:
        case: ExecutionSpec（或兼容的旧 dict 形态），``retry_count`` 控制
              自动重试次数。
        workspace: Working directory for test execution.
        env: Optional environment variables to inject/override (merged with os.environ).
        expectation: 期望规格（ExpectationSpec 的原始断言字典）；旧 dict
                     形态的 ``case`` 缺省回落到 ``case["expected"]``。
        update_baseline: If True, accept comparison failures as new baselines
                         （accept 步骤在编排层执行，Validator 只读）。
        output_max_chars: Max characters for output in result dict.

    ``retry_count`` (defaults to 0) controls how many additional times the
    command is re-run after the first failure.  ``retry_count=0`` means no
    retry (behaviour identical to previous versions).
    """
    retry_count: int = _spec_get(case, "retry_count", 0)
    max_attempts = retry_count + 1
    total_duration = 0.0
    last_result: Optional[TestResultData] = None
    attempt_history: List[Dict[str, Any]] = []

    expectation = _resolve_expectation(case, expectation)

    for attempt in range(1, max_attempts + 1):
        result = _execute_command_once(
            case, expectation, workspace, env,
            update_baseline=update_baseline,
            error_analysis=error_analysis,
            output_max_chars=output_max_chars,
        )
        total_duration += result["duration"]
        attempt_history.append({
            "attempt": attempt,
            "status": result["status"],
            "message": result.get("message", ""),
            "duration": result["duration"],
        })
        last_result = result

        if result["status"] == "passed":
            break

        if attempt < max_attempts:
            logger.info(
                "Retrying '%s' (attempt %d/%d)...",
                _spec_get(case, "name", ""), attempt + 1, max_attempts,
            )

    if last_result is not None:
        last_result["duration"] = total_duration
        last_result["attempts"] = len(attempt_history)
        last_result["attempt_history"] = attempt_history
        if retry_count > 0 and last_result["status"] == "passed" and len(attempt_history) > 1:
            last_result["flaky"] = True

    return last_result if last_result is not None else result
