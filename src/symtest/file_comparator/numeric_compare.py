#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file numeric_compare.py
@brief Shared numeric comparison core (compare stage of "cut + compare")
@author Xiaotong Wang
@date 2026
"""

import re
import math
from fractions import Fraction
from numbers import Integral, Real
from dataclasses import dataclass

import numpy as np


def validate_allow_nonfinite(value, *, name="allow_nonfinite"):
    """Reject truthy non-booleans rather than silently enabling the policy."""
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool, got {type(value).__name__}")
    return value


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
    # Mismatched positions that involve a non-finite value (NaN / +-Inf);
    # >0 only in default reject mode. Lets lane-level difference messages
    # distinguish non-finite rejections from ordinary tolerance failures.
    nonfinite_mismatched: int = 0


def _as_compare_array(values):
    """Preserve integers before NumPy can promote a mixed sequence to float.

    Object arrays hold Python integers, including the full int64/uint64 range.
    Pure floating inputs retain the vectorized float64 path. Precision already
    lost in a caller-created floating array cannot be recovered here.
    """
    if isinstance(values, np.ndarray) and values.dtype.kind in "fc":
        return np.asarray(values, dtype=np.float64).ravel()
    arr = np.array(values, dtype=object, copy=True).ravel()
    has_integer = False
    for i, value in enumerate(arr):
        if isinstance(value, Integral):
            arr[i] = int(value)
            has_integer = True
        else:
            arr[i] = float(value)
    return arr if has_integer else arr.astype(np.float64)


def _finite(values):
    if values.dtype != object:
        return np.isfinite(values)
    return np.fromiter((isinstance(v, int) or math.isfinite(v) for v in values),
                       dtype=bool, count=values.size)


def _symmetric_close(expected, actual, rtol, atol, allow_nonfinite=False):
    """
    @brief Vectorized symmetric closeness (math.isclose formula):
             |a - b| <= max(rtol * max(|a|, |b|), atol)
    @note Default (allow_nonfinite=False): any NaN or +-Inf on either side
          is a mismatch — non-finite output usually means a solver failure
          and must not silently pass. NaN == NaN and +Inf == +Inf are only
          treated as equal when allow_nonfinite=True.
    """
    if expected.dtype == object or actual.dtype == object:
        close = np.zeros(expected.size, dtype=bool)
        abs_err = np.empty(expected.size, dtype=np.float64)
        for i, (a, b) in enumerate(zip(expected, actual)):
            # Convert NumPy integer scalars too: fixed-width subtraction can
            # overflow, including when signed and unsigned arrays are mixed.
            a = int(a) if isinstance(a, Integral) else float(a)
            b = int(b) if isinstance(b, Integral) else float(b)
            if ((isinstance(a, int) or math.isfinite(a)) and
                    (isinstance(b, int) or math.isfinite(b))):
                if isinstance(a, int) and isinstance(b, int):
                    error = abs(b - a)
                elif isinstance(a, int) or isinstance(b, int):
                    # Preserve the exact represented float when paired with an
                    # integer; int-float subtraction would round the integer.
                    error = abs(Fraction(b) - Fraction(a))
                else:
                    error = abs(b - a)
                tolerance = max(rtol * max(abs(a), abs(b)), atol)
                close[i] = error <= tolerance
                abs_err[i] = float(error)
            elif allow_nonfinite:
                close[i] = (a == b) or (math.isnan(a) and math.isnan(b))
                abs_err[i] = np.nan if close[i] else np.inf
            else:
                close[i] = False
                abs_err[i] = np.inf
        return close, abs_err

    with np.errstate(invalid="ignore"):
        abs_err = np.abs(actual - expected)
    tol = np.maximum(rtol * np.maximum(np.abs(expected), np.abs(actual)), atol)
    # Tolerance test applies only to finite values (inf vs finite must not
    # accidentally pass because rtol * inf would make tol = inf).
    both_finite = np.isfinite(expected) & np.isfinite(actual)
    close = np.zeros_like(abs_err, dtype=bool)
    close[both_finite] = abs_err[both_finite] <= tol[both_finite]
    if allow_nonfinite:
        # equal_nan=True
        close |= np.isnan(expected) & np.isnan(actual)
        # equal_inf: same-sign infinities are equal
        close |= np.isinf(expected) & np.isinf(actual) & (
            np.signbit(expected) == np.signbit(actual)
        )
    return close, abs_err


def compare_numeric(expected, actual, rtol=1e-5, atol=1e-8,
                    filter_func=None, collect_stats=True, allow_nonfinite=False):
    """
    @brief Compare two numeric datasets with symmetric tolerance + error stats.
    @param expected: NumPy-compatible numeric input (expected / reference values)
    @param actual: NumPy-compatible numeric input (actual / compared values)
    @param rtol float: Relative tolerance
    @param atol float: Absolute tolerance
    @param filter_func: Optional vectorized filter callable applied element-wise;
                        only positions where BOTH values satisfy the filter are compared.
    @param collect_stats bool: If False, skip error statistics (only closeness/mask).
    @param allow_nonfinite bool: If True, NaN == NaN and same-sign +Inf == +Inf
                        count as equal (legacy semantics). Default False: any
                        non-finite value on either side is a mismatch — solver
                        outputs containing NaN/Inf usually indicate a failure.
                        Non-finite positions are forced into the comparison and
                        can never be silently excluded by the data filter.
    @return NumericComparisonStats
    @note Integers are preserved per element, including mixed sequences and
          full int64/uint64 ranges. Verdict uses unrounded differences;
          reported magnitude statistics use float64.
    """
    allow_nonfinite = validate_allow_nonfinite(allow_nonfinite)
    expected = _as_compare_array(expected)
    actual = _as_compare_array(actual)

    if expected.size != actual.size:
        raise ValueError(
            f"Expected and actual arrays must have the same size: "
            f"{expected.size} != {actual.size}"
        )

    # ── Data filter: keep positions where BOTH values pass ──
    # Non-finite rejection overrides the filter: a NaN/Inf cell must never be
    # silently dropped by a data filter (e.g. '>1e-6' excludes NaN); it is
    # forced into the comparison and rejected there.
    nonfinite = (~_finite(expected)) | (~_finite(actual))
    if filter_func is not None:
        mask1 = np.asarray(filter_func(expected), dtype=bool)
        mask2 = np.asarray(filter_func(actual), dtype=bool)
        keep = mask1 & mask2
    else:
        keep = np.ones(expected.size, dtype=bool)
    if not allow_nonfinite:
        keep = keep | nonfinite

    total = int(np.sum(keep))

    if not collect_stats:
        # Closeness computed over the kept subset.
        close = np.zeros(expected.size, dtype=bool)
        if total > 0:
            c, _ = _symmetric_close(expected[keep], actual[keep], rtol, atol,
                                    allow_nonfinite=allow_nonfinite)
            close[keep] = c
        # Only kept positions can be mismatches; excluded cells were never compared.
        mismatch_mask = keep & ~close
        return NumericComparisonStats(
            total=total,
            mismatched=int(np.sum(mismatch_mask)),
            mismatch_mask=mismatch_mask,
            max_abs_error=None,
            max_abs_error_index=None,
            max_rel_error=None,
            max_rel_error_index=None,
            mean_abs_error=0.0,
            rms_abs_error=0.0,
            sum_abs_error=0.0,
            sum_sq_abs_error=0.0,
            nonfinite_mismatched=int(np.sum(mismatch_mask & nonfinite)),
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

    close, abs_err = _symmetric_close(exp_keep, act_keep, rtol, atol,
                                      allow_nonfinite=allow_nonfinite)
    mismatch = ~close
    mismatched = int(np.sum(mismatch))

    # Flat indices (within the original array) of kept positions.
    keep_idx = np.flatnonzero(keep)

    # ── Error statistics (over ALL kept numeric cells, matching ones included) ──
    # Non-finite cells (NaN / inf) are excluded from magnitude statistics:
    # their error magnitude is undefined. In allow_nonfinite mode identical
    # NaN / inf pairs contribute zero error by definition; in default reject
    # mode they are counted in total/mismatched but have no magnitude.
    finite = _finite(exp_keep) & _finite(act_keep)
    stat_idx = keep_idx[finite]
    # Magnitude statistics use float64 after exact verdict calculation.
    stat_abs_err = abs_err[finite].astype(np.float64)
    stat_expected = np.asarray(exp_keep[finite], dtype=np.float64)
    n_stat = int(np.sum(finite))

    if n_stat > 0:
        sum_abs = float(np.sum(stat_abs_err))
        sum_sq = float(np.sum(stat_abs_err ** 2))

        max_abs_error = float(np.max(stat_abs_err))
        max_abs_stat_pos = int(np.argmax(stat_abs_err))
        max_abs_error_index = int(stat_idx[max_abs_stat_pos])

        # Relative error: inf when reference value is zero but error is non-zero;
        # zero when the reference is zero and the values agree exactly.
        ref_abs = np.abs(stat_expected)
        rel_err = np.full(stat_abs_err.shape, np.inf)
        nonzero = ref_abs > 0
        with np.errstate(invalid="ignore"):
            rel_err[nonzero] = stat_abs_err[nonzero] / ref_abs[nonzero]
        rel_err[~nonzero & (stat_abs_err == 0)] = 0.0

        max_rel_error = float(np.max(rel_err))
        max_rel_stat_pos = int(np.argmax(rel_err))
        max_rel_error_index = int(stat_idx[max_rel_stat_pos])

        mean_abs_error = sum_abs / total
        rms_abs_error = np.sqrt(sum_sq / total)
    else:
        # No finite cells: magnitudes are undefined.
        sum_abs = 0.0
        sum_sq = 0.0
        max_abs_error = None
        max_abs_error_index = None
        max_rel_error = None
        max_rel_error_index = None
        mean_abs_error = 0.0
        rms_abs_error = 0.0

    # Build full-length mismatch mask (True where values differ beyond tolerance).
    mismatch_mask = np.zeros(expected.size, dtype=bool)
    mismatch_mask[keep_idx[mismatch]] = True

    # Non-finite rejections among the mismatches (default reject mode only:
    # in allow_nonfinite mode identical non-finite pairs are not mismatches).
    nonfinite_keep = (~_finite(exp_keep)) | (~_finite(act_keep))
    nonfinite_mismatched = int(np.sum(mismatch & nonfinite_keep)) if not allow_nonfinite else 0

    return NumericComparisonStats(
        total=total,
        mismatched=mismatched,
        mismatch_mask=mismatch_mask,
        max_abs_error=max_abs_error,
        max_abs_error_index=max_abs_error_index,
        max_rel_error=max_rel_error,
        max_rel_error_index=max_rel_error_index,
        mean_abs_error=float(mean_abs_error),
        rms_abs_error=float(rms_abs_error),
        sum_abs_error=sum_abs,
        sum_sq_abs_error=sum_sq,
        nonfinite_mismatched=nonfinite_mismatched,
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
        try:
            value = int(value_str)
        except ValueError:
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
            if arr.dtype == object:
                if not all(isinstance(v, Real) for v in arr.flat):
                    return np.ones_like(arr, dtype=bool)
            elif not np.issubdtype(arr.dtype, np.number):
                # For non-numeric types, do not filter.
                return np.ones_like(arr, dtype=bool)
            if np.issubdtype(arr.dtype, np.integer):
                # abs(int64.min) overflows in a fixed-width array.
                arr = arr.astype(object)
            target = np.abs(arr) if use_abs else arr
            return op_func(target, value)

        return filter_func
    except Exception:
        _warn(f"Failed to parse data filter '{filter_str}'. Ignoring filter.")
        return None
