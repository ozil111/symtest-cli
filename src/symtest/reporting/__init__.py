"""Reporting / result-consumer 层（原则 5）。

``diagnosis.build_next_action_hint`` 是 result consumer：只消费失败结论，
不参与执行与判定。
"""
from .diagnosis import build_next_action_hint

__all__ = [
    "build_next_action_hint",
]
