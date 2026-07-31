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
import math
import re
from .text_comparator import TextComparator
from .result import Difference

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

        if content1 == content2:
            return True, [], False
            
        differences = []
        max_diffs = 10

        # ── Error analysis accumulators ──
        total_numeric_cells = 0
        mismatched_cells = 0
        sum_abs_error = 0.0
        sum_sq_abs_error = 0.0
        max_abs_error = None
        max_abs_error_at = None
        max_rel_error = None
        max_rel_error_at = None
        
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
            
            # Compare column values
            for j, (cell1, cell2) in enumerate(zip(row1, row2)):
                if cell1 != cell2:
                    # Try numeric tolerance comparison
                    try:
                        num1 = float(cell1)
                        num2 = float(cell2)
                        # Apply data filter
                        if self.filter_func:
                            if not (self.filter_func(num1) and self.filter_func(num2)):
                                continue
                        total_numeric_cells += 1
                        abs_err = abs(num2 - num1)
                        if math.isclose(num1, num2, rel_tol=self.rtol, abs_tol=self.atol):
                            continue  # Within tolerance

                        # Mismatched numeric cell
                        mismatched_cells += 1
                        sum_abs_error += abs_err
                        sum_sq_abs_error += abs_err * abs_err
                        rel_err = abs_err / max(abs(num1), 1e-300) if abs(num1) > 0 else float("inf")

                        if max_abs_error is None or abs_err > max_abs_error:
                            max_abs_error = abs_err
                            max_abs_error_at = f"row {i+1}, column {j+1}"
                        if max_rel_error is None or rel_err > max_rel_error:
                            max_rel_error = rel_err
                            max_rel_error_at = f"row {i+1}, column {j+1}"
                    except (ValueError, TypeError):
                        pass  # Non-numeric, fall through

                    if len(differences) < max_diffs:
                        differences.append(Difference(
                            position=f"row {i+1}, column {j+1}",
                            expected=cell1,
                            actual=cell2,
                            diff_type="cell_mismatch"
                        ))

            if not self.error_analysis and len(differences) >= max_diffs:
                break

        truncated = len(differences) >= max_diffs

        # ── Store error stats ──
        if self.error_analysis and total_numeric_cells > 0:
            self._error_stats = {
                "total_numeric_cells": total_numeric_cells,
                "mismatched_cells": mismatched_cells,
                "max_abs_error": max_abs_error,
                "max_abs_error_at": max_abs_error_at,
                "max_rel_error": max_rel_error,
                "max_rel_error_at": max_rel_error_at,
                "mean_abs_error": sum_abs_error / mismatched_cells if mismatched_cells > 0 else 0.0,
                "rms_abs_error": math.sqrt(sum_sq_abs_error / mismatched_cells) if mismatched_cells > 0 else 0.0,
            }

        if not differences:
            return True, [], False
        return False, differences, truncated

    def _parse_filter(self):
        """Parse data filter string and return a scalar filter function"""
        if not self.data_filter:
            return None
        self.logger.debug(f"Parsing data filter: {self.data_filter}")
        try:
            match = re.match(
                r"^(abs)?([><]=?|==)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$",
                self.data_filter.replace(" ", ""),
            )
            if not match:
                self.logger.warning(
                    f"Invalid data filter format: {self.data_filter}. Ignoring filter."
                )
                return None
            use_abs, op, value_str = match.groups()
            value = float(value_str)
            op_map = {
                ">": lambda x: x > value,
                ">=": lambda x: x >= value,
                "<": lambda x: x < value,
                "<=": lambda x: x <= value,
                "==": lambda x: x == value,
            }

            def filter_func(x):
                target = abs(x) if use_abs else x
                return op_map[op](target)

            self.logger.debug(
                f"Created filter function for pattern: {use_abs or ''}{op}{value}"
            )
            return filter_func
        except Exception as e:
            self.logger.error(
                f"Failed to parse data filter '{self.data_filter}': {e}. Ignoring filter."
            )
            return None