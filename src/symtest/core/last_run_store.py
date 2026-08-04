# -*- coding: utf-8 -*-

"""
Last-run state store for ``--last-failed`` support.

Stores per-case status in ``<workspace>/.symtest/last_run.json``.
Each run **overwrites** the status of every case that was executed,
so "previously failed but now fixed" cases are immediately removed
from the failed set.  Cases that were not executed in this run
retain their previous status.
"""

import json
import os
from typing import Dict, List, Optional

LAST_RUN_DIR = ".symtest"
LAST_RUN_FILENAME = "last_run.json"


def _last_run_path(workspace: str) -> str:
    """Return the full path to ``last_run.json`` for a workspace."""
    return os.path.join(workspace, LAST_RUN_DIR, LAST_RUN_FILENAME)


def load_last_run(workspace: str) -> Dict:
    """Load last-run state. Returns empty dict when file doesn't exist."""
    path = _last_run_path(workspace)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}


def save_last_run(workspace: str, data: Dict) -> None:
    """Write last-run state, creating the directory if needed."""
    dir_path = os.path.join(workspace, LAST_RUN_DIR)
    os.makedirs(dir_path, exist_ok=True)
    path = _last_run_path(workspace)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_last_run(
    workspace: str,
    results: List[Dict],
) -> None:
    """Update last-run state with the results from the current execution.

    For each result dict in *results*:
    - The case's entry is **overwritten** with the current status.
    - Cases in the existing file that were NOT part of this run
      retain their previous status (e.g. when running a subset via ``-t``).

    This ensures ``--last-failed`` never includes a case that passed
    in the most recent run, since passing results overwrite any prior
    failure record.
    """
    data = load_last_run(workspace)

    for result in results:
        name = result.get("name", "")
        if not name:
            continue
        # Only store status + the case name
        data[name] = {
            "status": result.get("status", "unknown"),
        }

    save_last_run(workspace, data)


def get_last_failed_names(workspace: str) -> List[str]:
    """Return the names of cases that failed in the last run.

    Returns an empty list when no last-run state exists (first run).
    """
    data = load_last_run(workspace)
    if not data:
        return []
    return sorted(
        name for name, info in data.items()
        if info.get("status") in ("failed", "timeout", "xpassed")
    )


def get_last_run_summary(workspace: str) -> Dict[str, int]:
    """Return a summary counts dict: total, passed, failed, xfailed, xpassed, timeout."""
    data = load_last_run(workspace)
    summary = {"total": 0, "passed": 0, "failed": 0, "xfailed": 0, "xpassed": 0, "timeout": 0}
    for info in data.values():
        st = info.get("status", "unknown")
        summary["total"] += 1
        if st == "passed":
            summary["passed"] += 1
        elif st == "xfailed":
            summary["xfailed"] += 1
        elif st == "xpassed":
            summary["xpassed"] += 1
            summary["failed"] += 1  # xpassed IS a suite failure
        elif st == "failed":
            summary["failed"] += 1
        elif st == "timeout":
            summary["timeout"] += 1
            summary["failed"] += 1  # timeout counts in failure aggregate
    return summary
