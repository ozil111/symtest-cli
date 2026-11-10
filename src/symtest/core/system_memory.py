# -*- coding: utf-8 -*-
"""系统内存快照（调度层只读事实）。

为并行调度的内存准入提供当前机器的内存余量：

- Windows：``GlobalMemoryStatusEx`` 读取可用物理内存（含可回收 standby 页），
  ``GetPerformanceInfo`` 计算系统提交余量
  ``(CommitLimit − CommitTotal) × PageSize``。两者口径不同：物理内存是否
  充足与系统还能承诺多少内存，应分别检查。
- 非 Windows 平台本轮不实现（返回全 ``None`` 的快照），调用方按
  "不可用"降级处理，不得据此阻塞调度。

快照只描述事实，不含任何判定语义（够不够由调度层决定）。
"""
import logging
import os
from dataclasses import dataclass
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
    if os.name != "nt":
        return MemorySnapshot()
    try:
        return _read_windows_snapshot()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Memory snapshot unavailable: %s", exc)
        return MemorySnapshot()


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
