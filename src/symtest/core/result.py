"""TestResult：Execution + Validation + 编排元数据的组合类型（1.4 v2）。

``to_dict()`` 产出与 1.3 完全一致的 ``TestResultData`` wire format ——
runner / reporter / TUI / CLI 消费的结果 JSON 结构逐位保持，本类型只是
编排层内部的结构化表示。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TestResult:
    """一次 attempt（execute → validate → [accept]）的组合结论。"""

    # ── 执行事实（来自 ExecutionResult） ──
    name: str = ""
    command: str = ""
    return_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    output: str = ""
    duration: float = 0.0

    # ── 验证结论（来自 ValidationResult） ──
    status: str = "failed"  # 'passed' | 'failed' | 'timeout'
    message: str = ""
    failure_kind: Optional[str] = None
    assertion_results: List[Dict[str, Any]] = field(default_factory=list)
    compare_failures: List[Dict[str, Any]] = field(default_factory=list)

    # ── 编排元数据（retry / xfail / 用例描述） ──
    attempts: int = 1
    flaky: bool = False
    attempt_history: List[Dict[str, Any]] = field(default_factory=list)
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    baseline_updated: List[str] = field(default_factory=list)
    failed_step: Optional[int] = None
    expected: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    next_action_hint: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为 1.3 兼容的 ``TestResultData`` wire format。"""
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "command": self.command,
            "output": self.output,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration": self.duration,
            "expected": self.expected,
            "description": self.description,
            "tags": self.tags,
            "failure_kind": self.failure_kind,
            "attempts": self.attempts,
            "flaky": self.flaky,
            "attempt_history": self.attempt_history,
            "step_results": self.step_results,
            "compare_failures": self.compare_failures,
            "baseline_updated": self.baseline_updated,
            "failed_step": self.failed_step,
            "assertion_results": self.assertion_results,
            "next_action_hint": self.next_action_hint,
        }
