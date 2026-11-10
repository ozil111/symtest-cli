# -*- coding: utf-8 -*-
"""Linux cgroup v2 进程组管理（原则 2：纯执行事实）。

一次命令执行绑定一个独立 cgroup：

``创建组目录 → shell 将自身 pid 写入 cgroup.procs 后 exec 命令
→ communicate/超时 → 排空等待 → 读取 memory.peak → 清理组目录``

- shell 先把**自身 pid** 写入 ``cgroup.procs`` 再 ``exec`` 命令：写入时刻
  shell 尚未派生任何后代，命令本身及其全部后代从一开始就在组内，
  消除"启动后迁移 PID 漏掉已创建子进程"的竞态；``exec`` 保留 pid 与
  组成员身份，stdout/stderr 管道与普通 Popen 完全一致；
- 不使用 ``preexec_fn``：多线程进程中 fork+回调有死锁风险，shell
  包装是等价且安全的实现；
- 峰值由内核持续维护（``memory.peak`` 为组及其后代的 cgroup 记账
  口径——含匿名内存、文件缓存及部分内核内存，**不是物理内存峰值，
  也不是 Windows 提交内存**），无需采样即可捕捉短暂尖峰；
- 不设置 ``memory.max`` 硬上限：测量只做记录，不做限制；
- 超时经 ``terminate`` 终止整组（killpg + 组内 pid 逐个 SIGKILL，
  覆盖 setsid 逃逸的后代），对齐 Windows ``TerminateJobObject`` 语义；
- 排空判定：``cgroup.procs`` 为空，或所列 pid 全部不存活（无 reaper
  的环境可能残留已退出进程的记录）；
- 能力探测 ``is_supported`` 通过**实际创建探针子组**验证（mkdir 权限
  + memory 控制器在父组 ``subtree_control`` 中激活），结果按进程缓存；
  探测失败（如无 cgroup 委派权限）调用方按"测量不可用"降级，准入
  仍可依据手动/默认需求执行；
- 任何操作失败以 :class:`CgroupError` 抛出，调用方回退普通 subprocess
  路径，测量不可用不影响执行与判定语义。

cgroup v2 细节：子组只有在父组 ``cgroup.subtree_control`` 启用
``+memory`` 后才有 ``memory.peak`` 等文件（``memory.peak`` 需内核
≥ 6.8）；父组若已有进程直接挂载则启用控制器返回 EINVAL——探针如实
探测并缓存结论，不做二次猜测。
"""
import logging
import os
import shlex
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("symtest.core.execution.linux_cgroup")

#: 峰值数据来源标识（写入 ExecutionResult.peak_memory_source）
PEAK_SOURCE = "linux_cgroup_v2"

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_POLL_INTERVAL_S = 0.1
_CLOSE_RETRY_S = 2.0


class CgroupError(Exception):
    """cgroup 操作失败（调用方应回退普通 subprocess 路径）。"""


class CgroupHandle:
    """一次命令执行的 cgroup 引用（opaque，调用方只负责原样归还）。"""

    __slots__ = ("path", "pid")

    def __init__(self, path: Path, pid: int):
        self.path = path
        self.pid = pid


# ---------------------------------------------------------------------------
# 自身 cgroup 定位
# ---------------------------------------------------------------------------

def _own_cgroup_dir() -> Optional[Path]:
    """返回当前进程所在的 cgroup v2 目录；非 v2 / 读取失败返回 None。"""
    try:
        content = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and not parts[1]:
            rel = parts[2].strip().strip("/")
            return _CGROUP_ROOT.joinpath(rel) if rel else _CGROUP_ROOT
    return None


def _new_group_name() -> str:
    """每次执行的唯一子组名（测试可 monkeypatch 为确定名）。"""
    return "symtest-%d-%s" % (os.getpid(), uuid.uuid4().hex[:8])


def _read_pids(group_dir: Path) -> List[int]:
    """读取组内存活进程列表（cgroup.procs）；失败返回空表（保守排空）。"""
    try:
        text = (group_dir / "cgroup.procs").read_text(encoding="utf-8")
    except OSError:
        return []
    return [int(tok) for tok in text.split() if tok.isdigit()]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 别人的进程：仍在运行，按存活处理
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 能力探测（probe-by-doing，按进程缓存）
# ---------------------------------------------------------------------------

_supported_cache: Optional[bool] = None


def is_supported() -> bool:
    """Linux + cgroup v2 + 可在自身组下创建带 memory 记账的子组。

    通过实际创建一个探针子组并验证 ``memory.peak`` 存在来判断——这是
    "mkdir 权限 + memory 控制器已激活"的唯一可靠组合检验；探测后立即
    清理。结果按进程缓存（文件系统布局不会在运行中途改变语义）。
    """
    global _supported_cache
    if _supported_cache is not None:
        return _supported_cache
    _supported_cache = _probe_support()
    return _supported_cache


def _probe_support() -> bool:
    if os.name != "posix":
        return False
    base = _own_cgroup_dir()
    if base is None:
        return False
    probe = base / ("symtest-probe-%d" % os.getpid())
    try:
        probe.mkdir()
    except FileExistsError:
        # 上次崩溃进程的同名残留：清理空目录后重试一次
        _safe_rmdir(probe)
        try:
            probe.mkdir()
        except OSError:
            return False
    except OSError:
        return False
    try:
        if not (probe / "memory.peak").exists():
            # memory 控制器未在父组 subtree_control 激活。父组可写时尝试
            # 启用（手动委派场景）；失败（含"父组已有进程"的 EINVAL、
            # 只读文件系统）即判定不支持。
            if not _try_enable_memory_controller(base):
                return False
            if not (probe / "memory.peak").exists():
                return False
        return True
    finally:
        if not _safe_rmdir(probe):
            logger.debug("cgroup probe directory left behind: %s", probe)


