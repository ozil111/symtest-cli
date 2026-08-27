import subprocess
import signal
import time
import os
import shlex
import logging
from typing import Any, List, Optional, Dict

from .assertions import Assertions, ValidationError
from .types import ExpectedResult, TestCaseData, TestResultData

logger = logging.getLogger("symtest.core.execution")

# Default maximum chars for command output in reports.
# Full output is still written to disk when output_dir is set.
DEFAULT_OUTPUT_MAX_CHARS = 20000

# Maximum number of differences retained per compare_failures entry in JSON output.
# The text report already limits display to 5; this prevents large CSV/H5 diffs
# from blowing up AI context windows.
DEFAULT_MAX_DIFFERENCES = 50

# Commands that are shell builtins (not real executables).
# With shell=False, these must be wrapped via the platform shell.
if os.name == 'nt':
    _SHELL_BUILTINS = frozenset(['echo', 'dir', 'type', 'copy', 'del', 'ren',
                                  'cd', 'md', 'rd', 'set', 'cls', 'move'])
else:
    _SHELL_BUILTINS = frozenset(['echo', 'cd', 'pwd', 'export', 'source'])


def _normalize_cmd_list(command: str, args: List[str]) -> List[str]:
    """If command is a shell builtin, wrap with the platform shell interpreter."""
    if command.lower() in _SHELL_BUILTINS:
        if os.name == 'nt':
            return ['cmd', '/d', '/c', command, *args]
        else:
            return ['/bin/sh', '-c', shlex.join([command, *args])]
    return [command, *args]


def _trim_output(output: str, max_chars: int = DEFAULT_OUTPUT_MAX_CHARS) -> str:
    """Trim long output: keep head 1/3 + tail 2/3 of max_chars."""
    if len(output) <= max_chars:
        return output
    head_size = max_chars // 3
    tail_size = max_chars - head_size
    trimmed = len(output) - max_chars
    return (
        output[:head_size]
        + f"\n\n[... {trimmed} chars truncated ...]\n\n"
        + output[-tail_size:]
    )


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


