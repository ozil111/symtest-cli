"""Unit tests for the shared numeric comparison core (numeric_compare.py)."""
import numpy as np
import pytest

from symtest.file_comparator.numeric_compare import compare_numeric, parse_data_filter


# ── Basic closeness ──

def test_exact_equality():
    res = compare_numeric([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert res.total == 3
    assert res.mismatched == 0
    assert np.all(~res.mismatch_mask)
    assert res.max_abs_error is None
    assert res.max_rel_error is None


def test_within_rtol():
    # diff/ref ~ 1e-6 < rtol 1e-3
    res = compare_numeric([1000.0], [1000.001], rtol=1e-3, atol=0.0)
    assert res.mismatched == 0


def test_within_atol():
    res = compare_numeric([0.0], [1e-9], rtol=1e-5, atol=1e-8)
    assert res.mismatched == 0


def test_outside_tolerance():
    res = compare_numeric([1.0], [2.0], rtol=1e-5, atol=1e-8)
    assert res.mismatched == 1
    assert np.all(res.mismatch_mask)


def test_positive_negative_values():
    res = compare_numeric([1.0, -1.0], [1.0, -1.0])
    assert res.mismatched == 0


def test_positive_negative_mismatch():
    res = compare_numeric([1.0], [-1.0])
    assert res.mismatched == 1
    assert res.max_abs_error == pytest.approx(2.0, abs=1e-12)


def test_zero_reference_relative_error_inf():
    # expected zero, actual non-zero -> relative error should be inf
    res = compare_numeric([0.0], [5.0], rtol=1e-5, atol=1e-8)
    assert res.mismatched == 1
    assert res.max_rel_error == float("inf")


def test_very_small_values_within_atol():
    res = compare_numeric([1e-20], [2e-20], rtol=1e-5, atol=1e-8)
    # within atol -> no mismatch
    assert res.mismatched == 0


def test_nan_equal_nan():
    res = compare_numeric([np.nan], [np.nan])
    assert res.mismatched == 0


def test_nan_vs_number_mismatch():
    res = compare_numeric([np.nan], [1.0])
    assert res.mismatched == 1


def test_inf_matching():
    res = compare_numeric([np.inf], [np.inf])
    assert res.mismatched == 0


def test_neg_inf_matching():
    res = compare_numeric([-np.inf], [-np.inf])
    assert res.mismatched == 0


def test_inf_vs_finite_mismatch():
    res = compare_numeric([np.inf], [1e300])
    assert res.mismatched == 1


# ── Error statistics ──

def test_max_abs_error():
    res = compare_numeric([10.0, 1.0], [0.0, 1.5])
    assert res.mismatched == 2
    assert res.max_abs_error == pytest.approx(10.0, abs=1e-9)
    # max_abs at index 0
    assert res.max_abs_error_index == 0


def test_max_rel_error():
    # index0: ref 1.0 actual 2.0 rel=1.0 ; index1: ref 100.0 actual 200.0 rel=1.0
    # make one clearly larger relative error
    res = compare_numeric([1.0, 100.0], [1.001, 100.001], rtol=1e-9, atol=1e-12)
    assert res.mismatched == 2
    assert res.max_rel_error == pytest.approx(1e-3, rel=1e-6)
    assert res.max_rel_error_index == 0


def test_mean_abs_error():
    res = compare_numeric([2.0, 5.0], [3.0, 8.0])
    # abs errs: 1.0 and 3.0 -> mean = 2.0
    assert res.mean_abs_error == pytest.approx(2.0, abs=1e-9)


def test_rms_abs_error():
    import math
    res = compare_numeric([2.0, 5.0], [3.0, 8.0])
    # abs errs: 1.0 and 3.0 -> rms = sqrt((1+9)/2) = sqrt(5)
    assert res.rms_abs_error == pytest.approx(math.sqrt(5), abs=1e-9)


def test_mismatch_count():
    res = compare_numeric([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 1.0, 3.0])
    assert res.total == 4
    assert res.mismatched == 2
    assert res.mismatch_mask.tolist() == [False, True, False, True]


def test_stats_tracking_offsets():
    """max_*_error_index should map back to the flat index of the original input."""
    res = compare_numeric([1.0, 100.0, 2.0], [1.0, 101.0, 2.0])
    assert res.mismatched == 1
    assert res.max_abs_error_index == 1
    assert res.max_rel_error_index == 1


def test_collect_stats_false():
    res = compare_numeric([1.0, 2.0], [3.0, 4.0], collect_stats=False)
    assert res.mismatched == 2
    assert res.max_abs_error is None
    assert res.max_rel_error is None
    assert res.mean_abs_error == 0.0
    assert res.rms_abs_error == 0.0


def test_no_mismatch_collect_stats_true():
    res = compare_numeric([1.0, 2.0], [1.0, 2.0], collect_stats=True)
    assert res.mismatched == 0
    assert res.max_abs_error is None
    assert res.mean_abs_error == 0.0
    assert res.rms_abs_error == 0.0


# ── Data filter ──

def test_data_filter_keeps_only_passing_both():
    # filter > 1.0 ; cell 0: 0.5 fails in expected -> excluded
    # cell 1: 3.0 vs 3.1 both pass -> mismatch
    res = compare_numeric([0.5, 3.0], [9.9, 3.1], filter_func=parse_data_filter(">1.0"))
    assert res.total == 1
    assert res.mismatched == 1
    assert res.max_abs_error == pytest.approx(0.1, abs=1e-9)


def test_data_filter_abs_prefix():
    res = compare_numeric([-0.002], [0.002], filter_func=parse_data_filter("abs>0.001"))
    assert res.total == 1
    assert res.mismatched == 1


def test_data_filter_filters_all():
    res = compare_numeric([0.5], [9.9], filter_func=parse_data_filter(">1.0"))
    assert res.total == 0
    assert res.mismatched == 0


def test_parse_data_filter_none_for_empty():
    assert parse_data_filter(None) is None
    assert parse_data_filter("") is None


def test_parse_data_filter_invalid_returns_none():
    assert parse_data_filter("not-a-filter") is None


def test_parse_data_filter_operators():
    f = parse_data_filter(">=5")
    assert bool(f(np.asarray([6.0]))) is True
    assert bool(f(np.asarray([4.0]))) is False


# ── Multi-dimensional ndarray ──

def test_multidimensional_ndarray():
    a = np.array([[1.0, 2.0], [3.0, 4.0]])
    b = np.array([[1.0, 2.0], [3.0, 5.0]])
    res = compare_numeric(a, b)
    assert res.total == 4
    assert res.mismatched == 1
    assert res.mismatch_mask.tolist() == [False, False, False, True]
    assert res.max_abs_error == pytest.approx(1.0, abs=1e-9)


# ── Size mismatch ──

def test_size_mismatch_raises():
    with pytest.raises(ValueError):
        compare_numeric([1.0, 2.0], [1.0])
