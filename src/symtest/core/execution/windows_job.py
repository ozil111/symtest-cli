# -*- coding: utf-8 -*-
"""Windows Job Object 进程组管理（原则 2：纯执行事实）。

一次命令执行绑定一个 Job Object：

``创建 Job → 以挂起状态 Popen 主进程 → 主进程加入 Job → 恢复主线程
→ communicate/超时 → 读取 PeakJobMemoryUsed → 关闭句柄``

- 后代进程默认继承 Job 成员身份（"脚本 → 启动器 → 求解器"整组被统计）；
- 峰值由操作系统持续维护，无需采样即可捕捉短暂尖峰；
- ``PeakJobMemoryUsed`` 是**提交内存口径**，不是物理内存峰值，调用方
  不得将其描述为"峰值物理内存"；
- 超时经 ``TerminateJobObject`` 终止整组进程，消除只杀直接子进程的遗留；
- Job 设置了 ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``：SymTest 自身异常
  退出时组内进程随句柄关闭被清理，防止孤儿求解器；
- 任何 API 失败以 :class:`JobError` 抛出，调用方回退普通 subprocess 路径，
  测量不可用不影响执行与判定语义。
"""
import ctypes
import logging
import subprocess
from ctypes import wintypes
from typing import List, Optional, Tuple

logger = logging.getLogger("symtest.core.execution.windows_job")

#: 峰值数据来源标识（写入 ExecutionResult.peak_memory_source）
PEAK_SOURCE = "windows_job_commit"

# Windows API 常量
_CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INFINITE_MS = 0xFFFFFFFF


class JobError(Exception):
    """Job Object 操作失败（调用方应回退普通 subprocess 路径）。"""


# ---------------------------------------------------------------------------
# ctypes 结构定义
# ---------------------------------------------------------------------------

class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
    ]


def is_supported() -> bool:
    """仅 Windows 平台可用（本轮不实现 Linux cgroup）。"""
    import os
    return os.name == "nt"


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


# ---------------------------------------------------------------------------
# 公开操作
# ---------------------------------------------------------------------------

