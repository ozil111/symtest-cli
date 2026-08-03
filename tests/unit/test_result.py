#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Difference and ComparisonResult classes."""

import json
import pytest

from symtest.file_comparator.result import Difference, ComparisonResult


# =============================================================================
# Difference tests
# =============================================================================


class TestDifferenceInit:
    """Test Difference construction and attribute access."""

    def test_default_values(self):
        d = Difference()
        assert d.position is None
        assert d.expected is None
        assert d.actual is None
        assert d.diff_type == "content"

    def test_full_construction(self):
        d = Difference(
            position="line 5",
            expected="hello",
            actual="world",
            diff_type="content",
        )
        assert d.position == "line 5"
        assert d.expected == "hello"
        assert d.actual == "world"
        assert d.diff_type == "content"


class TestDifferenceStr:
    """Test Difference.__str__ for all diff_type branches."""

    def test_content_type(self):
        d = Difference(position="line 3", expected="foo", actual="bar", diff_type="content")
        result = str(d)
        assert "line 3" in result
        assert "foo" in result
        assert "bar" in result

    def test_missing_type(self):
        d = Difference(position="line 10", expected="missing_content", diff_type="missing")
        result = str(d)
        assert "line 10" in result
        assert "missing_content" in result
        # With value-based display, shows expected value even for non-content types
        assert "expected" in result

    def test_extra_type(self):
        d = Difference(position="line 5", actual="extra_stuff", diff_type="extra")
        result = str(d)
        assert "line 5" in result
        assert "extra_stuff" in result
        # With value-based display, shows actual value even for non-content types
        assert "got" in result

    def test_unknown_type(self):
        d = Difference(position="byte 100", diff_type="unknown_type")
        result = str(d)
        assert "At byte 100" == result

    def test_size_type(self):
        d = Difference(
            position="file size",
            expected="1024 bytes",
            actual="2048 bytes",
            diff_type="size",
        )
        result = str(d)
        # With value-based display, shows expected/actual for all types
        assert "1024 bytes" in result
        assert "2048 bytes" in result
        assert "file size" in result


class TestDifferenceToDict:
    """Test Difference.to_dict()."""

    def test_to_dict(self):
        d = Difference(position="L1", expected="a", actual="b", diff_type="content")
        result = d.to_dict()
        assert result == {
            "position": "L1",
            "expected": "a",
            "actual": "b",
            "diff_type": "content",
        }

    def test_to_dict_with_none(self):
        d = Difference()
        result = d.to_dict()
        assert result["position"] is None
        assert result["expected"] is None
        assert result["actual"] is None
        assert result["diff_type"] == "content"


# =============================================================================
# ComparisonResult tests
# =============================================================================


class TestComparisonResultInit:
    """Test ComparisonResult construction and defaults."""

    def test_default_initialisation(self):
        cr = ComparisonResult()
        assert cr.file1 is None
        assert cr.file2 is None
        assert cr.file1_size is None
        assert cr.file2_size is None
        assert cr.start_line == 0
        assert cr.end_line is None
        assert cr.start_column == 0
        assert cr.end_column is None
        assert cr.identical is None
        assert cr.differences == []
        assert cr.error is None
        assert cr.similarity is None
        assert cr.truncated is False

    def test_full_initialisation(self):
        cr = ComparisonResult(
            file1="a.txt",
            file2="b.txt",
            start_line=5,
            end_line=10,
            start_column=2,
            end_column=8,
        )
        assert cr.file1 == "a.txt"
        assert cr.file2 == "b.txt"
        assert cr.start_line == 5
        assert cr.end_line == 10
        assert cr.start_column == 2
        assert cr.end_column == 8


# ---------------------------------------------------------------------------
# _get_range_str
# ---------------------------------------------------------------------------


class TestGetRangeStr:
    """Test ComparisonResult._get_range_str() branches."""

    def test_no_range(self):
        cr = ComparisonResult()
        assert cr._get_range_str() == ""

    def test_line_range_with_end(self):
        cr = ComparisonResult(start_line=2, end_line=5)
        # start_line=2 → "lines 3", end_line=5 → "-6"
        result = cr._get_range_str()
        assert "lines 3-6" in result

    def test_line_range_without_end(self):
        cr = ComparisonResult(start_line=3)
        # start_line=3 → "lines 4"
        result = cr._get_range_str()
        assert "lines 4" in result
        assert "-" not in result

    def test_column_range_with_end(self):
        cr = ComparisonResult(start_column=1, end_column=4)
        result = cr._get_range_str()
        assert "columns 2-5" in result

    def test_column_range_without_end(self):
        cr = ComparisonResult(start_column=5)
        result = cr._get_range_str()
        assert "columns 6" in result
        assert "-" not in result

    def test_both_line_and_column_range(self):
        cr = ComparisonResult(start_line=1, end_line=3, start_column=2, end_column=6)
        result = cr._get_range_str()
        assert "lines 2-4" in result
        assert "columns 3-7" in result
        # Should join with comma
        assert "," in result

    def test_start_column_zero_and_end_column_none(self):
        cr = ComparisonResult(start_column=0, end_column=None)
        # start_column=0 means condition (start_column > 0) is False
        result = cr._get_range_str()
        assert "column" not in result.lower()


# ---------------------------------------------------------------------------
# __str__
# ---------------------------------------------------------------------------


