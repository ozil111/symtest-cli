# -*- coding: utf-8 -*-

"""
.symtest Runtime History Store

Manages persistent storage of per-case runtime history for smart scheduling
and regression detection.
"""

import json
import os
from typing import Dict, Optional

SYMTEST_FILENAME = "history.json"


def _empty_history() -> dict:
    """Return an empty history structure."""
    return {"version": 1, "cases": {}}


def ensure_symtest(history_dir: str) -> None:
    """Create .symtest in the directory if it doesn't exist."""
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_empty_history(), f, indent=2)


def load_history(history_dir: str) -> dict:
    """Load .symtest from the directory. Auto-init if missing."""
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    if not os.path.exists(path):
        ensure_symtest(history_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "cases" not in data:
        data["cases"] = {}
    return data


def save_history(history_dir: str, history: dict) -> None:
    """Write history back to .symtest."""
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, SYMTEST_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_case(history: dict, name: str, duration: float) -> None:
    """Update a single case's record using cumulative average."""
    cases = history.setdefault("cases", {})
    if name in cases:
        rec = cases[name]
        old_avg = rec["avg_duration"]
        count = rec["run_count"]
        rec["avg_duration"] = (old_avg * count + duration) / (count + 1)
        rec["last_duration"] = duration
        rec["run_count"] = count + 1
    else:
        cases[name] = {
            "avg_duration": duration,
            "last_duration": duration,
            "run_count": 1,
        }


def reset_cases(history: dict, case_names: set) -> int:
    """Remove given case names from history. Returns count of removed entries."""
    cases = history.get("cases", {})
    cleared = 0
    for name in case_names:
        if name in cases:
            del cases[name]
            cleared += 1
    return cleared


def check_regression(
    history: dict, name: str, duration: float, threshold: float = 1.5
) -> Optional[str]:
    """Return a warning message if duration exceeds avg * threshold, else None."""
    cases = history.get("cases", {})
    if name not in cases:
        return None
    avg = cases[name]["avg_duration"]
    if avg <= 0:
        return None
    if duration > avg * threshold:
        ratio = duration / avg
        return (
            f"⚠ WARNING: Case '{name}' regressed: "
            f"{duration:.2f}s vs avg {avg:.2f}s ({ratio:.2f}x slower)"
        )
    return None
