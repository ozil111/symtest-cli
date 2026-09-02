"""
Unified configuration parsing layer.

Shared logic for loading test cases from a config dict (already parsed from
JSON/YAML) into TestCase objects.

Sequence execution lives in ``core/orchestration/sequence.py`` (1.4: 编排层).

Backward-compatible: the runner classes still expose ``load_test_cases()`` and
``_run_sequence()`` as before; they merely delegate to the functions here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .test_case import TestCase, TestStep
from ..utils.path_resolver import resolve_paths

logger = logging.getLogger("symtest.core.config_loader")

# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')


def substitute_placeholders(
    config: Dict[str, Any],
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """递归替换 config 中字符串值的 ``{placeholder}`` 占位符。

    只替换 ``variables`` 中存在的 key，未匹配的 ``{xxx}`` 原样保留，
    不会影响 ``expected.matches`` 等字段中的正则模式（如 ``{2}``）。
    """
    if not variables:
        return config

    def _sub(value: Any) -> Any:
        if isinstance(value, str):
            return _PLACEHOLDER_RE.sub(
                lambda m: str(variables[m.group(1)])
                if m.group(1) in variables else m.group(0),
                value,
            )
        if isinstance(value, list):
            return [_sub(item) for item in value]
        if isinstance(value, dict):
            return {k: _sub(v) for k, v in value.items()}
        return value

    return _sub(config)


# ---------------------------------------------------------------------------
# Test-case parsing (loaded dict → list[TestCase])
# ---------------------------------------------------------------------------

def _split_and_resolve(
    command_string: str,
    args: List[str],
    workspace: Path,
    path_resolver: Any,
) -> Tuple[str, List[str]]:
    """Split a command string into executable + leading args, then resolve paths.

    ``path_resolver`` must be a ``PathResolver`` instance (or duck-typed
    equivalent with ``split_command`` / ``resolve_paths`` methods).
    """
    executable, leading_args = path_resolver.split_command(command_string)
    return executable, (
        resolve_paths(leading_args, str(workspace))
        + path_resolver.resolve_paths(args)
    )


def _parse_env(raw_env: Any) -> Dict[str, str]:
    """Normalize a case-level ``env`` mapping to a ``{str: str}`` dict.

    Environment variables are strings by nature; numeric/boolean values are
    coerced with ``str()`` to match ``EnvironmentSetup`` behaviour.
    """
    if not raw_env:
        return {}
    return {str(k): str(v) for k, v in raw_env.items()}


def parse_test_cases(
    config: Dict[str, Any],
    workspace: Optional[Path] = None,
    path_resolver: Any = None,
) -> List[TestCase]:
    """Parse ``config['test_cases']`` (Schema v2) into ``TestCase`` objects.

    v2 分层形态：``case["execution"]``（command 简写 或 steps 完整形）、
    ``case["expected"]``、``case["scheduling"]``。单命令简写被归一为
    单元素 steps 列表（单 step 时 case 级 expected == step 级 expected）。

    When *workspace* and *path_resolver* are provided (Runner mode),
    command/args paths are resolved.

    解析器全系统唯一且只接受 canonical TestCase：必填字段缺失即抛
    ``ValueError``（1.4 原则 6：无 TUI 宽松模式后门）。编辑半成品的
    宽松形态由 TUI 侧自行 normalize 后再调用本函数。
    """
    cases: List[TestCase] = []
    resolve = workspace is not None and path_resolver is not None

    for case in config.get("test_cases", []):
        execution = case.get("execution") or {}
        scheduling = case.get("scheduling") or {}
        case_expected: Dict[str, Any] = case.get("expected", {})

        # Normalize both modes to a single ``steps`` list.  A single-command
        # shorthand becomes a single-element list; a sequence case uses its
        # ``execution.steps`` directly.  Declaring both forms is ambiguous
        # (Schema v2 oneOf 互斥) and is rejected outright instead of being
        # silently resolved.
        is_sequence = "steps" in execution
        if is_sequence and ("command" in execution or "args" in execution):
            raise ValueError(
                f"Test case '{case.get('name', 'unnamed')}': 'execution' "
                f"declares both 'steps' and 'command'/'args' — the two forms "
                f"are mutually exclusive (choose one)"
            )
        if is_sequence:
            step_configs: List[Dict[str, Any]] = list(execution.get("steps", []))
        else:
            step_configs = [{
                "command": execution.get("command", ""),
                "args": execution.get("args", []),
                "expected": case_expected,
                "timeout": execution.get("timeout"),
                "retry_count": execution.get("retry_count", 0),
            }]

        steps: List[TestStep] = []
        for step in step_configs:
            step_required = ["command", "args", "expected"]
            if not all(field in step for field in step_required):
                raise ValueError(
                    f"Step in test case '{case.get('name', 'unnamed')}' "
                    f"is missing required fields"
                )
            if resolve:
                executable, resolved_args = _split_and_resolve(
                    step["command"], step["args"], workspace, path_resolver
                )
            else:
                executable = step.get("command", "")
                resolved_args = step.get("args", [])
            steps.append(TestStep.from_flat(
                command=executable,
                args=resolved_args,
                expected=step["expected"] if "expected" in step else step.get("expected", {}),
                timeout=step.get("timeout"),
                retry_count=step.get("retry_count", 0),
            ))

        if is_sequence:
            cases.append(TestCase(
                name=case.get("name", ""),
                steps=steps,
                expected=case_expected,
                description=case.get("description", ""),
                resources=scheduling.get("resources"),
                tags=case.get("tags", []),
                expected_failure=case.get("expected_failure", False),
                xfail_reason=case.get("xfail_reason", ""),
                xfail_quiet=case.get("xfail_quiet", False),
                depends_on=scheduling.get("depends_on", []),
                env=_parse_env(execution.get("env")),
            ))
        else:
            # ── Single-command mode: execution shorthand fields → steps[0] ──
            missing = [f for f in ("name", "execution", "expected") if f not in case]
            missing += [f for f in ("command", "args") if f not in execution]
            if missing:
                raise ValueError(
                    f"Test case {case.get('name', 'unnamed')} "
                    f"is missing required fields"
                )
            cases.append(TestCase(
                name=case.get("name", ""),
                steps=None,
                command=steps[0].command,
                args=steps[0].args,
                expected=steps[0].expected,
                description=case.get("description", ""),
                timeout=steps[0].timeout,
                resources=scheduling.get("resources"),
                tags=case.get("tags", []),
                retry_count=steps[0].retry_count,
                expected_failure=case.get("expected_failure", False),
                xfail_reason=case.get("xfail_reason", ""),
                xfail_quiet=case.get("xfail_quiet", False),
                depends_on=scheduling.get("depends_on", []),
                env=_parse_env(execution.get("env")),
            ))

    return cases
