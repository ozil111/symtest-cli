"""
Unified configuration I/O with import-expansion support.

Provides ``load_config`` and ``save_config`` as the canonical read/write
entry points for test configuration files, with transparent import expansion.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .import_expander import expand_imports, _load_raw_config

logger = logging.getLogger("cli_test_framework.config.config_io")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(
    config_file_path: Union[str, Path],
    *,
    expand: bool = True,
) -> Dict[str, Any]:
    """Load and (optionally) expand import references in a config file.

    Parameters
    ----------
    config_file_path:
        Path to the config file (JSON or YAML).
    expand:
        If ``True`` (default), recursively expand ``import`` references.

    Returns
    -------
        A config dict with ``test_cases`` (and optionally ``setup``).
    """
    path = Path(config_file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    config = _load_raw_config(path)

    if expand:
        config = expand_imports(config, path)

    return config


def save_config(
    config: Dict[str, Any],
    file_path: Union[str, Path],
) -> None:
    """Save a config dict to file, choosing the format by extension.

    Parameters
    ----------
    config:
        Config dict (must contain at least ``test_cases``).
    file_path:
        Output path; ``.json`` → JSON, ``.yaml``/``.yml`` → YAML.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    elif ext in (".yaml", ".yml"):
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    else:
        raise ValueError(
            f"Unsupported output format: {ext} (expected .json, .yaml, or .yml)"
        )

    logger.info("Config saved to: %s", path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_required_fields(test_case: Dict[str, Any], index: int, source: str) -> List[str]:
    """Check required fields for a single test case dict. Returns list of error messages."""
    errors: List[str] = []
    prefix = f"[{source}] case #{index}"

    name = test_case.get("name", "<unnamed>")
    prefix = f"[{source}] case '{name}'"

    if "steps" in test_case:
        # Sequence mode
        for si, step in enumerate(test_case["steps"]):
            for field in ("command", "args", "expected"):
                if field not in step:
                    errors.append(f"{prefix} step {si}: missing required field '{field}'")
    else:
        # Single-command mode
        for field in ("name", "command", "args", "expected"):
            if field not in test_case:
                errors.append(f"{prefix}: missing required field '{field}'")

    return errors


# ---------------------------------------------------------------------------
# Warning-level checks (do not affect ``valid``)
# ---------------------------------------------------------------------------

def _command_warning(command: Any, workspace: Path) -> Optional[str]:
    """Return a warning message if a command is clearly not executable.

    Heuristic only — shell builtins, ``{placeholder}`` commands, and anything
    resolvable via PATH pass silently.
    """
    if not isinstance(command, str) or not command.strip():
        return "empty command"

    from ..core.execution import _SHELL_BUILTINS

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


def _validate_case_warnings(
    test_case: Dict[str, Any], source: str, workspace: Path,
) -> List[str]:
    """Warning-level checks for a single test case dict."""
    warnings: List[str] = []
    name = test_case.get("name", "<unnamed>")
    prefix = f"[{source}] case '{name}'"

    if "steps" in test_case:
        for si, step in enumerate(test_case.get("steps", [])):
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
        cmd_warn = _command_warning(test_case.get("command"), workspace)
        if cmd_warn:
            warnings.append(f"{prefix}: {cmd_warn}")
        warnings.extend(
            _baseline_warnings(test_case.get("expected"), prefix, workspace)
        )

    return warnings


def validate_config(
    config_file_path: Union[str, Path],
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a test config file (with import expansion) without running tests.

    Checks (errors — affect ``valid``):
    - JSON/YAML syntax correctness (implicit from successful load)
    - Required fields on every test case
    - Import target existence
    - Circular import detection

    Warning-level checks (reported in ``warnings``, do not affect ``valid``):
    - ``command`` executability (PATH lookup / path existence)
    - ``compare_files`` baseline file existence

    Returns a dict with keys ``valid`` (bool), ``errors`` (list),
    ``warnings`` (list), and ``summary`` (dict with file/case counts).
    """
    path = Path(config_file_path).resolve()
    errors: List[str] = []
    warnings: List[str] = []
    files_loaded: List[str] = []
    total_cases = 0
    ws = Path(workspace).resolve() if workspace else Path.cwd()

    try:
        config = _load_raw_config(path)
    except Exception as exc:
        return {
            "valid": False,
            "errors": [f"Syntax error in {path}: {exc}"],
            "warnings": [],
            "summary": {"files": 0, "cases": 0},
        }

    # Collect all files and cases (walk the import tree)
    def _walk(current_path: Path, current_config: Dict[str, Any], visited: set) -> None:
        nonlocal total_cases
        canonical = str(current_path.resolve())
        if canonical in visited:
            errors.append(f"Circular import detected: {canonical}")
            return
        visited.add(canonical)
        files_loaded.append(str(current_path))

        for idx, item in enumerate(current_config.get("test_cases", [])):
            if "import" in item:
                sub_path = (current_path.parent / item["import"]).resolve()
                if not sub_path.exists():
                    errors.append(
                        f"Import target not found: {sub_path} "
                        f"(referenced by {current_path})"
                    )
                    continue
                try:
                    sub_config = _load_raw_config(sub_path)
                    _walk(sub_path, sub_config, visited)
                except Exception as exc:
                    errors.append(f"Error loading {sub_path}: {exc}")
            else:
                total_cases += 1
                errors.extend(_validate_required_fields(item, idx, str(current_path)))
                warnings.extend(_validate_case_warnings(item, str(current_path), ws))

    _walk(path, config, set())

    valid = len(errors) == 0
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "files": len(files_loaded),
            "cases": total_cases,
            "files_loaded": files_loaded,
        },
    }