def _build_next_action_hint(
    failure_kind: Optional[str],
    *,
    update_baseline: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build a structured remediation hint for a failed test case.

    The ``command`` field is left as ``None`` here because the execution layer
    does not know the config file path; runners fill it in (see
    ``BaseRunner._fill_hint_command``).

    ``action`` vocabulary (stable, for AI consumers to branch on):
    - ``update_baseline``  – file comparison failed; accept new output as baseline
    - ``update_expected``  – an expectation assertion failed; fix program or config
    - ``increase_timeout`` – the command timed out
    - ``investigate``      – execution errors and everything else
    """
    if not failure_kind:
        return None
    if failure_kind == "file_compare":
        if update_baseline:
            return {
                "action": "investigate",
                "command": None,
                "reason": (
                    "File comparison failed even though --update-baseline was "
                    "enabled; the actual output file may be missing or "
                    "unreadable. Inspect compare_failures for details."
                ),
            }
        return {
            "action": "update_baseline",
            "command": None,
            "reason": (
                "File comparison failed. If the new output is the intended "
                "behavior, re-run with --update-baseline to accept it as the "
                "new baseline; otherwise inspect compare_failures/diff_summary "
                "and fix the program under test."
            ),
        }
    if failure_kind in ("return_code", "output_contains", "output_matches"):
        return {
            "action": "update_expected",
            "command": None,
            "reason": (
                f"Assertion '{failure_kind}' failed. If the new behavior is "
                "intended, update the 'expected' block in the test config; "
                "otherwise fix the program under test. Compare 'expected' "
                "against 'stdout'/'stderr' and 'assertion_results' in this "
                "result to locate the discrepancy."
            ),
        }
    if failure_kind == "timeout":
        return {
            "action": "increase_timeout",
            "command": None,
            "reason": (
                "The command timed out. Increase 'timeout' in the test "
                "config or investigate why the program did not finish."
            ),
        }
    if failure_kind == "execution_error":
        return {
            "action": "investigate",
            "command": None,
            "reason": (
                "The command failed to execute. Check that it exists, that "
                "arguments are valid, and that the environment is set up "
                "correctly."
            ),
        }
    return {
        "action": "investigate",
        "command": None,
        "reason": (
            "Investigate the failure using 'message', 'stdout'/'stderr' and "
            "'expected' in this result."
        ),
    }


def validate_result(
    expected: ExpectedResult,
    actual: TestResultData,
    workspace: Optional[str] = None,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
) -> List[Dict[str, Any]]:
    """
    Pure validation logic. Collects all assertion failures and raises
    ``ValidationError`` with structured data when any fail.

    :param expected:  Expected result specification from the test case.
    :param actual:    Actual test result data produced by command execution.
    :param workspace: Working directory; used to resolve relative file paths in
                      ``compare_files`` assertions.
    :param update_baseline: If True, overwrite baseline files on comparison failure.
    :returns: Per-assertion pass/fail detail (``assertion_results``) when all
              assertions pass. On failure the same data is carried by the
              raised ``ValidationError.assertion_results``.
    """
    assertions = Assertions()
    failure_messages: List[str] = []
    failure_kind: Optional[str] = None
    compare_failures: List[Dict[str, Any]] = []
    baseline_updated: List[str] = []
    assertion_results: List[Dict[str, Any]] = []

    # ── return_code ──
    if "return_code" in expected:
        exc_msg = None
        try:
            assertions.return_code_equals(actual["return_code"], expected["return_code"])
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
                assertions.contains(actual["output"], text)
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
            assertions.matches(actual["output"], expected["output_matches"])
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
            cf_result = _dispatch_file_compare(spec, workspace, assertions, update_baseline=update_baseline, error_analysis=error_analysis)
            assertion_results.append(cf_result)
            if cf_result.get("passed") is False:
                if failure_kind is None:
                    failure_kind = "file_compare"
                compare_failures.extend(cf_result.get("compare_failures", []))
                failure_messages.append(cf_result.get("message", ""))
            if cf_result.get("baseline_updated"):
                baseline_updated.extend(cf_result.get("baseline_updated", []))

    if failure_messages:
        raise ValidationError(
            message="; ".join(failure_messages),
            failure_kind=failure_kind or "unknown",
            compare_failures=compare_failures,
            baseline_updated=baseline_updated,
            assertion_results=assertion_results,
        )

    return assertion_results


def _dispatch_file_compare(
    spec: Dict[str, Any],
    workspace: Optional[str],
    assertions: Assertions,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
) -> Dict[str, Any]:
    """Extract fields from a compare_files spec dict and delegate to Assertions.compare_files.

    Returns a structured dict with ``passed``, ``compare_failures``, ``baseline_updated``, ``message``.
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
            update_baseline=update_baseline,
            error_analysis=error_analysis,
            **comparator_kwargs,
        )
        if cf_result.get("baseline_updated"):
            return {
                "assertion": "compare_files",
                "passed": True,
                "error_stats": cf_result.get("error_stats"),
                "compare_failures": [],
                "baseline_updated": [baseline_path],
                "message": "",
            }
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


