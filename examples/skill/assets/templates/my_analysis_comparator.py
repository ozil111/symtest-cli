#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file my_analysis_comparator.py
@brief Minimal, runnable workspace plugin template for symtest-cli
@details Copy this file into <workspace>/comparators/ and adapt the logic.
         It is auto-discovered and registered as type "myanalysis" (class
         name minus the "Comparator" suffix, lowercased).
@author Xiaotong Wang
@date 2025
"""

from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator import ComparisonResult
from symtest.file_comparator.result import Difference


class MyAnalysisComparator(BaseComparator):
    """
    @brief Analysis-style comparator that does not use the two-file model.
    @details Overrides compare_files() directly. The framework constructs it
             with verbose / error_analysis plus every extra kwarg from the
             config compareSpec, so __init__ must forward **kwargs to super.
    """

    def __init__(self, pass_threshold=1e-6, **kwargs):
        # IMPORTANT: forward **kwargs so the framework's verbose=,
        # error_analysis= and config extra params never break construction.
        super().__init__(**kwargs)
        self.pass_threshold = pass_threshold

    # BaseComparator declares read_content / compare_content as abstract
    # methods, so they must be implemented even if compare_files overrides
    # everything (otherwise the class cannot be instantiated).
    def read_content(self, file_path, start_line=0, end_line=None,
                     start_column=0, end_column=None):
        raise NotImplementedError(
            "MyAnalysisComparator uses compare_files directly; "
            "read_content/compare_content are not used."
        )

    def compare_content(self, content1, content2):
        raise NotImplementedError(
            "MyAnalysisComparator uses compare_files directly; "
            "read_content/compare_content are not used."
        )

    def compare_files(self, file1, file2, **kwargs):
        """
        @param file1 str: baseline file path (as in assertions.py)
        @param file2 str: actual output file path
        @return ComparisonResult: structured result consumed by the report.
        """
        result = ComparisonResult(file1=str(file1), file2=str(file2))

        # TODO: replace with real analysis logic (read file1/file2, run
        # subprocess, compute metrics, etc.).
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
        result.error_stats = metrics  # optional, shown in report
        result.command_output = None  # optional: subprocess stdout -> report
        return result
