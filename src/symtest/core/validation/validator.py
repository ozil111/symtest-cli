"""只读验证器（原则 3）。

自 1.3 ``core/execution.py::validate_result`` / ``_dispatch_file_compare`` /
``_trim_compare_failures`` 逐位搬入；变化只有两点：
1. 输入从 ``TestResultData`` dict 改为 ``ExecutionResult``（验证不感知
   status / hint 等编排语义）；
2. 移除 ``update_baseline`` 写盘分支 —— Validator 永远只读，baseline 覆盖
   由编排层 accept 步骤（``orchestration/accept.py``）执行。
"""
import logging
from typing import Any, Dict, List, Mapping, Optional

from ..execution.result import ExecutionResult
from .assertions import Assertions, ValidationError
from .result import ValidationResult

logger = logging.getLogger("symtest.core.validation.validator")

# Maximum number of differences retained per compare_failures entry in JSON output.
# The text report already limits display to 5; this prevents large CSV/H5 diffs
# from blowing up AI context windows.
DEFAULT_MAX_DIFFERENCES = 50


def _trim_compare_failures(
    compare_failures: List[Dict[str, Any]],
    max_diffs: int = DEFAULT_MAX_DIFFERENCES,
) -> List[Dict[str, Any]]:
    """Truncate the ``differences`` list inside each compare_failure entry.

    The text report already only shows the first 5 differences, but the JSON
    output previously carried the full list — which could reach megabytes for
    large CSV/H5 comparisons.  This function caps the retained differences so
    that AI consumers get a representative sample without context-window blowup.
    """
    if not compare_failures:
        return compare_failures
    trimmed: List[Dict[str, Any]] = []
    for cf in compare_failures:
        diffs = cf.get("differences", [])
        if len(diffs) > max_diffs:
            cf_copy = dict(cf)
            cf_copy["differences"] = diffs[:max_diffs]
            cf_copy["differences_truncated"] = True
            cf_copy["differences_total"] = len(diffs)
            trimmed.append(cf_copy)
        else:
            trimmed.append(cf)
    return trimmed


def _dispatch_file_compare(
    spec: Dict[str, Any],
    workspace: Optional[str],
    assertions: Assertions,
    *,
    error_analysis: bool = False,
) -> Dict[str, Any]:
    """Extract fields from a compare_files spec dict and delegate to Assertions.compare_files.

    Returns a structured dict with ``passed``, ``compare_failures``, ``message``.
    """
    actual_path = spec.get("actual", "")
    baseline_path = spec.get("baseline", "")
    file_type = spec.get("type", None)

    # All remaining keys are forwarded as comparator kwargs
    known_keys = {"actual", "baseline", "type"}
    comparator_kwargs = {k: v for k, v in spec.items() if k not in known_keys}

    try:
        cf_result = assertions.compare_files(
            actual_path=actual_path,
            baseline_path=baseline_path,
            file_type=file_type,
            workspace=workspace,
            error_analysis=error_analysis,
            **comparator_kwargs,
        )
        return {
            "assertion": "compare_files",
            "passed": True,
            "error_stats": cf_result.get("error_stats"),
            "compare_failures": [],
            "baseline_updated": [],
            "message": "",
        }
    except ValidationError as e:
        return {
            "assertion": "compare_files",
            "passed": False,
            "compare_failures": e.compare_failures,
            "baseline_updated": e.baseline_updated,
            "message": str(e),
        }


def validate_result(
    expected: Mapping[str, Any],
    actual: ExecutionResult,
    workspace: Optional[str] = None,
    *,
    error_analysis: bool = False,
) -> ValidationResult:
    """Pure, read-only validation logic. Collects all assertion failures.

    :param expected:  Expectation mapping from the test case (return_code /
                      output_contains / output_matches / compare_files).
    :param actual:    Execution facts produced by the executor.
    :param workspace: Working directory; used to resolve relative file paths in
                      ``compare_files`` assertions.
    :param error_analysis: If True, enable comparator error statistics.
    :returns: ValidationResult —— ``passed=True`` 时 ``assertion_results``
              携带逐条断言明细；失败时附带 ``failure_kind`` / ``message`` /
              ``compare_failures``（不抛异常，由编排层消费）。
    """
    # ── timeout：执行事实，是否算失败由 Validator 判定（原则 2） ──
    if actual.timed_out:
        return ValidationResult(
            passed=False,
            failure_kind="timeout",
            message=(
                f"Timeout reached! Killed after {actual.timeout_limit} seconds."
            ),
        )

    assertions = Assertions()
    failure_messages: List[str] = []
    failure_kind: Optional[str] = None
    compare_failures: List[Dict[str, Any]] = []
    assertion_results: List[Dict[str, Any]] = []

    # ── return_code ──
    if "return_code" in expected:
        exc_msg = None
        try:
            assertions.return_code_equals(actual.return_code, expected["return_code"])
        except AssertionError as e:
            exc_msg = str(e)
        if exc_msg:
            failure_messages.append(exc_msg)
            if failure_kind is None:
                failure_kind = "return_code"
            assertion_results.append({"assertion": "return_code", "passed": False, "message": exc_msg})
        else:
            assertion_results.append({"assertion": "return_code", "passed": True})

    # ── output_contains ──
    if "output_contains" in expected:
        for text in expected["output_contains"]:
            exc_msg = None
            try:
                assertions.contains(actual.output, text)
            except AssertionError as e:
                exc_msg = str(e)
            if exc_msg:
                failure_messages.append(exc_msg)
                if failure_kind is None:
                    failure_kind = "output_contains"
                assertion_results.append({"assertion": "output_contains", "passed": False, "message": exc_msg, "text": text})
            else:
                assertion_results.append({"assertion": "output_contains", "passed": True, "text": text})

    # ── output_matches ──
    if "output_matches" in expected and expected["output_matches"]:
        exc_msg = None
        try:
            assertions.matches(actual.output, expected["output_matches"])
        except AssertionError as e:
            exc_msg = str(e)
        if exc_msg:
            failure_messages.append(exc_msg)
            if failure_kind is None:
                failure_kind = "output_matches"
            assertion_results.append({"assertion": "output_matches", "passed": False, "message": exc_msg})
        else:
            assertion_results.append({"assertion": "output_matches", "passed": True})

    # ── compare_files ──
    if "compare_files" in expected:
        for spec in expected["compare_files"]:
            cf_result = _dispatch_file_compare(spec, workspace, assertions, error_analysis=error_analysis)
            assertion_results.append(cf_result)
            if cf_result.get("passed") is False:
                if failure_kind is None:
                    failure_kind = "file_compare"
                compare_failures.extend(cf_result.get("compare_failures", []))
                failure_messages.append(cf_result.get("message", ""))

    if failure_messages:
        return ValidationResult(
            passed=False,
            failure_kind=failure_kind or "unknown",
            message="; ".join(failure_messages),
            assertion_results=assertion_results,
            compare_failures=compare_failures,
        )

    return ValidationResult(passed=True, assertion_results=assertion_results)
