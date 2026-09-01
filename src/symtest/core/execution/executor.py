"""纯 subprocess 执行器（原则 2）。

函数体自 1.3 ``core/execution.py::_execute_command_once`` 的执行部分
逐位搬入：``_normalize_cmd_list`` / 超时 killpg / ``_trim_output`` 行为
不变。本模块不得 import ``validation`` / ``assertions``（guard 测试强制）。
"""
import logging
import os
import shlex
import signal
import subprocess
import time
from collections.abc import Mapping
from typing import Any, List, Optional, Union

from .result import ExecutionResult

logger = logging.getLogger("symtest.core.execution.executor")

# Default maximum chars for command output in reports.
# Full output is still written to disk when output_dir is set.
DEFAULT_OUTPUT_MAX_CHARS = 20000

# Commands that are shell builtins (not real executables).
# With shell=False, these must be wrapped via the platform shell.
if os.name == 'nt':
    _SHELL_BUILTINS = frozenset(['echo', 'dir', 'type', 'copy', 'del', 'ren',
                                  'cd', 'md', 'rd', 'set', 'cls', 'move'])
else:
    _SHELL_BUILTINS = frozenset(['echo', 'cd', 'pwd', 'export', 'source'])


def _normalize_cmd_list(command: str, args: List[str]) -> List[str]:
    """If command is a shell builtin, wrap with the platform shell interpreter."""
    if command.lower() in _SHELL_BUILTINS:
        if os.name == 'nt':
            return ['cmd', '/d', '/c', command, *args]
        else:
            return ['/bin/sh', '-c', shlex.join([command, *args])]
    return [command, *args]


def _trim_output(output: str, max_chars: int = DEFAULT_OUTPUT_MAX_CHARS) -> str:
    """Trim long output: keep head 1/3 + tail 2/3 of max_chars."""
    if len(output) <= max_chars:
        return output
    head_size = max_chars // 3
    tail_size = max_chars - head_size
    trimmed = len(output) - max_chars
    return (
        output[:head_size]
        + f"\n\n[... {trimmed} chars truncated ...]\n\n"
        + output[-tail_size:]
    )


def _spec_get(spec: Any, key: str, default: Any = None) -> Any:
    """统一读取 ExecutionSpec 属性或旧 dict 形态的键（Phase 3 移除 dict 支持）。"""
    if isinstance(spec, Mapping):
        return spec.get(key, default)
    return getattr(spec, key, default)


def execute_command(
    spec: Any,
    workspace: Optional[str] = None,
    env: Optional[Union[Mapping[str, str], dict]] = None,
    *,
    output_max_chars: int = DEFAULT_OUTPUT_MAX_CHARS,
) -> ExecutionResult:
    """Execute a single command once (no retry, no validation).

    :param spec: ExecutionSpec（或兼容的 Mapping），读取 name/command/args/
                 timeout/env；不读取任何判定语义。
    :param workspace: Working directory for the subprocess.
    :param env: Optional environment variables to inject/override (merged with
                os.environ; case-level ``env`` in *spec* takes the highest
                precedence).
    :param output_max_chars: Max characters for trimmed output fields.
    :returns: ExecutionResult —— 纯执行事实；Popen/communicate 异常记录在
              ``error`` 字段而非抛出，交由编排层分类。
    """
    name: str = _spec_get(spec, "name", "") or ""
    command: str = _spec_get(spec, "command", "") or ""
    args: List[Any] = _spec_get(spec, "args", None) or []
    timeout_limit = _spec_get(spec, "timeout", None)
    if timeout_limit is None:
        timeout_limit = 3600
    spec_env = _spec_get(spec, "env", None) or {}

    # perf_counter: high-resolution monotonic clock; on Windows, time.time()
    # has ~15.6ms granularity and can yield duration == 0.0 for fast commands.
    start_time = time.perf_counter()
    cmd_list = _normalize_cmd_list(command, [str(arg) for arg in args])
    full_command = " ".join(cmd_list)

    result = ExecutionResult(
        name=name,
        command=full_command,
        timeout_limit=timeout_limit,
    )

    # Prepare environment variables
    # Default to current environment, merge with provided env if any.
    # Case-level ``env`` (if present) is applied last so it takes the highest
    # precedence, allowing it to override both inherited environment variables
    # and scheduler-injected values (e.g. OMP_NUM_THREADS).
    current_env = os.environ.copy()
    if env:
        current_env.update(env)
    if spec_env:
        current_env.update(spec_env)

    try:
        process = subprocess.Popen(
            cmd_list,
            cwd=workspace if workspace else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env=current_env,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout_limit)
        except subprocess.TimeoutExpired:
            # Kill the entire process group to avoid orphan processes.
            # Never killpg() PID 0 or 1 — they belong to init/system.
            try:
                if os.name == 'posix' and process.pid and process.pid > 1:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass  # process already exited or cannot be killed
            stdout, stderr = process.communicate()  # reap the process
            result.timed_out = True
            result.output = _trim_output((stdout or "") + (stderr or ""), output_max_chars)
            result.stdout = _trim_output(stdout or "", output_max_chars)
            result.stderr = _trim_output(stderr or "", output_max_chars)
            result.return_code = None
        else:
            raw_output = stdout + stderr
            result.output = _trim_output(raw_output, output_max_chars)
            result.stdout = _trim_output(stdout, output_max_chars)
            result.stderr = _trim_output(stderr, output_max_chars)
            result.return_code = process.returncode
    except Exception as exc:
        result.error = str(exc)
    finally:
        result.duration = time.perf_counter() - start_time

    return result