class TestComparisonResultStr:
    """Test ComparisonResult.__str__() branches."""

    def test_error(self):
        cr = ComparisonResult()
        cr.error = "File not found"
        result = str(cr)
        assert "Error during comparison" in result
        assert "File not found" in result

    def test_identical_without_range(self):
        cr = ComparisonResult()
        cr.identical = True
        result = str(cr)
        assert "identical" in result

    def test_identical_with_range(self):
        cr = ComparisonResult(start_line=2, end_line=5)
        cr.identical = True
        result = str(cr)
        assert "identical" in result
        assert "lines" in result

    def test_different_without_similarity(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.differences = [
            Difference(position="line 1", expected="a", actual="b"),
        ]
        result = str(cr)
        assert "different" in result
        assert "1 differences" in result
        assert "line 1" in result

    def test_different_with_similarity(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.similarity = 0.85
        cr.differences = [
            Difference(position="line 1", expected="a", actual="b"),
            Difference(position="line 2", expected="c", actual="d"),
        ]
        result = str(cr)
        assert "2 differences" in result
        assert "Similarity Index: 0.85" in result

    def test_different_zero_differences(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.differences = []
        result = str(cr)
        assert "0 differences" in result

    def test_different_truncated(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.truncated = True
        cr.differences = [
            Difference(position="line 1", expected="a", actual="b"),
        ]
        result = str(cr)
        assert "more differences not shown" in result


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestComparisonResultToDict:
    """Test ComparisonResult.to_dict()."""

    def test_to_dict_basic(self):
        cr = ComparisonResult(file1="a.txt", file2="b.txt")
        cr.identical = True
        cr.file1_size = 100
        cr.file2_size = 100
        cr.similarity = 1.0
        result = cr.to_dict()

        assert result["file1"] == "a.txt"
        assert result["file2"] == "b.txt"
        assert result["file1_size"] == 100
        assert result["file2_size"] == 100
        assert result["identical"] is True
        assert result["similarity"] == 1.0
        assert result["error"] is None
        assert result["differences"] == []
        assert result["truncated"] is False
        assert result["range"]["start_line"] == 0
        assert result["range"]["end_line"] is None

    def test_to_dict_with_differences(self):
        cr = ComparisonResult()
        cr.differences = [
            Difference(position="L1", expected="a", actual="b"),
            Difference(position="L2", expected="c", actual="d"),
        ]
        result = cr.to_dict()
        assert len(result["differences"]) == 2
        assert result["differences"][0]["position"] == "L1"
        assert result["differences"][1]["diff_type"] == "content"


# ---------------------------------------------------------------------------
# to_html
# ---------------------------------------------------------------------------


class TestComparisonResultToHtml:
    """Test ComparisonResult.to_html() branches."""

    def test_error(self):
        cr = ComparisonResult()
        cr.error = "Something went wrong"
        html = cr.to_html()
        assert "Error during comparison" in html
        assert "Something went wrong" in html
        assert "class='error'" in html
        assert "<html>" not in html  # error case returns a div only

    def test_identical(self):
        cr = ComparisonResult()
        cr.identical = True
        html = cr.to_html()
        assert "identical" in html
        assert "class='identical'" in html
        assert "<html>" in html

    def test_identical_with_range(self):
        cr = ComparisonResult(start_line=1, end_line=3)
        cr.identical = True
        html = cr.to_html()
        assert "identical" in html
        assert "lines" in html

    def test_different_no_similarity(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.differences = [
            Difference(position="L1", expected="hello", actual="world", diff_type="content"),
        ]
        html = cr.to_html()
        assert "different" in html
        assert "class='different'" in html
        assert "1 differences" in html
        assert "hello" in html
        assert "world" in html
        assert "Position:" in html
        assert "Type:" in html
        # Should not contain similarity
        assert "Similarity" not in html

    def test_different_with_similarity(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.similarity = 0.92
        cr.differences = [
            Difference(position="byte 100", expected="ff", actual="00"),
        ]
        html = cr.to_html()
        assert "Similarity Index: 0.92" in html

    def test_multiple_differences(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.differences = [
            Difference(position="L1", expected="a", actual="b"),
            Difference(position="L2", expected="c", actual="d"),
            Difference(position="L3", expected="e", actual="f"),
        ]
        html = cr.to_html()
        assert "3 differences" in html
        assert "Difference 1" in html
        assert "Difference 2" in html
        assert "Difference 3" in html


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------


class TestComparisonResultToJson:
    """Test ComparisonResult.to_json()."""

    def test_to_json_basic(self):
        cr = ComparisonResult(file1="a.txt", file2="b.txt")
        cr.identical = True
        result = cr.to_json()
        parsed = json.loads(result)
        assert parsed["file1"] == "a.txt"
        assert parsed["identical"] is True

    def test_to_json_with_differences(self):
        cr = ComparisonResult()
        cr.identical = False
        cr.differences = [
            Difference(position="L1", expected="a", actual="b"),
        ]
        result = cr.to_json()
        parsed = json.loads(result)
        assert len(parsed["differences"]) == 1
        assert parsed["differences"][0]["position"] == "L1"

    def test_to_json_is_valid_json(self):
        cr = ComparisonResult()
        cr.error = "Something failed"
        result = cr.to_json()
        # Should not raise
        parsed = json.loads(result)
        assert parsed["error"] == "Something failed"

    def test_to_json_with_none_values(self):
        cr = ComparisonResult()
        cr.identical = None
        result = cr.to_json()
        parsed = json.loads(result)
        assert parsed["identical"] is None
