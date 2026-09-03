#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file csv_comparator.py
@brief CSV file comparator implementation with row and column comparison
@author Xiaotong Wang
@date 2025
"""

import csv
import io
import re
import numpy as np
from .text_comparator import TextComparator
from .result import Difference
from .numeric_compare import compare_numeric, parse_data_filter

class CsvComparator(TextComparator):
    """
    @brief Comparator for CSV files with row and column comparison
    @details This class extends TextComparator to provide specialized CSV comparison
             capabilities, including:
             - Row count comparison
             - Column count comparison
             - Cell value comparison
             - Configurable delimiter and quote character
    """
    
    def __init__(self, encoding="utf-8", delimiter=",", quotechar='"', chunk_size=8192, verbose=False, rtol=1e-5, atol=1e-8, data_filter=None, error_analysis=False, **kwargs):
        """
        @brief Initialize CSV comparator with configuration
        @param encoding str: File encoding (default: utf-8)
        @param delimiter str: CSV field delimiter (default: comma)
        @param quotechar str: Character used for quoting fields (default: double quote)
        @param chunk_size int: Size of chunks for reading large files
        @param verbose bool: Enable verbose output
        @param rtol float: Relative tolerance for numerical comparison (default: 1e-5)
        @param atol float: Absolute tolerance for numerical comparison (default: 1e-8)
        @param data_filter str: Data filter expression applied before numeric comparison
        @param error_analysis bool: Enable streaming error statistics over ALL numeric cells
        @param **kwargs: Additional parameters (ignored)
        """
        super().__init__(encoding=encoding, chunk_size=chunk_size, verbose=verbose, **kwargs)
        self.delimiter = delimiter
        self.quotechar = quotechar
        self.rtol = rtol
        self.atol = atol
        self.data_filter = data_filter
        self.filter_func = self._parse_filter()
        self.error_analysis = error_analysis
        self._error_stats = None
    
    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Read and parse CSV content from file
        @param file_path Path: Path to the CSV file
        @param start_line int: Starting line number
        @param end_line int: Ending line number
        @param start_column int: Starting column number
        @param end_column int: Ending column number
        @return list: List of rows, where each row is a list of cell values
        @details Reads CSV content and parses it into a structured format,
                 supporting line and column range selection
        """
        # First read the file as text
        text_content = super().read_content(file_path, start_line, end_line, start_column, end_column)
        
        # Join the lines to create a CSV string
        csv_text = ''.join(text_content)
        
        # Parse the CSV
        csv_data = []
        csv_reader = csv.reader(
            io.StringIO(csv_text), 
            delimiter=self.delimiter,
            quotechar=self.quotechar
        )
        
        for row in csv_reader:
            # Apply column range if specified
            if start_column > 0 or end_column is not None:
                col_start = start_column
                col_end = end_column if end_column is not None else len(row)
                row = row[col_start:col_end+1]
            csv_data.append(row)
            
        return csv_data
    
    def compare_content(self, content1, content2):
        """
        @brief Compare CSV content structurally
        @param content1 list: First CSV data to compare (list of rows)
        @param content2 list: Second CSV data to compare (list of rows)
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        @details Performs structural comparison of CSV data, including:
                 - Row count comparison
                 - Column count comparison per row
                 - Cell value comparison
                 - Limits the number of reported differences
                 - When error_analysis=True, accumulates streaming stats over ALL numeric cells
        """
        self._error_stats = None  # Reset per comparison

        # Fast path only when stats are not requested; with error_analysis we
        # must still traverse all numeric cells to build the statistics.
        if content1 == content2 and not self.error_analysis:
            return True, [], False
            
        differences = []
        max_diffs = 10

        # ── Numeric core accumulators ──
        # error_analysis mode collects ALL filtered numeric cells (matching or not)
        # and delegates statistics to the shared numeric core.
        stats_exp = []
        stats_act = []
        stats_pos = []  # (row, col) 0-based, aligned with stats_exp/stats_act

        # Check row count
        if len(content1) != len(content2):
            differences.append(Difference(
                position="row count",
                expected=f"{len(content1)} rows",
                actual=f"{len(content2)} rows",
                diff_type="row_count_mismatch"
            ))
        
        # Compare rows
        for i, (row1, row2) in enumerate(zip(content1, content2)):
            # Check column count in this row
            if len(row1) != len(row2):
                if len(differences) < max_diffs:
                    differences.append(Difference(
                        position=f"row {i+1}",
                        expected=f"{len(row1)} columns",
                        actual=f"{len(row2)} columns",
                        diff_type="column_count_mismatch"
                    ))
                if not self.error_analysis and len(differences) >= max_diffs:
                    break
            
            # Collect numeric cells in this row (for delegated closeness check)
            row_exp = []
            row_act = []
            row_pos = []  # (row, col) 0-based
            for j, (cell1, cell2) in enumerate(zip(row1, row2)):
                num1 = num2 = None
                try:
                    num1 = float(cell1)
                    num2 = float(cell2)
                except (ValueError, TypeError):
                    pass  # Non-numeric

                is_numeric = num1 is not None and num2 is not None
                passes_filter = True
                if is_numeric and self.filter_func:
                    # vectorized filter applied element-wise on scalar input
                    if not (bool(self.filter_func(np.asarray(num1))) and
                            bool(self.filter_func(np.asarray(num2)))):
                        passes_filter = False

                if is_numeric and passes_filter:
                    # Counted as a numeric cell (regardless of text equality)
                    row_exp.append(num1)
                    row_act.append(num2)
                    row_pos.append((i, j))
                    if self.error_analysis:
                        stats_exp.append(num1)
                        stats_act.append(num2)
                        stats_pos.append((i, j))

                if cell1 == cell2:
                    continue
                if is_numeric:
                    # Numeric cell: within-tolerance decisions are made below via the core.
                    # Filtered-out numeric cells are skipped entirely (no difference).
                    continue

                # Non-numeric text mismatch
                if len(differences) < max_diffs:
                    differences.append(Difference(
                        position=f"row {i+1}, column {j+1}",
                        expected=cell1,
                        actual=cell2,
                        diff_type="cell_mismatch"
                    ))

            # Determine closeness for this row's numeric cells via the shared core.
            if row_exp:
                row_res = compare_numeric(
                    row_exp, row_act, rtol=self.rtol, atol=self.atol,
                    filter_func=self.filter_func, collect_stats=False,
                )
                for k, is_mismatch in enumerate(row_res.mismatch_mask):
                    if is_mismatch and len(differences) < max_diffs:
                        ri, cj = row_pos[k]
                        differences.append(Difference(
                            position=f"row {ri+1}, column {cj+1}",
                            expected=content1[ri][cj],
                            actual=content2[ri][cj],
                            diff_type="cell_mismatch"
                        ))

            if not self.error_analysis and len(differences) >= max_diffs:
                break

        truncated = len(differences) >= max_diffs

        # ── Store error stats via the shared numeric core ──
        if self.error_analysis and stats_exp:
            res = compare_numeric(
                stats_exp, stats_act, rtol=self.rtol, atol=self.atol,
                filter_func=self.filter_func, collect_stats=True,
            )
            max_abs_error = res.max_abs_error
            max_rel_error = res.max_rel_error
            max_abs_error_at = None
            max_rel_error_at = None
            if max_abs_error is not None:
                ri, cj = stats_pos[res.max_abs_error_index]
                max_abs_error_at = f"row {ri+1}, column {cj+1}"
            if max_rel_error is not None:
                ri, cj = stats_pos[res.max_rel_error_index]
                max_rel_error_at = f"row {ri+1}, column {cj+1}"
            self._error_stats = {
                "total_numeric_cells": res.total,
                "mismatched_cells": res.mismatched,
                "max_abs_error": max_abs_error,
                "max_abs_error_at": max_abs_error_at,
                "max_rel_error": max_rel_error,
                "max_rel_error_at": max_rel_error_at,
                "mean_abs_error": res.mean_abs_error,
                "rms_abs_error": res.rms_abs_error,
            }

        if not differences:
            return True, [], False
        return False, differences, truncated

    def _parse_filter(self):
        """Parse data filter string and return a filter function (delegates to numeric core)"""
        return parse_data_filter(self.data_filter, logger=self.logger)