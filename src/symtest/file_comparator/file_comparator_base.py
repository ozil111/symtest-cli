#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file file_comparator_base.py
@brief File-lane comparator: two-file model (read + compare template method)
@author Xiaotong Wang
@date 2025

This class hosts the legacy two-file template that used to live on the root
``BaseComparator``.  Only file-lane comparators (text/json/csv/xml/h5/binary)
implement ``read_content``/``compare_content``; autonomous-lane and data-lane
plugins are no longer forced to provide empty stubs for them.
"""

from abc import abstractmethod
import logging
from pathlib import Path

from .base_comparator import ComparatorBase, CompareContext
from .result import ComparisonResult


class FileComparator(ComparatorBase):
    """
    @brief Abstract base for two-file comparison (file lane).
    @details Template method :meth:`compare_files` orchestrates
             read -> compare -> result assembly, including the line-window
             position offsetting for text-style comparators.  Subclasses
             implement :meth:`read_content` and :meth:`compare_content`.
    """

    def __init__(self, encoding: str = "utf-8", chunk_size: int = 8192,
                 verbose: bool = False):
        """
        @brief Initialize file-lane state.
        @param encoding str: Text decoding for file reads (default "utf-8").
        @param chunk_size int: Chunk size for large-file reads (default 8192).
        @param verbose bool: Raises THIS comparator's own logger to DEBUG.
               File-lane justified (byte/hex/text diff tracing); it touches
               only the comparator's named logger, never global logging
               policy.  The factory also accepts ``verbose`` for any lane.
        """
        super().__init__()
        self.encoding = encoding
        self.chunk_size = chunk_size
        if verbose:
            self.logger.setLevel(logging.DEBUG)

    @abstractmethod
    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Read file content with specified range
        @param file_path Path: Path to the file to read
        @param start_line int: Starting line number (0-based)
        @param end_line int: Ending line number (0-based, None for end of file)
        @param start_column int: Starting column number (0-based)
        @param end_column int: Ending column number (0-based, None for end of line)
        @return object: File content in a format suitable for comparison
        """

    @abstractmethod
    def compare_content(self, content1, content2):
        """
        @brief Compare two content objects and return comparison details
        @param content1 object: First content object to compare
        @param content2 object: Second content object to compare
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        """

    def compare(self, ctx: CompareContext) -> ComparisonResult:  # type: ignore[override]
        """
        @brief Compare ``ctx.baseline`` vs ``ctx.actual`` via the file template.
        @details Method-level window parameters (``start_line``/``end_line``/
                 ``start_column``/``end_column``, already converted to 0-based
                 by the assertion layer) are consumed from ``ctx.params``;
                 everything else was forwarded to the constructor.
        """
        params = dict(ctx.params or {})
        method_params = {}
        for key in ("start_line", "end_line", "start_column", "end_column"):
            if key in params:
                method_params[key] = params.pop(key)
        return self.compare_files(ctx.baseline, ctx.actual, **method_params)

    def compare_files(self, file1, file2, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Compare two files with the specified parameters
        @param file1 Path: Path to the first file (baseline slot)
        @param file2 Path: Path to the second file (actual slot)
        @param start_line int: Starting line number (0-based)
        @param end_line int: Ending line number (0-based, None for end of file)
        @param start_column int: Starting column number (0-based)
        @param end_column int: Ending column number (0-based, None for end of line)
        @return ComparisonResult: Result object containing comparison details
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

            # Record file metadata
            file1_path = Path(file1)
            file2_path = Path(file2)
            result.file1_size = file1_path.stat().st_size
            result.file2_size = file2_path.stat().st_size

            # Read content with specified ranges
            self.logger.debug(f"Reading content from files")
            content1 = self.read_content(file1, start_line, end_line, start_column, end_column)
            content2 = self.read_content(file2, start_line, end_line, start_column, end_column)

            # Compare content
            self.logger.debug(f"Comparing content")
            identical, differences, truncated = self.compare_content(content1, content2)

            # Adjust line numbers in differences to reflect original file line numbers
            # compare_content reports positions relative to the sliced content (1-based),
            # but we need to offset by start_line to reflect positions in the original file
            if start_line > 0:
                import re
                for diff in differences:
                    if diff.position and isinstance(diff.position, str):
                        # Position format is "line N"
                        match = re.match(r'^line (\d+)$', diff.position)
                        if match:
                            original_line = int(match.group(1)) + start_line
                            diff.position = f"line {original_line}"

            # Update result
            result.identical = identical
            result.differences = differences
            result.truncated = truncated
            result.error_stats = getattr(self, "_error_stats", None)

            return result

        except Exception as e:
            self.logger.error(f"Error during comparison: {str(e)}")
            result.error = str(e)
            result.identical = False
            return result
