# -*- coding: utf-8 -*-
"""平台进程组测量后端的统一入口（原则 2 的分发层）。

按 ``os.name`` 分发到具体后端，自身不含任何逻辑：

- Windows：``windows_job.py``（Job Object，提交内存峰值）；
- Linux：``linux_cgroup.py``（cgroup v2，整组记账峰值）。

调用方（executor）只面向本模块的中性命名，两个后端的行为契约一致：
start 失败抛后端异常（调用方回退普通 subprocess）、wait 超时返回
False、query 失败返回 None、close 幂等清理。
"""
import os

from . import linux_cgroup, windows_job


def is_supported() -> bool:
    """当前平台是否有可用的进程组测量后端。"""
    if os.name == "nt":
        return windows_job.is_supported()
    return linux_cgroup.is_supported()


def start_group(cmd_list, cwd=None, env=None):
    """以测量方式启动命令：返回 ``(Popen, handle)``，调用方负责 close。"""
    if os.name == "nt":
        return windows_job.start_in_job(cmd_list, cwd=cwd, env=env)
    return linux_cgroup.start_in_cgroup(cmd_list, cwd=cwd, env=env)


def wait_group(handle, timeout_ms: int) -> bool:
    """等待组内全部进程结束；True 已排空，False 超时。"""
    if os.name == "nt":
        return windows_job.wait_job_complete(handle, timeout_ms)
    return linux_cgroup.wait_complete(handle, timeout_ms)


def terminate_group(handle) -> None:
    """终止组内全部进程（超时清理整组）。失败仅记录。"""
    if os.name == "nt":
        windows_job.terminate_job(handle)
    else:
        linux_cgroup.terminate(handle)


def query_peak_bytes(handle):
    """读取组内存峰值（字节）；测量不可用返回 None。"""
    if os.name == "nt":
        return windows_job.query_peak_memory_bytes(handle)
    return linux_cgroup.query_peak_bytes(handle)


def query_cpu_time(handle):
    """Windows Job user + kernel seconds; None on unsupported/query failure."""
    if os.name == "nt":
        return windows_job.query_cpu_time(handle)
    return None


def close_group(handle) -> None:
    """清理组资源（句柄/目录）。"""
    if os.name == "nt":
        windows_job.close_job(handle)
    else:
        linux_cgroup.close_group(handle)


def peak_source() -> str:
    """当前平台后端的峰值数据来源标识（写入 peak_memory_source）。"""
    if os.name == "nt":
        return windows_job.PEAK_SOURCE
    return linux_cgroup.PEAK_SOURCE
