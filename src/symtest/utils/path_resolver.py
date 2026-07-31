import os
import shlex
from pathlib import Path
from typing import List, Tuple, Union
import shutil


WorkspaceLike = Union[str, Path]

# Commands that are shell builtins (not real executables).
# Recognised here so they pass through as-is rather than being treated
# as workspace-relative paths.  Wrapping (cmd /d /c …) happens later
# in execution._normalize_cmd_list.
if os.name == 'nt':
    _SHELL_BUILTINS = frozenset(['echo', 'dir', 'type', 'copy', 'del', 'ren',
                                  'cd', 'md', 'rd', 'set', 'cls', 'move'])
else:
    _SHELL_BUILTINS = frozenset(['echo', 'cd', 'pwd', 'export', 'source'])


def _as_workspace_path(workspace: WorkspaceLike) -> Path:
    return workspace if isinstance(workspace, Path) else Path(workspace)


def resolve_command(command: str, workspace: WorkspaceLike) -> str:
    """
    Resolve command path:
    - absolute path: keep
    - available in PATH: keep
    - otherwise treat as relative to workspace
    """
    workspace_path = _as_workspace_path(workspace)

    if Path(command).is_absolute():
        return command

    if shutil.which(command) is not None:
        return command

    return str(workspace_path / command)


def _looks_like_relative_path(arg: str) -> bool:
    """Check if arg explicitly starts with a relative path prefix."""
    return (arg.startswith("./") or arg.startswith(".\\") or
            arg.startswith("../") or arg.startswith("..\\"))


def resolve_paths(args: List[str], workspace: WorkspaceLike) -> List[str]:
    """Resolve explicitly relative paths (starting with ./ or ../) against workspace."""
    workspace_path = _as_workspace_path(workspace)
    resolved: List[str] = []
    for arg in args:
        if _looks_like_relative_path(arg):
            resolved.append(str(workspace_path / arg))
        else:
            resolved.append(arg)
    return resolved


def split_command(command_string: str, workspace: WorkspaceLike) -> Tuple[str, List[str]]:
    """
    Split a potentially multi-word command string into its executable and leading arguments.
    Uses shlex to correctly handle quoted executables (e.g. ''"C:\\Program Files\\app.exe" -v'').

    Example:
        ''"C:\\Python\\python.exe" -c "print('hi')"'' -> ("C:\\Python\\python.exe", ["-c", "print('hi')"])
        "python ./script.py"                           -> ("python", ["./script.py"])
        "echo hello world"                             -> ("echo", ["hello", "world"])
    """
    s = command_string.strip()
    if not s:
        return "", []

    # Use shlex to properly handle quoted segments.
    # posix=False preserves Windows backslash-paths but leaves quotes intact.
    # On Windows we strip quotes manually; on Unix posix=True strips them natively.
    try:
        parts = shlex.split(s, posix=(os.name != 'nt'))
    except ValueError:
        parts = s.split()
    if os.name == 'nt':
        parts = [p.strip('"') for p in parts]

    cmd = parts[0]
    remaining = parts[1:]

    # Real executable: absolute path or found in PATH
    if os.path.isabs(cmd) or shutil.which(cmd) is not None:
        return cmd, remaining

    # Shell builtin -> pass through as-is; wrapping happens at execution time
    if cmd.lower() in _SHELL_BUILTINS:
        return cmd, remaining

    # Otherwise treat as workspace-relative path
    return str(Path(workspace) / cmd), remaining


class PathResolver:
    """
    Backwards-compatible wrapper; delegates to pure functions.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def resolve_paths(self, args: List[str]) -> List[str]:
        return resolve_paths(args, self.workspace)

    def resolve_command(self, command: str) -> str:
        return resolve_command(command, self.workspace)

    def split_command(self, command_string: str) -> Tuple[str, List[str]]:
        """Split and resolve a command string. Returns (executable, leading_args)."""
        return split_command(command_string, self.workspace)

    def parse_command_string(self, command_string: str) -> str:
        """
        Backward-compatible: resolves and returns the executable name only.
        Prefer split_command() for new code.
        """
        executable, _ = split_command(command_string, self.workspace)
        return executable
