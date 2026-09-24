#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file my_analysis_comparator.py
@brief Autonomous-lane workspace plugin template for symtest-cli (v2 contract)
@details Copy this file into <workspace>/comparators/ and adapt the logic.
         Auto-discovered and registered as type "myanalysis" (class name minus
         the "Comparator" suffix, lowercased) — or set a `comparator_type`
         class attribute to override the name.

Autonomous lane = the plugin OWNS the verdict (e.g. composite thresholds,
label parsing, sign/asymptotic checks).  If your data is plain numeric
arrays compared with rtol/atol, use the data lane instead
(see my_channel_extractor.py / the built-in "script_extract" type).

v2 contract notes (breaking vs. pre-2.x):
- Implement `compare(self, ctx) -> ComparisonResult`; do NOT override
  `compare_files`, and do NOT implement `read_content`/`compare_content`
  (they no longer exist on the root class).
- `ctx` carries invocation context only: workspace / actual / baseline /
  params (window ranges) / error_analysis.  Comparator configuration lives
  ONLY in constructor state (single source of truth).
- Declare path-like constructor params in `path_params`; the framework
  resolves them against the workspace BEFORE construction.  Never resolve
  paths against CWD.
- Constructor parameters are STRICT: unknown/misspelled compareSpec keys
  fail loudly at construction.  Opt into free-form config only explicitly
  (your own `**params` catch-all).
"""

from symtest.file_comparator.base_comparator import BaseComparator, CompareContext
from symtest.file_comparator.result import ComparisonResult, Difference


class MyAnalysisComparator(BaseComparator):
    """
    @brief Analysis-style comparator that owns its verdict.
    @details Constructor parameters are strict — a misspelled config key
             (e.g. "pass_threhsold") fails construction instead of silently
             using the default.
    """

    # Constructor params holding filesystem paths (framework-resolved).
    path_params = ("script", "case_dir")

    def __init__(self, script="", case_dir=None, pass_threshold=1e-6):
        super().__init__()
        self.script = script
        self.case_dir = case_dir  # already workspace-resolved via path_params
        self.pass_threshold = pass_threshold

    def compare(self, ctx: CompareContext) -> ComparisonResult:
        """
        @param ctx CompareContext: invocation context (paths resolved).
        @return ComparisonResult: structured result consumed by the report.
        """
        result = ComparisonResult(
            file1=str(ctx.baseline or ""),
            file2=str(ctx.actual or ""),
        )

        # TODO: replace with real analysis logic — read ctx.actual /
        # ctx.baseline, run a subprocess (self.script, cwd=self.case_dir),
        # parse metrics from stdout, etc.
        metrics = {"max_error": 0.0}
        max_error = metrics["max_error"]
        identical = max_error < self.pass_threshold

        result.identical = identical
        result.differences = [
            Difference(
                position="max_error",
                expected=f"<{self.pass_threshold}",
                actual=str(max_error),
                diff_type="content",
            )
        ] if not identical else []
        result.error_stats = metrics  # free-form dict; rendered generically
        result.command_output = None  # optional: subprocess stdout -> report
        return result
