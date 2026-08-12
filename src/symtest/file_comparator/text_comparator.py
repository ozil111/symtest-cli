#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file text_comparator.py
@brief Text file comparator implementation with line-by-line comparison
@author Xiaotong Wang
@date 2025
"""

import difflib
import re
from .base_comparator import BaseComparator
from .result import Difference

class TextComparator(BaseComparator):
    """
    @brief Comparator for text files with line-by-line comparison
    @details This class implements text file comparison using Python's difflib
             for detailed difference detection. It supports line and column-based
             range selection for comparison.
    """
    
    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Read text content with specified range
        @param file_path Path: Path to the text file to read
        @param start_line int: Starting line number (0-based)
        @param end_line int: Ending line number (0-based, None for end of file)
        @param start_column int: Starting column number (0-based)
        @param end_column int: Ending column number (0-based, None for end of line)
        @return list: List of text lines within the specified range
        @throws ValueError: If line or column ranges are invalid
        @throws UnicodeDecodeError: If file encoding is incorrect
        @throws FileNotFoundError: If file doesn't exist
        @throws IOError: If there are other file reading errors
        """
        try:
            self.logger.debug(f"Reading text file: {file_path}")
            with open(file_path, 'r', encoding=self.encoding) as f:
                lines = f.readlines()
                
            if start_line < 0:
                raise ValueError("Start line cannot be negative")
                
            if end_line is not None:
                if end_line < start_line:
                    raise ValueError("End line cannot be before start line")
                if end_line >= len(lines):
                    self.logger.warning(f"End line {end_line} exceeds file length {len(lines)}, capping at {len(lines)-1}")
                    end_line = len(lines) - 1
            else:
                end_line = len(lines) - 1
                
            if start_line >= len(lines):
                raise ValueError(f"Start line {start_line} is beyond file length {len(lines)}")
                
            selected_lines = lines[start_line:end_line+1]
            
            if start_column < 0:
                raise ValueError("Start column cannot be negative")
                
            if start_column > 0 or end_column is not None:
                self.logger.debug(f"Applying column range: {start_column} to {end_column}")
                processed_lines = []
                for line in selected_lines:
                    if end_column is not None and end_column < start_column:
                        raise ValueError("End column cannot be before start column")
                    # Make sure we don't exceed line length
                    effective_end = end_column
                    if effective_end is not None and effective_end >= len(line):
                        effective_end = len(line) - 1
                    # Apply column range, handle if start_column is beyond line length
                    if start_column >= len(line):
                        processed_lines.append("")
                    else:
                        processed_lines.append(line[start_column:None if effective_end is None else effective_end+1])
                return processed_lines
            
            return selected_lines
            
        except UnicodeDecodeError as e:
            raise ValueError(f"File encoding error for {file_path}. Try specifying a different encoding. Error: {str(e)}")
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except IOError as e:
            raise ValueError(f"Error reading file {file_path}: {str(e)}")
    
    def compare_content(self, content1, content2):
        """
        @brief Compare text content and return detailed differences
        @param content1 list: First list of text lines to compare
        @param content2 list: Second list of text lines to compare
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        @details Uses difflib to generate a detailed comparison of the text content.
                 Returns a tuple containing a boolean indicating if the content is identical
                 and a list of Difference objects describing any differences found.
                 Limits the number of differences reported to 10 to avoid overwhelming output.
        """
        self.logger.debug(f"Comparing text content")
        
        if content1 == content2:
            return True, [], False
            
        differences = []
        
        # Use difflib for more detailed comparison
        diff = list(difflib.unified_diff(content1, content2, n=0))
        
        # Process the diff output to create structured differences
        line_diffs = []
        for line in diff[2:]:  # Skip the first two header lines
            if line.startswith('@@'):
                # Parse hunk header for real line numbers: @@ -start1,c1 +start2,c2 @@
                match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if match:
                    line_diffs.append(('hunk', (int(match.group(1)), int(match.group(3)))))
                continue
            elif line.startswith('-'):
                line_diffs.append(('remove', line[1:]))
            elif line.startswith('+'):
                line_diffs.append(('add', line[1:]))
            else:
                line_diffs.append(('context', line[1:]))
        
        # Convert diff to our difference format
        # In unified_diff(content1, content2):
        #   '-' lines come from content1 (= actual file)
        #   '+' lines come from content2 (= baseline file)
        # So: expected = '+' lines (baseline), actual = '-' lines (actual file)
        line_num1 = 0
        line_num2 = 0
        i = 0
        while i < len(line_diffs):
            action, line = line_diffs[i]
            if action == 'hunk':
                # Reset to real line numbers from the hunk header (convert 1-based to 0-based)
                line_num1 = line[0] - 1
                line_num2 = line[1] - 1
                i += 1
                continue
            elif action == 'remove':
                # Collect consecutive remove block (actual file lines)
                removes = []
                while i < len(line_diffs) and line_diffs[i][0] == 'remove':
                    removes.append(line_diffs[i][1])
                    i += 1
                # Collect following add block (baseline file lines)
                adds = []
                while i < len(line_diffs) and line_diffs[i][0] == 'add':
                    adds.append(line_diffs[i][1])
                    i += 1
                # Pair by position
                max_len = max(len(removes), len(adds))
                for k in range(max_len):
                    act_val = removes[k] if k < len(removes) else None
                    exp_val = adds[k] if k < len(adds) else None
                    if act_val is not None and exp_val is not None:
                        # Content difference: both sides have a line, values differ
                        differences.append(Difference(
                            position=f"line {line_num1+k+1}",
                            expected=exp_val,
                            actual=act_val,
                            diff_type="content"
                        ))
                    elif exp_val is not None:
                        # Missing: baseline has a line, actual doesn't
                        differences.append(Difference(
                            position=f"line {line_num2+k+1}",
                            expected=exp_val,
                            actual=None,
                            diff_type="missing"
                        ))
                    else:
                        # Extra: actual has a line, baseline doesn't
                        differences.append(Difference(
                            position=f"line {line_num1+k+1}",
                            expected=None,
                            actual=act_val,
                            diff_type="extra"
                        ))
                line_num1 += len(removes)
                line_num2 += len(adds)
                continue
            elif action == 'add':
                # Standalone add (baseline has line, actual doesn't)
                differences.append(Difference(
                    position=f"line {line_num2+1}",
                    expected=line,
                    actual=None,
                    diff_type="missing"
                ))
                line_num2 += 1
                i += 1
            elif action == 'context':
                line_num1 += 1
                line_num2 += 1
                i += 1
        
        # Limit the number of differences reported
        max_diffs = 10
        truncated = len(differences) > max_diffs
        if truncated:
            differences = differences[:max_diffs]
            
        return False, differences, truncated