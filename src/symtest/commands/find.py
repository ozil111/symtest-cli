"""symtest find — search test cases across all imported configurations.

Replaces the search capability of the retired TUI: loads the config through
the same pipeline as the runners (import expansion + inheritance resolution
via ``load_config``), parses cases with the single system-wide parser, then
matches each case across name / command / args / tags / description using
one of three modes:

- ``substring`` (default): case-insensitive substring
- ``regex``: case-insensitive regular expression (invalid pattern simply
  matches nothing, never raises; the pattern is compiled once per search)
- ``fuzzy``: bigram-overlap scoring with field weights, results ranked by
  score

An empty pattern lists all cases in every mode (consistent semantics).

Exit codes (grep semantics): 0 = matches found, 1 = no match, 2 = error
(config unreadable / unparseable).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

from ..config.config_io import load_config
from ..core.config_loader import parse_test_cases
from ..core.test_case import TestCase

logger = logging.getLogger("symtest.commands.find")

# ---------------------------------------------------------------------------
# Search helpers (moved verbatim from the retired TUI CaseController)
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


def _regex_match(pattern: Pattern[str], case: TestCase) -> bool:
    """Compiled-pattern search across all searchable fields.

    Compilation happens once per search in :func:`search_cases`; this
    function only applies the already-compiled pattern.
    """
    for _field_name, extractor in _SEARCH_FIELDS:
        if pattern.search(extractor(case)):
            return True
    return False


def _fuzzy_score(query: str, case: TestCase) -> float:
    """N-gram overlap scorer; higher = better match."""
    q = query.lower()
    q_bigrams = {q[i: i + 2] for i in range(len(q) - 1)} if len(q) >= 2 else {q}
    if not q_bigrams:
        return 0.0

    total = 0.0
    for field_name, extractor in _SEARCH_FIELDS:
        text = extractor(case).lower()
        text_bigrams = {text[i: i + 2] for i in range(len(text) - 1)}
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


def search_cases(
    cases: List[TestCase],
    query: str,
    mode: str = "substring",
    tags: Optional[List[str]] = None,
) -> List[int]:
    """Return sorted list of indices for cases matching *query*.

    Parameters
    ----------
    cases:
        Parsed TestCase list.
    query:
        Search term. An empty term short-circuits to all cases in every
        mode (consistent semantics, no matcher run).
    mode:
        ``"substring"`` (default), ``"fuzzy"``, or ``"regex"``.
    tags:
        Optional tag filter (OR relationship), applied after the query match.
    """
    if not query:
        indices = list(range(len(cases)))
    elif mode == "fuzzy":
        indices = _fuzzy_match(query, cases)
    elif mode == "regex":
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = None
        indices = (
            [i for i, tc in enumerate(cases) if _regex_match(pattern, tc)]
            if pattern is not None
            else []
        )
    else:  # substring (default)
        indices = [i for i, tc in enumerate(cases) if _substring_match(query, tc)]

    if tags:
        indices = [i for i in indices if any(t in cases[i].tags for t in tags)]

    return indices


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------


def _case_summary(index: int, tc: TestCase) -> Dict[str, Any]:
    """Build the display/JSON summary dict for one matched case."""
    return {
        "index": index + 1,
        "name": tc.name,
        "command": tc.command,
        "args": list(tc.args),
        "tags": list(tc.tags),
        "description": tc.description or "",
        "timeout": tc.timeout,
        "mode": "steps" if tc.steps else "single",
    }


def _display_width(text: str) -> int:
    """Terminal display width: CJK full/wide chars count as 2 columns."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _print_table(rows: List[Dict[str, Any]]) -> None:
    """Print matched cases as aligned columns (the retired TUI table layout)."""
    headers = ["#", "Name", "Command", "Tags", "Timeout", "Mode"]

    def fmt(row: Dict[str, Any]) -> List[str]:
        return [
            str(row["index"]),
            row["name"],
            row["command"],
            ",".join(row["tags"]),
            "-" if row["timeout"] is None else str(row["timeout"]),
            row["mode"],
        ]

    cells = [headers] + [fmt(r) for r in rows]
    widths = [max(_display_width(c[i]) for c in cells) for i in range(len(headers))]

    def pad(cell: str, width: int) -> str:
        return cell + " " * (width - _display_width(cell))

    for i, row in enumerate(cells):
        line = "  ".join(pad(cell, widths[j]) for j, cell in enumerate(row)).rstrip()
        print(line)
        if i == 0:
            print("  ".join("-" * w for w in widths))


def run_find(args) -> int:
    """CLI entry for ``symtest find``.

    Returns
    -------
    int
        0 = matches found, 1 = no match, 2 = error.
    """
    workspace_path = Path(args.workspace) if args.workspace else Path.cwd()
    config_file = (workspace_path / args.config_file).resolve()

    try:
        config = load_config(config_file)
        cases = parse_test_cases(config)
    except Exception as e:
        logger.error("Failed to load configuration: %s", e)
        return 2

    logger.info("Loaded %d test case(s) from %s", len(cases), config_file)

    matched = search_cases(
        cases,
        args.pattern,
        mode=getattr(args, "mode", "substring"),
        tags=getattr(args, "tag", None),
    )

    if not matched:
        print(f"No test cases match pattern '{args.pattern}'.")
        return 1

    rows = [_case_summary(i, cases[i]) for i in matched]

    if getattr(args, "output_format", "text") == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(f"\n{len(matched)}/{len(cases)} test case(s) match "
              f"'{args.pattern}' in {config_file.name}:\n")
        _print_table(rows)
        print()

    return 0
