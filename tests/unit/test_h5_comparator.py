#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for H5Comparator - focuses on logic not covered by integration tests.
"""

import numpy as np
import h5py
import pytest
from pathlib import Path

from symtest.file_comparator.h5_comparator import H5Comparator
from symtest.file_comparator.result import Difference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_h5(path, datasets, groups=None, attrs_per_ds=None, group_attrs=None):
    """
    Create an H5 file.

    :param path: file path
    :param datasets: dict of {ds_path: np.array or list}
    :param groups: dict of {group_path: list_of_child_keys}  (optional)
    :param attrs_per_ds: dict of {ds_path: {key: val}}  (optional)
    :param group_attrs: dict of {group_path: {key: val}}  (optional)
    """
    with h5py.File(path, "w") as f:
        # Create groups first
        if groups:
            for group_path, child_keys in groups.items():
                parts = group_path.split("/")
                grp = f
                for part in parts:
                    if part:
                        grp = grp.require_group(part)
                # Add group attributes
                if group_attrs and group_path in group_attrs:
                    for k, v in group_attrs[group_path].items():
                        grp.attrs[k] = v

        # Create datasets
        for ds_path, data in datasets.items():
            arr = np.array(data["data"]) if isinstance(data, dict) else np.array(data)
            parts = ds_path.split("/")
            parent = f
            for part in parts[:-1]:
                parent = parent.require_group(part)
            ds = parent.create_dataset(parts[-1], data=arr)
            # Dataset-level attrs
            ds_attrs = None
            if attrs_per_ds and ds_path in attrs_per_ds:
                ds_attrs = attrs_per_ds[ds_path]
            elif isinstance(data, dict) and "attrs" in data:
                ds_attrs = data["attrs"]
            if ds_attrs:
                for k, v in ds_attrs.items():
                    ds.attrs[k] = v


def compare(file1, file2, **kwargs):
    comp = H5Comparator(**kwargs)
    return comp.compare_files(file1, file2)


# ===========================================================================
# _parse_filter
# ===========================================================================

class TestParseFilter:
    """Test _parse_filter logic independently."""

    def test_no_filter_returns_none(self):
        comp = H5Comparator()
        assert comp.filter_func is None

    def test_invalid_filter_returns_none(self):
        comp = H5Comparator(data_filter="invalid!!pattern")
        assert comp.filter_func is None

    @pytest.mark.parametrize("expr", ["abs>0.1", ">1e-5", ">=10", "<=-3", "==0"])
    def test_valid_filters_created(self, expr):
        comp = H5Comparator(data_filter=expr)
        assert comp.filter_func is not None

    def test_abs_greater_than(self):
        comp = H5Comparator(data_filter="abs>1.0")
        data = np.array([-0.5, 0.5, -1.5, 1.5])
        result = comp.filter_func(data)
        np.testing.assert_array_equal(result, [False, False, True, True])

    def test_greater_than(self):
        comp = H5Comparator(data_filter=">0")
        data = np.array([-1, 0, 1])
        result = comp.filter_func(data)
        np.testing.assert_array_equal(result, [False, False, True])

    def test_less_equal(self):
        comp = H5Comparator(data_filter="<=2")
        data = np.array([1, 2, 3])
        result = comp.filter_func(data)
        np.testing.assert_array_equal(result, [True, True, False])

    def test_non_numeric_data_returns_all_true(self):
        comp = H5Comparator(data_filter=">0")
        data = np.array(["a", "b"])
        result = comp.filter_func(data)
        assert np.all(result)


# ===========================================================================
# read_content - structure_only mode
# ===========================================================================

class TestReadContentStructureOnly:
    """Test read_content in structure_only mode."""

    def test_structure_only_skips_data(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"ds": np.array([1.0, 2.0, 3.0])})
        comp = H5Comparator(structure_only=True)
        content = comp.read_content(f1)
        ds_info = content["ds"]
        assert ds_info["type"] == "dataset"
        assert "data" not in ds_info  # no data loaded
        assert ds_info["shape"] == (3,)

    def test_structure_only_reads_groups(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"g/ds": np.array([1.0])})
        comp = H5Comparator(structure_only=True)
        content = comp.read_content(f1)
        assert "g" in content
        assert content["g"]["type"] == "group"

    def test_structure_only_all_datasets(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"a": np.array([1]), "b": np.array([2.0, 3.0])})
        comp = H5Comparator(structure_only=True)
        content = comp.read_content(f1)
        assert set(content.keys()) - {'_file_path', '_start_line', '_end_line', '_start_column', '_end_column'} == {"a", "b"}


# ===========================================================================
# read_content - range constraints (start_line, end_line, start_column, end_column)
# ===========================================================================

class TestReadContentRange:
    """Test read_content with line/column range constraints."""

    def test_1d_range_slicing(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"ds": np.arange(10, dtype=float)})
        comp = H5Comparator()
        content = comp.read_content(f1, start_line=2, end_line=5)
        np.testing.assert_array_equal(content["ds"]["data"], [2.0, 3.0, 4.0])

    def test_2d_range_slicing(self, tmp_path):
        f1 = tmp_path / "a.h5"
        data = np.arange(20, dtype=float).reshape(4, 5)
        create_h5(f1, {"ds": data})
        comp = H5Comparator()
        content = comp.read_content(f1, start_line=1, end_line=3, start_column=1, end_column=4)
        expected = data[1:3, 1:4]
        np.testing.assert_array_equal(content["ds"]["data"], expected)

    def test_end_line_beyond_shape(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"ds": np.array([1.0, 2.0])})
        comp = H5Comparator()
        content = comp.read_content(f1, end_line=100)
        np.testing.assert_array_equal(content["ds"]["data"], [1.0, 2.0])


# ===========================================================================
# read_content - table selection & regex
# ===========================================================================

class TestReadContentTableSelection:
    """Test read_content with tables and table_regex parameters."""

    def test_tables_selects_specific_datasets(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"ds1": np.array([1]), "ds2": np.array([2])})
        comp = H5Comparator(tables=["ds1"])
        content = comp.read_content(f1)
        assert "ds1" in content
        assert "ds2" not in content

    def test_table_regex_matches(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"metric_a": np.array([1]), "metric_b": np.array([2]), "other": np.array([3])})
        comp = H5Comparator(table_regex="metric_.*")
        content = comp.read_content(f1)
        assert "metric_a" in content
        assert "metric_b" in content
        assert "other" not in content

    def test_multiple_regex_patterns_comma_separated(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"cat_a": np.array([1]), "dog_b": np.array([2]), "other": np.array([3])})
        comp = H5Comparator(table_regex="cat_.*,dog_.*")
        content = comp.read_content(f1)
        assert "cat_a" in content
        assert "dog_b" in content
        assert "other" not in content

    def test_literal_path_escaped_when_no_metacharacters(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"group/data": np.array([1]), "group/other": np.array([2])})
        # "group/data" has no regex metacharacters, should be treated as literal
        comp = H5Comparator(table_regex="group/data")
        content = comp.read_content(f1)
        assert "group/data" in content
        assert "group/other" not in content

    def test_table_not_found_logs_warning(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"ds": np.array([1])})
        comp = H5Comparator(tables=["nonexistent"])
        content = comp.read_content(f1)
        # No crash, just a warning; content should have no matched datasets
        ds_keys = set(content.keys()) - {'_file_path', '_start_line', '_end_line', '_start_column', '_end_column'}
        assert "nonexistent" not in ds_keys

    def test_expand_path_true_reads_group_children(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"parent/child": np.array([1])})
        comp = H5Comparator(tables=["parent"], expand_path=True)
        content = comp.read_content(f1)
        assert "parent/child" in content

    def test_expand_path_false_skips_group_children(self, tmp_path):
        f1 = tmp_path / "a.h5"
        create_h5(f1, {"parent/child": np.array([1])})
        comp = H5Comparator(tables=["parent"], expand_path=False)
        content = comp.read_content(f1)
        # "parent" is a group, only its metadata (keys, attrs) is stored
        assert "parent" in content
        assert content["parent"]["type"] == "group"
        assert "parent/child" not in content


# ===========================================================================
# compare_content - type mismatch
# ===========================================================================

class TestCompareContentTypeMismatch:
    """Test compare_content when one side is dataset and the other is group."""

    def test_dataset_vs_group(self):
        comp = H5Comparator()
        content1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0])}}
        content2 = {"ds": {"type": "group", "keys": ["a"], "attrs": {}}}
        identical, diffs, _ = comp.compare_content(content1, content2)
        assert not identical
        assert any("type" in d.position for d in diffs)


# ===========================================================================
# compare_content - shape / dtype differences
# ===========================================================================

class TestCompareContentShapeDtype:
    """Test compare_content when shape or dtype differ."""

    def test_shape_mismatch(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (4,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0, 4.0])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any("shape" in d.position for d in diffs)

    def test_dtype_mismatch(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "int32", "attrs": {}, "data": np.array([1, 2, 3])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any("dtype" in d.position for d in diffs)


# ===========================================================================
# compare_content - table missing in second file
# ===========================================================================

class TestCompareContentTableMissing:
    """Test compare_content when a table exists in one file but not the other."""

    def test_table_missing_in_content2(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0])}}
        c2 = {}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any(d.diff_type == "structure" and "ds" in d.position for d in diffs)

    def test_table_missing_in_content1(self):
        comp = H5Comparator()
        c1 = {}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0, 3.0])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any(d.diff_type == "structure" for d in diffs)


# ===========================================================================
# compare_content - group keys differences
# ===========================================================================

class TestCompareContentGroupKeys:
    """Test compare_content when groups have different keys."""

    def test_group_missing_keys(self):
        comp = H5Comparator()
        c1 = {"g": {"type": "group", "keys": ["a", "b"], "attrs": {}}}
        c2 = {"g": {"type": "group", "keys": ["a"], "attrs": {}}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any("keys" in d.position for d in diffs)

    def test_group_extra_keys(self):
        comp = H5Comparator()
        c1 = {"g": {"type": "group", "keys": ["a"], "attrs": {}}}
        c2 = {"g": {"type": "group", "keys": ["a", "b"], "attrs": {}}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        assert any("keys" in d.position and d.diff_type == "structure" for d in diffs)


# ===========================================================================
# _compare_attributes
# ===========================================================================

class TestCompareAttributes:
    """Test attribute comparison logic."""

    def test_identical_attrs(self):
        comp = H5Comparator()
        attrs1 = {"units": "m", "version": 2}
        attrs2 = {"units": "m", "version": 2}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert diffs == []

    def test_missing_attribute(self):
        comp = H5Comparator()
        attrs1 = {"units": "m", "version": 2}
        attrs2 = {"units": "m"}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert len(diffs) == 1
        assert diffs[0].diff_type == "missing_attribute"

    def test_extra_attribute(self):
        comp = H5Comparator()
        attrs1 = {"units": "m"}
        attrs2 = {"units": "m", "version": 2}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert len(diffs) == 1
        assert diffs[0].diff_type == "extra_attribute"

    def test_different_attribute_values(self):
        comp = H5Comparator()
        attrs1 = {"units": "m"}
        attrs2 = {"units": "km"}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert len(diffs) == 1
        assert diffs[0].diff_type == "attribute"

    def test_numpy_array_attrs_equal(self):
        comp = H5Comparator()
        attrs1 = {"range": np.array([1.0, 2.0, 3.0])}
        attrs2 = {"range": np.array([1.0, 2.0, 3.0])}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert diffs == []

    def test_numpy_array_attrs_different(self):
        comp = H5Comparator()
        attrs1 = {"range": np.array([1.0, 2.0])}
        attrs2 = {"range": np.array([1.0, 3.0])}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert len(diffs) == 1
        assert diffs[0].diff_type == "attribute"

    def test_array_vs_scalar_attr(self):
        comp = H5Comparator()
        attrs1 = {"val": np.array([1.0])}
        attrs2 = {"val": 1.0}
        diffs = comp._compare_attributes(attrs1, attrs2, "ds")
        assert len(diffs) == 1
        assert diffs[0].diff_type == "attribute"


# ===========================================================================
# compare_content - data comparison (numeric)
# ===========================================================================

class TestCompareContentNumericData:
    """Test numeric data comparison including NaN and tolerance."""

    def test_nan_values_equal_with_equal_nan(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, np.nan])}}
        c2 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, np.nan])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert identical

    def test_numeric_data_within_tolerance(self):
        comp = H5Comparator(rtol=1e-3, atol=1e-6)
        c1 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.0001, 2.0001])}}
        identical, _, _ = comp.compare_content(c1, c2)
        assert identical

    def test_numeric_data_outside_tolerance(self):
        comp = H5Comparator(rtol=1e-5, atol=1e-8)
        c1 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.0, 2.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "float64", "attrs": {}, "data": np.array([1.01, 2.0])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical


# ===========================================================================
# compare_content - string / non-numeric data
# ===========================================================================

class TestCompareContentStringData:
    """Test comparison of string/non-numeric datasets."""

    def test_identical_string_data(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "b", "c"])}}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "b", "c"])}}
        identical, _, _ = comp.compare_content(c1, c2)
        assert identical

    def test_different_string_data_without_show_content_diff(self):
        comp = H5Comparator()
        c1 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "b"])}}
        c2 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "x"])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        # Without show_content_diff, reports a single summary diff
        assert len(diffs) == 1
        assert "differs" in diffs[0].actual.lower() or "differs" in str(diffs[0].expected).lower()

    def test_different_string_data_with_show_content_diff(self):
        comp = H5Comparator(show_content_diff=True)
        c1 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "b"])}}
        c2 = {"ds": {"type": "dataset", "shape": (2,), "dtype": "object", "attrs": {},
                      "data": np.array(["a", "x"])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical
        # With show_content_diff, reports per-element differences (max 10)
        assert len(diffs) >= 1
        # The position should include an index
        assert any("[" in d.position for d in diffs)


# ===========================================================================
# compare_content - data_filter
# ===========================================================================

class TestCompareContentWithFilter:
    """Test that data_filter correctly masks data during comparison."""

    def test_filter_makes_different_data_identical(self):
        comp = H5Comparator(data_filter=">5")
        c1 = {"ds": {"type": "dataset", "shape": (4,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.0, 2.0, 10.0, 20.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (4,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.0, 2.0, 10.0, 20.0])}}
        identical, _, _ = comp.compare_content(c1, c2)
        assert identical

    def test_filter_preserves_differences_in_passing_region(self):
        comp = H5Comparator(data_filter=">5")
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.0, 10.0, 20.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.0, 10.0, 99.0])}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical

    def test_filter_excludes_all_mismatched_data(self):
        comp = H5Comparator(data_filter=">100")
        # All differences are in values <= 100, so filter excludes them
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.0, 2.0, 3.0])}}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {},
                      "data": np.array([1.1, 2.2, 3.3])}}
        # Values all <= 100, so filter keeps nothing → empty arrays → equal
        # Actually: combined_mask = mask1 & mask2. If all values <= 100, mask is all False,
        # so filtered arrays are empty, and np.allclose of empty arrays returns True.
        identical, _, _ = comp.compare_content(c1, c2)
        assert identical


# ===========================================================================
# compare_content - structure_only mode
# ===========================================================================

class TestCompareContentStructureOnly:
    """Test structure_only mode skips data comparison."""

    def test_structure_only_ignores_data_diff(self):
        comp = H5Comparator(structure_only=True)
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}}}
        c2 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert identical
        assert diffs == []

    def test_structure_only_still_detects_shape_diff(self):
        comp = H5Comparator(structure_only=True)
        c1 = {"ds": {"type": "dataset", "shape": (3,), "dtype": "float64", "attrs": {}}}
        c2 = {"ds": {"type": "dataset", "shape": (4,), "dtype": "float64", "attrs": {}}}
        identical, diffs, _ = comp.compare_content(c1, c2)
        assert not identical


# ===========================================================================
# compare_content - attrs comparison integration
# ===========================================================================

class TestCompareContentAttributes:
    """Test that attribute differences are detected in compare_content."""

    def test_attr_difference_detected(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"ds": np.array([1.0, 2.0])}, attrs_per_ds={"ds": {"units": "m"}})
        create_h5(f2, {"ds": np.array([1.0, 2.0])}, attrs_per_ds={"ds": {"units": "km"}})
        result = compare(f1, f2)
        assert not result.identical
        assert any("attrs" in d.position for d in result.differences)

    def test_missing_attr_detected(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"ds": np.array([1.0])}, attrs_per_ds={"ds": {"version": 1, "units": "m"}})
        create_h5(f2, {"ds": np.array([1.0])}, attrs_per_ds={"ds": {"version": 1}})
        result = compare(f1, f2)
        assert not result.identical
        assert any(d.diff_type == "missing_attribute" for d in result.differences)


# ===========================================================================
# compare_content - chunked reading (large datasets)
# ===========================================================================

class TestCompareContentChunked:
    """Test chunked comparison for large datasets (size >= 1M elements)."""

    def _create_large_h5(self, path, data):
        """Create an H5 file with a large dataset."""
        with h5py.File(path, "w") as f:
            f.create_dataset("big", data=data)

    def test_large_identical_1d(self, tmp_path):
        data = np.random.rand(1_100_000)
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data)
        self._create_large_h5(f2, data)
        result = compare(f1, f2)
        assert result.identical

    def test_large_different_1d(self, tmp_path):
        data1 = np.zeros(1_100_000)
        data2 = np.zeros(1_100_000)
        data2[5000] = 1.0  # one different value
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data1)
        self._create_large_h5(f2, data2)
        result = compare(f1, f2)
        assert not result.identical

    def test_large_identical_2d(self, tmp_path):
        data = np.random.rand(1100, 1000)  # 1.1M elements
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data)
        self._create_large_h5(f2, data)
        result = compare(f1, f2)
        assert result.identical

    def test_large_different_2d(self, tmp_path):
        data1 = np.zeros((1100, 1000))
        data2 = np.zeros((1100, 1000))
        data2[0, 0] = 1.0
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data1)
        self._create_large_h5(f2, data2)
        result = compare(f1, f2)
        assert not result.identical

    def test_large_with_data_filter(self, tmp_path):
        data1 = np.ones(1_100_000) * 0.001
        data2 = np.ones(1_100_000) * 0.002
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data1)
        self._create_large_h5(f2, data2)
        # Filter: only compare values > 0.5, but all are small → all filtered out → identical
        result = compare(f1, f2, data_filter=">0.5")
        assert result.identical

    def test_large_shape_mismatch(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        with h5py.File(f1, "w") as f:
            f.create_dataset("big", data=np.zeros(1_100_000))
        with h5py.File(f2, "w") as f:
            f.create_dataset("big", data=np.zeros((1100, 1000)))
        result = compare(f1, f2)
        assert not result.identical
        # Should have shape difference (detected before chunked reading)
        assert any("shape" in d.position for d in result.differences)

    def test_large_3d_identical(self, tmp_path):
        data = np.random.rand(110, 100, 100)  # 1.1M elements
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data)
        self._create_large_h5(f2, data)
        result = compare(f1, f2)
        assert result.identical

    def test_large_3d_different(self, tmp_path):
        data1 = np.zeros((110, 100, 100))
        data2 = np.zeros((110, 100, 100))
        data2[0, 0, 0] = 1.0
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        self._create_large_h5(f1, data1)
        self._create_large_h5(f2, data2)
        result = compare(f1, f2)
        assert not result.identical


# ===========================================================================
# compare_files - end-to-end attribute comparison
# ===========================================================================

class TestCompareFilesAttributes:
    """End-to-end tests for attribute comparison via compare_files."""

    def test_identical_files_with_attrs(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"ds": np.array([1.0, 2.0])}, attrs_per_ds={"ds": {"units": "m", "scale": 1.0}})
        create_h5(f2, {"ds": np.array([1.0, 2.0])}, attrs_per_ds={"ds": {"units": "m", "scale": 1.0}})
        result = compare(f1, f2)
        assert result.identical

    def test_group_attrs_difference(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"g/ds": np.array([1.0])}, groups={"g": ["ds"]}, group_attrs={"g": {"version": 1}})
        create_h5(f2, {"g/ds": np.array([1.0])}, groups={"g": ["ds"]}, group_attrs={"g": {"version": 2}})
        result = compare(f1, f2)
        assert not result.identical


# ===========================================================================
# verbose / debug mode
# ===========================================================================

class TestDebugMode:
    """Test that verbose/debug mode doesn't break functionality."""

    def test_verbose_mode(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"ds": np.array([1.0])})
        create_h5(f2, {"ds": np.array([1.0])})
        result = compare(f1, f2, verbose=True)
        assert result.identical

    def test_debug_mode(self, tmp_path):
        f1 = tmp_path / "a.h5"
        f2 = tmp_path / "b.h5"
        create_h5(f1, {"ds": np.array([1.0])})
        create_h5(f2, {"ds": np.array([1.0])})
        result = compare(f1, f2, debug=True)
        assert result.identical
