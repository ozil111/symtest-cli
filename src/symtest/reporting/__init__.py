"""Reporting / result-consumer 层（原则 5）。

``diagnosis.build_next_action_hint`` 是 result consumer：只消费失败结论，
不参与执行与判定。``attach_next_action_hint(s)`` 是表现层装配点：orchestration
只产出 ``failure_kind``，hint 在 CLI 报告装配阶段 / TUI run_case 填充。
"""
from .diagnosis import (
    attach_next_action_hint,
    attach_next_action_hints,
    build_next_action_hint,
)

__all__ = [
    "build_next_action_hint",
    "attach_next_action_hint",
    "attach_next_action_hints",
]
