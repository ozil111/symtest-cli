"""
Unified configuration parsing layer.

Shared logic for loading test cases from a config dict (already parsed from
JSON/YAML) into TestCase objects, and for executing sequence test cases.

Backward-compatible: the runner classes still expose ``load_test_cases()`` and
``_run_sequence()`` as before; they merely delegate to the functions here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .test_case import TestCase, TestCaseStep
from .execution import execute_single_test_case
from ..utils.path_resolver import resolve_paths

logger = logging.getLogger("cli_test_framework.core.config_loader")

# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')


def substitute_placeholders(
    config: Dict[str, Any],
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """递归替换 config 中字符串值的 ``{placeholder}`` 占位符。

    只替换 ``variables`` 中存在的 key，未匹配的 ``{xxx}`` 原样保留，
    不会影响 ``expected.matches`` 等字段中的正则模式（如 ``{2}``）。
    """
    if not variables:
        return config

    def _sub(value: Any) -> Any:
        if isinstance(value, str):
            return _PLACEHOLDER_RE.sub(
                lambda m: str(variables[m.group(1)])
                if m.group(1) in variables else m.group(0),
                value,
            )
        if isinstance(value, list):
            return [_sub(item) for item in value]
        if isinstance(value, dict):
            return {k: _sub(v) for k, v in value.items()}
        return value

    return _sub(config)


# ---------------------------------------------------------------------------
# Test-case parsing (loaded dict → list[TestCase])
# ---------------------------------------------------------------------------

def _split_and_resolve(
    command_string: str,
    args: List[str],
    workspace: Path,
    path_resolver: Any,
) -> Tuple[str, List[str]]:
    """Split a command string into executable + leading args, then resolve paths.

    ``path_resolver`` must be a ``PathResolver`` instance (or duck-typed
    equivalent with ``split_command`` / ``resolve_paths`` methods).
    """
    executable, leading_args = path_resolver.split_command(command_string)
    return executable, (
        resolve_paths(leading_args, str(workspace))
        + path_resolver.resolve_paths(args)
    )


def parse_test_cases(
    config: Dict[str, Any],
    workspace: Optional[Path] = None,
    path_resolver: Any = None,
) -> List[TestCase]:
    """Parse ``config['test_cases']`` into a list of ``TestCase`` objects.

    Supports both single-command mode and sequence (``steps``) mode.

    When *workspace* and *path_resolver* are provided (Runner mode),
    required fields are validated and command/args paths are resolved.
    When omitted (TUI mode), missing fields get sensible defaults and
    raw values are kept as-is for display purposes.
    """
    cases: List[TestCase] = []
    resolve = workspace is not None and path_resolver is not None

    for case in config.get("test_cases", []):
        if "steps" in case:
            # ── Sequence mode ──
            steps: List[TestCaseStep] = []
            for step in case.get("steps", []):
                if resolve:
                    step_required = ["command", "args", "expected"]
                    if not all(field in step for field in step_required):
                        raise ValueError(
                            f"Step in test case '{case.get('name', 'unnamed')}' "
                            f"is missing required fields"
                        )
                    executable, resolved_args = _split_and_resolve(
                        step["command"], step["args"], workspace, path_resolver
                    )
                    steps.append(TestCaseStep(
                        command=executable,
                        args=resolved_args,
                        expected=step["expected"],
                        timeout=step.get("timeout"),
                        retry_count=step.get("retry_count", 0),
                    ))
                else:
                    steps.append(TestCaseStep(
                        command=step.get("command", ""),
                        args=step.get("args", []),
                        expected=step.get("expected", {}),
                        timeout=step.get("timeout"),
                        retry_count=step.get("retry_count", 0),
                    ))
            cases.append(TestCase(
                name=case.get("name", ""),
                steps=steps,
                expected=case.get("expected", {}),
                description=case.get("description", ""),
                resources=case.get("resources"),
                tags=case.get("tags", []),
            ))
        else:
            # ── Single-command mode (backward-compatible) ──
            if resolve:
                required_fields = ["name", "command", "args", "expected"]
                if not all(field in case for field in required_fields):
                    raise ValueError(
                        f"Test case {case.get('name', 'unnamed')} "
                        f"is missing required fields"
                    )
                executable, resolved_args = _split_and_resolve(
                    case["command"], case["args"], workspace, path_resolver
                )
                cases.append(TestCase(
                    name=case["name"],
                    command=executable,
                    args=resolved_args,
                    expected=case["expected"],
                    description=case.get("description", ""),
                    timeout=case.get("timeout"),
                    resources=case.get("resources"),
                    tags=case.get("tags", []),
                    retry_count=case.get("retry_count", 0),
                ))
            else:
                cases.append(TestCase(
                    name=case.get("name", ""),
                    command=case.get("command", ""),
                    args=case.get("args", []),
                    expected=case.get("expected", {}),
                    description=case.get("description", ""),
                    timeout=case.get("timeout"),
                    resources=case.get("resources"),
                    tags=case.get("tags", []),
                    retry_count=case.get("retry_count", 0),
                ))

    return cases


# ---------------------------------------------------------------------------
# Step helper (duck-typed access for TestCaseStep / dict)
# ---------------------------------------------------------------------------

def _step_attr(step: Any, key: str, default: Any = None) -> Any:
    """Get attribute from a ``TestCaseStep`` or key from a ``dict``."""
    if isinstance(step, dict):
        return step.get(key, default)
    return getattr(step, key, default)


# ---------------------------------------------------------------------------
# Shared sequence execution (TestCaseStep list → result dict)
# ---------------------------------------------------------------------------

def execute_sequence(
    case_name: str,
    steps: List[Any],
    workspace: Optional[str] = None,
    *,
    print_prefix: str = "",
    lock: Any = None,
    executor: Any = None,
    case_expected: Optional[Dict[str, Any]] = None,
    update_baseline: bool = False,
    resume: bool = False,
) -> Dict[str, Any]:
    """Execute a sequence test case (fail-fast).

    ``steps`` may be a list of ``TestCaseStep`` objects or plain dicts
    containing ``command`` / ``args`` / ``expected`` / (optional) ``timeout``.

    Parameters
    ----------
    case_name:
        Name of the test case (used in step-names and the result).
    steps:
        Ordered list of steps to execute.
    workspace:
        Working directory for command execution.
    print_prefix:
        Optional prefix printed before every message (e.g. ``"[Worker]"``).
    lock:
        Deprecated; retained for backward compatibility with callers that
        still pass a ``threading.Lock``.  Logging is natively thread-safe,
        so the lock is no longer used.
    executor:
        Optional override for ``execute_single_test_case``.
        Defaults to the canonical import; callers that need monkeypatch
        support (e.g. process_worker) should pass their own reference.
    case_expected:
        Optional case-level ``expected`` assertions (return_code,
        output_contains, output_matches, compare_files) that are
        evaluated after *all* steps pass.  Supports the same fields
        as step-level ``expected``.
    update_baseline:
        If True, overwrite baseline files on comparison failure in steps.
        Forwarded to ``execute_single_test_case`` for each step.
    resume:
        If True, attempt to skip already-passed steps by loading persisted
        state from ``.cli-test/sequence_state/<case_name>.json``.  When the
        config hash matches, previously passed steps are skipped and their
        cached outputs are spliced into ``combined_output``.  When the full
        case passes, the state file is deleted.  Uses a pure-trust model:
        no artifact validation is performed.
    """
    if executor is None:
        executor = execute_single_test_case

    combined_output = ""
    total_duration = 0.0
    all_passed = True
    last_result = None
    failed_step = None
    step_results: List[Dict[str, Any]] = []
    case_assertion_results: List[Dict[str, Any]] = []
    case_hint: Optional[Dict[str, Any]] = None

    prefix = f"{print_prefix} " if print_prefix else ""

    # ── Resume: skip previously passed steps ──
    start_step = 0
    state = None
    if resume and workspace:
        from .sequence_state import (
            compute_config_hash,
            load_sequence_state,
            load_step_output,
            save_sequence_state,
        )

        config_hash = compute_config_hash(steps, case_expected)
        state = load_sequence_state(workspace, case_name)

        if state and state.get("config_hash") == config_hash:
            saved_steps = state.get("steps", {})
            for idx in sorted(int(k) for k in saved_steps.keys()):
                if idx - 1 >= len(steps):
                    break
                sinfo = saved_steps[str(idx)]
                if sinfo.get("status") != "passed":
                    break  # stop at first unpassed step

                # Reconstruct this step as "resumed"
                cached = load_step_output(workspace, case_name, idx)
                if cached is None:
                    logger.warning(
                        "  %sResume: cached output for step %d missing; "
                        "restarting from step 1.",
                        prefix, idx,
                    )
                    start_step = 0
                    combined_output = ""
                    total_duration = 0.0
                    step_results.clear()
                    break

                step = steps[idx - 1]
                command_str = (
                    f"{_step_attr(step, 'command')} "
                    f"{' '.join(_step_attr(step, 'args'))}".strip()
                )
                step_results.append({
                    "step": idx,
                    "name": f"{case_name} [step {idx}/{len(steps)}]",
                    "status": "passed",
                    "message": "",
                    "duration": sinfo.get("duration", 0),
                    "command": command_str,
                    "resumed": True,
                })
                combined_output += cached
                total_duration += sinfo.get("duration", 0)
                start_step = idx  # next step to run

            if start_step > 0:
                logger.info(
                    "  %sResume: skipping %d already-passed step(s), "
                    "starting at step %d.",
                    prefix, start_step, start_step + 1,
                )
        elif state and state.get("config_hash") != config_hash:
            logger.info(
                "  %sResume: config changed; discarding stale state "
                "and running full sequence.",
                prefix,
            )
        else:
            logger.info(
                "  %sResume: no saved state for '%s'; running full sequence.",
                prefix, case_name,
            )
    elif resume and not workspace:
        logger.warning(
            "  %sResume: no workspace set; cannot load sequence state.",
            prefix,
        )

    for i, step in enumerate(steps):
        if i < start_step:
            continue  # already resumed

        step_idx = i + 1
        step_name = f"{case_name} [step {step_idx}/{len(steps)}]"
        step_case: Dict[str, Any] = {
            "name": step_name,
            "command": _step_attr(step, "command"),
            "args": _step_attr(step, "args"),
            "expected": _step_attr(step, "expected"),
            "description": None,
            "timeout": _step_attr(step, "timeout"),
            "resources": None,
            "retry_count": _step_attr(step, "retry_count", 0),
        }

        command_preview = (
            f"{step_case['command']} {' '.join(step_case['args'])}".strip()
        )
        logger.info("  %sExecuting step %d/%d: %s", prefix, step_idx, len(steps), command_preview)

        result = executor(step_case, workspace, update_baseline=update_baseline)

        if result["output"].strip():
            logger.debug("  %sCommand output for %s:", prefix, step_name)
            for line in result["output"].splitlines():
                logger.debug("    %s", line)

        step_result = {
            "step": step_idx,
            "name": step_name,
            "status": result["status"],
            "message": result.get("message", ""),
            "duration": result.get("duration", 0),
            "command": f"{step_case['command']} {' '.join(step_case['args'])}".strip(),
        }
        step_results.append(step_result)

        combined_output += result["output"]
        total_duration += result["duration"]
        last_result = result

        if result["status"] != "passed":
            all_passed = False
            failed_step = step_idx
            if result.get("message"):
                logger.error("  %sError at step %d: %s", prefix, step_idx, result["message"])
            break

        # ── Persist step progress for resume ──
        if resume and workspace:
            from .sequence_state import (
                compute_config_hash,
                save_sequence_state,
                save_step_output,
            )

            if state is None:
                config_hash = compute_config_hash(steps, case_expected)
                state = {
                    "case": case_name,
                    "config_hash": config_hash,
                    "steps": {},
                }

            state["steps"][str(step_idx)] = {
                "status": "passed",
                "duration": result.get("duration", 0),
            }
            save_sequence_state(workspace, case_name, state)
            save_step_output(
                workspace, case_name, step_idx, result["output"],
            )

    # ── Case-level assertions ──
    if all_passed and case_expected:
        try:
            from .execution import validate_result

            case_result: Dict[str, Any] = {
                "name": case_name,
                "status": "passed",
                "message": "",
                "command": "",
                # Validate against full combined output; only trim when reporting
                "output": combined_output,
                "return_code": last_result["return_code"] if last_result else None,
                "duration": total_duration,
            }
            case_assertion_results = validate_result(case_expected, case_result, workspace)
        except AssertionError as exc:
            from .execution import _build_next_action_hint

            all_passed = False
            failed_step = len(steps) + 1  # synthetic step number
            case_assertion_results = getattr(exc, "assertion_results", [])
            case_hint = _build_next_action_hint(
                getattr(exc, "failure_kind", None), update_baseline=update_baseline,
            )
            last_result = {
                "name": case_name,
                "status": "failed",
                "message": f"Case-level assertion failed: {exc}",
                "command": "",
                "output": "",
                "return_code": None,
                "duration": 0.0,
                "failure_kind": getattr(exc, "failure_kind", None),
                "compare_failures": getattr(exc, "compare_failures", []),
            }
            step_result = {
                "step": "case_assertion",
                "name": case_name,
                "status": "failed",
                "message": f"Case-level assertion failed: {exc}",
                "duration": 0,
                "command": "case-level expected check",
            }
            step_results.append(step_result)
            logger.error("  %sCase-level assertion failed: %s", prefix, exc)

    # ── Resume cleanup: delete state on full pass ──
    if resume and workspace and all_passed:
        from .sequence_state import delete_sequence_state

        delete_sequence_state(workspace, case_name)
        logger.info("  %sResume: full pass; sequence state cleaned up.", prefix)

    status = "passed" if all_passed else (last_result["status"] if last_result else "failed")
    message = ""
    if not all_passed:
        total_steps = len(steps) + (
            1 if case_expected and failed_step == len(steps) + 1 else 0
        )
        message = (
            f"Failed at step {failed_step}/{total_steps}: "
            f"{last_result['message']}" if last_result else "Unknown error"
        )

    # ── Output sliming: only keep the failed step's output ──
    # When all steps pass, keep the full combined output.
    # When a step or case-level assertion fails, only expose the failed step's
    # output (or empty for case-level failures).
    if all_passed:
        slim_output = combined_output
    elif last_result is not None:
        if failed_step == len(steps) + 1:
            slim_output = ""
        else:
            slim_output = last_result.get("output", "")
    else:
        slim_output = ""

    # ── assertion_results / next_action_hint resolution ──
    # Case-level assertion data takes precedence; otherwise propagate the
    # failed step's data so sequence results honor the same contract as
    # single-command results.
    if case_assertion_results:
        assertion_results = case_assertion_results
    elif not all_passed and last_result is not None:
        assertion_results = last_result.get("assertion_results", [])
    else:
        assertion_results = []

    if case_hint is not None:
        next_action_hint = case_hint
    elif not all_passed and last_result is not None:
        next_action_hint = last_result.get("next_action_hint")
    else:
        next_action_hint = None

    command_summary = " -> ".join(
        f"{_step_attr(s, 'command')} {' '.join(_step_attr(s, 'args'))}".strip()
        for s in steps
    )

    return {
        "name": case_name,
        "status": status,
        "message": message,
        "command": command_summary,
        "output": slim_output,
        "return_code": last_result["return_code"] if last_result else None,
        "duration": total_duration,
        "step_results": step_results,
        "failed_step": failed_step,
        "failure_kind": last_result.get("failure_kind") if last_result else None,
        "compare_failures": last_result.get("compare_failures", []) if last_result else [],
        "attempts": last_result.get("attempts", 1) if last_result else 1,
        "flaky": last_result.get("flaky", False) if last_result else False,
        "assertion_results": assertion_results,
        "next_action_hint": next_action_hint,
    }
