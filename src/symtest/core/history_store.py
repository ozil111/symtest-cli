# -*- coding: utf-8 -*-

"""
.symtest Runtime History Store

Manages persistent storage of per-case runtime history for smart scheduling
and regression detection.
"""

import json
import os
from typing import Dict, Optional

SYMTEST_FILENAME = "history.json"


def _empty_history() -> dict:
    """Return an empty history structure."""
    return {"version": 1, "cases": {}}


def ensure_symtest(history_dir: str) -> None:
    """Create .symtest in the directory if it doesn't exist."""
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_empty_history(), f, indent=2)


def load_history(history_dir: str) -> dict:
    """Load .symtest from the directory. Auto-init if missing."""
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    if not os.path.exists(path):
        ensure_symtest(history_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "cases" not in data:
        data["cases"] = {}
    return data


def save_history(history_dir: str, history: dict) -> None:
    """Write history back to .symtest."""
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_case(history: dict, name: str, duration: float) -> None:
    """Update a single case's record using cumulative average.

    兼容"只有内存记录、没有耗时字段"的记录（``update_case_memory`` 可
    先于任何 passed 运行创建记录）：缺失的 ``avg_duration`` / ``run_count``
    按 0 处理，不抛 KeyError。
    """
    cases = history.setdefault("cases", {})
    if name in cases:
        rec = cases[name]
        old_avg = rec.get("avg_duration", 0)
        count = rec.get("run_count", 0)
        rec["avg_duration"] = (old_avg * count + duration) / (count + 1)
        rec["last_duration"] = duration
        rec["run_count"] = count + 1
    else:
        cases[name] = {
            "avg_duration": duration,
            "last_duration": duration,
            "run_count": 1,
        }


def update_case_memory(
    history: dict, name: str, peak_bytes, source: Optional[str] = None,
) -> None:
    """Record one process-group memory-peak measurement (bytes).

    与耗时的累计平均语义相互独立：

    - 内存记录采用 ``last_peak_memory_bytes``（最近值）+
      ``max_peak_memory_bytes``（历史最大）+ ``peak_memory_count``
      （样本数）+ ``peak_memory_source``（测量来源，如
      ``windows_job_commit``）；调度估算使用历史最大值，偶发高峰
      不被平均稀释；
    - 记录条件与耗时不同：任何获得有效测量的运行都可记录（含
      failed / timeout），这些数据同样保护下一次调度决策；
    - 允许产生"只有内存字段、没有 avg_duration"的记录，耗时读取方
      （``update_case`` / ``check_regression``）均已兼容。

    ``peak_bytes`` 非正数或 ``None`` 视为无有效测量，直接忽略。
    """
    if not peak_bytes or peak_bytes <= 0:
        return
    cases = history.setdefault("cases", {})
    rec = cases.setdefault(name, {})
    rec["last_peak_memory_bytes"] = peak_bytes
    prev_max = rec.get("max_peak_memory_bytes")
    if prev_max is None or peak_bytes > prev_max:
        rec["max_peak_memory_bytes"] = peak_bytes
    rec["peak_memory_count"] = rec.get("peak_memory_count", 0) + 1
    if source:
        rec["peak_memory_source"] = source


def reset_cases(history: dict, case_names: set) -> int:
    """Remove given case names from history. Returns count of removed entries."""
    cases = history.get("cases", {})
    cleared = 0
    for name in case_names:
        if name in cases:
            del cases[name]
            cleared += 1
    return cleared


def check_regression(
    history: dict, name: str, duration: float, threshold: float = 1.5
) -> Optional[str]:
    """Return a warning message if duration exceeds avg * threshold, else None."""
    cases = history.get("cases", {})
    if name not in cases:
        return None
    avg = cases[name].get("avg_duration", 0)
    if avg <= 0:
        return None
    if duration > avg * threshold:
        ratio = duration / avg
        return (
            f"⚠ WARNING: Case '{name}' regressed: "
            f"{duration:.2f}s vs avg {avg:.2f}s ({ratio:.2f}x slower)"
        )
    return None
