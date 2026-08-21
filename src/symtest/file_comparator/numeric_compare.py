#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file numeric_compare.py
@brief Shared numeric comparison core (compare stage of "cut + compare")
@author Xiaotong Wang
@date 2026
"""

import re
from dataclasses import dataclass

import numpy as np


@dataclass
class NumericComparisonStats:
    """
    @brief Lightweight numeric comparison statistics.
    @details Returned by compare_numeric() and consumed by file comparators
             (CsvComparator / H5Comparator) to build their own _error_stats dict.
             Holds no file-level semantics.
    """
    total: int
    mismatched: int
    mismatch_mask: "np.ndarray | None"
    max_abs_error: "float | None"
    max_abs_error_index: "int | None"
    max_rel_error: "float | None"
    max_rel_error_index: "int | None"
    mean_abs_error: float
    rms_abs_error: float
    sum_abs_error: float
    sum_sq_abs_error: float


def _as_float_array(values):
    """Coerce scalar / sequence / ndarray input into a float64 ndarray."""
    return np.asarray(values, dtype=np.float64).ravel()


def _symmetric_close(expected, actual, rtol, atol):
    """
    @brief Vectorized symmetric closeness (math.isclose formula):
             |a - b| <= max(rtol * max(|a|, |b|), atol)
    @note NaN == NaN is treated as equal (equal_nan=True semantics).
          +Inf == +Inf and -Inf == -Inf are treated as equal.
    """
    with np.errstate(invalid="ignore"):
        abs_err = np.abs(actual - expected)
    tol = np.maximum(rtol * np.maximum(np.abs(expected), np.abs(actual)), atol)
    # Tolerance test applies only to finite values (inf vs finite must not
    # accidentally pass because rtol * inf would make tol = inf).
    both_finite = np.isfinite(expected) & np.isfinite(actual)
    close = np.zeros_like(abs_err, dtype=bool)
    close[both_finite] = abs_err[both_finite] <= tol[both_finite]
    # equal_nan=True
    close |= np.isnan(expected) & np.isnan(actual)
    # equal_inf: same-sign infinities are equal
    close |= np.isinf(expected) & np.isinf(actual) & (
        np.signbit(expected) == np.signbit(actual)
    )
    return close, abs_err


def compare_numeric(expected, actual, rtol=1e-5, atol=1e-8,
                    filter_func=None, collect_stats=True):
    """
    @brief Compare two numeric datasets with symmetric tolerance + error stats.
    @param expected: NumPy-compatible numeric input (expected / reference values)
    @param actual: NumPy-compatible numeric input (actual / compared values)
    @param rtol float: Relative tolerance
    @param atol float: Absolute tolerance
    @param filter_func: Optional vectorized filter callable applied element-wise;
                        only positions where BOTH values satisfy the filter are compared.
    @param collect_stats bool: If False, skip error statistics (only closeness/mask).
    @return NumericComparisonStats
    """
    expected = _as_float_array(expected)
    actual = _as_float_array(actual)

    if expected.size != actual.size:
        raise ValueError(
            f"Expected and actual arrays must have the same size: "
            f"{expected.size} != {actual.size}"
        )

    # ── Data filter: keep positions where BOTH values pass ──
    if filter_func is not None:
        mask1 = np.asarray(filter_func(expected), dtype=bool)
        mask2 = np.asarray(filter_func(actual), dtype=bool)
        keep = mask1 & mask2
    else:
        keep = np.ones(expected.size, dtype=bool)

    total = int(np.sum(keep))

    if not collect_stats:
        # Closeness computed over the kept subset.
        close = np.zeros(expected.size, dtype=bool)
        if total > 0:
            c, _ = _symmetric_close(expected[keep], actual[keep], rtol, atol)
            close[keep] = c
        return NumericComparisonStats(
            total=total,
            mismatched=int(np.sum(~close)),
            mismatch_mask=~close,
            max_abs_error=None,
            max_abs_error_index=None,
            max_rel_error=None,
            max_rel_error_index=None,
            mean_abs_error=0.0,
            rms_abs_error=0.0,
            sum_abs_error=0.0,
            sum_sq_abs_error=0.0,
        )

    if total == 0:
        return NumericComparisonStats(
            total=0,
            mismatched=0,
            mismatch_mask=np.zeros(expected.size, dtype=bool),
            max_abs_error=None,
            max_abs_error_index=None,
            max_rel_error=None,
            max_rel_error_index=None,
            mean_abs_error=0.0,
            rms_abs_error=0.0,
            sum_abs_error=0.0,
            sum_sq_abs_error=0.0,
        )

    exp_keep = expected[keep]
    act_keep = actual[keep]

    close, abs_err = _symmetric_close(exp_keep, act_keep, rtol, atol)
    mismatch = ~close
    mismatched = int(np.sum(mismatch))

    # Flat indices (within the original array) of kept positions.
    keep_idx = np.flatnonzero(keep)

    if mismatched == 0:
        return NumericComparisonStats(
            total=total,
            mismatched=0,
            mismatch_mask=np.zeros(expected.size, dtype=bool),
            max_abs_error=None,
            max_abs_error_index=None,
            max_rel_error=None,
            max_rel_error_index=None,
            mean_abs_error=0.0,
            rms_abs_error=0.0,
            sum_abs_error=0.0,
            sum_sq_abs_error=0.0,
        )

    # ── Error statistics (over mismatched cells only) ──
    mism_abs_err = abs_err[mismatch]
    mism_expected = exp_keep[mismatch]

    sum_abs = float(np.sum(mism_abs_err))
    sum_sq = float(np.sum(mism_abs_err ** 2))

    max_abs_error = float(np.max(mism_abs_err))
    max_abs_keep_pos = int(np.argmax(mism_abs_err))
    max_abs_error_index = int(keep_idx[mismatch][max_abs_keep_pos])

    # Relative error: inf when reference value is zero but error is non-zero (CSV semantics).
    ref_abs = np.abs(mism_expected)
    rel_err = np.full(mism_abs_err.shape, np.inf)
    nonzero = ref_abs > 0
    with np.errstate(invalid="ignore"):
        rel_err[nonzero] = mism_abs_err[nonzero] / ref_abs[nonzero]

    max_rel_error = float(np.max(rel_err))
    max_rel_keep_pos = int(np.argmax(rel_err))
    max_rel_error_index = int(keep_idx[mismatch][max_rel_keep_pos])

    mean_abs_error = sum_abs / mismatched if mismatched > 0 else 0.0
    rms_abs_error = np.sqrt(sum_sq / mismatched) if mismatched > 0 else 0.0

    # Build full-length mismatch mask (True where values differ beyond tolerance).
    mismatch_mask = np.zeros(expected.size, dtype=bool)
    mismatch_mask[keep_idx[mismatch]] = True

    return NumericComparisonStats(
        total=total,
        mismatched=mismatched,
        mismatch_mask=mismatch_mask,
        max_abs_error=max_abs_error,
        max_abs_error_index=max_abs_error_index,
        max_rel_error=max_rel_error,
        max_rel_error_index=max_rel_error_index,
        mean_abs_error=mean_abs_error,
        rms_abs_error=float(rms_abs_error),
        sum_abs_error=sum_abs,
        sum_sq_abs_error=sum_sq,
    )


def parse_data_filter(filter_str, logger=None):
    """
    @brief Parse a data filter expression into a vectorized filter callable.
    @param filter_str str: e.g. '>1e-6', 'abs>0.1', '>=100', '==0', '<-10'
    @param logger: Optional logger for warnings (ignored for non-ndarray input).
    @return callable or None: Vectorized filter, or None when invalid/absent.
    """
    if not filter_str:
        return None

    def _warn(msg):
        if logger is not None:
            logger.warning(msg)

    try:
        match = re.match(
            r"^(abs)?([><]=?|==)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$",
            filter_str.replace(" ", ""),
        )
        if not match:
            _warn(f"Invalid data filter format: {filter_str}. Ignoring filter.")
            return None

        use_abs, op, value_str = match.groups()
        value = float(value_str)

        op_map = {
            ">": np.greater,
            ">=": np.greater_equal,
            "<": np.less,
            "<=": np.less_equal,
            "==": np.equal,
        }

        op_func = op_map[op]

        def filter_func(data):
            arr = np.asarray(data)
            if not np.issubdtype(arr.dtype, np.number):
                # For non-numeric types, do not filter.
                return np.ones_like(arr, dtype=bool)
            target = np.abs(arr) if use_abs else arr
            return op_func(target, value)

        return filter_func
    except Exception:
        _warn(f"Failed to parse data filter '{filter_str}'. Ignoring filter.")
        return None
