"""执行层（原则 2）：纯 subprocess → ExecutionResult。

Executor 不知道"通过/失败"：不 import assertions/validation，
不感知 expected / baseline / next_action_hint / status。
"""
from .executor import (
    DEFAULT_OUTPUT_MAX_CHARS,
    execute_command,
)
from .result import ExecutionResult

__all__ = [
    "DEFAULT_OUTPUT_MAX_CHARS",
    "ExecutionResult",
    "execute_command",
]
