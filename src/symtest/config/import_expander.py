"""
Import reference expander for test configuration files.

Allows a main config file to reference sub-config files via ``"import"``
entries inside ``test_cases``, recursively expanding them at load time.

Example::

    {
      "setup": { ... },
      "test_cases": [
        { "import": "cases/text_tests.json", "tags": ["text", "fast"] },
        { "import": "cases/json_tests.yaml" },
        { "name": "inline_case", "command": "echo", ... }
      ]
    }

When ``"tags"`` is specified on an import entry, the tags are injected into
every test case from that imported file.  Tags already present on individual
cases are merged (import-level tags come first, deduplicated).

The expansion produces a flat ``test_cases`` list with all imported cases
inlined.  The Runner layer never sees the ``import`` keys.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("symtest.config.import_expander")


def _load_raw_config(file_path: Path) -> Dict[str, Any]:
    """Load a raw config dict from a JSON or YAML file."""
    ext = file_path.suffix.lower()
    if ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    elif ext in (".yaml", ".yml"):
        import yaml

        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
        raise ValueError(
            f"Unsupported config file format: {file_path} (expected .json, .yaml, or .yml)"
        )


def _deep_merge_setup(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two setup dicts; overlay values win on conflict."""
    merged = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            # Deep merge nested dicts (e.g. environment_variables)
            merged[key] = _deep_merge_setup(merged[key], value)
        else:
            merged[key] = value
    return merged


def expand_imports(
    config: Dict[str, Any],
    config_path: Path,
    loaded_paths: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Recursively expand ``import`` references in a config dict.

    For each item in ``config["test_cases"]`` that contains an ``"import"``
    key, loads the referenced file, recursively expands it, and inlines its
    ``test_cases`` list in place of the ``import`` entry.

    Parameters
    ----------
    config:
        Raw config dict (already parsed from JSON/YAML).
    config_path:
        Absolute or resolved path to the config file (used as the base
        for resolving relative ``import`` paths).
    loaded_paths:
        Set of already-loaded canonical paths (for cycle detection).

    Returns
    -------
        A new config dict with all ``import`` references expanded.
    """
    if loaded_paths is None:
        loaded_paths = set()

    canonical = str(config_path.resolve())
    if canonical in loaded_paths:
        raise RuntimeError(
            f"Circular import detected: {canonical} is already loaded. "
            f"Loaded chain: {loaded_paths}"
        )
    loaded_paths.add(canonical)

    base_dir = config_path.parent
    setup = config.get("setup", {})
    raw_cases: List[Dict[str, Any]] = config.get("test_cases", [])
    expanded_cases: List[Dict[str, Any]] = []

    for item in raw_cases:
        if "import" in item:
            import_rel = item["import"]
            import_tags = item.get("tags", [])
            sub_path = (base_dir / import_rel).resolve()

            if not sub_path.exists():
                raise FileNotFoundError(
                    f"Imported config file not found: {sub_path} "
                    f"(referenced from {config_path})"
                )

            logger.debug("Expanding import: %s -> %s", import_rel, sub_path)

            sub_config = _load_raw_config(sub_path)
            # Recursively expand (pass loaded_paths copy for cycle detection)
            sub_config = expand_imports(sub_config, sub_path, loaded_paths)

            # Merge setup from sub-file
            sub_setup = sub_config.get("setup", {})
            if sub_setup:
                setup = _deep_merge_setup(setup, sub_setup)

            sub_cases = sub_config.get("test_cases", [])

            # Inject import-level tags into each imported case
            if import_tags:
                for case in sub_cases:
                    existing = case.get("tags", [])
                    case["tags"] = list(dict.fromkeys(import_tags + existing))

            expanded_cases.extend(sub_cases)
        else:
            expanded_cases.append(item)

    result: Dict[str, Any] = {"test_cases": expanded_cases}
    if setup:
        result["setup"] = setup

    return result
