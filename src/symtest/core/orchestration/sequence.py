"""Sequence 引擎（原则 4：编排层）。

自 1.3 ``core/config_loader.py::execute_sequence`` / ``_step_attr`` 逐位
搬入；变化只有依赖归位：

- 单步执行经由 ``orchestration.single.execute_single_test_case``
  （executor 参数仍可注入，保持 monkeypatch 支持）；
- case 级判定经由 ``validation.validator.validate_result``（只读），
  ``--update-baseline`` 经由 ``orchestration.accept`` accept 步骤；
- 结果只携带 ``failure_kind``；``next_action_hint`` 由表现层装配点
  （``reporting.diagnosis.attach_next_action_hint``）填充（原则 5）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..execution.result import ExecutionResult
from ..test_case import ExecutionSpec
from ..validation.validator import validate_result
from ..validation.assertions import ValidationError  # noqa: F401  (legacy except 兼容)
from .accept import apply_baseline_accept
from .single import execute_single_test_case

logger = logging.getLogger("symtest.core.orchestration.sequence")


# ---------------------------------------------------------------------------
# Step helper (duck-typed access for TestStep / dict)
# ---------------------------------------------------------------------------

def _step_attr(step: Any, key: str, default: Any = None) -> Any:
    """Get attribute from a ``TestStep``（dict 支持已在 Phase 3 移除）。"""
    return getattr(step, key, default)


# ---------------------------------------------------------------------------
# Shared sequence execution (TestStep list → result dict)
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
    error_analysis: bool = False,
    resume: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a sequence test case (fail-fast).

    ``steps`` must be a list of ``TestStep`` objects（v2：dict 形态已在
    Schema v2 落地后移除，跨进程路径由 process_worker 重建为对象）。

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
        If True, accept comparison failures as new baselines
        （accept 步骤在编排层执行，Validator 只读）.
    resume:
        If True, attempt to skip already-passed steps by loading persisted
        state from ``.symtest/sequence_state/<case_name>.json``.  When the
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

    prefix = f"{print_prefix} " if print_prefix else ""

    # ── Resume: skip previously passed steps ──
    start_step = 0
    state = None
    if resume and workspace:
        from ..sequence_state import (
            compute_config_hash,
            load_sequence_state,
            load_step_output,
            save_sequence_state,
        )

        config_hash = compute_config_hash(steps, case_expected, env)
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
        step_spec = ExecutionSpec(
            name=step_name,
            command=_step_attr(step, "command"),
            args=_step_attr(step, "args"),
            timeout=_step_attr(step, "timeout"),
            retry_count=_step_attr(step, "retry_count", 0),
            env=env or {},
        )
        step_expected = _step_attr(step, "expected") or {}

        command_preview = (
            f"{step_spec.command} {' '.join(step_spec.args)}".strip()
        )
        logger.info("  %sExecuting step %d/%d: %s", prefix, step_idx, len(steps), command_preview)

        result = executor(
            step_spec, workspace,
            expectation=step_expected,
            update_baseline=update_baseline,
            error_analysis=error_analysis,
        )

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
            "command": f"{step_spec.command} {' '.join(step_spec.args)}".strip(),
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
            from ..sequence_state import (
                compute_config_hash,
                save_sequence_state,
                save_step_output,
            )

            if state is None:
                config_hash = compute_config_hash(steps, case_expected, env)
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
            # 合成 case 级执行事实：以全部步骤的合并输出与末步返回码参与判定
            case_exec = ExecutionResult(
                name=case_name,
                command="",
                return_code=last_result["return_code"] if last_result else None,
                output=combined_output,
                duration=total_duration,
            )
            case_vr = validate_result(
                case_expected, case_exec, workspace, error_analysis=error_analysis,
            )
            if case_vr.passed:
                case_assertion_results = case_vr.assertion_results
            else:
                # accept 步骤（原则 3：写盘在编排层，不在 Validator）
                accepted = None
                if update_baseline and case_vr.failure_kind == "file_compare":
                    accepted = apply_baseline_accept(case_vr, workspace)
                if accepted is not None:
                    case_assertion_results = accepted
                else:
                    all_passed = False
                    failed_step = len(steps) + 1  # synthetic step number
                    case_assertion_results = case_vr.assertion_results
                    last_result = {
                        "name": case_name,
                        "status": "failed",
                        "message": f"Case-level assertion failed: {case_vr.message}",
                        "command": "",
                        "output": "",
                        "return_code": None,
                        "duration": 0.0,
                        "failure_kind": case_vr.failure_kind,
                        "compare_failures": case_vr.compare_failures,
                    }
                    step_result = {
                        "step": "case_assertion",
                        "name": case_name,
                        "status": "failed",
                        "message": f"Case-level assertion failed: {case_vr.message}",
                        "duration": 0,
                        "command": "case-level expected check",
                    }
                    step_results.append(step_result)
                    logger.error("  %sCase-level assertion failed: %s", prefix, case_vr.message)
        except AssertionError as exc:
            all_passed = False
            failed_step = len(steps) + 1  # synthetic step number
            case_assertion_results = getattr(exc, "assertion_results", [])
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
        from ..sequence_state import delete_sequence_state

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

    # ── assertion_results resolution ──
    # Case-level assertion data takes precedence; otherwise propagate the
    # failed step's data so sequence results honor the same contract as
    # single-command results.  ``next_action_hint`` is left None here: the
    # presentation layer (reporting attach point) builds it from
    # ``failure_kind``（原则 5 单向流）.
    if case_assertion_results:
        assertion_results = case_assertion_results
    elif not all_passed and last_result is not None:
        assertion_results = last_result.get("assertion_results", [])
    else:
        assertion_results = []

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
        "next_action_hint": None,
    }
