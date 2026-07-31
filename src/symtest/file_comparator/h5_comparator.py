from .base_comparator import BaseComparator
import h5py
import numpy as np
import logging
import re

class H5Comparator(BaseComparator):
    def __init__(self, tables=None, table_regex=None, structure_only=False, show_content_diff=False, debug=False, rtol=1e-5, atol=1e-8, expand_path=True, data_filter=None, error_analysis=False, **kwargs):
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
        """
        super().__init__(**kwargs)
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
        
        # Set debug level if verbose is enabled
        if kwargs.get('verbose', False) or debug:
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
                        if obj.size < 1000000:
                            # Small dataset: read entire dataset into memory
                            data = obj[:]
                            if isinstance(data, np.ndarray):
                                if end_line is None:
                                    end_line_actual = data.shape[0]
                                else:
                                    end_line_actual = min(end_line, data.shape[0])
                                    
                                if len(data.shape) == 1:
                                    data = data[start_line:end_line_actual]
                                elif len(data.shape) > 1:
                                    if end_column is None:
                                        end_column_actual = data.shape[1]
                                    else:
                                        end_column_actual = min(end_column, data.shape[1])
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
                if 'data' in table1 and 'data' in table2:
                    data1 = table1['data']
                    data2 = table2['data']
                    
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
                            dataset_diff = self._compare_dataset_chunked(
                                table1, table2, table_name, file1_path, file2_path
                            )
                            if dataset_diff:
                                differences.extend(dataset_diff)
                                identical = False
                    elif isinstance(data1, np.ndarray) and isinstance(data2, np.ndarray):
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
                            
                            # 对于数值类型数据使用 isclose
                            if np.issubdtype(data1.dtype, np.number) and np.issubdtype(data2.dtype, np.number):
                                is_close = np.isclose(filtered_data1, filtered_data2, equal_nan=True, rtol=self.rtol, atol=self.atol)
                                all_close = np.all(is_close)

                                # ── Error analysis: streaming stats over ALL numeric cells ──
                                if self.error_analysis:
                                    f1 = np.asarray(filtered_data1, dtype=np.float64)
                                    f2 = np.asarray(filtered_data2, dtype=np.float64)
                                    n_cells = int(f1.size)
                                    _ea_total += n_cells
                                    if not all_close:
                                        mismatched = int(np.sum(~is_close))
                                        _ea_mismatched += mismatched
                                        diff = np.abs(f2 - f1)
                                        abs_err_vals = diff[~is_close]
                                        _ea_sum_abs += float(np.sum(abs_err_vals))
                                        _ea_sum_sq += float(np.sum(abs_err_vals ** 2))
                                        table_max_abs = float(np.max(abs_err_vals))
                                        if _ea_max_abs is None or table_max_abs > _ea_max_abs:
                                            _ea_max_abs = table_max_abs
                                            _ea_max_abs_at = table_name
                                        # Relative error (avoid div by zero)
                                        d1_vals = np.abs(f1[~is_close])
                                        safe_div = np.where(d1_vals > 0, d1_vals, 1e-300)
                                        rel_errs = abs_err_vals / safe_div
                                        table_max_rel = float(np.max(rel_errs))
                                        if _ea_max_rel is None or table_max_rel > _ea_max_rel:
                                            _ea_max_rel = table_max_rel
                                            _ea_max_rel_at = table_name

                                if not all_close:
                                    if self.show_content_diff:
                                        # 如果过滤后数据不相等，需要找到原始数据的索引来报告差异
                                        # 简化处理：直接报告内容不同
                                        differences.append(self._create_difference(
                                            position=table_name,
                                            expected="Same content (after filtering)",
                                            actual="Content differs (after filtering)",
                                            diff_type="content"
                                        ))
                                    else:
                                        # Just report that content differs
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
        if self.error_analysis and _ea_total > 0:
            self._error_stats = {
                "total_numeric_cells": _ea_total,
                "mismatched_cells": _ea_mismatched,
                "max_abs_error": _ea_max_abs,
                "max_abs_error_at": _ea_max_abs_at,
                "max_rel_error": _ea_max_rel,
                "max_rel_error_at": _ea_max_rel_at,
                "mean_abs_error": _ea_sum_abs / _ea_mismatched if _ea_mismatched > 0 else 0.0,
                "rms_abs_error": (np.sqrt(_ea_sum_sq / _ea_mismatched) if _ea_mismatched > 0 else 0.0),
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
        """Parse data filter string and return a filter function"""
        if not self.data_filter:
            return None

        self.logger.debug(f"Parsing data filter: {self.data_filter}")
        try:
            # 匹配模式，例如 'abs>0.1', '>=1e-5', '<-10'
            match = re.match(r"^(abs)?([><]=?|==)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$", self.data_filter.replace(" ", ""))
            if not match:
                self.logger.warning(f"Invalid data filter format: {self.data_filter}. Ignoring filter.")
                return None

            use_abs, op, value_str = match.groups()
            value = float(value_str)

            op_map = {
                '>': np.greater,
                '>=': np.greater_equal,
                '<': np.less,
                '<=': np.less_equal,
                '==': np.equal
            }

            def filter_func(data):
                if not isinstance(data, np.ndarray) or not np.issubdtype(data.dtype, np.number):
                    return np.ones_like(data, dtype=bool)  # 对于非数字类型，不过滤
                
                target_data = np.abs(data) if use_abs else data
                return op_map[op](target_data, value)

            self.logger.debug(f"Created filter function for pattern: {use_abs or ''}{op}{value}")
            return filter_func
        except Exception as e:
            self.logger.error(f"Failed to parse data filter '{self.data_filter}': {e}. Ignoring filter.")
            return None
    
    def _compare_dataset_chunked(self, table1, table2, table_name, file1_path, file2_path):
        """
        Compare large datasets using chunked reading to avoid loading entire dataset into memory
        @param table1 dict: Dataset info from first file
        @param table2 dict: Dataset info from second file
        @param table_name str: Name/path of the dataset
        @param file1_path str: Path to first HDF5 file
        @param file2_path str: Path to second HDF5 file
        @return list: List of Difference objects, empty if datasets are identical
        """
        differences = []
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
                    return differences
                
                # Determine chunk size (1000 rows at a time, adjustable based on memory constraints)
                chunk_size = 1000
                total_rows = ds1.shape[0]
                
                # Handle different dimensionalities
                if len(ds1.shape) == 1:
                    # 1D array: simple chunking
                    for start_idx in range(0, total_rows, chunk_size):
                        end_idx = min(start_idx + chunk_size, total_rows)
                        
                        # Read only this slice
                        slice1 = ds1[start_idx:end_idx]
                        slice2 = ds2[start_idx:end_idx]
                        
                        # Apply filter if specified
                        if self.filter_func:
                            mask1 = self.filter_func(slice1)
                            mask2 = self.filter_func(slice2)
                            combined_mask = mask1 & mask2
                            slice1 = slice1[combined_mask]
                            slice2 = slice2[combined_mask]
                        
                        # Compare slices
                        if np.issubdtype(ds1.dtype, np.number) and np.issubdtype(ds2.dtype, np.number):
                            if not np.all(np.isclose(slice1, slice2, equal_nan=True, rtol=self.rtol, atol=self.atol)):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx}]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                # Early return on first difference to save time
                                return differences
                        else:
                            if not np.array_equal(slice1, slice2):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx}]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                return differences
                
                elif len(ds1.shape) == 2:
                    # 2D array: chunk along first dimension
                    for start_idx in range(0, total_rows, chunk_size):
                        end_idx = min(start_idx + chunk_size, total_rows)
                        
                        # Read slice along first dimension
                        slice1 = ds1[start_idx:end_idx, :]
                        slice2 = ds2[start_idx:end_idx, :]
                        
                        # Apply filter if specified
                        if self.filter_func:
                            mask1 = self.filter_func(slice1)
                            mask2 = self.filter_func(slice2)
                            combined_mask = mask1 & mask2
                            # Flatten for filtering, then reshape
                            flat1 = slice1.flatten()
                            flat2 = slice2.flatten()
                            slice1 = flat1[combined_mask.flatten()]
                            slice2 = flat2[combined_mask.flatten()]
                        
                        # Compare slices
                        if np.issubdtype(ds1.dtype, np.number) and np.issubdtype(ds2.dtype, np.number):
                            if not np.all(np.isclose(slice1, slice2, equal_nan=True, rtol=self.rtol, atol=self.atol)):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx},:]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                return differences
                        else:
                            if not np.array_equal(slice1, slice2):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx},:]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                return differences
                
                else:
                    # Higher dimensional arrays: chunk along first dimension
                    # This is a simplified approach; for very high-dimensional arrays,
                    # you might want more sophisticated chunking
                    for start_idx in range(0, total_rows, chunk_size):
                        end_idx = min(start_idx + chunk_size, total_rows)
                        
                        # Create slice tuple
                        slice_tuple1 = (slice(start_idx, end_idx),) + (slice(None),) * (len(ds1.shape) - 1)
                        slice_tuple2 = (slice(start_idx, end_idx),) + (slice(None),) * (len(ds2.shape) - 1)
                        
                        slice1 = ds1[slice_tuple1]
                        slice2 = ds2[slice_tuple2]
                        
                        # Apply filter if specified (flatten for filtering)
                        if self.filter_func:
                            flat1 = slice1.flatten()
                            flat2 = slice2.flatten()
                            mask1 = self.filter_func(flat1)
                            mask2 = self.filter_func(flat2)
                            combined_mask = mask1 & mask2
                            slice1 = flat1[combined_mask]
                            slice2 = flat2[combined_mask]
                        
                        # Compare slices
                        if np.issubdtype(ds1.dtype, np.number) and np.issubdtype(ds2.dtype, np.number):
                            if not np.all(np.isclose(slice1, slice2, equal_nan=True, rtol=self.rtol, atol=self.atol)):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx},...]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                return differences
                        else:
                            if not np.array_equal(slice1, slice2):
                                differences.append(self._create_difference(
                                    position=f"{table_name}[{start_idx}:{end_idx},...]",
                                    expected="Content matches",
                                    actual="Content differs",
                                    diff_type="content"
                                ))
                                return differences
                
        except Exception as e:
            self.logger.error(f"Error in chunked comparison of {table_name}: {str(e)}")
            differences.append(self._create_difference(
                position=table_name,
                expected="Successful comparison",
                actual=f"Error: {str(e)}",
                diff_type="error"
            ))
        
        return differences