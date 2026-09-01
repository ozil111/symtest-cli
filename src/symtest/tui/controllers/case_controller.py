"""Bridge between config I/O and the TUI: CRUD, search, run."""

from __future__ import annotations

import copy
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...core.test_case import TestCase, TestCaseStep
from ...core.orchestration.single import execute_single_test_case
from ...core.orchestration.sequence import execute_sequence
from ...core.config_loader import parse_test_cases
from ...config.config_io import load_config, save_config

logger = logging.getLogger("symtest.tui.controller")

# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

# Field weights for fuzzy scoring (higher = more important).
_FIELD_WEIGHTS: Dict[str, float] = {
    "name": 2.0,
    "command": 1.5,
    "tags": 1.0,
    "description": 1.0,
    "args": 0.5,
}

# Default searchable fields and their extractors
_SEARCH_FIELDS = [
    ("name", lambda tc: tc.name),
    ("command", lambda tc: tc.command),
    ("args", lambda tc: " ".join(tc.args)),
    ("tags", lambda tc: ",".join(tc.tags)),
    ("description", lambda tc: tc.description or ""),
]


def _substring_match(query: str, case: TestCase) -> bool:
    """Case-insensitive substring match across all searchable fields."""
    q = query.lower()
    for _field_name, extractor in _SEARCH_FIELDS:
        if q in extractor(case).lower():
            return True
    return False


def _regex_match(query: str, case: TestCase) -> bool:
    """Regex search across all searchable fields (case-insensitive)."""
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        return False
    for _field_name, extractor in _SEARCH_FIELDS:
        if pattern.search(extractor(case)):
            return True
    return False


def _fuzzy_score(query: str, case: TestCase) -> float:
    """N-gram overlap scorer; higher = better match."""
    q = query.lower()
    q_bigrams = {q[i : i + 2] for i in range(len(q) - 1)} if len(q) >= 2 else {q}
    if not q_bigrams:
        return 0.0

    total = 0.0
    for field_name, extractor in _SEARCH_FIELDS:
        text = extractor(case).lower()
        text_bigrams = {text[i : i + 2] for i in range(len(text) - 1)}
        if not text_bigrams:
            continue
        overlap = len(q_bigrams & text_bigrams) / len(q_bigrams)
        total += _FIELD_WEIGHTS.get(field_name, 0.5) * overlap
    return total


def _fuzzy_match(query: str, cases: List[TestCase], threshold: float = 0.15) -> List[int]:
    """Return indices of cases whose fuzzy score meets *threshold*."""
    scored: List[Tuple[int, float]] = []
    for i, tc in enumerate(cases):
        s = _fuzzy_score(query, tc)
        if s >= threshold:
            scored.append((i, s))
    scored.sort(key=lambda x: -x[1])
    return [idx for idx, _ in scored]


# ---------------------------------------------------------------------------
# CaseController
# ---------------------------------------------------------------------------


