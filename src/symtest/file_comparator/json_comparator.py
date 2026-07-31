#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file json_comparator.py
@brief JSON file comparator implementation with support for exact and key-based comparison
@author Xiaotong Wang
@date 2025
"""

import json
from .text_comparator import TextComparator
from .result import Difference

class JsonComparator(TextComparator):
    """
    @brief Comparator for JSON files with support for exact and key-based comparison
    @details This class extends TextComparator to provide specialized JSON comparison
             capabilities, including:
             - Exact comparison of JSON structures
             - Key-based comparison for lists of objects
             - Detailed difference reporting with path information
    """
    
    def __init__(self, encoding="utf-8", chunk_size=8192, verbose=False, key_field=None, compare_mode="exact", **kwargs):
        """
        @brief Initialize the JSON comparator
        @param encoding str: File encoding
        @param chunk_size int: Chunk size for reading files
        @param verbose bool: Enable verbose logging
        @param key_field str or list: Field name(s) to use as key for comparing JSON objects in lists
        @param compare_mode str: Comparison mode: 'exact' (default) or 'key-based'
        @param **kwargs: Additional parameters (ignored)
        """
        super().__init__(encoding=encoding, chunk_size=chunk_size, verbose=verbose, **kwargs)
        self.key_field = key_field
        self.compare_mode = compare_mode

    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """
        @brief Read and parse JSON content from file
        @param file_path Path: Path to the JSON file
        @param start_line int: Starting line number
        @param end_line int: Ending line number
        @param start_column int: Starting column number
        @param end_column int: Ending column number
        @return dict or list: Parsed JSON content
        @throws ValueError: If JSON is invalid or key fields are missing
        """
        # Read the text content using the parent class method
        text_content = super().read_content(file_path, start_line, end_line, start_column, end_column)
        
        # Convert to a single string
        json_text = ''.join(text_content)
        try:
            json_data = json.loads(json_text)
            return json_data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_path}: {str(e)}")

    def compare_content(self, content1, content2):
        """
        @brief Compare JSON content using the specified comparison mode
        @param content1 dict or list: First JSON content to compare
        @param content2 dict or list: Second JSON content to compare
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        """
        # Quick check for exact equality
        if content1 == content2:
            return True, [], False
        
        # Different comparison modes
        differences = []
        if self.compare_mode == "key-based" and self.key_field:
            self._compare_json_key_based(content1, content2, "", differences)
        else:
            self._compare_json_exact(content1, content2, "", differences)
        
        identical = len(differences) == 0
        return identical, differences, False

    def _compare_json_exact(self, obj1, obj2, path, differences, max_diffs=10):
        """
        @brief Perform exact JSON comparison
        @param obj1: First JSON object to compare
        @param obj2: Second JSON object to compare
        @param path str: Current path in the JSON structure
        @param differences list: List to store found differences
        @param max_diffs int: Maximum number of differences to report
        @details Compares JSON objects recursively, checking for:
                 - Type mismatches
                 - Missing or extra keys in dictionaries
                 - Length mismatches in lists
                 - Value mismatches
        """
        if len(differences) >= max_diffs:
            return

        # Type check
        if type(obj1) != type(obj2):
            differences.append(Difference(
                position=path or "root",
                expected=f"{type(obj1).__name__}: {obj1}",
                actual=f"{type(obj2).__name__}: {obj2}",
                diff_type="type_mismatch"
            ))
            return

        # Dictionary comparison
        if isinstance(obj1, dict):
            keys1 = set(obj1.keys())
            keys2 = set(obj2.keys())

            # Check for missing keys
            for key in keys1 - keys2:
                differences.append(Difference(
                    position=f"{path}.{key}" if path else key,
                    expected=obj1[key],
                    actual=None,
                    diff_type="missing_key"
                ))
                if len(differences) >= max_diffs:
                    return

            # Check for extra keys
            for key in keys2 - keys1:
                differences.append(Difference(
                    position=f"{path}.{key}" if path else key,
                    expected=None,
                    actual=obj2[key],
                    diff_type="extra_key"
                ))
                if len(differences) >= max_diffs:
                    return

            # Compare common keys recursively
            for key in keys1 & keys2:
                new_path = f"{path}.{key}" if path else key
                self._compare_json_exact(obj1[key], obj2[key], new_path, differences, max_diffs)

        # List comparison
        elif isinstance(obj1, list):
            if len(obj1) != len(obj2):
                differences.append(Difference(
                    position=path or "root",
                    expected=f"list with {len(obj1)} items",
                    actual=f"list with {len(obj2)} items",
                    diff_type="length_mismatch"
                ))

            # Compare items by position
            for i in range(min(len(obj1), len(obj2))):
                new_path = f"{path}[{i}]"
                self._compare_json_exact(obj1[i], obj2[i], new_path, differences, max_diffs)

        # Value comparison
        elif obj1 != obj2:
            differences.append(Difference(
                position=path or "root",
                expected=obj1,
                actual=obj2,
                diff_type="value_mismatch"
            ))

    def _compare_json_key_based(self, obj1, obj2, path, differences, max_diffs=10):
        """
        @brief Perform key-based JSON comparison for lists of objects
        @param obj1: First JSON object to compare
        @param obj2: Second JSON object to compare
        @param path str: Current path in the JSON structure
        @param differences list: List to store found differences
        @param max_diffs int: Maximum number of differences to report
        @details Similar to exact comparison but with special handling for lists
                 of objects, using key fields to match items instead of position
        """
        if len(differences) >= max_diffs:
            return

        # Type check
        if type(obj1) != type(obj2):
            differences.append(Difference(
                position=path or "root",
                expected=f"{type(obj1).__name__}: {obj1}",
                actual=f"{type(obj2).__name__}: {obj2}",
                diff_type="type_mismatch"
            ))
            return

        # Dictionary comparison (same as exact comparison)
        if isinstance(obj1, dict):
            keys1 = set(obj1.keys())
            keys2 = set(obj2.keys())

            # Check for missing keys
            for key in keys1 - keys2:
                differences.append(Difference(
                    position=f"{path}.{key}" if path else key,
                    expected=obj1[key],
                    actual=None,
                    diff_type="missing_key"
                ))
                if len(differences) >= max_diffs:
                    return

            # Check for extra keys
            for key in keys2 - keys1:
                differences.append(Difference(
                    position=f"{path}.{key}" if path else key,
                    expected=None,
                    actual=obj2[key],
                    diff_type="extra_key"
                ))
                if len(differences) >= max_diffs:
                    return

            # Compare common keys recursively
            for key in keys1 & keys2:
                new_path = f"{path}.{key}" if path else key
                self._compare_json_key_based(obj1[key], obj2[key], new_path, differences, max_diffs)

        # List comparison - the key difference for key-based comparison
        elif isinstance(obj1, list) and isinstance(obj2, list):
            # Check if we can do key-based comparison
            if self.key_field and all(isinstance(item, dict) for item in obj1 + obj2):
                self._compare_lists_by_key(obj1, obj2, path, differences, max_diffs)
            else:
                # Fall back to position-based comparison if key-based is not possible
                if len(obj1) != len(obj2):
                    differences.append(Difference(
                        position=path or "root",
                        expected=f"list with {len(obj1)} items",
                        actual=f"list with {len(obj2)} items", 
                        diff_type="length_mismatch"
                    ))

                # Compare items by position
                for i in range(min(len(obj1), len(obj2))):
                    new_path = f"{path}[{i}]"
                    self._compare_json_key_based(obj1[i], obj2[i], new_path, differences, max_diffs)

        # Value comparison
        elif obj1 != obj2:
            differences.append(Difference(
                position=path or "root",
                expected=obj1,
                actual=obj2,
                diff_type="value_mismatch"
            ))

    def _compare_lists_by_key(self, list1, list2, path, differences, max_diffs=10):
        """
        @brief Compare two lists of dictionaries using key field(s) to match items
        @param list1 list: First list of dictionaries
        @param list2 list: Second list of dictionaries
        @param path str: Current path in the JSON structure
        @param differences list: List to store found differences
        @param max_diffs int: Maximum number of differences to report
        @details Matches items in lists using specified key fields instead of position,
                 allowing for reordered lists with the same content
        """
        # Convert key_field to list if it's a string
        key_fields = self.key_field if isinstance(self.key_field, list) else [self.key_field]
        
        # Create dictionaries indexed by the key fields
        dict1 = {}
        dict2 = {}
        
        # Function to create compound key from an item
        def get_key(item):
            if not all(k in item for k in key_fields):
                return None  # Skip items without all key fields
            return tuple(str(item.get(k)) for k in key_fields)
        
        # Build dictionaries from lists
        for i, item in enumerate(list1):
            key = get_key(item)
            if key:
                dict1[key] = (i, item)
        
        for i, item in enumerate(list2):
            key = get_key(item)
            if key:
                dict2[key] = (i, item)
        
        # Find keys in the first list that are missing from the second
        for key in set(dict1.keys()) - set(dict2.keys()):
            idx, item = dict1[key]
            key_str = ".".join(f"{k}={v}" for k, v in zip(key_fields, key))
            differences.append(Difference(
                position=f"{path}[{idx}] (key: {key_str})",
                expected=item,
                actual=None,
                diff_type="missing_item"
            ))
            if len(differences) >= max_diffs:
                return
        
        # Find keys in the second list that are missing from the first
        for key in set(dict2.keys()) - set(dict1.keys()):
            idx, item = dict2[key]
            key_str = ".".join(f"{k}={v}" for k, v in zip(key_fields, key))
            differences.append(Difference(
                position=f"{path}[{idx}] (key: {key_str})",
                expected=None,
                actual=item,
                diff_type="extra_item"
            ))
            if len(differences) >= max_diffs:
                return
        
        # Compare matching items
        for key in set(dict1.keys()) & set(dict2.keys()):
            idx1, item1 = dict1[key]
            idx2, item2 = dict2[key]
            key_str = ".".join(f"{k}={v}" for k, v in zip(key_fields, key))
            new_path = f"{path}[key:{key_str}]"
            
            # Skip identical items
            if item1 == item2:
                continue
                
            # Recursive comparison of matched items
            self._compare_json_key_based(item1, item2, new_path, differences, max_diffs)