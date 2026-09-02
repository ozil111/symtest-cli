"""Draft 配置规范化（宽松形态归一，1.4 原则 6 的 DSL 层配套）。

core parser 全系统唯一且只接受 canonical TestCase；半成品/草稿配置
（TUI 编辑中间态、v1 迁移输出等）先经 ``normalize_draft_config`` 补齐
必填字段缺省值，再调用严格 ``core.config_loader.parse_test_cases``。

本模块属于 ``config`` 层（DSL 规范化），不在 ``core`` 内 —— core 不提供
任何宽松解析形态。
"""
from __future__ import annotations

import copy
from typing import Any, Dict


def normalize_draft_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize half-finished draft cases into canonical config dicts.

    为缺字段的 case 补齐 canonical 必填项的缺省值（深拷贝，不改动入参）：

    - case 级：``name`` / ``execution`` / ``expected``；
    - 单命令形态：``execution.command`` / ``execution.args``；
    - steps 形态：每个 step 的 ``command`` / ``args`` / ``expected``。

    ``import`` 引用项原样跳过（由 import 展开管线处理）。
    """
    normalized = copy.deepcopy(config)
    for case in normalized.get("test_cases", []):
        if not isinstance(case, dict) or "import" in case:
            continue
        case.setdefault("name", "")
        execution = case.setdefault("execution", {})
        if "steps" in execution:
            for step in execution.get("steps", []):
                if isinstance(step, dict):
                    step.setdefault("command", "")
                    step.setdefault("args", [])
                    step.setdefault("expected", {})
        else:
            execution.setdefault("command", "")
            execution.setdefault("args", [])
        case.setdefault("expected", {})
    return normalized