class CaseController:
    """Holds test cases in memory and bridges config_io ↔ TUI."""

    def __init__(self):
        self._cases: List[TestCase] = []
        self._file_path: Optional[Path] = None
        self._workspace: Optional[str] = None
        self._dirty = False
        self._setup: Dict[str, Any] = {}
        self._update_baseline: bool = False
        self._history_dir: Optional[str] = None
        self._update_history: bool = False

    # -- properties ----------------------------------------------------------

    @property
    def cases(self) -> List[TestCase]:
        return self._cases

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    @property
    def file_name(self) -> str:
        return self._file_path.name if self._file_path else "(untitled)"

    @property
    def workspace(self) -> Optional[str]:
        return self._workspace

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def case_count(self) -> int:
        return len(self._cases)

    @property
    def update_baseline(self) -> bool:
        return self._update_baseline

    @update_baseline.setter
    def update_baseline(self, value: bool) -> None:
        self._update_baseline = value

    @property
    def history_dir(self) -> Optional[str]:
        return self._history_dir

    @history_dir.setter
    def history_dir(self, value: Optional[str]) -> None:
        self._history_dir = value

    @property
    def update_history(self) -> bool:
        return self._update_history

    @update_history.setter
    def update_history(self, value: bool) -> None:
        self._update_history = value

    # -- load / save ---------------------------------------------------------

    def load(self, file_path: str, workspace: Optional[str] = None) -> int:
        """Load config from *file_path*, parse test cases, return case count."""
        path = Path(file_path).resolve()
        config = load_config(path)

        # Store setup for later re-serialisation
        self._setup = config.get("setup", {})
        self._file_path = path
        self._workspace = workspace

        # Parse test cases via unified entry point. TUI owns the relaxed
        # form explicitly (1.4 原则 6)：no path resolution for display and
        # strict=False so incomplete cases get sensible defaults.
        self._cases = parse_test_cases(config, strict=False)
        self._dirty = False
        return len(self._cases)

    def save(self, file_path: Optional[str] = None) -> None:
        """Persist cases to the current file (or *file_path* if given)."""
        target = Path(file_path) if file_path else self._file_path
        if target is None:
            raise ValueError("No file path set for save.")

        config: Dict[str, Any] = {"test_cases": []}
        if self._setup:
            config["setup"] = self._setup
        config["test_cases"] = [tc.to_dict() for tc in self._cases]

        save_config(config, target)

        if file_path:
            self._file_path = Path(file_path).resolve()

        self._dirty = False

    def save_as(self, file_path: str) -> None:
        """Save to a different file."""
        self.save(file_path=file_path)

    # -- CRUD ----------------------------------------------------------------

    def get_case(self, index: int) -> TestCase:
        return self._cases[index]

    def add_case(self, case: TestCase) -> int:
        """Append *case*; return its index."""
        self._cases.append(case)
        self._dirty = True
        return len(self._cases) - 1

    def update_case(self, index: int, case: TestCase) -> None:
        self._cases[index] = case
        self._dirty = True

    def delete_case(self, index: int) -> None:
        del self._cases[index]
        self._dirty = True

    def duplicate_case(self, index: int) -> int:
        """Deep-copy case at *index*, append '_copy' to name."""
        original = self._cases[index]
        new_case = copy.deepcopy(original)
        new_case.name = original.name + "_copy"
        return self.add_case(new_case)

    def move_case(self, from_idx: int, to_idx: int) -> None:
        """Move case from *from_idx* to *to_idx*."""
        if from_idx == to_idx:
            return
        case = self._cases.pop(from_idx)
        self._cases.insert(to_idx, case)
        self._dirty = True

    def swap_cases(self, i: int, j: int) -> None:
        self._cases[i], self._cases[j] = self._cases[j], self._cases[i]
        self._dirty = True

    # -- search --------------------------------------------------------------

    def search(
        self,
        query: str,
        mode: str = "substring",
        tag: Optional[str] = None,
    ) -> List[int]:
        """Return sorted list of indices for cases matching *query*.

        Parameters
        ----------
        query:
            Search term.
        mode:
            ``"substring"`` (default), ``"fuzzy"``, or ``"regex"``.
        tag:
            Optional tag filter (exact match).
        """
        if mode == "fuzzy":
            indices = _fuzzy_match(query, self._cases)
        elif mode == "regex":
            indices = [i for i, tc in enumerate(self._cases) if _regex_match(query, tc)]
        else:  # substring (default)
            indices = [i for i, tc in enumerate(self._cases) if _substring_match(query, tc)]

        # Apply tag filter
        if tag:
            indices = [i for i in indices if tag in self._cases[i].tags]

        return indices

    def get_all_tags(self) -> List[str]:
        """Collect unique tags across all cases, sorted."""
        tags: set = set()
        for tc in self._cases:
            tags.update(tc.tags)
        return sorted(tags)

    # -- run ----------------------------------------------------------------

    def run_case(self, index: int) -> Dict[str, Any]:
        """Execute a single test case and return the result dict."""
        case = self._cases[index]
        if case.steps:
            # Sequence mode — use execute_sequence (consistent with Runner)
            result = execute_sequence(
                case_name=case.name,
                steps=case.steps,
                workspace=self._workspace,
                update_baseline=self._update_baseline,
            )
        else:
            # Single-command mode — ExecutionSpec + expectation 直供编排层
            result = execute_single_test_case(
                case.execution,
                self._workspace,
                expectation=case.expected,
                update_baseline=self._update_baseline,
            )
        self._record_history(case.name, result)
        return result

    def _record_history(self, case_name: str, result: Dict[str, Any]) -> None:
        """Per-case history recording with optional reset support."""
        if not self._history_dir:
            return
        from pathlib import Path as _Path
        from ...core.history_store import load_history, save_history, reset_cases, update_case

        history_dir = str((_Path(self._workspace or ".") / self._history_dir).resolve())
        history = load_history(history_dir)

        if self._update_history:
            cleared = reset_cases(history, {case_name})
            if cleared:
                logger.info("History reset: cleared '%s'", case_name)

        if result.get("status") == "passed":
            update_case(history, case_name, result.get("duration", 0))
        save_history(history_dir, history)

    @staticmethod
    def create_empty_case(mode: str = "single") -> TestCase:
        """Create a blank TestCase."""
        if mode == "sequence":
            return TestCase(name="new_case", steps=[])
        return TestCase(name="new_case", command="", args=[], expected={}, tags=[])
