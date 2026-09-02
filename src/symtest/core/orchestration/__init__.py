"""编排层（原则 4）：组合执行与验证，不实现底层语义。

- ``single``：单用例 attempt 组合（execute → validate → [accept]）+
  retry policy + attempt_history / flaky 聚合；
- ``sequence``：sequence 引擎（自 config_loader 迁入）；
- ``accept``：``--update-baseline`` 的独立 accept 步骤（原则 3 例外处理）。

依赖方向：orchestration 可 import execution 与 validation；execution 与
validation 互不 import。
"""
from .single import execute_single_test_case
from .sequence import execute_sequence

__all__ = [
    "execute_single_test_case",
    "execute_sequence",
]
