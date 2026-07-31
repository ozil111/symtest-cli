"""
Test-case inheritance resolver.

Resolves ``extends`` references in ``test_cases``, merges field definitions
via deep-merge (dict) / whole-replace (list), collects ``variables`` for
per-case placeholder substitution, and removes ``abstract`` (template) cases.

Used after ``expand_imports`` and before ``substitute_placeholders`` /
``parse_test_cases`` in the config loading pipeline.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("symtest.config.inheritance_expander")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_inheritance(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ``extends`` chains, remove ``abstract`` cases, collect ``variables``.

    Parameters
    ----------
    config:
        Config dict already expanded by ``expand_imports``.  Must contain a
        ``test_cases`` list; may optionally contain ``setup``.

    Returns
    -------
        A new config dict where:
        - every ``abstract: true`` case has been removed,
        - every ``extends`` reference has been resolved (merged with parent),
        - each concrete case may carry a ``variables`` dict (deep-merged from
          ancestor chain).  The ``variables`` are *not* substituted — that is
          the job of ``apply_variables``.

    Raises
    ------
    ValueError
        If an ``extends`` target is not found among all test-cases (including
        abstract ones).
    ValueError
        If a circular ``extends`` chain is detected.
    """
    result = copy.deepcopy(config)
    raw_cases: List[Dict[str, Any]] = result.get("test_cases", [])
    if not raw_cases:
        return result

    # -- Build name → case lookup (includes abstract bases) --
    all_by_name: Dict[str, Dict[str, Any]] = {}
    for case in raw_cases:
        name = case.get("name")
        if name:
            all_by_name[name] = case

    # -- Resolve each case --
    resolved_cases: List[Dict[str, Any]] = []
    for case in raw_cases:
        resolved_case = _resolve_one(case, all_by_name, visited=[])
        # abstract cases are templates — only exclude them from the final list;
        # they still serve as bases for extends resolution above
        if not resolved_case.get("abstract"):
            resolved_case.pop("abstract", None)
            resolved_cases.append(resolved_case)

    result["test_cases"] = resolved_cases
    return result


def apply_variables(
    config: Dict[str, Any],
    global_variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Per-case placeholder substitution with global ``--var`` overlay.

    Parameters
    ----------
    config:
        Config dict already processed by ``resolve_inheritance``.  Each
        concrete case may carry a ``variables`` key.
    global_variables:
        Global variables from ``--var`` CLI flag.  These take precedence
        over case-level ``variables`` (global overlays).

    Returns
    -------
        A new config dict with all ``{placeholder}`` replaced.  The
        ``variables`` key is consumed (removed) from every case.  ``setup``
        is substituted with global variables only.
    """
    from ..core.config_loader import substitute_placeholders

    result = copy.deepcopy(config)
    gv = global_variables or {}

    # -- Substitute setup with global variables only --
    if "setup" in result and gv:
        result["setup"] = substitute_placeholders(result["setup"], gv)

    for case in result.get("test_cases", []):
        case_vars = case.pop("variables", {})
        effective = dict(case_vars)
        effective.update(gv)  # global overlays
        if effective:
            _sub_in_place(case, effective, substitute_placeholders)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deep_merge_dicts(base: dict, overlay: dict) -> dict:
    """Deep-merge *overlay* into *base*.

    - Both values are dict → recurse.
    - Otherwise overlay value wins (list / scalar are whole-replaced, not extended).
    - Returns a new dict (does not mutate inputs).
    """
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_one(
    case: Dict[str, Any],
    all_by_name: Dict[str, Dict[str, Any]],
    visited: List[str],
) -> Dict[str, Any]:
    """Resolve a single case's ``extends`` chain recursively.

    Returns a fully-merged dict (may have ``abstract: true`` — the caller
    filters abstract cases from the final list).  Abstract cases *can* serve
    as extends targets; they are only excluded from the output, not from
    inheritance resolution.
    """
    extends_target = case.get("extends")
    if extends_target is None:
        # No inheritance — keep as-is
        result = dict(case)
        result.pop("extends", None)
        return result

    # -- Resolve parent chain --
    name = case.get("name", "<unnamed>")
    if extends_target not in all_by_name:
        raise ValueError(
            f"extends target not found: '{extends_target}' "
            f"(referenced by case '{name}')"
        )

    # Cycle detection
    if extends_target in visited:
        chain = " -> ".join(visited + [extends_target])
        raise ValueError(
            f"Circular extends detected: {chain}"
        )
    visited.append(extends_target)

    parent = all_by_name[extends_target]
    resolved_parent = _resolve_one(parent, all_by_name, visited)

    visited.pop()

    # -- Merge: parent fields → child fields (child wins) --
    merged = _deep_merge_dicts(resolved_parent, case)

    # Remove internal markers
    merged.pop("extends", None)

    # abstract: child's own value wins (default False), NOT inherited from parent
    merged["abstract"] = case.get("abstract", False)

    return merged


def _sub_in_place(
    case: Dict[str, Any],
    variables: Dict[str, Any],
    substitute_fn,
) -> None:
    """Apply placeholder substitution to *case* in-place via *substitute_fn*."""
    substituted = substitute_fn(case, variables)
    case.clear()
    case.update(substituted)
