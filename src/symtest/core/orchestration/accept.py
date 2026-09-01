"""``--update-baseline`` 的 accept 步骤（原则 3 受控写盘点）。

Validator 永远只读（原则 3）；baseline 覆盖（复制 actual → baseline）由
编排层在一次 attempt（execute → validate）拿到失败结论后执行，属独立的
accept 步骤，不是验证的一部分。

行为与 1.3 ``Assertions.compare_files(update_baseline=True)`` 逐位保持：
- 仅当失败原因是"内容不一致"（比较器本身未出错）时接受；
- 路径解析 / makedirs / copy2 语义不变；
- 部分接受后遇错中止时，已复制的文件保留（与 1.3 一致）；
- 接受成功后 compare_files 断言条目改写为 passed=True 并携带
  ``baseline_updated``（与 1.3 ``_dispatch_file_compare`` 成功分支一致）。
"""
import logging
import os
import shutil
from typing import Any, Dict, List, Optional

from ..validation.result import ValidationResult

logger = logging.getLogger("symtest.core.orchestration.accept")


def _resolve(path: str, workspace: Optional[str]) -> str:
    """与 1.3 ``Assertions.compare_files`` 相同的 workspace 路径解析。"""
    if path and workspace and not os.path.isabs(path):
        return os.path.join(workspace, path)
    return path


def apply_baseline_accept(
    validation_result: ValidationResult,
    workspace: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """尝试接受 ``--update-baseline``：复制 actual → baseline 并改判通过。

    :param validation_result: 只读验证的失败结论。
    :param workspace: 用于解析 compare_files 中的相对路径。
    :returns: 全部失败断言均可接受时，返回改写后的完整
              ``assertion_results`` 列表（失败条目替换为成功条目）；
              任一条目不可接受（比较器错误、路径缺失、复制失败）则返回
              ``None``，由调用方保留失败结论（investigate）。
    """
    rebuilt: List[Dict[str, Any]] = []
    accepted_all = True

    for entry in validation_result.assertion_results:
        if entry.get("assertion") == "compare_files" and entry.get("passed") is False:
            cf_list = entry.get("compare_failures") or []
            response = cf_list[0] if cf_list else None
            if (
                response is None
                or response.get("error")
                or not response.get("actual")
                or not response.get("baseline")
            ):
                accepted_all = False
                rebuilt.append(entry)
                continue

            actual_orig = response["actual"]
            baseline_orig = response["baseline"]
            actual_path = _resolve(actual_orig, workspace)
            baseline_path = _resolve(baseline_orig, workspace)

            try:
                # Overwrite baseline with actual
                os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
                shutil.copy2(actual_path, baseline_path)
            except OSError as exc:
                logger.warning(
                    "  [UPDATE BASELINE] failed to copy %s → %s: %s",
                    actual_orig, baseline_orig, exc,
                )
                accepted_all = False
                rebuilt.append(entry)
                continue

            logger.info("  [UPDATE BASELINE] %s → %s", actual_orig, baseline_orig)
            rebuilt.append({
                "assertion": "compare_files",
                "passed": True,
                "error_stats": response.get("error_stats"),
                "compare_failures": [],
                "baseline_updated": [baseline_orig],
                "message": "",
            })
        else:
            rebuilt.append(entry)

    return rebuilt if accepted_all else None
