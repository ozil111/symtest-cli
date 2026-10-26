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
from pathlib import Path
from .text_comparator import TextComparator
from .result import Difference, ComparisonResult
from .numeric_compare import compare_numeric, parse_data_filter


def _parse_cell_number(cell):
    """
    @brief Parse a CSV cell into int (exact) or float, or None if non-numeric.
    @details Integer text keeps Python int so the shared numeric core can use
             exact integer comparisons (avoids float64 rounding loss for large
             integers, e.g. 2**53 vs 2**53+1); float text falls back to float.
    """
    if not isinstance(cell, str):
        return None
    try:
        return int(cell)
    except ValueError:
        pass
    try:
        return float(cell)
    except ValueError:
        return None


class _NumericStatsAccumulator:
    """
    @brief Streaming accumulator for per-row numeric error statistics.
    @details Shared by the in-memory and streaming CSV comparison paths so
             error-analysis statistics have a single implementation.
    """

    def __init__(self):
        self.total = 0
        self.mismatched = 0
        self.sum_abs = self.sum_sq = 0.0
        self.max_abs_error = None
        self.max_abs_error_at = None
        self.max_rel_error = None
        self.max_rel_error_at = None

    def add(self, row_res, row_pos):
        """Fold one compare_numeric() row result into the running totals."""
        self.total += row_res.total
        self.mismatched += row_res.mismatched
        self.sum_abs += row_res.sum_abs_error
        self.sum_sq += row_res.sum_sq_abs_error
        if row_res.max_abs_error is not None and (
                self.max_abs_error is None or row_res.max_abs_error > self.max_abs_error):
            self.max_abs_error = row_res.max_abs_error
            ri, cj = row_pos[row_res.max_abs_error_index]
            self.max_abs_error_at = f"row {ri+1}, column {cj+1}"
        if row_res.max_rel_error is not None and (
                self.max_rel_error is None or row_res.max_rel_error > self.max_rel_error):
            self.max_rel_error = row_res.max_rel_error
            ri, cj = row_pos[row_res.max_rel_error_index]
            self.max_rel_error_at = f"row {ri+1}, column {cj+1}"

    def to_stats(self):
        """Return the _error_stats dict, or None when no numeric cell was seen."""
        if not self.total:
            return None
        return {
            "total_numeric_cells": self.total,
            "mismatched_cells": self.mismatched,
            "max_abs_error": self.max_abs_error,
            "max_abs_error_at": self.max_abs_error_at,
            "max_rel_error": self.max_rel_error,
            "max_rel_error_at": self.max_rel_error_at,
            "mean_abs_error": self.sum_abs / self.total,
            "rms_abs_error": float(np.sqrt(self.sum_sq / self.total)),
        }


