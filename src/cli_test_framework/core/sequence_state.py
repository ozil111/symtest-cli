"""
Sequence state store for step-level resume (``--resume``).

Stores intermediate step results so that when a sequence test case fails,
re-running with ``--resume`` skips already-passed steps and reconstructs
``combined_output`` from cached step outputs.

State file: ``<workspace>/.cli-test/sequence_state/<case_name>.json``
Output cache: ``<workspace>/.cli-test/sequence_state/cache/<case_name>.step<N>.log``

**Trust model**: ``--resume`` trusts that workspace artifacts (input files,
pre-step outputs) have not been modified between runs.  No artifact
validation is performed — the user asserts correctness by opting into resume.
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cli_test_framework.core.sequence_state")

SEQUENCE_STATE_DIR = ".cli-test/sequence_state"
CACHE_SUBDIR = "cache"


def _state_dir_path(workspace: str) -> str:
    return os.path.join(workspace, SEQUENCE_STATE_DIR)


def _cache_dir_path(workspace: str) -> str:
    return os.path.join(_state_dir_path(workspace), CACHE_SUBDIR)


def _case_state_path(workspace: str, case_name: str) -> str:
    return os.path.join(_state_dir_path(workspace), f"{case_name}.json")


def _step_output_path(workspace: str, case_name: str, step_idx: int) -> str:
    dir_path = _cache_dir_path(workspace)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{case_name}.step{step_idx}.log")


def compute_config_hash(
    steps: List[Any],
    case_expected: Optional[Dict[str, Any]] = None,
) -> str:
    """Compute a deterministic SHA-256 hash of the step configuration.

    If any step's command/args/expected or the case-level expected block
    changes, the hash will differ and ``--resume`` will fall back to a full
    re-run.
    """
    hasher = hashlib.sha256()
    for i, step in enumerate(steps):
        cmd = (
            getattr(step, "command", "")
            if hasattr(step, "command")
            else step.get("command", "")
        )
        args = (
            getattr(step, "args", [])
            if hasattr(step, "args")
            else step.get("args", [])
        )
        expected = (
            getattr(step, "expected", {})
            if hasattr(step, "expected")
            else step.get("expected", {})
        )
        hasher.update(
            f"step{i}:{cmd}:{sorted(args)}:{sorted(expected.items())}".encode(
                "utf-8"
            )
        )
    if case_expected:
        hasher.update(
            f"case_expected:{sorted(case_expected.items())}".encode("utf-8")
        )
    return hasher.hexdigest()


def load_sequence_state(
    workspace: str, case_name: str
) -> Optional[Dict[str, Any]]:
    """Load persisted step state for a case.  Returns ``None`` if not found."""
    path = _case_state_path(workspace, case_name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Corrupted sequence state for %s, ignoring.", case_name)
        return None


def save_sequence_state(
    workspace: str, case_name: str, state: Dict[str, Any]
) -> None:
    """Persist step state for a case."""
    dir_path = _state_dir_path(workspace)
    os.makedirs(dir_path, exist_ok=True)
    path = _case_state_path(workspace, case_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def delete_sequence_state(workspace: str, case_name: str) -> None:
    """Remove state file and cached step outputs (case fully passed)."""
    # Remove state file
    path = _case_state_path(workspace, case_name)
    if os.path.exists(path):
        os.remove(path)
    # Remove cached step outputs
    for step_idx in range(1, 100):  # reasonable upper bound
        out_path = _step_output_path(workspace, case_name, step_idx)
        if os.path.exists(out_path):
            os.remove(out_path)
        else:
            break


def save_step_output(
    workspace: str, case_name: str, step_idx: int, output: str
) -> str:
    """Save step output to cache and return the cache file path."""
    path = _step_output_path(workspace, case_name, step_idx)
    with open(path, "w", encoding="utf-8") as f:
        f.write(output)
    return path


def load_step_output(
    workspace: str, case_name: str, step_idx: int
) -> Optional[str]:
    """Load cached step output.  Returns ``None`` if not found."""
    path = _step_output_path(workspace, case_name, step_idx)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