def _try_enable_memory_controller(group_dir: Path) -> bool:
    """尝试在组上启用 +memory 控制器（子组获得 memory.* 文件的前提）。

    写入成功即返回 True；控制器是否真正激活由调用方复核新建子组的
    ``memory.peak`` 是否存在（内核会把 subtree_control 归一化，不靠
    回读校验）。
    """
    controllers = group_dir / "cgroup.controllers"
    subtree = group_dir / "cgroup.subtree_control"
    try:
        if "memory" not in controllers.read_text(encoding="utf-8").split():
            return False
        if not os.access(subtree, os.W_OK):
            return False
        with open(subtree, "a", encoding="utf-8") as f:
            f.write("+memory\n")
        return True
    except OSError as exc:
        logger.debug("cannot enable memory controller in %s: %s", group_dir, exc)
        return False


# ---------------------------------------------------------------------------
# 公开操作
# ---------------------------------------------------------------------------

def start_in_cgroup(
    cmd_list: List[str],
    cwd=None,
    env=None,
) -> Tuple[subprocess.Popen, CgroupHandle]:
    """在新建 cgroup 中启动命令（整组进程从执行起就在组内）。

    实现：``/bin/sh -c 'echo $$ > <组>/cgroup.procs && exec "$@"'``——
    shell 尚无后代时先迁移自身，再 exec 成命令进程；后代继承组成员
    身份（"脚本 → 启动器 → 求解器"整组被统计）。

    :returns: ``(Popen, handle)``；调用方负责 ``close_group``。
    :raises CgroupError: 组目录创建失败（如无委派权限）。
    """
    base = _own_cgroup_dir()
    if base is None:
        raise CgroupError("no cgroup v2 hierarchy found for this process")
    group_dir = base / _new_group_name()
    try:
        group_dir.mkdir()
    except OSError as exc:
        raise CgroupError(
            f"cannot create cgroup {group_dir}: {exc}") from exc

    procs_file = shlex.quote(str(group_dir / "cgroup.procs"))
    # "$@" 经 sh 位置参数传入原始命令，不与脚本内容混淆；&& 确保
    # 迁移失败时不执行命令（进程组外执行会造成漏统计，宁可失败回退）。
    script = f'echo $$ > {procs_file} && exec "$@"'
    try:
        process = subprocess.Popen(
            ["/bin/sh", "-c", script, "sh", *cmd_list],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env=env,
        )
    except Exception:
        _safe_rmdir(group_dir)
        raise
    return process, CgroupHandle(group_dir, process.pid)


def wait_complete(handle: CgroupHandle, timeout_ms: int) -> bool:
    """等待组内全部进程结束（轮询 cgroup.procs）。

    排空判定：文件为空（内核语义：成员退出且被回收后即移出），或所列
    pid 全部不存活（无 reaper 的环境下文件可能残留已退出进程）。

    :returns: True 已排空；False 超时（后代进程仍在运行）。
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        pids = _read_pids(handle.path)
        if not pids or not any(_pid_alive(pid) for pid in pids):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL_S)


def terminate(handle: CgroupHandle) -> None:
    """终止组内全部进程（超时清理整组，防遗留求解器）。失败仅记录。

    先 killpg 杀会话（大多数后代），再对组内仍存活的 pid 逐个 SIGKILL
    （覆盖 setsid 逃逸进程组但仍在 cgroup 内的后代）。
    """
    try:
        if handle.pid and handle.pid > 1:
            os.killpg(handle.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # 进程组已消失或不可杀，继续按 cgroup 名单清理
    for pid in _read_pids(handle.path):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            logger.debug("cannot kill pid %d in %s: %s", pid, handle.path, exc)


def query_peak_bytes(handle: CgroupHandle) -> Optional[int]:
    """读取 ``memory.peak``（cgroup 记账口径，字节）。

    失败返回 ``None``（测量不可用），不得返回 0 伪装成功。
    """
    try:
        text = (handle.path / "memory.peak").read_text(encoding="utf-8")
        peak = int(text.strip())
        return peak if peak > 0 else None
    except Exception as exc:
        logger.warning("query_peak_bytes failed: %s", exc)
        return None


def close_group(handle: CgroupHandle) -> None:
    """清理组目录（不终止进程；残留成员时短暂等待后保留并告警）。

    真 cgroupfs 上 ``cgroup.procs`` 等伪文件不阻塞 rmdir——只有存活
    成员或子组才阻塞；超时路径 terminate 后成员异步退出，故有界重试。
    """
    deadline = time.monotonic() + _CLOSE_RETRY_S
    while not _safe_rmdir(handle.path):
        if time.monotonic() >= deadline:
            logger.warning(
                "cannot remove cgroup %s (left in place)", handle.path,
            )
            return
        time.sleep(_POLL_INTERVAL_S)


def _safe_rmdir(group_dir: Path) -> bool:
    try:
        group_dir.rmdir()
        return True
    except OSError:
        return False