class CsvComparator(TextComparator):
    """
    @brief Comparator for CSV files with row and column comparison
    @details This class extends TextComparator to provide specialized CSV comparison
             capabilities, including:
             - Row count comparison
             - Column count comparison
             - Cell value comparison
             - Configurable delimiter and quote character
             - Streaming two-file comparison (compare_files) with O(1) row memory
    """

    def __init__(self, encoding="utf-8", delimiter=",", quotechar='"', chunk_size=8192, rtol=1e-5, atol=1e-8, data_filter=None, error_analysis=False):
        """
        @brief Initialize CSV comparator with configuration
        @param encoding str: File encoding (default: utf-8)
        @param delimiter str: CSV field delimiter (default: comma)
        @param quotechar str: Character used for quoting fields (default: double quote)
        @param chunk_size int: Size of chunks for reading large files
        @param rtol float: Relative tolerance for numerical comparison (default: 1e-5)
        @param atol float: Absolute tolerance for numerical comparison (default: 1e-8)
        @param data_filter str: Data filter expression applied before numeric comparison
        @param error_analysis bool: Enable streaming error statistics over ALL numeric cells
        @note Parameters are strict: unknown/misspelled config keys fail loudly.
        """
        super().__init__(encoding=encoding, chunk_size=chunk_size)
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
        # Line ranges apply at the text layer (one CSV record per text line).
        # Column ranges are CSV FIELD indices, applied after parsing below —
        # passing them to the text layer would slice characters and destroy
        # the CSV field structure before parsing.
        text_content = super().read_content(file_path, start_line, end_line, 0, None)

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

    def compare_files(self, file1, file2, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Streaming two-file CSV comparison with O(1) row memory
        @param file1 Path: Path to the first file (baseline slot)
        @param file2 Path: Path to the second file (actual slot)
        @param start_line int: Starting record index (0-based, inclusive)
        @param end_line int: Ending record index (0-based, inclusive) or None
        @param start_column int: Starting CSV field index (0-based, inclusive)
        @param end_column int: Ending CSV field index (0-based, inclusive) or None
        @return ComparisonResult: Result object containing comparison details
        @details Overrides the FileComparator template so both files are read
                 and compared record by record; memory stays proportional to
                 one row pair instead of the full files. Verdict semantics
                 (windows, tolerances, filters, error statistics, difference
                 capping, position offsetting) match the in-memory path via
                 the shared per-row helper.
        """
        result = ComparisonResult(
            file1=str(file1) if file1 else "",
            file2=str(file2) if file2 else "",
            start_line=start_line,
            end_line=end_line,
            start_column=start_column,
            end_column=end_column
        )

        try:
            self.logger.info(f"Comparing files: {file1} and {file2}")

            # Range validation mirrors the text layer's error messages.
            if start_line < 0:
                raise ValueError("Start line cannot be negative")
            if end_line is not None and end_line < start_line:
                raise ValueError("End line cannot be before start line")
            if start_column < 0:
                raise ValueError("Start column cannot be negative")
            if end_column is not None and end_column < start_column:
                raise ValueError("End column cannot be before start column")

            # Record file metadata
            file1_path = Path(file1)
            file2_path = Path(file2)
            result.file1_size = file1_path.stat().st_size
            result.file2_size = file2_path.stat().st_size

            self.logger.debug("Using streaming row-by-row comparison")

            differences = []
            max_diffs = 10
            acc = _NumericStatsAccumulator() if self.error_analysis else None
            early_stop = False

            counts1 = [0]
            counts2 = [0]
            records1 = self._iter_records(file1_path, start_line, end_line, counts1)
            records2 = self._iter_records(file2_path, start_line, end_line, counts2)

            row_index = 0
            for rec1, rec2 in zip(records1, records2):
                rec1 = self._apply_column_window(rec1, start_column, end_column)
                rec2 = self._apply_column_window(rec2, start_column, end_column)
                # Fast path only when stats are not requested; with
                # error_analysis every numeric cell must still be traversed.
                if acc is None and rec1 == rec2:
                    row_index += 1
                    continue
                if self._compare_row_pair(rec1, rec2, row_index, differences, max_diffs, acc):
                    early_stop = True
                    break
                row_index += 1

            # Drain both sides so counts[0] holds the total record counts.
            # Cheap: records are counted, never stored or numerically compared.
            for _ in records1:
                pass
            for _ in records2:
                pass

            # Row-window validation mirrors the text layer's error message.
            if counts1[0] < start_line:
                raise ValueError(f"Start line {start_line} is beyond file length {counts1[0]}")
            if counts2[0] < start_line:
                raise ValueError(f"Start line {start_line} is beyond file length {counts2[0]}")

            # Row count mismatch: prepend like the in-memory path (it is the
            # first difference there) and keep the report capped at max_diffs.
            if counts1[0] != counts2[0]:
                differences.insert(0, Difference(
                    position="row count",
                    expected=f"{counts1[0]} rows",
                    actual=f"{counts2[0]} rows",
                    diff_type="row_count_mismatch"
                ))
                del differences[max_diffs:]

            truncated = len(differences) >= max_diffs

            # Offset window-relative positions back to original file coordinates.
            self._offset_difference_positions(differences, start_line, start_column)

            # Update result
            self._error_stats = acc.to_stats() if acc is not None else None
            result.identical = not differences
            result.differences = differences
            result.truncated = truncated
            result.error_stats = self._error_stats

            return result

        except Exception as e:
            self.logger.error(f"Error during comparison: {str(e)}")
            result.error = str(e)
            result.identical = False
            return result

    def _iter_records(self, file_path, start_line, end_line, counts):
        """
        @brief Stream CSV records inside the row window.
        @param file_path Path: File to read
        @param start_line int: First record index (0-based, inclusive)
        @param end_line int: Last record index (0-based, inclusive) or None
        @param counts list: One-element accumulator for the total record count
        @details Yields at most (end_line - start_line + 1) records. Records
                 outside the window are consumed and counted but not yielded,
                 so exhausting this generator always leaves the file's total
                 record count in counts[0]. Error mapping matches the text
                 layer (encoding / missing file / IO errors).
        """
        try:
            with open(file_path, 'r', encoding=self.encoding) as f:
                reader = csv.reader(f, delimiter=self.delimiter, quotechar=self.quotechar)
                skipped = 0
                yielded = 0
                window_len = None if end_line is None else max(end_line - start_line + 1, 0)
                for record in reader:
                    counts[0] += 1
                    if skipped < start_line:
                        skipped += 1
                        continue
                    if window_len is not None and yielded >= window_len:
                        continue
                    yield record
                    yielded += 1
        except UnicodeDecodeError as e:
            raise ValueError(
                f"File encoding error for {file_path}. Try specifying a different encoding. "
                f"Error: {str(e)}")
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except IOError as e:
            raise ValueError(f"Error reading file {file_path}: {str(e)}")

    @staticmethod
    def _apply_column_window(row, start_column, end_column):
        """Slice a record to the CSV-field column window (same as read_content)."""
        if start_column > 0 or end_column is not None:
            col_start = start_column
            col_end = end_column if end_column is not None else len(row)
            return row[col_start:col_end+1]
        return row

    def _compare_row_pair(self, row1, row2, row_index, differences, max_diffs, acc):
        """
        @brief Compare one row pair; shared by the in-memory and streaming paths.
        @param row1 list: Baseline row (already column-window sliced)
        @param row2 list: Actual row (already column-window sliced)
        @param row_index int: 0-based row index relative to the sliced content
        @param differences list: Difference list to append to
        @param max_diffs int: Maximum number of reported differences
        @param acc _NumericStatsAccumulator or None: Stats accumulator
        @return bool: True when the caller may stop early (diff cap reached
                      and error statistics are not requested)
        @details Single source of the per-row verdict logic: column count
                 check, numeric cell collection, shared numeric core
                 delegation, and mismatch reporting. All appends are guarded
                 by the diff cap, so the reported difference list is
                 independent of which path invokes this helper.
        """
        # Check column count in this row
        if len(row1) != len(row2):
            if len(differences) < max_diffs:
                differences.append(Difference(
                    position=f"row {row_index+1}",
                    expected=f"{len(row1)} columns",
                    actual=f"{len(row2)} columns",
                    diff_type="column_count_mismatch"
                ))

        # Collect numeric cells in this row (for delegated closeness check)
        row_exp = []
        row_act = []
        row_pos = []  # (row, col) 0-based
        for j, (cell1, cell2) in enumerate(zip(row1, row2)):
            num1 = _parse_cell_number(cell1)
            num2 = _parse_cell_number(cell2)

            is_numeric = num1 is not None and num2 is not None
            if is_numeric:
                # Counted as a numeric cell (regardless of text equality)
                row_exp.append(num1)
                row_act.append(num2)
                row_pos.append((row_index, j))

            if cell1 == cell2:
                continue
            if is_numeric:
                # Numeric cell: within-tolerance decisions are made below via the core.
                # Filtered-out numeric cells are skipped entirely (no difference).
                continue

            # Non-numeric text mismatch
            if len(differences) < max_diffs:
                differences.append(Difference(
                    position=f"row {row_index+1}, column {j+1}",
                    expected=cell1,
                    actual=cell2,
                    diff_type="cell_mismatch"
                ))

        # Determine closeness for this row's numeric cells via the shared core.
        if row_exp:
            row_res = compare_numeric(
                row_exp, row_act, rtol=self.rtol, atol=self.atol,
                filter_func=self.filter_func, collect_stats=acc is not None,
            )
            if acc is not None:
                acc.add(row_res, row_pos)
            for k, is_mismatch in enumerate(row_res.mismatch_mask):
                if is_mismatch and len(differences) < max_diffs:
                    ri, cj = row_pos[k]
                    differences.append(Difference(
                        position=f"row {ri+1}, column {cj+1}",
                        expected=row1[cj],
                        actual=row2[cj],
                        diff_type="cell_mismatch"
                    ))

        return acc is None and len(differences) >= max_diffs

    def compare_content(self, content1, content2):
        """
        @brief Compare CSV content structurally (in-memory path)
        @param content1 list: First CSV data to compare (list of rows)
        @param content2 list: Second CSV data to compare (list of rows)
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        @details Performs structural comparison of CSV data, including:
                 - Row count comparison
                 - Column count comparison per row
                 - Cell value comparison
                 - Limits the number of reported differences
                 - When error_analysis=True, accumulates streaming stats over ALL numeric cells
                 Kept for direct callers of the read/compare API; compare_files
                 uses the streaming path. Verdict logic is shared via
                 _compare_row_pair so the two paths cannot drift apart.
        """
        self._error_stats = None  # Reset per comparison

        # Fast path only when stats are not requested; with error_analysis we
        # must still traverse all numeric cells to build the statistics.
        if content1 == content2 and not self.error_analysis:
            return True, [], False

        differences = []
        max_diffs = 10
        acc = _NumericStatsAccumulator() if self.error_analysis else None

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
            if self._compare_row_pair(row1, row2, i, differences, max_diffs, acc):
                break

        truncated = len(differences) >= max_diffs

        # ── Store accumulated statistics without a second comparison ──
        if acc is not None:
            self._error_stats = acc.to_stats()

        if not differences:
            return True, [], False
        return False, differences, truncated

    def _parse_filter(self):
        """Parse data filter string and return a filter function (delegates to numeric core)"""
        return parse_data_filter(self.data_filter, logger=self.logger)
