"""失败诊断（next_action_hint，原则 5：result consumer）。

自 1.3 ``core/execution.py::_build_next_action_hint`` 原样搬入（公开化命名）。
``command`` 字段由装配点填充（``attach_next_action_hint(s)``，CLI 报告
装配阶段 / TUI 表现层调用），orchestration 只产出 ``failure_kind``。
"""
from typing import Any, Dict, Optional


def build_next_action_hint(
    failure_kind: Optional[str],
    *,
    update_baseline: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build a structured remediation hint for a failed test case.

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


def _hint_command(
    case_name: str,
    config_path: Optional[str],
    *,
    is_update_baseline: bool,
) -> str:
    """Build the concrete re-run CLI command inside a hint."""
    base = f'symtest run "{config_path}"'
    if is_update_baseline:
        base += " --update-baseline"
    return f'{base} -t "{case_name}"'


def attach_next_action_hint(
    result: Dict[str, Any],
    *,
    update_baseline: bool = False,
    config_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Reporting 装配点：按 ``failure_kind`` 为单个失败结果填充 hint。

    Orchestration 只产出 ``failure_kind``（原则 5 单向流）；本函数在结果
    装配/输出阶段（CLI 报告输出前 / TUI run_case）调用，为 ``failure_kind``
    非空的结果构建结构化建议并填充具体 CLI 命令。已带 hint 的结果只补
    command 字段（幂等）。

    Returns:
        填充后的 hint；结果无失败结论时为 ``None``。
    """
    hint = result.get("next_action_hint")
    if hint is None:
        failure_kind = result.get("failure_kind")
        if not failure_kind:
            return None
        hint = build_next_action_hint(failure_kind, update_baseline=update_baseline)
        result["next_action_hint"] = hint
    if hint and not hint.get("command") and config_path is not None:
        # 与 1.3 runner 行为一致：--update-baseline 标志只由 hint 的 action
        # 决定（update_baseline 形态仅在未开启 --update-baseline 时出现）。
        hint["command"] = _hint_command(
            result.get("name", ""), config_path,
            is_update_baseline=(hint.get("action") == "update_baseline"),
        )
    return hint


def attach_next_action_hints(
    results: Dict[str, Any],
    *,
    update_baseline: bool = False,
    config_path: Optional[str] = None,
) -> None:
    """对整次运行的 ``results``（含 ``details`` 列表）批量装配 hint。

    CLI 报告输出前的唯一装配点，覆盖顺序 / 并行 / skip 全部路径；
    passed / skipped 结果无 ``failure_kind``，天然不产生 hint。
    """
    for detail in results.get("details", []):
        attach_next_action_hint(
            detail, update_baseline=update_baseline, config_path=config_path,
        )
