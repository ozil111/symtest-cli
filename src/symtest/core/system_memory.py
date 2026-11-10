# -*- coding: utf-8 -*-
"""系统内存快照（调度层只读事实）。

为并行调度的内存准入提供当前机器的内存余量：

- Windows：``GlobalMemoryStatusEx`` 读取可用物理内存（含可回收 standby 页），
  ``GetPerformanceInfo`` 计算系统提交余量
  ``(CommitLimit − CommitTotal) × PageSize``。两者口径不同：物理内存是否
  充足与系统还能承诺多少内存，应分别检查。
- Linux：``/proc/meminfo`` 的 ``MemAvailable``（不发生交换情况下还能供新
  程序使用的内存，含部分可回收缓存）作为基准余量；若处于有限额的
  cgroup v2 中，则对当前组及全部祖先组计算 ``memory.max −
  memory.current`` 余量并取最小值，与 ``MemAvailable`` 取更小——避免只
  看到宿主机内存而忽略组限额。Linux 没有独立的系统级提交上限概念，
  有效余量（钳制后）同时充当物理余量与提交余量两种角色，总量取
  ``min(MemTotal, 最小组限额)``（水位校验据此在限额环境中正确拦截）。
- 其他平台不实现（返回全 ``None`` 的快照），调用方按"不可用"降级处理，
  不得据此阻塞调度。

快照只描述事实，不含任何判定语义（够不够由调度层决定）。
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("symtest.core.system_memory")


@dataclass(frozen=True)
class MemorySnapshot:
    """一次系统内存读取的只读事实（字节）。``None`` 表示该项不可用。"""

    total_physical_bytes: Optional[int] = None
    avail_physical_bytes: Optional[int] = None
    avail_commit_bytes: Optional[int] = None
    # 系统提交上限（CommitLimit × PageSize）；请求超过它则结构性不可满足
    commit_limit_bytes: Optional[int] = None

    @property
    def usable(self) -> bool:
        """至少读到了可用物理内存才视为可用快照。"""
        return self.avail_physical_bytes is not None


def read_memory_snapshot() -> MemorySnapshot:
    """读取当前系统内存快照；任何 API 失败返回不可用快照（不抛异常）。"""
    if os.name == "nt":
        try:
            return _read_windows_snapshot()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Memory snapshot unavailable: %s", exc)
            return MemorySnapshot()
    if os.name == "posix":
        try:
            return _read_linux_snapshot()
        except Exception as exc:
            logger.warning("Memory snapshot unavailable: %s", exc)
            return MemorySnapshot()
    return MemorySnapshot()


# ---------------------------------------------------------------------------
# Linux implementation (/proc + cgroup v2, no extra dependency)
# ---------------------------------------------------------------------------

_MEMINFO_PATH = Path("/proc/meminfo")
_SELF_CGROUP_PATH = Path("/proc/self/cgroup")
_CGROUP_ROOT = Path("/sys/fs/cgroup")


def _parse_meminfo(text: str) -> dict:
    """解析 /proc/meminfo 文本，返回 {"MemTotal": kB, ...}（int 值）。"""
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        tokens = rest.split()
        if tokens and tokens[0].isdigit():
            values[key.strip()] = int(tokens[0])
    return values


def _own_cgroup_relpath() -> Optional[str]:
    """读取 /proc/self/cgroup，返回 cgroup v2 相对路径（根组返回 ""）。"""
    content = _SELF_CGROUP_PATH.read_text(encoding="utf-8")
    for line in content.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and not parts[1]:
            return parts[2].strip().strip("/")
    return None


def _cgroup_limits() -> tuple:
    """对当前组及全部祖先组计算 (最小组限额, 最小组余量)。

    仅统计存在 ``memory.max`` 且值非 "max" 的层；缺文件或无限额的层
    不参与钳制。返回 ``(None, None)`` 表示无任何限额。
    """
    rel = _own_cgroup_relpath()
    if rel is None:
        return None, None
    nodes = [""] + [p for p in rel.split("/") if p]
    min_limit = None
    min_margin = None
    for i in range(len(nodes)):
        group_dir = _CGROUP_ROOT.joinpath(*nodes[: i + 1])
        try:
            text = (group_dir / "memory.max").read_text(encoding="utf-8")
            limit_kb = int(text.strip())
        except (OSError, ValueError):
            continue  # 无该文件（如根组）/ "max"（无限额）/ 读取失败
        if min_limit is None or limit_kb < min_limit:
            min_limit = limit_kb
        try:
            current_kb = int((group_dir / "memory.current")
                             .read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            current_kb = 0
        margin_kb = max(0, limit_kb - current_kb)
        if min_margin is None or margin_kb < min_margin:
            min_margin = margin_kb
    return min_limit, min_margin


def _read_linux_snapshot() -> MemorySnapshot:
    """Linux 快照：MemAvailable 与 cgroup 限额余量取更小值。"""
    meminfo = _parse_meminfo(_MEMINFO_PATH.read_text(encoding="utf-8"))
    total_kb = meminfo.get("MemTotal")
    if not total_kb:
        raise ValueError("MemTotal missing from /proc/meminfo")
    avail_kb = meminfo.get("MemAvailable", 0)

    limit_kb, margin_kb = _cgroup_limits()
    effective_kb = avail_kb
    if margin_kb is not None:
        effective_kb = min(effective_kb, margin_kb)
    if limit_kb is not None:
        total_kb = min(total_kb, limit_kb)

    effective = effective_kb * 1024
    return MemorySnapshot(
        total_physical_bytes=int(total_kb * 1024),
        avail_physical_bytes=int(max(effective, 0)),
        # Linux 无系统级提交上限概念：单一有效预算同时充当两种角色
        avail_commit_bytes=int(max(effective, 0)),
        commit_limit_bytes=int(total_kb * 1024),
    )


# ---------------------------------------------------------------------------
# Windows implementation (ctypes, no extra dependency)
# ---------------------------------------------------------------------------

def _read_windows_snapshot() -> MemorySnapshot:
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    class PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("CommitTotal", ctypes.c_size_t),
            ("CommitLimit", ctypes.c_size_t),
            ("CommitPeak", ctypes.c_size_t),
            ("PhysicalTotal", ctypes.c_size_t),
            ("PhysicalAvailable", ctypes.c_size_t),
            ("SystemCache", ctypes.c_size_t),
            ("KernelTotal", ctypes.c_size_t),
            ("KernelPaged", ctypes.c_size_t),
            ("KernelNonpaged", ctypes.c_size_t),
            ("PageSize", ctypes.c_size_t),
            ("HandleCount", wintypes.DWORD),
            ("ProcessCount", wintypes.DWORD),
            ("ThreadCount", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError(f"GlobalMemoryStatusEx failed: {ctypes.get_last_error()}")

    perf = PERFORMANCE_INFORMATION()
    perf.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
    if not psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
        raise OSError(f"GetPerformanceInfo failed: {ctypes.get_last_error()}")

    avail_commit = (perf.CommitLimit - perf.CommitTotal) * perf.PageSize

    return MemorySnapshot(
        total_physical_bytes=int(status.ullTotalPhys),
        avail_physical_bytes=int(status.ullAvailPhys),
        avail_commit_bytes=int(max(avail_commit, 0)),
        commit_limit_bytes=int(perf.CommitLimit * perf.PageSize),
    )
