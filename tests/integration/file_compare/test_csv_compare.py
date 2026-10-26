from symtest.file_comparator.factory import ComparatorFactory
import pytest


def compare_csv(file1, file2, **kwargs):
    compare_kwargs = {
        key: kwargs.pop(key)
        for key in ("start_line", "end_line", "start_column", "end_column")
        if key in kwargs
    }
    comparator = ComparatorFactory.create_comparator("csv", **kwargs)
    return comparator.compare_files(file1, file2, **compare_kwargs)


def test_csv_identical_files(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    content = "id,name\n1,Ada\n2,Grace\n"
    file1.write_text(content, encoding="utf-8")
    file2.write_text(content, encoding="utf-8")

    result = compare_csv(file1, file2)

    assert result.identical
    assert result.differences == []


def test_csv_cell_difference(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,name\n1,Ada\n", encoding="utf-8")
    file2.write_text("id,name\n1,Grace\n", encoding="utf-8")

    result = compare_csv(file1, file2)

    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"
    assert diff.position == "row 2, column 2"
    assert diff.expected == "Ada"
    assert diff.actual == "Grace"


def test_csv_row_and_column_count_differences(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,name\n1,Ada\n2,Grace\n", encoding="utf-8")
    file2.write_text("id,name,role\n1,Ada,admin\n", encoding="utf-8")

    result = compare_csv(file1, file2)

    assert not result.identical
    diff_types = {diff.diff_type for diff in result.differences}
    assert "row_count_mismatch" in diff_types
    assert "column_count_mismatch" in diff_types


def test_csv_column_range_limits_scope(tmp_path):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,name,status\n1,Ada,old\n", encoding="utf-8")
    file2.write_text("id,name,status\n1,Ada,new\n", encoding="utf-8")

    result = compare_csv(file1, file2, start_column=0, end_column=1)

    assert result.identical


def test_csv_numeric_tolerance_within_range(tmp_path):
    """Numeric cells within tolerance should be treated as equal"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,value\n1,1.000001\n2,3.0\n", encoding="utf-8")
    file2.write_text("id,value\n1,1.0\n2,3.00001\n", encoding="utf-8")

    result = compare_csv(file1, file2, rtol=1e-5, atol=1e-5)

    assert result.identical
    assert result.differences == []


def test_csv_numeric_tolerance_exceeded(tmp_path):
    """Numeric cells exceeding tolerance should be reported as mismatch"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,value\n1,1.0\n", encoding="utf-8")
    file2.write_text("id,value\n1,2.0\n", encoding="utf-8")

    result = compare_csv(file1, file2, rtol=1e-5, atol=1e-8)

    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"
    assert diff.expected == "1.0"
    assert diff.actual == "2.0"


def test_csv_numeric_tolerance_mixed_with_string(tmp_path):
    """Non-numeric cells should still use string comparison even with tolerance enabled"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,name,value\n1,Ada,1.0\n", encoding="utf-8")
    file2.write_text("id,name,value\n1,Grace,1.000001\n", encoding="utf-8")

    result = compare_csv(file1, file2, rtol=1e-5, atol=1e-5)

    assert not result.identical
    # Only the string mismatch should be reported; numeric value is within tolerance
    diff_types = [d.diff_type for d in result.differences]
    assert "cell_mismatch" in diff_types
    string_diffs = [d for d in result.differences if d.diff_type == "cell_mismatch"]
    assert any(d.expected == "Ada" and d.actual == "Grace" for d in string_diffs)


def test_csv_data_filter_greater_than(tmp_path):
    """Cells that don't meet filter criteria in both files should be skipped"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("value\n0.0\n100.0\n-0.002\n", encoding="utf-8")
    file2.write_text("value\n0.0\n100.1\n0.002\n", encoding="utf-8")

    # '>100.0' filters out the 100.0 vs 100.1 pair (100.0 does NOT satisfy >100.0)
    result = compare_csv(file1, file2, data_filter=">100.0")
    assert result.identical


def test_csv_data_filter_greater_equal(tmp_path):
    """'>=' includes the boundary value so mismatch should be reported"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("value\n0.0\n100.0\n", encoding="utf-8")
    file2.write_text("value\n0.0\n100.1\n", encoding="utf-8")

    # '>=100.0' keeps the 100.0 vs 100.1 pair, which is outside tolerance
    result = compare_csv(file1, file2, data_filter=">=100.0", rtol=1e-5, atol=1e-8)
    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"


def test_csv_data_filter_abs_prefix(tmp_path):
    """'abs' prefix compares absolute value"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("value\n0.0\n-0.002\n0.003\n", encoding="utf-8")
    file2.write_text("value\n0.0\n0.002\n0.003\n", encoding="utf-8")

    # abs>0.001 filters out the -0.002 vs 0.002 pair
    # (abs(-0.002)=0.002 > 0.001 AND abs(0.002)=0.002 > 0.001 → both satisfy)
    result = compare_csv(file1, file2, data_filter="abs>0.001")
    assert not result.identical  # -0.002 vs 0.002 differ, both satisfy filter


def test_csv_data_filter_skips_non_numeric(tmp_path):
    """Non-numeric cells are unaffected by data filter"""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("name\nAlice\nBob\n", encoding="utf-8")
    file2.write_text("name\nAlice\nCharlie\n", encoding="utf-8")

    # Both strings fall through to string mismatch; data_filter only affects numeric paths
    result = compare_csv(file1, file2, data_filter=">0")
    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"
    assert diff.expected == "Bob"
    assert diff.actual == "Charlie"


def test_csv_column_range_detects_difference_in_selected_column(tmp_path):
    """Regression: column ranges select CSV FIELDS, not characters.

    Previously the column window was applied twice: once as a character
    slice on each text line (destroying the CSV field structure) and once
    as a field slice, so a difference in the selected column could be
    silently trimmed away.
    """
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,value\n1,10\n2,20\n", encoding="utf-8")
    file2.write_text("id,value\n1,99\n2,20\n", encoding="utf-8")

    # Select only the second column (0-based inclusive: columns 1..1)
    result = compare_csv(file1, file2, start_column=1, end_column=1)
    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"
    assert diff.expected == "10"
    assert diff.actual == "99"
    assert diff.position == "row 2, column 2"


def test_csv_column_range_start_only_detects_difference(tmp_path):
    """start_column without end_column must still select the field tail."""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,value,extra\n1,10,x\n", encoding="utf-8")
    file2.write_text("id,value,extra\n1,99,x\n", encoding="utf-8")

    result = compare_csv(file1, file2, start_column=1)
    assert not result.identical


def test_csv_column_range_excludes_difference_outside_scope(tmp_path):
    """Differences outside the selected column window are ignored."""
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,value,status\n1,10,old\n", encoding="utf-8")
    file2.write_text("id,value,status\n1,10,new\n", encoding="utf-8")

    # Window covers only column 1 ("value"); the "status" difference is outside
    result = compare_csv(file1, file2, start_column=1, end_column=1)
    assert result.identical


def test_csv_large_integer_no_float_precision_collapse(tmp_path):
    """Regression: 2**53 vs 2**53+1 must not collapse onto the same float64.

    Previously every numeric cell was parsed with float(), so distinct
    large integers compared equal under zero tolerance.
    """
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("value\n9007199254740992\n", encoding="utf-8")  # 2**53
    file2.write_text("value\n9007199254740993\n", encoding="utf-8")  # 2**53 + 1

    result = compare_csv(file1, file2, rtol=0.0, atol=0.0)
    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "cell_mismatch"
    assert diff.expected == "9007199254740992"
    assert diff.actual == "9007199254740993"


@pytest.mark.parametrize("error_analysis", [False, True])
@pytest.mark.parametrize("baseline,actual,total", [
    ("9007199254740992,1.0\n", "9007199254740993,1.0\n", 2),
    ("9007199254740992\n1.0\n", "9007199254740993\n1.0\n", 2),
    (f"{2**64 - 2}\n", f"{2**64 - 1}\n", 1),
    (f"{-2**63}\n", f"{-2**63 + 1}\n", 1),
])
def test_csv_integer_verdict_and_stats_agree(tmp_path, error_analysis, baseline, actual, total):
    file1, file2 = tmp_path / "a.csv", tmp_path / "b.csv"
    file1.write_text(baseline, encoding="utf-8")
    file2.write_text(actual, encoding="utf-8")
    result = compare_csv(file1, file2, rtol=0, atol=0, error_analysis=error_analysis)
    assert not result.identical
    assert result.error is None
    if error_analysis:
        stats = result.error_stats
        assert stats["total_numeric_cells"] == total
        assert stats["mismatched_cells"] == 1
        assert stats["max_abs_error"] == 1
        assert stats["mean_abs_error"] == 1 / total
        assert stats["rms_abs_error"] == pytest.approx((1 / total)**0.5)
        assert stats["max_abs_error_at"] == "row 1, column 1"
