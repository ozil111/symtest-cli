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
    # Stats cover ALL cells: zero errors everywhere.
    assert res.max_abs_error == pytest.approx(0.0, abs=1e-12)
    assert res.max_rel_error == pytest.approx(0.0, abs=1e-12)


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


def test_collect_stats_false_with_filter_excluded_not_mismatch():
    """Regression: filtered-out positions must not be flagged as mismatches."""
    # filter >1.0: cell0 (0.5 vs 9.9) excluded; cell1 (3.0 vs 3.0) kept and equal
    res = compare_numeric([0.5, 3.0], [9.9, 3.0],
                          filter_func=parse_data_filter(">1.0"),
                          collect_stats=False)
    assert res.total == 1
    assert res.mismatched == 0
    assert res.mismatch_mask.tolist() == [False, False]


def test_collect_stats_false_with_filter_keeps_real_mismatch():
    # filter >1.0: cell0 excluded; cell1 (3.0 vs 3.5) kept and mismatched
    res = compare_numeric([0.5, 3.0], [9.9, 3.5],
                          filter_func=parse_data_filter(">1.0"),
                          collect_stats=False)
    assert res.total == 1
    assert res.mismatched == 1
    assert res.mismatch_mask.tolist() == [False, True]


def test_collect_stats_false_all_filtered_out():
    res = compare_numeric([0.5], [9.9],
                          filter_func=parse_data_filter(">1.0"),
                          collect_stats=False)
    assert res.total == 0
    assert res.mismatched == 0
    assert res.mismatch_mask.tolist() == [False]


def test_no_mismatch_collect_stats_true():
    res = compare_numeric([1.0, 2.0], [1.0, 2.0], collect_stats=True)
    assert res.mismatched == 0
    # Stats cover ALL cells: zero errors everywhere, denominators = total.
    assert res.max_abs_error == pytest.approx(0.0, abs=1e-12)
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


# ── Integer exact lane ──

def test_large_integers_do_not_collapse_onto_float64():
    """Regression: 2**53 vs 2**53+1 are distinct under zero tolerance."""
    res = compare_numeric([2**53], [2**53 + 1], rtol=0.0, atol=0.0)
    assert res.mismatched == 1
    assert res.max_abs_error == pytest.approx(1.0)


def test_large_integers_within_rtol_pass_on_int_lane():
    # diff 2 / ref 2**53 ~ 2.2e-16 < rtol 1e-15
    res = compare_numeric([2**53], [2**53 + 2], rtol=1e-15, atol=0.0)
    assert res.mismatched == 0


def test_small_integer_difference_respects_atol():
    res = compare_numeric([1], [2], rtol=0.0, atol=1.0)
    assert res.mismatched == 0
    res = compare_numeric([1], [2], rtol=0.0, atol=0.5)
    assert res.mismatched == 1


def test_integer_stats_use_exact_differences():
    res = compare_numeric([2**53, 10], [2**53 + 1, 10], rtol=0.0, atol=0.0)
    assert res.mismatched == 1
    assert res.max_abs_error == pytest.approx(1.0)
    assert res.max_abs_error_index == 0
    # mean over ALL compared cells: (1 + 0) / 2
    assert res.mean_abs_error == pytest.approx(0.5)


def test_mixed_int_and_float_inputs_fall_back_to_float_lane():
    # One side int, one side float: still compares equal (float lane promotion)
    res = compare_numeric([10], [10.0])
    assert res.mismatched == 0


@pytest.mark.parametrize("collect_stats", [False, True])
@pytest.mark.parametrize("expected,actual", [
    ([2**53, 1.0], [2**53 + 1, 1.0]),
    ([2**53, 2**62], [2**53 + 1, 2**62]),
    ([2**62], [2**62 + 1]),
    ([2**63 - 2], [2**63 - 1]),
    ([-2**63], [-2**63 + 1]),
    (np.array([2**64 - 2], dtype=np.uint64),
     np.array([2**64 - 1], dtype=np.uint64)),
    (np.array([-2**63], dtype=np.int64),
     np.array([2**64 - 1], dtype=np.uint64)),
    ([2**53 + 1], [float(2**53)]),
    ([float(2**53)], [2**53 + 1]),
])
def test_integer_precision_independent_of_neighbors_and_dtype(expected, actual, collect_stats):
    res = compare_numeric(expected, actual, rtol=0.0, atol=0.0,
                          collect_stats=collect_stats)
    assert res.mismatched == 1
    assert res.mismatch_mask[0]
    if collect_stats:
        assert res.max_abs_error > 0


def test_integer_extreme_difference_does_not_overflow():
    res = compare_numeric([-2**63], [2**64 - 1], rtol=0, atol=0)
    assert res.max_abs_error == float(3 * 2**63 - 1)
    assert res.rms_abs_error == res.max_abs_error


def test_integer_boundary_tolerance_does_not_round_difference():
    # float(2**53 + 1) rounds down to the tolerance: verdict must use the int.
    res = compare_numeric([0], [2**53 + 1], rtol=0, atol=float(2**53))
    assert res.mismatched == 1


def test_integer_filter_preserves_mixed_values_and_minimum_int64():
    res = compare_numeric([-2**63, 2**53, 1.0],
                          [-2**63 + 1, 2**53 + 1, 2.0],
                          rtol=0, atol=0, filter_func=parse_data_filter("abs>1000"))
    assert res.total == 2
    assert res.mismatched == 2
    assert res.max_abs_error == 1


def test_object_input_is_not_modified_by_normalization():
    values = np.array([np.int64(2**53), "1.0"], dtype=object)
    res = compare_numeric(values, [2**53 + 1, 1.0], rtol=0, atol=0)
    assert res.mismatched == 1
    assert isinstance(values[0], np.int64)
    assert values[1] == "1.0"


def test_integer_lane_with_filter():
    res = compare_numeric([0, 2**53], [1, 2**53 + 1],
                          filter_func=parse_data_filter(">1000"),
                          rtol=0.0, atol=0.0)
    # cell 0 excluded by filter; cell 1 kept and mismatched
    assert res.total == 1
    assert res.mismatched == 1
    assert res.mismatch_mask.tolist() == [False, True]
