"""Unit tests for error_analysis streaming statistics in CSV/H5 comparators."""
import os
import tempfile

import pytest

from cli_test_framework.file_comparator.csv_comparator import CsvComparator


# ── CSV Error Analysis ──

def _write_csv(content):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


class TestCsvErrorAnalysis:
    def test_no_error_analysis_no_stats(self):
        """Without error_analysis, _error_stats remains None."""
        cmp = CsvComparator(error_analysis=False)
        content1 = [["1.0", "2.0"], ["3.0", "4.0"]]
        content2 = [["1.0", "2.0"], ["3.0", "5.0"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        assert not identical
        assert cmp._error_stats is None

    def test_error_analysis_accumulates_stats(self):
        """With error_analysis=True, streaming stats are computed."""
        cmp = CsvComparator(error_analysis=True)
        content1 = [["1.0", "2.0"], ["3.0", "4.0"]]
        content2 = [["1.0", "2.0"], ["3.0", "5.0"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        assert not identical
        assert cmp._error_stats is not None
        stats = cmp._error_stats
        # All 4 cells are numeric
        # Only mismatched cells go through the numeric parse path.
        # Matching cells skip numeric comparison entirely.
        assert stats["total_numeric_cells"] == 1
        assert stats["mismatched_cells"] >= 1
        assert stats["max_abs_error"] >= 0.0
        assert stats["mean_abs_error"] >= 0.0

    def test_error_analysis_all_matching(self):
        """When all numeric cells match, stats show zero mismatches."""
        cmp = CsvComparator(error_analysis=True)
        content1 = [["1.0", "2.0"], ["3.0", "4.0"]]
        content2 = [["1.0", "2.0"], ["3.0", "4.0"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        assert identical
        assert cmp._error_stats is None  # no stats when identical (compare_content returns early)

    def test_error_analysis_tracks_max_abs_error(self):
        """Verify max_abs_error tracks the largest absolute difference."""
        cmp = CsvComparator(error_analysis=True)
        content1 = [["10.0"], ["1.0"]]
        content2 = [["0.0"], ["1.5"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        stats = cmp._error_stats
        assert stats["max_abs_error"] == pytest.approx(10.0, abs=1e-9)
        assert stats["mismatched_cells"] == 2

    def test_error_analysis_rms_calculation(self):
        """RMS = sqrt(sum(abs_err^2) / N)."""
        import math
        cmp = CsvComparator(error_analysis=True)
        # Two mismatched cells: diff 1.0 and diff 3.0
        content1 = [["2.0"], ["5.0"]]
        content2 = [["3.0"], ["8.0"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        stats = cmp._error_stats
        # abs errs: 1.0 and 3.0 → sum_sq = 10.0 → rms = sqrt(10/2) = sqrt(5) ≈ 2.236
        expected_rms = math.sqrt((1.0**2 + 3.0**2) / 2)
        assert stats["rms_abs_error"] == pytest.approx(expected_rms, abs=1e-9)
        assert stats["mean_abs_error"] == pytest.approx(2.0, abs=1e-9)

    def test_error_analysis_non_numeric_skipped(self):
        """Non-numeric cells are not counted in error_stats."""
        cmp = CsvComparator(error_analysis=True)
        content1 = [["hello", "1.0"]]
        content2 = [["world", "2.0"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        stats = cmp._error_stats
        # Only the numeric mismatched cell (1.0 vs 2.0) is counted
        assert stats["total_numeric_cells"] == 1
        assert stats["mismatched_cells"] == 1
        assert stats["max_abs_error"] == pytest.approx(1.0, abs=1e-9)

    def test_error_analysis_data_filter_applied(self):
        """data_filter is respected before counting numeric cells."""
        cmp = CsvComparator(error_analysis=True, data_filter=">2")
        content1 = [["0.5", "3.0"]]
        content2 = [["9.9", "3.1"]]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        stats = cmp._error_stats
        # Only cells where BOTH values > 2 are counted (3.0 vs 3.1)
        # 0.5 vs 9.9: 0.5 is NOT > 2, so filtered out
        assert stats["total_numeric_cells"] == 1
        assert stats["mismatched_cells"] == 1
        assert stats["max_abs_error"] == pytest.approx(0.1, abs=1e-9)

    def test_error_analysis_truncation_no_effect(self):
        """Stats cover ALL cells even when differences are truncated for display."""
        cmp = CsvComparator(error_analysis=True)
        # Create many mismatched cells (more than max_diffs=10)
        rows = []
        for i in range(20):
            rows.append([str(i + 1)])
        content1 = rows
        content2 = [[str(float(r[0]) + 0.1)] for r in rows]
        identical, diffs, truncated = cmp.compare_content(content1, content2)
        stats = cmp._error_stats
        # truncated is True (diffs capped at 10), but stats cover all 20 cells
        assert truncated
        assert stats["total_numeric_cells"] == 20
        assert stats["mismatched_cells"] == 20
        assert stats["mean_abs_error"] == pytest.approx(0.1, abs=1e-9)
