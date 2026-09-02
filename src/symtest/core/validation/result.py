"""ValidationResult：验证结论（原则 3）。

Validator 的输出：判定结论 + 每条断言的明细。纯数据，跨进程序列化安全。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ValidationResult:
    """一次验证（ExpectationSpec vs ExecutionResult）的结论。"""

    passed: bool
    failure_kind: Optional[str] = None
    # 'return_code' | 'output_contains' | 'output_matches' |
    # 'file_compare' | 'timeout' | 'execution_error' | 'unknown'
    message: str = ""
    assertion_results: List[Dict[str, Any]] = field(default_factory=list)
    compare_failures: List[Dict[str, Any]] = field(default_factory=list)
