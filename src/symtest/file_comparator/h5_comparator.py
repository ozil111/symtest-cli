from .file_comparator_base import FileComparator
import h5py
import numpy as np
import logging
import re
from .numeric_compare import compare_numeric, parse_data_filter

class H5Comparator(FileComparator):
    def __init__(self, tables=None, table_regex=None, structure_only=False, show_content_diff=False, debug=False, rtol=1e-5, atol=1e-8, expand_path=True, data_filter=None, error_analysis=False, encoding="utf-8", verbose=False):
        """
        Initialize H5 comparator
        :param tables: List of table names to compare. If None, compare all tables
        :param table_regex: Regular expression pattern to match table names
        :param structure_only: If True, only compare file structure without comparing content
        :param show_content_diff: If True, show detailed content differences
        :param debug: If True, enable debug mode
        :param rtol: Relative tolerance for numerical comparison
        :param atol: Absolute tolerance for numerical comparison
        :param expand_path: If True, expand group paths to compare all sub-items. Defaults to True.
        :param data_filter: String filter expression for data comparison (e.g., '>1e-6', 'abs>1e-9')
        :param error_analysis: Enable streaming error statistics over ALL numeric cells
        :param encoding: Text encoding for attribute values
        :param verbose: Debug logging of this comparator's own logger
        @note Parameters are strict: unknown/misspelled config keys fail loudly.
        """
        super().__init__(encoding=encoding, verbose=verbose)
        self.tables = tables
        self.table_regex = table_regex
        self.structure_only = structure_only
        self.show_content_diff = show_content_diff
        self.rtol = rtol
        self.atol = atol
        self.expand_path = expand_path
        self.data_filter = data_filter
        self.filter_func = self._parse_filter()
        self.error_analysis = error_analysis
        self._error_stats = None
        
        # Set debug level if debug mode is enabled (verbose is handled by
        # the file-lane base constructor / factory).
        if debug:
            self.logger.setLevel(logging.DEBUG)
            
        self.logger.debug(f"Initialized H5Comparator with structure_only={structure_only}, show_content_diff={show_content_diff}, rtol={rtol}, atol={atol}, expand_path={expand_path}, data_filter={data_filter}")
        if table_regex:
            self.logger.debug(f"Using table regex pattern: {table_regex}")

    def read_content(self, file_path, start_line=0, end_line=None, start_column=0, end_column=None):
        """Read H5 file content"""
        content = {}
        processed_paths = set()
        
        # Store file path for later chunked reading if needed
        content['_file_path'] = str(file_path)
        content['_start_line'] = start_line
        content['_end_line'] = end_line
        content['_start_column'] = start_column
        content['_end_column'] = end_column
        
        # Log whether we're in structure-only mode
        self.logger.debug(f"Reading file {file_path} in structure-only mode: {self.structure_only}")
        self.logger.debug(f"Tables parameter: {self.tables}")
        self.logger.debug(f"Table regex parameter: {self.table_regex}")
        
        with h5py.File(file_path, 'r') as f:
            # Function to collect structure information
            def collect_structure(name, obj):
                if name in processed_paths:
                    self.logger.debug(f"Path {name} already processed, skipping.")
                    return

                if isinstance(obj, h5py.Dataset):
                    content[name] = {
                        'type': 'dataset',
                        'shape': obj.shape,
                        'dtype': str(obj.dtype),
                        'attrs': dict(obj.attrs)
                    }
                    self.logger.debug(f"Collected structure for dataset: {name}")
                    processed_paths.add(name)
                elif isinstance(obj, h5py.Group) and name:  # Skip root group
                    content[name] = {
                        'type': 'group',
                        'keys': list(obj.keys()),
                        'attrs': dict(obj.attrs)
                    }
                    self.logger.debug(f"Collected structure for group: {name}")
                    processed_paths.add(name)
            
            # Function to collect structure and data
            def collect_structure_and_data(name, obj):
                if name in processed_paths:
                    self.logger.debug(f"Path {name} already processed, skipping.")
                    return

                if isinstance(obj, h5py.Dataset):
                    dataset_info = {
                        'type': 'dataset',
                        'shape': obj.shape,
                        'dtype': str(obj.dtype),
                        'attrs': dict(obj.attrs)
                    }
                    
                    # Read data with range constraints and chunk-based reading for large datasets
                    try:
                        # Threshold for chunk-based reading (1 million elements = ~8MB for float64)
                        # For datasets smaller than this, read entire dataset for efficiency
                        if obj.shape == ():
                            # Scalar / 0-d dataset: the line/column window has
                            # no axis to apply; read the scalar as-is.
                            data = obj[()]
                            dataset_info['data'] = data
                            self.logger.debug(f"Collected scalar dataset: {name}")
                        elif obj.size < 1000000:
                            # Small dataset: read entire dataset into memory
                            data = obj[:]
                            if isinstance(data, np.ndarray):
                                # Window semantics (0-based, end inclusive) match
                                # the file-lane base contract: start_line/end_line
                                # select rows, start_column/end_column select
                                # columns (axis 1, 2D+ only).
                                if end_line is None:
                                    end_line_actual = data.shape[0]
                                else:
                                    end_line_actual = min(end_line + 1, data.shape[0])

                                if len(data.shape) == 1:
                                    data = data[start_line:end_line_actual]
                                elif len(data.shape) > 1:
                                    if end_column is None:
                                        end_column_actual = data.shape[1]
                                    else:
                                        end_column_actual = min(end_column + 1, data.shape[1])
                                    data = data[start_line:end_line_actual, start_column:end_column_actual]

                            dataset_info['data'] = data
                            self.logger.debug(f"Collected full data for small dataset: {name} (size: {obj.size})")
                        else:
                            # Large dataset: mark for chunked reading during comparison
                            # Don't load entire dataset into memory
                            dataset_info['data'] = None  # Will be read chunk-by-chunk during comparison
                            dataset_info['dataset_path'] = name  # Store dataset path for later chunked reading
                            dataset_info['needs_chunked_reading'] = True
                            self.logger.debug(f"Marked large dataset for chunked reading: {name} (size: {obj.size})")

                    except Exception as e:
                        self.logger.error(f"Error reading data from {name}: {str(e)}")
                        # Record the failure so comparison can fail loudly
                        # instead of silently skipping this dataset's data.
                        dataset_info['read_error'] = str(e)
                    
                    content[name] = dataset_info
                    processed_paths.add(name)
                    
                elif isinstance(obj, h5py.Group) and name:  # Skip root group
                    content[name] = {
                        'type': 'group',
                        'keys': list(obj.keys()),
                        'attrs': dict(obj.attrs)
                    }
                    self.logger.debug(f"Collected structure for group: {name}")
                    processed_paths.add(name)
            
            if self.tables or self.table_regex:
                # If specific tables or regex pattern is specified
                regex_patterns = []
                if self.table_regex:
                    # Split by comma to support multiple regex patterns
                    regex_strings = [pattern.strip() for pattern in self.table_regex.split(',')]
                    self.logger.debug(f"Parsed regex patterns: {regex_strings}")
                    
                    for regex_str in regex_strings:
                        # If the regex looks like a simple path (no regex metacharacters except . and /),
                        # escape it to treat it as a literal string
                        self.logger.debug(f"Processing regex pattern: {regex_str}")
                        # Check if it contains regex metacharacters other than . and /
                        import string
                        regex_metacharacters = set('[]{}()*+?^$|\\')
                        if not any(char in regex_str for char in regex_metacharacters):
                            # Escape dots and other special characters for literal matching
                            escaped_regex_str = re.escape(regex_str)
                            self.logger.debug(f"Treating pattern as literal path, escaped: {escaped_regex_str}")
                            regex_patterns.append(re.compile(escaped_regex_str))
                        else:
                            self.logger.debug(f"Using pattern as regular expression: {regex_str}")
                            regex_patterns.append(re.compile(regex_str))
                
                def should_process(name):
                    if self.tables and name in self.tables:
                        self.logger.debug(f"Matched by tables list: {name}")
                        return True
                    for pattern in regex_patterns:
                        if pattern.fullmatch(name):
                            self.logger.debug(f"Matched by regex pattern {pattern.pattern}: {name}")
                            return True
                    return False
                
                def process_item(name, item):
                    try:
                        # Process the current item first
                        if self.structure_only:
                            collect_structure(name, item)
                        else:
                            collect_structure_and_data(name, item)

                        # If it's a group and expand_path is enabled, visit all its members
                        if self.expand_path and isinstance(item, h5py.Group):
                            self.logger.debug(f"Expanding group path: {name}")
                            
                            def visitor(sub_name, sub_obj):
                                full_path = f"{name}/{sub_name}"
                                self.logger.debug(f"Processing sub-item from expansion: {full_path}")
                                if self.structure_only:
                                    collect_structure(full_path, sub_obj)
                                else:
                                    collect_structure_and_data(full_path, sub_obj)
                            
                            item.visititems(visitor)

                    except Exception as e:
                        self.logger.error(f"Error processing {name}: {str(e)}")
                
                # First try direct path access for table names
                if self.tables:
                    for table_path in self.tables:
                        try:
                            if table_path in f:
                                process_item(table_path, f[table_path])
                            else:
                                self.logger.warning(f"Table {table_path} not found in {file_path}")
                        except Exception as e:
                            self.logger.error(f"Error processing {table_path}: {str(e)}")
                
                # Then process regex pattern if specified
                if regex_patterns:
                    def visit_with_regex(name, obj):
                        self.logger.debug(f"Checking path: {name}")
                        if should_process(name):
                            self.logger.debug(f"Processing matched path: {name}")
                            process_item(name, obj)
                        else:
                            self.logger.debug(f"Skipping path: {name}")
                    f.visititems(visit_with_regex)
            else:
                # If no tables specified, read all datasets
                if self.structure_only:
                    f.visititems(collect_structure)
                else:
                    f.visititems(collect_structure_and_data)
        
        self.logger.debug(f"Read {len(content)} items from {file_path}")
        self.logger.debug(f"Items read: {list(content.keys())}")
        return content

    def compare_content(self, content1, content2):
        """Compare two H5 file contents
        @return tuple: (bool, list, bool) - (identical, differences, truncated)
        """
        self._error_stats = None  # Reset per comparison
        identical = True
        differences = []

        # ── Error analysis accumulators ──
        _ea_total = 0
        _ea_mismatched = 0
        _ea_sum_abs = 0.0
        _ea_sum_sq = 0.0
        _ea_max_abs = None
        _ea_max_abs_at = None
        _ea_max_rel = None
        _ea_max_rel_at = None

        # Filter out metadata keys (starting with _)
        metadata_keys = {'_file_path', '_start_line', '_end_line', '_start_column', '_end_column'}
        
        # Get all unique table names (excluding metadata)
        all_tables = (set(content1.keys()) | set(content2.keys())) - metadata_keys
        
        # Debug log
        self.logger.debug(f"Structure-only mode: {self.structure_only}")
        self.logger.debug(f"Number of tables to compare: {len(all_tables)}")
        
        for table_name in all_tables:
            # Debug log
            self.logger.debug(f"Comparing table: {table_name}")
            if table_name in content1 and table_name in content2:
                self.logger.debug(f"Table1 keys: {content1[table_name].keys()}")
                self.logger.debug(f"Table2 keys: {content2[table_name].keys()}")
            
            # Check if table exists in both files
            if table_name not in content1:
                differences.append(self._create_difference(
                    position=table_name,
                    expected="Table exists",
                    actual="Table missing",
                    diff_type="structure"
                ))
                identical = False
                continue
                
            if table_name not in content2:
                differences.append(self._create_difference(
                    position=table_name,
                    expected="Table exists",
                    actual="Table missing",
                    diff_type="structure"
                ))
                identical = False
                continue
            
            table1 = content1[table_name]
            table2 = content2[table_name]
            
            # Compare table type
            if table1.get('type') != table2.get('type'):
                differences.append(self._create_difference(
                    position=f"{table_name}/type",
                    expected=table1.get('type'),
                    actual=table2.get('type'),
                    diff_type="structure"
                ))
                identical = False
                continue
            
            # For datasets, compare shape and dtype
            if table1.get('type') == 'dataset':
                if table1['shape'] != table2['shape']:
                    differences.append(self._create_difference(
                        position=f"{table_name}/shape",
                        expected=str(table1['shape']),
                        actual=str(table2['shape']),
                        diff_type="structure"
                    ))
                    identical = False
                
                if table1['dtype'] != table2['dtype']:
                    differences.append(self._create_difference(
                        position=f"{table_name}/dtype",
                        expected=str(table1['dtype']),
                        actual=str(table2['dtype']),
                        diff_type="structure"
                    ))
                    identical = False
            
            # For groups, compare keys
            elif table1.get('type') == 'group':
                keys1 = set(table1['keys'])
                keys2 = set(table2['keys'])
                if keys1 != keys2:
                    missing_keys = keys1 - keys2
                    extra_keys = keys2 - keys1
                    if missing_keys:
                        differences.append(self._create_difference(
                            position=f"{table_name}/keys",
                            expected=str(sorted(missing_keys)),
                            actual="Keys missing",
                            diff_type="structure"
                        ))
                    if extra_keys:
                        differences.append(self._create_difference(
                            position=f"{table_name}/keys",
                            expected="No extra keys",
                            actual=str(sorted(extra_keys)),
                            diff_type="structure"
                        ))
                    identical = False
            
            # Only compare attributes and data if not in structure-only mode
            if not self.structure_only:
                self.logger.debug(f"Comparing attributes and data for {table_name}")
                
                # Compare attributes
                attr_diff = self._compare_attributes(table1['attrs'], table2['attrs'], table_name)
                if attr_diff:
                    differences.extend(attr_diff)
                    identical = False
                
                # Compare data content
                # A read error on either side must fail the comparison loudly;
                # a dataset whose data could not be read must never silently pass.
                read_error = table1.get('read_error') or table2.get('read_error')
                if read_error:
                    differences.append(self._create_difference(
                        position=table_name,
                        expected="Data read successfully",
                        actual=f"Data read failed: {read_error}",
                        diff_type="error"
                    ))
                    identical = False
                elif 'data' in table1 and 'data' in table2:
                    # np.asarray normalizes scalars / 0-d values into arrays so
                    # they flow through the same comparison as array data.
                    data1 = np.asarray(table1['data'])
                    data2 = np.asarray(table2['data'])
                    
                    # Check if this is a large dataset that needs chunked comparison
                    if table1.get('needs_chunked_reading') or table2.get('needs_chunked_reading'):
                        # Large dataset: need to read from files in chunks
                        self.logger.debug(f"Comparing large dataset {table_name} using chunked reading")
                        # Get file paths from content dictionaries
                        file1_path = content1.get('_file_path')
                        file2_path = content2.get('_file_path')
                        
                        if not file1_path or not file2_path:
                            self.logger.error(f"File paths not available for chunked reading of {table_name}")
                            differences.append(self._create_difference(
                                position=table_name,
                                expected="File path available",
                                actual="File path missing",
                                diff_type="error"
                            ))
                            identical = False
                        else:
                            # Both files share the same comparison window
                            # (read_content stored it in the content metadata).
                            dataset_diff, ea = self._compare_dataset_chunked(
                                table1, table2, table_name, file1_path, file2_path,
                                start_line=content1.get('_start_line', 0),
                                end_line=content1.get('_end_line'),
                                start_column=content1.get('_start_column', 0),
                                end_column=content1.get('_end_column'),
                            )
                            if dataset_diff:
                                differences.extend(dataset_diff)
                                identical = False
                            # ── Error analysis: merge chunked statistics ──
                            if self.error_analysis and ea:
                                _ea_total += ea["total"]
                                _ea_mismatched += ea["mismatched"]
                                _ea_sum_abs += ea["sum_abs"]
                                _ea_sum_sq += ea["sum_sq"]
                                if ea["max_abs"] is not None:
                                    if _ea_max_abs is None or ea["max_abs"] > _ea_max_abs:
                                        _ea_max_abs = ea["max_abs"]
                                        _ea_max_abs_at = ea["max_abs_at"]
                                if ea["max_rel"] is not None:
                                    if _ea_max_rel is None or ea["max_rel"] > _ea_max_rel:
                                        _ea_max_rel = ea["max_rel"]
                                        _ea_max_rel_at = ea["max_rel_at"]
                    else:
                        # Small dataset: already in memory, compare directly
                        try:
                            # 应用过滤器
                            mask1 = self.filter_func(data1) if self.filter_func else np.ones_like(data1, dtype=bool)
                            mask2 = self.filter_func(data2) if self.filter_func else np.ones_like(data2, dtype=bool)
                            
                            # 我们只关心两个文件中都满足条件的位置
                            combined_mask = mask1 & mask2
                            
                            # 过滤后的数据
                            filtered_data1 = data1[combined_mask]
                            filtered_data2 = data2[combined_mask]
                            
                            if self.filter_func:
                                self.logger.debug(f"Applied filter to {table_name}: {np.sum(combined_mask)}/{data1.size} elements meet criteria")
                            
                            # 对于数值类型数据使用 shared numeric core
                            if np.issubdtype(data1.dtype, np.number) and np.issubdtype(data2.dtype, np.number):
                                res = compare_numeric(
                                    filtered_data1, filtered_data2,
                                    rtol=self.rtol, atol=self.atol,
                                    collect_stats=self.error_analysis,
                                )
                                all_close = res.mismatched == 0

                                # ── Error analysis: stats over ALL filtered numeric cells ──
                                if self.error_analysis:
                                    _ea_total += res.total
                                    _ea_mismatched += res.mismatched
                                    _ea_sum_abs += res.sum_abs_error
                                    _ea_sum_sq += res.sum_sq_abs_error
                                    if res.max_abs_error is not None:
                                        if _ea_max_abs is None or res.max_abs_error > _ea_max_abs:
                                            _ea_max_abs = res.max_abs_error
                                            _ea_max_abs_at = table_name
                                    if res.max_rel_error is not None:
                                        if _ea_max_rel is None or res.max_rel_error > _ea_max_rel:
                                            _ea_max_rel = res.max_rel_error
                                            _ea_max_rel_at = table_name

                                if not all_close:
                                    # 过滤后数据内容不同，报告差异（位置语义使用 dataset path）
                                    differences.append(self._create_difference(
                                        position=table_name,
                                        expected="Same content (after filtering)",
                                        actual="Content differs (after filtering)",
                                        diff_type="content"
                                    ))
                                    identical = False
                            # 对于字符串或其他类型直接比较
                            else:
                                if not np.array_equal(filtered_data1, filtered_data2):
                                    if self.show_content_diff:
                                        # For non-numeric arrays, find the first difference
                                        diff_indices = np.where(filtered_data1 != filtered_data2)
                                        for idx in list(zip(*diff_indices))[:10]:
                                            position = f"{table_name}[{','.join(map(str, idx))}]"
                                            differences.append(self._create_difference(
                                                position=position,
                                                expected=str(filtered_data1[idx]),
                                                actual=str(filtered_data2[idx]),
                                                diff_type="content"
                                            ))
                                    else:
                                        differences.append(self._create_difference(
                                            position=table_name,
                                            expected="Same content (after filtering)",
                                            actual="Content differs (after filtering)",
                                            diff_type="content"
                                        ))
                                    identical = False
                        except Exception as e:
                            self.logger.error(f"Error comparing data in table {table_name}: {str(e)}")
                            differences.append(self._create_difference(
                                position=table_name,
                                expected=f"Data type: {table1.get('dtype', 'unknown')}",
                                actual=f"Data type: {table2.get('dtype', 'unknown')}",
                                diff_type="error"
                            ))
                            identical = False

        # ── Store error stats ──
        # Mean / RMS use total numeric cells as the denominator (stats cover
        # ALL compared cells, matching ones included).
        if self.error_analysis and _ea_total > 0:
            self._error_stats = {
                "total_numeric_cells": _ea_total,
                "mismatched_cells": _ea_mismatched,
                "max_abs_error": _ea_max_abs,
                "max_abs_error_at": _ea_max_abs_at,
                "max_rel_error": _ea_max_rel,
                "max_rel_error_at": _ea_max_rel_at,
                "mean_abs_error": _ea_sum_abs / _ea_total,
                "rms_abs_error": np.sqrt(_ea_sum_sq / _ea_total),
            }

        return identical, differences, False

    def _compare_attributes(self, attrs1, attrs2, table_name):
        """Compare HDF5 attributes"""
        differences = []
        
        # Compare attribute keys
        keys1 = set(attrs1.keys())
        keys2 = set(attrs2.keys())
        
        # Check for missing attributes
        for key in keys1 - keys2:
            differences.append(self._create_difference(
                position=f"{table_name}/attrs/{key}",
                expected=str(attrs1[key]),
                actual="Attribute missing",
                diff_type="missing_attribute"
            ))
            
        for key in keys2 - keys1:
            differences.append(self._create_difference(
                position=f"{table_name}/attrs/{key}",
                expected="Attribute missing",
                actual=str(attrs2[key]),
                diff_type="extra_attribute"
            ))
            
        # Compare common attributes
        for key in keys1 & keys2:
            val1 = attrs1[key]
            val2 = attrs2[key]
            
            # Handle numpy arrays in attributes
            if isinstance(val1, np.ndarray) and isinstance(val2, np.ndarray):
                try:
                    if not np.array_equal(val1, val2):
                        differences.append(self._create_difference(
                            position=f"{table_name}/attrs/{key}",
                            expected=str(val1),
                            actual=str(val2),
                            diff_type="attribute"
                        ))
                except Exception as e:
                    self.logger.error(f"Error comparing array attribute {key}: {str(e)}")
                    differences.append(self._create_difference(
                        position=f"{table_name}/attrs/{key}",
                        expected=str(val1),
                        actual=str(val2),
                        diff_type="attribute"
                    ))
            elif isinstance(val1, np.ndarray) or isinstance(val2, np.ndarray):
                # One is array, one is not - they're different
                differences.append(self._create_difference(
                    position=f"{table_name}/attrs/{key}",
                    expected=str(val1),
                    actual=str(val2),
                    diff_type="attribute"
                ))
            else:
                # Regular comparison for non-array values
                if val1 != val2:
                    differences.append(self._create_difference(
                        position=f"{table_name}/attrs/{key}",
                        expected=str(val1),
                        actual=str(val2),
                        diff_type="attribute"
                    ))
                
        return differences

    def _create_difference(self, position, expected, actual, diff_type):
        """Create a Difference object"""
        from .result import Difference
        return Difference(position=position, expected=expected, actual=actual, diff_type=diff_type)

    def _parse_filter(self):
        """Parse data filter string and return a vectorized filter function (delegates to numeric core)"""
        return parse_data_filter(self.data_filter, logger=self.logger)
    
    def _compare_dataset_chunked(self, table1, table2, table_name, file1_path, file2_path,
                                 start_line=0, end_line=None, start_column=0, end_column=None):
        """
        Compare large datasets using chunked reading to avoid loading entire dataset into memory
        @param table1 dict: Dataset info from first file
        @param table2 dict: Dataset info from second file
        @param table_name str: Name/path of the dataset
        @param file1_path str: Path to first HDF5 file
        @param file2_path str: Path to second HDF5 file
        @param start_line int: Window start row (0-based, inclusive)
        @param end_line int: Window end row (0-based, inclusive; None for last row)
        @param start_column int: Window start column (0-based, inclusive; axis 1 for 2D+)
        @param end_column int: Window end column (0-based, inclusive; None for last column)
        @return tuple: (differences, error_stats or None) - list of Difference objects
               and, when error_analysis is enabled, accumulated statistics
               {"total", "mismatched", "sum_abs", "sum_sq", "max_abs", "max_abs_at",
               "max_rel", "max_rel_at"} (None otherwise)
        @details The line/column window uses the same 0-based, end-inclusive
                 semantics as the in-memory small-dataset branch. With
                 error_analysis enabled the whole window is traversed (no
                 early return on first difference) so statistics cover ALL
                 numeric cells.
        """
        differences = []
        ea = None
        if self.error_analysis:
            ea = {"total": 0, "mismatched": 0, "sum_abs": 0.0, "sum_sq": 0.0,
                  "max_abs": None, "max_abs_at": None,
                  "max_rel": None, "max_rel_at": None}
        dataset_path = table1.get('dataset_path') or table2.get('dataset_path') or table_name
        
        try:
            with h5py.File(file1_path, 'r') as f1, h5py.File(file2_path, 'r') as f2:
                ds1 = f1[dataset_path]
                ds2 = f2[dataset_path]
                
                # Verify shapes match (should already be checked, but verify again)
                if ds1.shape != ds2.shape:
                    differences.append(self._create_difference(
                        position=f"{table_name}/shape",
                        expected=str(ds1.shape),
                        actual=str(ds2.shape),
                        diff_type="structure"
                    ))
                    return differences, ea
                
                # Determine chunk size (1000 rows at a time, adjustable based on memory constraints)
                chunk_size = 1000
                total_rows = ds1.shape[0]
                
                ndim = len(ds1.shape)

                # Window bounds (0-based, end inclusive) -> exclusive slice
                # bounds, capped at the dataset extent like the small-dataset
                # branch. The chunked lane previously ignored the window
                # entirely and always compared the full dataset.
                win_row_start = max(start_line, 0)
                win_row_end = total_rows if end_line is None else min(end_line + 1, total_rows)
                win_row_end = max(win_row_end, win_row_start)
                if ndim >= 2:
                    total_cols = ds1.shape[1]
                    win_col_start = max(start_column, 0)
                    win_col_end = total_cols if end_column is None else min(end_column + 1, total_cols)
                    win_col_end = max(win_col_end, win_col_start)

                is_numeric = np.issubdtype(ds1.dtype, np.number) and np.issubdtype(ds2.dtype, np.number)
                mismatch_reported = False

                # Chunk along the first dimension; the column window applies
                # to axis 1 for 2D+ datasets, remaining axes are compared in full.
                for row_start in range(win_row_start, win_row_end, chunk_size):
                    row_end = min(row_start + chunk_size, win_row_end)

                    if ndim == 1:
                        slice1 = ds1[row_start:row_end]
                        slice2 = ds2[row_start:row_end]
                        position = f"{table_name}[{row_start}:{row_end}]"
                    elif ndim == 2:
                        slice1 = ds1[row_start:row_end, win_col_start:win_col_end]
                        slice2 = ds2[row_start:row_end, win_col_start:win_col_end]
                        position = f"{table_name}[{row_start}:{row_end},:]"
                    else:
                        slice_key = (slice(row_start, row_end), slice(win_col_start, win_col_end)) + (slice(None),) * (ndim - 2)
                        slice1 = ds1[slice_key]
                        slice2 = ds2[slice_key]
                        position = f"{table_name}[{row_start}:{row_end},...]"

                    # Apply filter if specified (flatten for element-wise masking)
                    if self.filter_func:
                        flat1 = slice1.ravel()
                        flat2 = slice2.ravel()
                        combined_mask = self.filter_func(flat1) & self.filter_func(flat2)
                        slice1 = flat1[combined_mask]
                        slice2 = flat2[combined_mask]

                    if is_numeric:
                        # Compare slices via shared numeric core
                        res = compare_numeric(slice1, slice2, rtol=self.rtol, atol=self.atol,
                                              collect_stats=self.error_analysis)
                        if ea is not None:
                            ea["total"] += res.total
                            ea["mismatched"] += res.mismatched
                            ea["sum_abs"] += res.sum_abs_error
                            ea["sum_sq"] += res.sum_sq_abs_error
                            if res.max_abs_error is not None:
                                if ea["max_abs"] is None or res.max_abs_error > ea["max_abs"]:
                                    ea["max_abs"] = res.max_abs_error
                                    ea["max_abs_at"] = table_name
                            if res.max_rel_error is not None:
                                if ea["max_rel"] is None or res.max_rel_error > ea["max_rel"]:
                                    ea["max_rel"] = res.max_rel_error
                                    ea["max_rel_at"] = table_name
                        if res.mismatched > 0:
                            if not mismatch_reported:
                                differences.append(self._create_difference(
                                    position=position,
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                mismatch_reported = True
                            # Early return on first difference to save time,
                            # but only when full-window statistics are not
                            # requested.
                            if ea is None:
                                return differences, ea
                    else:
                        if not np.array_equal(slice1, slice2):
                            differences.append(self._create_difference(
                                position=position,
                                expected="Content matches",
                                actual="Content differs",
                                diff_type="content"
                            ))
                            return differences, ea
                
        except Exception as e:
            self.logger.error(f"Error in chunked comparison of {table_name}: {str(e)}")
            differences.append(self._create_difference(
                position=table_name,
                expected="Successful comparison",
                actual=f"Error: {str(e)}",
                diff_type="error"
            ))
        
        return differences, ea