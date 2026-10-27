"""Unified configuration preparation pipeline — the single authoritative
entry point shared by ``symtest validate``, ``symtest run`` and ``symtest find``.

Pipeline (each stage stops processing structurally invalid input so later
code never sees malformed dicts)::

    read file (keep source)
    → validate raw form of every loaded file (``CONFIG_SCHEMA``)
    → expand imports
    → check duplicate case names
    → resolve extends inheritance
    → apply variables & placeholders
    → validate expanded form (``EXPANDED_CONFIG_SCHEMA``)
    → semantic checks (depends_on graph, outputs path bounds)
      + warning-level checks (command executability, baseline existence,
        output conflicts)
    → return ``PreparedConfig`` (config + diagnostics)

Structural rules live once in ``config_schema.py``; this module only
orchestrates stages and owns the semantic checks that a JSON Schema cannot
express (name resolution, path boundaries, cycles).
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from jsonschema import Draft202012Validator

from .config_schema import get_config_schema, get_expanded_config_schema
from .import_expander import expand_imports, _load_raw_config
from .inheritance_expander import resolve_inheritance, apply_variables

logger = logging.getLogger("symtest.config.prepared")

# Validators are immutable and thread-safe; build once per process.
RAW_VALIDATOR = Draft202012Validator(get_config_schema())
EXPANDED_VALIDATOR = Draft202012Validator(get_expanded_config_schema())

_EXPANDED_CASE_PATH = re.compile(r"^\$\.test_cases\[(\d+)\](.*)$")


class ConfigValidationError(ValueError):
    """Raised by strict consumers (``run`` / ``find``) on invalid configs.

    Carries the full diagnostic list; ``str()`` joins them line by line.
    """

    def __init__(self, errors: Union[List[str], str]):
        if isinstance(errors, str):
            errors = [errors]
        self.errors: List[str] = list(errors)
        super().__init__("\n".join(self.errors))


@dataclass
class PreparedConfig:
    """Result of ``prepare_config``: prepared config + diagnostics.

    ``config`` is ``None`` when the pipeline stopped on structural errors.
    """

    config: Optional[Dict[str, Any]]
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schema-level diagnostics
# ---------------------------------------------------------------------------

def _raw_schema_errors(config: Dict[str, Any], source: str) -> List[str]:
    """Validate a raw (original file) config dict; errors carry file + field."""
    errors: List[str] = []
    raw_errors = sorted(
        RAW_VALIDATOR.iter_errors(config),
        key=lambda e: (e.json_path, e.message),
    )
    for e in raw_errors:
        errors.append(f"[{source}] {e.json_path}: {e.message}")
    return errors


def _expanded_schema_errors(config: Dict[str, Any]) -> List[str]:
    """Validate an expanded config dict; errors carry the case name."""
    errors: List[str] = []
    cases = config.get("test_cases", [])
    expanded_errors = sorted(
        EXPANDED_VALIDATOR.iter_errors(config),
        key=lambda e: (e.json_path, e.message),
    )
    for e in expanded_errors:
        m = _EXPANDED_CASE_PATH.match(e.json_path)
        if m:
            idx = int(m.group(1))
            name = "<unnamed>"
            if 0 <= idx < len(cases) and isinstance(cases[idx], dict):
                name = cases[idx].get("name", "<unnamed>")
            errors.append(
                f"case '{name}' ({e.json_path}): {e.message}"
            )
        else:
            errors.append(f"{e.json_path}: {e.message}")
    return errors


# ---------------------------------------------------------------------------
# Semantic checks (expressed here, not in the JSON Schema)
# ---------------------------------------------------------------------------

def _get_execution(test_case: Dict[str, Any]) -> Dict[str, Any]:
    """Return the v2 ``execution`` block of a case dict (empty dict if absent)."""
    execution = test_case.get("execution")
    return execution if isinstance(execution, dict) else {}


def _get_depends_on(test_case: Dict[str, Any]) -> Any:
    """Return the v2 ``scheduling.depends_on`` of a case dict (default [])."""
    scheduling = test_case.get("scheduling")
    if isinstance(scheduling, dict):
        return scheduling.get("depends_on", [])
    return []


def _command_warning(command: Any, workspace: Path) -> Optional[str]:
    """Return a warning message if a command is clearly not executable.

    Heuristic only — shell builtins, ``{placeholder}`` commands, and anything
    resolvable via PATH pass silently.
    """
    if not isinstance(command, str) or not command.strip():
        return "empty command"

    from ..core.execution.executor import _SHELL_BUILTINS

    first = command.strip().split()[0]
    if "{" in first or "}" in first:
        return None  # variable placeholder; cannot resolve statically
    if first.lower() in _SHELL_BUILTINS:
        return None
    if Path(first).is_absolute() or "/" in first or "\\" in first:
        # Path-like command: resolve relative to the workspace
        candidate = Path(first)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        if not candidate.exists():
            return f"command not found: '{first}'"
        return None
    if shutil.which(first) is None:
        return f"command not found on PATH: '{first}'"
    return None


def _baseline_warnings(expected: Any, prefix: str, workspace: Path) -> List[str]:
    """Warn when a compare_files baseline file does not exist.

    ``actual`` files are produced by the test command, so only ``baseline``
    is checked. Placeholders (``{var}``) are skipped.
    """
    warnings: List[str] = []
    if not isinstance(expected, dict):
        return warnings
    compare_specs = expected.get("compare_files") or []
    for spec in compare_specs:
        if not isinstance(spec, dict):
            continue
        baseline = spec.get("baseline")
        if not baseline or not isinstance(baseline, str) or "{" in baseline:
            continue
        candidate = Path(baseline)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        if not candidate.exists():
            warnings.append(f"{prefix}: baseline file not found: '{baseline}'")
    return warnings


def _iter_case_outputs(test_case: Dict[str, Any]) -> List[Any]:
    """Yield all declared ``outputs`` entries of a case (case-level + steps)."""
    execution = _get_execution(test_case)
    entries: List[Any] = []
    outputs = execution.get("outputs")
    if isinstance(outputs, list):
        entries.extend(outputs)
    for step in execution.get("steps", []) or []:
        if isinstance(step, dict) and isinstance(step.get("outputs"), list):
            entries.extend(step["outputs"])
    return entries


def _outputs_errors(test_case: Dict[str, Any], prefix: str, workspace: Path) -> List[str]:
    """Error-level checks for declared ``outputs`` paths (Schema v2).

    Type/shape checks (array of strings) are owned by the JSON Schema; this
    check owns what a schema cannot express:

    - ``{placeholder}`` entries are skipped (cannot resolve statically);
    - resolved path must stay inside the workspace (no escape);
    - resolved path must not be the workspace root itself (e.g. ``"."``)
      and must not already exist as a directory — only files may be
      declared as outputs.
    """
    errors: List[str] = []
    for raw in _iter_case_outputs(test_case):
        if not isinstance(raw, str) or "{" in raw:
            continue
        p = Path(raw)
        candidate = p.resolve() if p.is_absolute() else (workspace / p).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError:
            errors.append(
                f"{prefix}: output path escapes workspace: '{raw}'"
            )
            continue
        if candidate == workspace:
            errors.append(
                f"{prefix}: output path resolves to the workspace root "
                f"(only files may be declared): '{raw}'"
            )
            continue
        if candidate.exists() and candidate.is_dir() and not candidate.is_symlink():
            errors.append(
                f"{prefix}: output path is a directory "
                f"(only files may be declared as outputs): '{raw}'"
            )
    return errors


def _case_warnings(test_case: Dict[str, Any], workspace: Path) -> List[str]:
    """Warning-level checks for a single expanded test case dict."""
    warnings: List[str] = []
    name = test_case.get("name", "<unnamed>")
    prefix = f"case '{name}'"

    execution = _get_execution(test_case)
    if "steps" in execution:
        for si, step in enumerate(execution.get("steps", [])):
            if not isinstance(step, dict):
                continue
            step_prefix = f"{prefix} step {si}"
            cmd_warn = _command_warning(step.get("command"), workspace)
            if cmd_warn:
                warnings.append(f"{step_prefix}: {cmd_warn}")
            warnings.extend(
                _baseline_warnings(step.get("expected"), step_prefix, workspace)
            )
        warnings.extend(
            _baseline_warnings(test_case.get("expected"), prefix, workspace)
        )
    else:
        cmd_warn = _command_warning(execution.get("command"), workspace)
        if cmd_warn:
            warnings.append(f"{prefix}: {cmd_warn}")
        warnings.extend(
            _baseline_warnings(test_case.get("expected"), prefix, workspace)
        )

    return warnings


def _depends_on_errors(cases: List[Dict[str, Any]]) -> List[str]:
    """Check depends_on references: target existence, no self-reference, no cycles."""
    errors: List[str] = []
    names = {
        case.get("name")
        for case in cases
        if isinstance(case.get("name"), str)
    }
    deps_map: Dict[str, List[str]] = {}
    for case in cases:
        case_name = case.get("name", "<unnamed>")
        deps = _get_depends_on(case)
        if not deps:
            deps_map[case_name] = []
            continue
        if not isinstance(deps, list):
            errors.append(f"case '{case_name}': depends_on must be an array of strings")
            deps_map[case_name] = []
            continue
        clean_deps: List[str] = []
        for dep in deps:
            if not isinstance(dep, str):
                errors.append(
                    f"case '{case_name}': depends_on entries must be strings, "
                    f"got {type(dep).__name__}"
                )
                continue
            if dep == case_name:
                errors.append(
                    f"case '{case_name}': cannot depend on itself ('{dep}')"
                )
                continue
            if dep not in names:
                errors.append(
                    f"case '{case_name}': depends_on target '{dep}' not found"
                )
                continue
            clean_deps.append(dep)
        deps_map[case_name] = clean_deps

    # Cycle detection: standard DFS with white/gray/black colouring.
    color: Dict[str, int] = {name: 0 for name in deps_map}  # 0 white, 1 gray, 2 black

    def _dfs(node: str, path: List[str]) -> None:
        color[node] = 1
        for dep in deps_map.get(node, []):
            if dep == node:
                continue  # self-reference already reported above
            state = color.get(dep)
            if state == 0:
                _dfs(dep, path + [dep])
            elif state == 1:
                idx = path.index(dep)
                chain = " -> ".join(path[idx:] + [dep])
                errors.append(f"Circular depends_on detected: {chain}")
        color[node] = 2

    for name in deps_map:
        if color[name] == 0:
            _dfs(name, [name])

    return errors


def _output_conflict_warnings(cases: List[Dict[str, Any]]) -> List[str]:
    """Warn when cases share an output path without depends_on ordering.

    Two concurrently scheduled cases declaring the same output path race on
    deletion. Pairs connected via depends_on are legitimate (upstream runs
    first) and are not flagged.
    """
    warnings: List[str] = []
    output_owners: Dict[str, List[str]] = {}
    for case in cases:
        name = case.get("name", "<unnamed>")
        for raw in _iter_case_outputs(case):
            if not isinstance(raw, str) or "{" in raw:
                continue
            key = str(Path(raw)).replace("\\", "/").lower()
            output_owners.setdefault(key, []).append(name)
    deps_map: Dict[str, List[str]] = {
        case.get("name", "<unnamed>"): (
            _get_depends_on(case) if isinstance(_get_depends_on(case), list) else []
        )
        for case in cases
    }
    for key, owners in output_owners.items():
        unique = list(dict.fromkeys(owners))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                a, b = unique[i], unique[j]
                if a in deps_map.get(b, []) or b in deps_map.get(a, []):
                    continue
                warnings.append(
                    f"output path declared by multiple cases without "
                    f"depends_on: '{key}' ({a}, {b}); concurrent runs may "
                    f"delete each other's artifacts"
                )
    return warnings


def _duplicate_name_errors(cases: List[Dict[str, Any]]) -> List[str]:
    """Flag duplicate case names — ambiguous for ``extends`` resolution."""
    errors: List[str] = []
    seen: set = set()
    for case in cases:
        name = case.get("name")
        if not name:
            continue
        if name in seen:
            errors.append(
                f"Duplicate case name '{name}' "
                f"(found in multiple config files; "
                f"extends references must be unambiguous)"
            )
        seen.add(name)
    return errors


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------

def prepare_config(
    config_file_path: Union[str, Path],
    *,
    workspace: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    file_loader: Optional[Callable] = None,
) -> PreparedConfig:
    """Load, validate and expand a config file through the shared pipeline.

    Parameters
    ----------
    config_file_path:
        Path to the config file (JSON, JSONC or YAML).
    workspace:
        Workspace root for path-boundary semantic checks (default: cwd).
    variables:
        Global ``--var`` overlay applied during placeholder substitution.
    file_loader:
        Optional ``callable(file_obj) -> dict`` used to read the *top-level*
        file (runner-injected ``json.load`` / ``yaml.safe_load``). Imported
        sub-files always load by extension.

    Returns
    -------
        A ``PreparedConfig``; ``config`` is ``None`` if a structural stage
        stopped processing.
    """
    path = Path(config_file_path).resolve()
    ws = Path(workspace).resolve() if workspace else Path.cwd()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    errors: List[str] = []
    warnings: List[str] = []
    files_loaded: List[str] = []

    def _summary(cases: Optional[List[Any]] = None) -> Dict[str, Any]:
        return {
            "files": len(files_loaded),
            "cases": len(cases) if cases is not None else 0,
            "files_loaded": list(files_loaded),
        }

    # ── 1. Read the top-level file ──────────────────────────────────
    try:
        if file_loader is not None:
            with open(path, "r", encoding="utf-8") as f:
                config = file_loader(f)
        else:
            config = _load_raw_config(path)
    except Exception as exc:
        return PreparedConfig(
            None, False, [f"Syntax error in {path}: {exc}"], [], _summary(),
        )
    files_loaded.append(str(path))

    # ── 2. Raw-form structural validation of the top-level file ─────
    raw_errors = _raw_schema_errors(config, str(path))
    if raw_errors:
        return PreparedConfig(None, False, raw_errors, [], _summary())

    # ── 3. Expand imports (each imported file gets the same check) ──
    def _on_file_loaded(sub_path: Path, sub_config: Dict[str, Any]) -> bool:
        files_loaded.append(str(sub_path))
        sub_errors = _raw_schema_errors(sub_config, str(sub_path))
        if sub_errors:
            errors.extend(sub_errors)
            return True  # skip inlining this import
        return False

    try:
        config = expand_imports(config, path, on_file_loaded=_on_file_loaded)
    except FileNotFoundError as exc:
        errors.append(str(exc))
        return PreparedConfig(None, False, errors, warnings, _summary())
    except RuntimeError as exc:
        # Circular import
        errors.append(str(exc))
        return PreparedConfig(None, False, errors, warnings, _summary())
    except ValueError as exc:
        # Unsupported file format
        errors.append(str(exc))
        return PreparedConfig(None, False, errors, warnings, _summary())

    raw_cases: List[Dict[str, Any]] = config.get("test_cases", [])

    # ── 4. Duplicate case names (ambiguous extends targets) ────────
    errors.extend(_duplicate_name_errors(raw_cases))

    # ── 5. Resolve extends inheritance ──────────────────────────────
    try:
        config = resolve_inheritance(config)
    except ValueError as exc:
        # extends target not found / circular extends
        errors.append(str(exc))
        return PreparedConfig(None, False, errors, warnings, _summary())

    # ── 6. Apply variables & placeholders ───────────────────────────
    config = apply_variables(config, variables)

    cases: List[Dict[str, Any]] = config.get("test_cases", [])

    # ── 7. Expanded-form completeness validation ────────────────────
    expanded_errors = _expanded_schema_errors(config)
    if expanded_errors:
        errors.extend(expanded_errors)
        return PreparedConfig(None, False, errors, warnings, _summary())

    # ── 8. Semantic checks + warning-level checks ───────────────────
    for case in cases:
        name = case.get("name", "<unnamed>")
        prefix = f"case '{name}'"
        errors.extend(_outputs_errors(case, prefix, ws))
        warnings.extend(_case_warnings(case, ws))
    errors.extend(_depends_on_errors(cases))
    warnings.extend(_output_conflict_warnings(cases))

    return PreparedConfig(
        config, len(errors) == 0, errors, warnings, _summary(cases),
    )