def start_in_job(
    cmd_list: List[str],
    cwd=None,
    env=None,
) -> Tuple[subprocess.Popen, int]:
    """以挂起状态创建子进程，绑定 Job 后恢复执行。

    挂起→绑定→恢复的顺序消除"Popen 返回后进程已派生后代、后代逃出
    Job"的竞态窗口。

    :returns: ``(Popen, job_handle)``；调用方负责 ``close_job``。
    :raises JobError: Job 创建 / 进程绑定 / 线程恢复失败。
    """
    kernel32 = _kernel32()

    # 1. 创建 Job 并设置 kill-on-close（异常退出时清理组内进程）
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise JobError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
    try:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise JobError(
                f"SetInformationJobObject failed: {ctypes.get_last_error()}")
    except Exception:
        kernel32.CloseHandle(job)
        raise

    # 2. 挂起创建主进程（stdout/stderr 管道行为与普通 Popen 完全一致）
    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,  # POSIX-only 参数，Windows 下忽略
            env=env,
            creationflags=_CREATE_SUSPENDED,
        )
    except Exception:
        kernel32.CloseHandle(job)
        raise

    # 3. 挂起的主进程加入 Job（此刻它还没有机会派生后代）
    try:
        process_handle = kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid)
        if not process_handle:
            raise JobError(
                f"OpenProcess({process.pid}) failed: {ctypes.get_last_error()}")
        try:
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                raise JobError(
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")
        finally:
            kernel32.CloseHandle(process_handle)

        # 4. 恢复主进程的全部线程（创建时刻只有主线程）
        _resume_process_threads(kernel32, process.pid)
    except Exception:
        # 绑定失败：终止挂起的进程并回退
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:  # pragma: no cover - best effort
            pass
        kernel32.CloseHandle(job)
        raise

    return process, job


def terminate_job(job: int) -> None:
    """终止 Job 内全部进程（超时清理整组，防遗留求解器）。失败仅记录。"""
    try:
        if not _kernel32().TerminateJobObject(job, 1):
            logger.warning(
                "TerminateJobObject failed: %s", ctypes.get_last_error())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("TerminateJobObject raised: %s", exc)


def wait_job_complete(job: int, timeout_ms: int) -> bool:
    """等待 Job 内全部进程结束（轮询进程数）。

    注意：Job 对象的 signaled 语义绑定 end-of-job-time 限制，成员全部
    退出**不会**置信号，不能用 ``WaitForSingleObject`` 等待排空；这里
    通过 ``JobObjectBasicProcessIdList`` 轮询 ``NumberOfAssignedProcesses``
    归零判断。已终止的进程立即移出 Job 成员列表，与句柄是否关闭无关。

    :returns: True 已排空；False 超时（后代进程仍在运行）。
    """
    import time as _time

    class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInJob", wintypes.DWORD),
            ("ProcessIdList", wintypes.DWORD * 1),  # 变长，实际按缓冲区大小
        ]

    _JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
    _POLL_INTERVAL_S = 0.1
    # 64 KiB 缓冲区可容纳约 1.6 万个 PID，覆盖大规模 MPI 场景
    buf_size = 65536
    buf = ctypes.create_string_buffer(buf_size)
    header = ctypes.cast(
        buf, ctypes.POINTER(_JOBOBJECT_BASIC_PROCESS_ID_LIST)).contents
    deadline = _time.monotonic() + timeout_ms / 1000.0

    try:
        kernel32 = _kernel32()
        while True:
            ok = kernel32.QueryInformationJobObject(
                job,
                _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                buf,
                buf_size,
                None,
            )
            if not ok:
                logger.warning(
                    "QueryInformationJobObject(process id list) failed: %s",
                    ctypes.get_last_error(),
                )
                return False
            if header.NumberOfAssignedProcesses == 0:
                return True
            if _time.monotonic() >= deadline:
                return False
            _time.sleep(_POLL_INTERVAL_S)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("wait_job_complete raised: %s", exc)
        return False


def query_peak_memory_bytes(job: int) -> Optional[int]:
    """读取 ``PeakJobMemoryUsed``（提交内存峰值，字节）。

    失败返回 ``None``（测量不可用），不得返回 0 伪装成功。
    """
    try:
        kernel32 = _kernel32()
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not kernel32.QueryInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise JobError(
                f"QueryInformationJobObject failed: {ctypes.get_last_error()}")
        peak = int(info.PeakJobMemoryUsed)
        return peak if peak > 0 else None
    except Exception as exc:
        logger.warning("query_peak_memory_bytes failed: %s", exc)
        return None


def close_job(job: int) -> None:
    """关闭 Job 句柄（kill-on-close：组内残留进程随之终止）。"""
    try:
        _kernel32().CloseHandle(job)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("close_job raised: %s", exc)


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _resume_process_threads(kernel32, pid: int) -> None:
    """枚举并恢复指定进程的所有线程（挂起创建后只有主线程）。"""
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INFINITE_MS:  # INVALID_HANDLE_VALUE
        raise JobError(
            f"CreateToolhelp32Snapshot failed: {ctypes.get_last_error()}")

    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        if not kernel32.Thread32First(snapshot, ctypes.byref(entry)):
            raise JobError(
                f"Thread32First failed: {ctypes.get_last_error()}")
        resumed = 0
        while True:
            if entry.th32OwnerProcessID == pid:
                thread_handle = kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread_handle:
                    try:
                        kernel32.ResumeThread(thread_handle)
                        resumed += 1
                    finally:
                        kernel32.CloseHandle(thread_handle)
            if not kernel32.Thread32Next(snapshot, ctypes.byref(entry)):
                break
        if resumed == 0:
            raise JobError(f"no thread resumed for pid {pid}")
    finally:
        kernel32.CloseHandle(snapshot)