def _execute_command_once(
    case: TestCaseData,
    workspace: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
    output_max_chars: int = DEFAULT_OUTPUT_MAX_CHARS,
) -> TestResultData:
    """Execute a single command once (no retry logic)."""
    # perf_counter: high-resolution monotonic clock; on Windows, time.time()
    # has ~15.6ms granularity and can yield duration == 0.0 for fast commands.
    start_time = time.perf_counter()
    cmd_list = _normalize_cmd_list(case["command"], [str(arg) for arg in case["args"]])
    timeout_limit = case.get("timeout", 3600)

    full_command = " ".join(cmd_list)

    result: TestResultData = {
        "name": case["name"],
        "status": "failed",
        "message": "",
        "command": full_command,
        "output": "",
        "stdout": "",
        "stderr": "",
        "return_code": None,
        "duration": 0.0,
        "expected": None,
        "description": None,
        "tags": [],
        "failure_kind": None,
        "attempts": 1,
        "flaky": False,
        "attempt_history": [],
        "step_results": [],
        "compare_failures": [],
        "baseline_updated": [],
        "failed_step": None,
        "assertion_results": [],
        "next_action_hint": None,
    }

    # Prepare environment variables
    # Default to current environment, merge with provided env if any.
    # Case-level ``env`` (if present) is applied last so it takes the highest
    # precedence, allowing it to override both inherited environment variables
    # and scheduler-injected values (e.g. OMP_NUM_THREADS).
    current_env = os.environ.copy()
    if env:
        current_env.update(env)
    case_env = case.get("env")
    if case_env:
        current_env.update(case_env)

    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=workspace if workspace else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env=current_env,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_limit)
        except subprocess.TimeoutExpired:
            # Kill the entire process group to avoid orphan processes.
            # Never killpg() PID 0 or 1 — they belong to init/system.
            try:
                if os.name == 'posix' and process.pid and process.pid > 1:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass  # process already exited or cannot be killed
            stdout, stderr = process.communicate()  # reap the process
            raw_output = (stdout or "") + (stderr or "")
            result["status"] = "timeout"
            result["failure_kind"] = "timeout"
            result["next_action_hint"] = _build_next_action_hint("timeout")
            result["message"] = f"Timeout reached! Killed after {timeout_limit} seconds."
            result["output"] = _trim_output(raw_output, output_max_chars)
            result["stdout"] = _trim_output(stdout or "", output_max_chars)
            result["stderr"] = _trim_output(stderr or "", output_max_chars)
            result["return_code"] = None
        else:
            raw_output = stdout + stderr
            result["output"] = _trim_output(raw_output, output_max_chars)
            result["stdout"] = _trim_output(stdout, output_max_chars)
            result["stderr"] = _trim_output(stderr, output_max_chars)
            result["return_code"] = process.returncode

            result["assertion_results"] = validate_result(
                case["expected"], result, workspace,
                update_baseline=update_baseline,
                error_analysis=error_analysis,
            )
            result["status"] = "passed"
    except ValidationError as exc:
        result["message"] = str(exc)
        result["failure_kind"] = exc.failure_kind
        result["compare_failures"] = _trim_compare_failures(exc.compare_failures)
        result["baseline_updated"] = exc.baseline_updated
        result["assertion_results"] = exc.assertion_results
        result["next_action_hint"] = _build_next_action_hint(
            exc.failure_kind, update_baseline=update_baseline,
        )
    except AssertionError as exc:
        # Legacy AssertionError catch for backward compatibility
        result["message"] = str(exc)
        result["failure_kind"] = result["failure_kind"] or "unknown"
        result["next_action_hint"] = _build_next_action_hint(result["failure_kind"])
    except Exception as exc:
        result["message"] = f"Execution error: {str(exc)}"
        result["failure_kind"] = "execution_error"
        result["next_action_hint"] = _build_next_action_hint("execution_error")
    finally:
        result["duration"] = time.perf_counter() - start_time

    return result


def execute_single_test_case(
    case: TestCaseData,
    workspace: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
    output_max_chars: int = DEFAULT_OUTPUT_MAX_CHARS,
) -> TestResultData:
    """
    Stateless execution of a single test case with optional retry.

    Args:
        case: Test case data (may include ``retry_count`` for automatic retries).
        workspace: Working directory for test execution.
        env: Optional environment variables to inject/override (merged with os.environ).
        update_baseline: If True, overwrite baseline files on comparison failure.
        output_max_chars: Max characters for output in result dict.

    ``retry_count`` (defaults to 0) controls how many additional times the
    command is re-run after the first failure.  ``retry_count=0`` means no
    retry (behaviour identical to previous versions).
    """
    retry_count: int = case.get("retry_count", 0)
    max_attempts = retry_count + 1
    total_duration = 0.0
    last_result: Optional[TestResultData] = None
    attempt_history: List[Dict[str, Any]] = []

    for attempt in range(1, max_attempts + 1):
        result = _execute_command_once(
            case, workspace, env,
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
                case["name"], attempt + 1, max_attempts,
            )

    if last_result is not None:
        last_result["duration"] = total_duration
        last_result["attempts"] = len(attempt_history)
        last_result["attempt_history"] = attempt_history
        if retry_count > 0 and last_result["status"] == "passed" and len(attempt_history) > 1:
            last_result["flaky"] = True

    return last_result if last_result is not None else result

