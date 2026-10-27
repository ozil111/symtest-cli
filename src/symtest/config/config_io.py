"""
Unified configuration I/O.

``load_config`` / ``save_config`` remain the canonical read/write entry
points for test configuration files.  ``validate_config`` delegates to the
shared preparation pipeline (``config.prepared.prepare_config``) so that
``symtest validate`` and ``symtest run`` apply identical rules; the JSON
Schema in ``config_schema.py`` is the single source of truth for structural
checks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .import_expander import _load_raw_config
from .prepared import prepare_config, ConfigValidationError

logger = logging.getLogger("symtest.config.config_io")

__all__ = [
    "load_config",
    "save_config",
    "validate_config",
    "ConfigValidationError",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(
    config_file_path: Union[str, Path],
    *,
    expand: bool = True,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and (optionally) prepare a config file through the shared pipeline.

    Parameters
    ----------
    config_file_path:
        Path to the config file (JSON, JSONC or YAML).
    expand:
        If ``True`` (default), run the full preparation pipeline: raw-form
        structural validation, ``import`` expansion, ``extends`` resolution,
        variable application and expanded-form validation.  Structural
        problems raise ``ConfigValidationError``.
        If ``False``, the file is read as-is with no expansion or validation
        (used for round-tripping draft / legacy dicts).

    workspace:
        Workspace root for semantic path checks (default: current directory).
        Used only when ``expand=True``.

    Returns
    -------
        A config dict with ``test_cases`` (and optionally ``setup``).
    """
    path = Path(config_file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    if not expand:
        return _load_raw_config(path)

    prepared = prepare_config(path, workspace=workspace)
    if not prepared.valid:
        raise ConfigValidationError(prepared.errors)
    return prepared.config


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
        Output path; ``.json``/``.jsonc`` → JSON, ``.yaml``/``.yml`` → YAML.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    path.parent.mkdir(parents=True, exist_ok=True)

    if ext in (".json", ".jsonc"):
        # .jsonc output is written as plain JSON: rewriting a config
        # (e.g. ``symtest migrate``) cannot preserve comments.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    elif ext in (".yaml", ".yml"):
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    else:
        raise ValueError(
            f"Unsupported output format: {ext} "
            f"(expected .json, .jsonc, .yaml, or .yml)"
        )

    logger.info("Config saved to: %s", path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(
    config_file_path: Union[str, Path],
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a test config file without running tests.

    Delegates to the shared preparation pipeline (``prepare_config``) — the
    same checks that gate ``symtest run`` — and returns a report dict.

    Error-level checks (affect ``valid``):
    - JSON/YAML syntax correctness (implicit from successful load)
    - Raw-form structure per the JSON Schema: field names, types, value
      ranges, execution-form mutual exclusion, unknown fields
    - Import target existence; circular import detection
    - Duplicate case names
    - extends target existence; circular inheritance detection
    - Expanded-form completeness: every executable case must be complete
      after inheritance resolution
    - ``outputs`` path validity (array of strings, no workspace escape)
    - depends_on target existence, self-reference and cycle detection

    Warning-level checks (reported in ``warnings``, do not affect ``valid``):
    - ``command`` executability (PATH lookup / path existence)
    - ``compare_files`` baseline file existence
    - same ``outputs`` path declared by multiple cases without depends_on

    Returns a dict with keys ``valid`` (bool), ``errors`` (list),
    ``warnings`` (list), and ``summary`` (dict with file/case counts).
    """
    prepared = prepare_config(config_file_path, workspace=workspace)
    return {
        "valid": prepared.valid,
        "errors": prepared.errors,
        "warnings": prepared.warnings,
        "summary": prepared.summary,
    }
