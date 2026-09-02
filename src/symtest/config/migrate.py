"""v1 平铺配置 → v2 分层配置的确定性机械映射（1.4 Phase 4）。

只做字段搬迁，不做任何语义解释：
- ``command/args/timeout/retry_count/env/steps`` → ``execution``；
- ``expected`` → ``expected``（位置不变）；
- ``depends_on/resources`` → ``scheduling``；
- 顶层 metadata（``name/description/tags/xfail_*/abstract/extends/
  variables/import/setup``）原样保留。

设计约束（docs/design_1_4.md §六 迁移设计）：
- 纯函数：结构化 dict 变换，不做 import 展开、不做路径解析、不校验必填
  （校验归 ``symtest validate``）；
- 幂等：输入已是 v2（含 ``execution``）时原样深拷贝返回；
- 可机械转换部分之外的项目特有内容（自定义 comparator、复杂 inheritance、
  workspace 插件等）由迁移复查 Skill 人工判断。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

# v1 平铺字段 → v2 去向
EXECUTION_FIELDS = ("command", "args", "timeout", "retry_count", "env", "steps")
SCHEDULING_FIELDS = ("depends_on", "resources")

# v2 输出中 metadata 的期望排列顺序（仅影响美观，不影响语义）
_METADATA_ORDER = (
    "name",
    "description",
    "tags",
    "expected_failure",
    "xfail_reason",
    "xfail_quiet",
    "abstract",
    "extends",
    "variables",
    "import",
)


def migrate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """迁移单个 test case dict（v1 平铺 → v2 分层）。

    已是 v2（含 ``execution``）的 case 原样深拷贝返回（幂等）。
    非 dict 元素（如 ``import`` 引用展开前的其他形态）原样返回。
    """
    if not isinstance(case, dict):
        return case
    if "execution" in case:
        return copy.deepcopy(case)

    execution: Dict[str, Any] = {k: case[k] for k in EXECUTION_FIELDS if k in case}
    scheduling: Dict[str, Any] = {k: case[k] for k in SCHEDULING_FIELDS if k in case}
    rest: Dict[str, Any] = {
        k: v for k, v in case.items()
        if k not in EXECUTION_FIELDS and k not in SCHEDULING_FIELDS
    }

    result: Dict[str, Any] = {}
    for key in _METADATA_ORDER:
        if key in rest:
            result[key] = rest.pop(key)
    # 其余未知/自定义字段保持在 metadata 区（v2 允许的顶层字段之外的内容
    # 交由 symtest validate 与迁移复查 Skill 判断）
    result.update(rest)

    expected = result.pop("expected", None)
    if execution:
        result["execution"] = execution
    if expected is not None:
        result["expected"] = expected
    if scheduling:
        result["scheduling"] = scheduling
    return result


def migrate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """迁移整个配置 dict（v1 平铺 → v2 分层）。

    仅处理 ``test_cases`` 数组内的 case；``setup`` 等顶层键原样保留。
    """
    if not isinstance(config, dict):
        raise ValueError("Config must be a dict (JSON/YAML object)")
    if "test_cases" not in config:
        raise ValueError("Config is missing the 'test_cases' field")

    result: Dict[str, Any] = {}
    for key, value in config.items():
        if key == "test_cases":
            cases: List[Any] = value if isinstance(value, list) else []
            result[key] = [migrate_case(tc) for tc in cases]
        else:
            result[key] = copy.deepcopy(value)
    return result
