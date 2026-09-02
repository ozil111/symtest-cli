"""失败诊断（next_action_hint，原则 5：result consumer）。

自 1.3 ``core/execution.py::_build_next_action_hint`` 原样搬入（公开化命名）。
``command`` 字段留 ``None``：本层不知道 config 文件路径，由 runner 填充
（见 ``BaseRunner._fill_hint_command``）。
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
