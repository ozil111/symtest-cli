#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file result.py
@brief Classes for representing file comparison results and differences
@author Xiaotong Wang
@date 2025
"""

import json


class Difference:
    """
    @brief Represents a single difference between files
    @details This class encapsulates information about a single difference found
             during file comparison, including position, expected and actual content,
             and the type of difference.
    """
    
    def __init__(self, position=None, expected=None, actual=None, diff_type="content"):
        """
        @brief Initialize a Difference object
        @param position: Position of the difference (can be line number, byte position, etc.)
        @param expected: Expected content at the position
        @param actual: Actual content found at the position
        @param diff_type: Type of difference ("content", "missing", "extra", etc.)
        """
        self.position = position  # Can be line number, byte position, etc.
        self.expected = expected  # Expected content
        self.actual = actual      # Actual content
        self.diff_type = diff_type  # Type of difference: "content", "missing", "extra", etc.
    
    def __str__(self):
        """
        @brief Convert the difference to a string representation
        @return str: Human-readable description of the difference
        @details Shows expected/actual values whenever they exist,
                 regardless of diff_type.
        """
        if self.expected is not None and self.actual is not None:
            return f"At {self.position}: expected '{self.expected}', got '{self.actual}'"
        elif self.expected is not None:
            return f"At {self.position}: expected '{self.expected}'"
        elif self.actual is not None:
            return f"At {self.position}: got '{self.actual}'"
        else:
            return f"At {self.position}"
    
    def to_dict(self):
        """
        @brief Convert the difference to a dictionary representation
        @return dict: Dictionary containing the difference details
        """
        return {
            "position": self.position,
            "expected": self.expected,
            "actual": self.actual,
            "diff_type": self.diff_type
        }

class ComparisonResult:
    """
    @brief Represents the result of a file comparison
    @details This class encapsulates all information about a file comparison,
             including file paths, comparison range, differences found,
             and additional metadata like file sizes and similarity index.
    """
    
    def __init__(self, file1=None, file2=None, start_line=0, end_line=None, 
                 start_column=0, end_column=None):
        """
        @brief Initialize a ComparisonResult object
        @param file1: Path to the first file
        @param file2: Path to the second file
        @param start_line: Starting line number for comparison (0-based)
        @param end_line: Ending line number for comparison (0-based, None for end of file)
        @param start_column: Starting column number for comparison (0-based)
        @param end_column: Ending column number for comparison (0-based, None for end of line)
        """
        self.file1 = file1
        self.file2 = file2
        self.file1_size = None
        self.file2_size = None
        self.start_line = start_line
        self.end_line = end_line
        self.start_column = start_column
        self.end_column = end_column
        self.identical = None
        self.differences = []
        self.error = None
        self.similarity = None  # Similarity index for binary comparisons
        self.truncated = False  # Whether differences were truncated due to max_diffs limit
        self.error_stats = None  # Optional error statistics from streaming numerical analysis
        self.command_output = None  # Optional subprocess stdout captured by script/custom comparators
    
    def __str__(self):
        """
        @brief Convert the comparison result to a string representation
        @return str: Human-readable description of the comparison result
        """
        if self.error:
            return f"Error during comparison: {self.error}"
        lines = []
        if self.identical:
            range_str = self._get_range_str()
            lines.append(f"Files are identical{range_str}.")
        else:
            lines.append(f"Files are different. Found {len(self.differences)} differences:")
            for i, diff in enumerate(self.differences, 1):
                lines.append(f"{i}. {diff}")
            if self.truncated:
                lines.append("... more differences not shown")
            if self.similarity is not None:
                lines.append(f"Similarity Index: {self.similarity:.2f}")
        return "\n".join(lines)
    
    def _get_range_str(self):
        """
        @brief Get a string representation of the comparison range
        @return str: Description of the line and column ranges being compared
        """
        parts = []
        if self.start_line > 0 or self.end_line is not None:
            line_range = f"lines {self.start_line+1}"
            if self.end_line is not None:
                line_range += f"-{self.end_line+1}"
            parts.append(line_range)
            
        if self.start_column > 0 or self.end_column is not None:
            col_range = f"columns {self.start_column+1}"
            if self.end_column is not None:
                col_range += f"-{self.end_column+1}"
            parts.append(col_range)
            
        if parts:
            return " in " + ", ".join(parts)
        return ""
    
    def to_dict(self):
        """
        @brief Convert the comparison result to a dictionary representation
        @return dict: Dictionary containing all comparison details
        """
        return {
            "file1": self.file1,
            "file2": self.file2,
            "file1_size": self.file1_size,
            "file2_size": self.file2_size,
            "range": {
                "start_line": self.start_line,
                "end_line": self.end_line,
                "start_column": self.start_column,
                "end_column": self.end_column
            },
            "identical": self.identical,
            "differences": [diff.to_dict() for diff in self.differences],
            "similarity": self.similarity,
            "error": self.error,
            "truncated": self.truncated,
            "error_stats": self.error_stats,
            "command_output": self.command_output,
        }
    
    def to_html(self):
        """
        @brief Convert the comparison result to HTML format
        @details Generates a complete HTML document with styling for displaying
                 the comparison results in a web browser
        @return str: HTML representation of the comparison result
        """
        if self.error:
            return f"<div class='error'>Error during comparison: {self.error}</div>"
            
        html = ["<html><head><style>",
                "body { font-family: Arial, sans-serif; }",
                ".identical { color: green; }",
                ".different { color: red; }",
                ".diff-item { margin: 10px 0; padding: 5px; border: 1px solid #ccc; }",
                "</style></head><body>"]
        
        if self.identical:
            range_str = self._get_range_str()
            html.append(f"<h2 class='identical'>Files are identical{range_str}.</h2>")
        else:
            html.append(f"<h2 class='different'>Files are different. Found {len(self.differences)} differences:</h2>")
            if self.similarity is not None:
                html.append(f"<p>Similarity Index: {self.similarity:.2f}</p>")
            html.append("<div class='diff-list'>")
            
            for i, diff in enumerate(self.differences, 1):
                html.append(f"<div class='diff-item'>")
                html.append(f"<h3>Difference {i}</h3>")
                html.append(f"<p>Position: {diff.position}</p>")
                html.append(f"<p>Expected: <pre>{diff.expected}</pre></p>")
                html.append(f"<p>Actual: <pre>{diff.actual}</pre></p>")
                html.append(f"<p>Type: {diff.diff_type}</p>")
                html.append("</div>")
                
            if self.truncated:
                html.append("<p class='truncated'>... more differences not shown</p>")
            html.append("</div>")
            
        html.append("</body></html>")
        return "\n".join(html)

    def to_json(self):
        """
        @brief Convert the comparison result to JSON format
        @return str: JSON representation of the comparison result
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)
