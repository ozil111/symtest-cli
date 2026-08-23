"""Parity tests: CSV and H5 comparators must share the same numeric comparison semantics.

The same logical numeric values, routed through CsvComparator and H5Comparator,
must produce identical core numeric statistics (identical/pass-fail, mismatch count,
max_abs_error, max_rel_error, mean_abs_error, rms_abs_error). Position descriptions
(row/column vs dataset/index) are allowed to differ.
"""
import numpy as np
import pytest

from symtest.file_comparator.csv_comparator import CsvComparator
from symtest.file_comparator.h5_comparator import H5Comparator


def _h5_content(arr1, arr2):
    """Build H5 compare_content dicts holding a single numeric dataset."""
    c1 = {
        "ds": {
            "type": "dataset", "shape": arr1.shape, "dtype": str(arr1.dtype),
            "attrs": {}, "data": np.asarray(arr1),
        }
    }
    c2 = {
        "ds": {
            "type": "dataset", "shape": arr2.shape, "dtype": str(arr2.dtype),
            "attrs": {}, "data": np.asarray(arr2),
        }
    }
    return c1, c2


def _stats_from_csv(expected, actual, **kwargs):
    """Run CSV compare_content with error_analysis=True on scalar value pairs."""
    cmp = CsvComparator(error_analysis=True, **kwargs)
    content1 = [[str(e)] for e in expected]
    content2 = [[str(a)] for a in actual]
    identical, _, _ = cmp.compare_content(content1, content2)
    return identical, cmp._error_stats


def _stats_from_h5(expected, actual, **kwargs):
    """Run H5 compare_content with error_analysis=True on the same numeric values."""
    cmp = H5Comparator(error_analysis=True, **kwargs)
    e = np.asarray(expected, dtype=np.float64)
    a = np.asarray(actual, dtype=np.float64)
    c1, c2 = _h5_content(e, a)
    identical, _, _ = cmp.compare_content(c1, c2)
    return identical, cmp._error_stats


def _assert_parity(expected, actual, **kwargs):
    csv_ident, csv_stats = _stats_from_csv(expected, actual, **kwargs)
    h5_ident, h5_stats = _stats_from_h5(expected, actual, **kwargs)

    assert csv_ident == h5_ident
    if csv_ident:
        return

    # Both must have produced stats; if both are all-matching, stats may be None.
    if csv_stats is None and h5_stats is None:
        return
    assert csv_stats is not None
    assert h5_stats is not None

    assert csv_stats["mismatched_cells"] == h5_stats["mismatched_cells"]
    assert csv_stats["total_numeric_cells"] == h5_stats["total_numeric_cells"]
    _assert_close_or_none(csv_stats["max_abs_error"], h5_stats["max_abs_error"])
    _assert_close_or_none(csv_stats["max_rel_error"], h5_stats["max_rel_error"])
    assert csv_stats["mean_abs_error"] == pytest.approx(h5_stats["mean_abs_error"], rel=1e-9, abs=1e-12)
    assert csv_stats["rms_abs_error"] == pytest.approx(h5_stats["rms_abs_error"], rel=1e-9, abs=1e-12)


def _assert_close_or_none(a, b):
    if a is None or b is None:
        assert a is None and b is None
    else:
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12)


# ── Parity across representative numeric scenarios ──

def test_parity_within_tolerance():
    _assert_parity([1.0, 2.0, 3.0], [1.0, 2.000001, 3.0], rtol=1e-5, atol=1e-5)


def test_parity_outside_tolerance():
    _assert_parity([1.0, 2.0, 3.0], [1.0, 3.0, 3.0], rtol=1e-5, atol=1e-8)


def test_parity_positive_negative():
    _assert_parity([1.0, -1.0], [1.0, -2.0], rtol=1e-5, atol=1e-8)


def test_parity_zero_reference():
    # zero reference with non-zero actual -> rel_err = inf on both sides
    _assert_parity([0.0], [5.0], rtol=1e-5, atol=1e-8)


def test_parity_very_small_values():
    _assert_parity([1e-20, 1e-19], [2e-20, 1e-19], rtol=1e-5, atol=1e-8)


def test_parity_nan():
    # NaN == NaN equal on both comparators
    _assert_parity([1.0, float("nan")], [1.0, float("nan")], rtol=1e-5, atol=1e-8)


def test_parity_inf():
    _assert_parity([float("inf"), 1.0], [float("inf"), 2.0], rtol=1e-5, atol=1e-8)


def test_parity_neg_inf():
    _assert_parity([float("-inf"), 1.0], [float("-inf"), 1.5], rtol=1e-5, atol=1e-8)


def test_parity_max_abs_error():
    _assert_parity([10.0, 1.0], [0.0, 1.5], rtol=1e-5, atol=1e-8)


def test_parity_max_rel_error():
    _assert_parity([1.0, 100.0], [1.001, 100.001], rtol=1e-9, atol=1e-12)


def test_parity_mean_and_rms():
    _assert_parity([2.0, 5.0], [3.0, 8.0], rtol=1e-5, atol=1e-8)


def test_parity_mismatch_count():
    _assert_parity([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 1.0, 3.0], rtol=1e-5, atol=1e-8)


def test_parity_data_filter():
    _assert_parity([0.5, 3.0], [9.9, 3.1], data_filter=">1.0")


def test_parity_mixed_scenario():
    # Mixed exact / within-tol / mismatched values in a single array.
    expected = [0.0, 1.0, 2.0, 5.0, float("inf"), float("nan"), -3.0]
    actual = [5.0, 1.0, 2.000001, 8.0, float("inf"), float("nan"), -3.5]
    _assert_parity(expected, actual, rtol=1e-5, atol=1e-8)


def test_parity_h5_multidimensional_matches_csv_semantics():
    # Multi-dimensional H5 ndarray: same numeric semantics as flattened CSV cells.
    arr1 = np.array([[1.0, 2.0], [3.0, 4.0]])
    arr2 = np.array([[1.0, 2.0], [3.0, 5.0]])
    cmp = H5Comparator(error_analysis=True, rtol=1e-5, atol=1e-8)
    c1, c2 = _h5_content(arr1, arr2)
    h5_identical, _, _ = cmp.compare_content(c1, c2)
    h5_stats = cmp._error_stats

    csv_identical, csv_stats = _stats_from_csv(
        arr1.ravel(), arr2.ravel(), rtol=1e-5, atol=1e-8
    )

    assert csv_identical == h5_identical
    assert csv_stats["mismatched_cells"] == h5_stats["mismatched_cells"]
    assert csv_stats["total_numeric_cells"] == h5_stats["total_numeric_cells"]
    _assert_close_or_none(csv_stats["max_abs_error"], h5_stats["max_abs_error"])
    assert csv_stats["rms_abs_error"] == pytest.approx(h5_stats["rms_abs_error"], rel=1e-9, abs=1e-12)
