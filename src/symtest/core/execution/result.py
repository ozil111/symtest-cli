"""ExecutionResult：纯执行事实（原则 2）。

只包含执行事实：``return_code / stdout / stderr / output / duration /
timed_out / error``；``peak_memory_bytes`` / ``peak_memory_source`` 是
进程组内存峰值的执行事实（Windows 提交内存口径），仅在有效测量时非空，
测量不可用时保持 ``None``（不得用 0 表示未知）。"timeout 是否算失败"由
Validator 判定，这里只报告 ``timed_out=True``。保持纯数据（无锁/无句柄）
以便跨进程序列化。
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    """一次命令执行的原始事实。"""

    name: str = ""
    command: str = ""
    return_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    output: str = ""  # combined（stdout + stderr），兼容 output_contains 语义
    duration: float = 0.0
    timed_out: bool = False
    timeout_limit: Optional[float] = None  # 生效的超时上限（执行事实）
    error: Optional[str] = None  # 执行层异常（如命令不存在）
    # ── 进程组内存峰值（执行事实，可选） ──
    peak_memory_bytes: Optional[int] = None  # 提交内存口径峰值；None=未测量
    peak_memory_source: Optional[str] = None  # 如 "windows_job_commit"
