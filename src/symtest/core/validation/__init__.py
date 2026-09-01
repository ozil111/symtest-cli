"""验证层（原则 3）：ExpectationSpec + ExecutionResult → ValidationResult。

Validator 不执行被测程序、不 retry、永远只读文件；``--update-baseline``
的写盘由编排层（orchestration.accept）在拿到 ValidationResult 后执行。
"""
from .assertions import Assertions, ValidationError
from .result import ValidationResult
from .validator import validate_result

__all__ = [
    "Assertions",
    "ValidationError",
    "ValidationResult",
    "validate_result",
]
