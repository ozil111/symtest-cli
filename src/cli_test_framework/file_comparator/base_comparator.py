#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file base_comparator.py
@brief Base abstract class for file comparison operations
@author Xiaotong Wang
@date 2025
"""

from abc import ABC, abstractmethod
import logging
from pathlib import Path
from .result import ComparisonResult, Difference

class BaseComparator(ABC):
    """
    @brief Base abstract class for all file comparators
    @details This class defines the interface and common functionality for all file comparators.
             It provides basic file comparison operations and logging capabilities.
    """
    
    def __init__(self, encoding="utf-8", chunk_size=8192, verbose=False, **kwargs):
        """
        @brief Initialize the base comparator
        @param encoding str: File encoding to use (default: "utf-8")
        @param chunk_size int: Size of chunks for reading large files (default: 8192)
        @param verbose bool: Enable verbose logging (default: False)
        """
        self.encoding = encoding
        self.chunk_size = chunk_size
        self.logger = logging.getLogger(f"file_comparator.{self.__class__.__name__}")
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
        pass

    @abstractmethod
    def compare_content(self, content1, content2):
        """
        @brief Compare two content objects and return comparison details
        @param content1 object: First content object to compare
        @param content2 object: Second content object to compare
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        """
        pass

    def compare_files(self, file1, file2, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Compare two files with the specified parameters
        @param file1 Path: Path to the first file
        @param file2 Path: Path to the second file
        @param start_line int: Starting line number (0-based)
        @param end_line int: Ending line number (0-based, None for end of file)
        @param start_column int: Starting column number (0-based)
        @param end_column int: Ending column number (0-based, None for end of line)
        @return ComparisonResult: Result object containing comparison details
        """
        result = ComparisonResult(
            file1=str(file1),
            file2=str(file2),
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