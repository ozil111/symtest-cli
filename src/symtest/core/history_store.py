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
REGRESSION_MIN_SAMPLES = 3


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


#: Linux cgroup v2 后端的峰值来源标识（见 execution/linux_cgroup.py）
LINUX_PEAK_SOURCE = "linux_cgroup_v2"


def update_case_memory(
    history: dict, name: str, peak_bytes, source: Optional[str] = None,
) -> None:
    """Record one process-group memory-peak measurement (bytes).

    与耗时的累计平均语义相互独立：

    - 内存记录采用最近值 + 历史最大 + 样本数；调度估算使用历史最大
      值，偶发高峰不被平均稀释；
    - 记录条件与耗时不同：任何获得有效测量的运行都可记录（含
      failed / timeout），这些数据同样保护下一次调度决策；
    - 允许产生"只有内存字段、没有 avg_duration"的记录，耗时读取方
      （``update_case`` / ``check_regression``）均已兼容。

    **峰值按来源隔离保存**：Linux cgroup 峰值与 Windows Job 提交峰值
    口径不同且数值不可比，分别写入 ``*_linux`` 字段与既有平铺字段，
    互不覆盖；调度读取方（``parallel_config_runner``）按平台读取对应
    字段，不得跨平台混用。

    ``peak_bytes`` 非正数或 ``None`` 视为无有效测量，直接忽略。
    """
    if not peak_bytes or peak_bytes <= 0:
        return
    cases = history.setdefault("cases", {})
    rec = cases.setdefault(name, {})
    if source == LINUX_PEAK_SOURCE:
        rec["last_peak_memory_bytes_linux"] = peak_bytes
        prev_max = rec.get("max_peak_memory_bytes_linux")
        if prev_max is None or peak_bytes > prev_max:
            rec["max_peak_memory_bytes_linux"] = peak_bytes
        rec["peak_memory_count_linux"] = (
            rec.get("peak_memory_count_linux", 0) + 1)
        return
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
    history: dict, name: str, duration: float, threshold: float = 1.5,
    cpu_time: Optional[float] = None,
) -> Optional[str]:
    """Warn above avg * threshold only after 3 prior successful timing samples.

    度量口径选择（见 ``base_runner._update_history``）：

    - 本次带 ``cpu_time``（Windows Job 测量）：只用 CPU 历史比较；CPU 样本
      不足时本次不告警、不回退墙钟（回退会重现并行负载下的墙钟误报）；
    - 本次无 ``cpu_time``（Linux / 测量失败）：退化为既有墙钟逻辑。
    """
    cases = history.get("cases", {})
    if name not in cases:
        return None
    if cpu_time is not None:
        if cases[name].get("cpu_run_count", 0) < REGRESSION_MIN_SAMPLES:
            return None
        avg = cases[name].get("avg_cpu_time", 0)
        if avg <= 0:
            return None
        if cpu_time > avg * threshold:
            ratio = cpu_time / avg
            return (
                f"⚠ WARNING: Case '{name}' regressed: "
                f"{cpu_time:.2f}s CPU vs avg {avg:.2f}s CPU ({ratio:.2f}x slower)"
            )
        return None
    if cases[name].get("run_count", 0) < REGRESSION_MIN_SAMPLES:
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


def update_case_cpu(history: dict, name: str, cpu_time: float) -> None:
    """Store measured Windows process-group CPU seconds, independently of wall time."""
    rec = history.setdefault("cases", {}).setdefault(name, {})
    count = rec.get("cpu_run_count", 0)
    rec["avg_cpu_time"] = (rec.get("avg_cpu_time", 0) * count + cpu_time) / (count + 1)
    rec["last_cpu_time"] = cpu_time
    rec["cpu_run_count"] = count + 1
    rec["cpu_time_source"] = "windows_job"
