#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file extractor_comparator.py
@brief Data-lane comparator: plugin extracts channels, framework owns verdict
@author Xiaotong Wang
@date 2026

Data-lane plugins (positioned like the built-in csv/h5 comparators) implement
:meth:`ExtractorComparator.extract` to turn arbitrary upstream inputs (files,
solver output, cross-file aggregates) into per-channel ``(expected, actual)``
numeric arrays.  The framework then runs the shared numeric core
(:func:`~symtest.file_comparator.numeric_compare.compare_numeric`) per channel
and aggregates the verdict — plugins never decide pass/fail themselves, so the
tolerance semantics stay predictable for AI/report consumers.

Config mapping (compareSpec passthrough)::

    {
      "type": "my_extractor",
      "inputs": {"ref": "baseline.csv"},          # free-form, plugin-defined
      "channels": {"S33": {"atol": 600.0}},       # per-channel overrides
      "default_channel": {"rtol": 1e-5, "atol": 1e-8}
    }

Custom error metrics (user requirement: unique analysis schemes) are supported
via ``ChannelData.extra_stats`` — a free-form dict merged into the channel
statistics.  Verdicts, however, always come from the framework tolerances;
plugins that must own the verdict belong in the autonomous lane instead.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np

from .base_comparator import ComparatorBase, CompareContext
from .numeric_compare import compare_numeric, parse_data_filter
from .result import ChannelResult, ComparisonResult, Difference


@dataclass
class ChannelData:
    """
    @brief One channel of extracted numeric data.
    @param expected: NumPy-compatible expected/reference values (baseline side)
    @param actual: NumPy-compatible actual values (command-output side)
    @param extra_stats: Optional plugin-defined metrics merged into the
           channel's ``stats`` dict (unique error-analysis schemes).
    """
    expected: Any
    actual: Any
    extra_stats: Optional[Dict[str, Any]] = None


class ExtractorComparator(ComparatorBase):
    """
    @brief Abstract base for data-lane (channel) comparators.
    @details Subclasses implement :meth:`extract`; this class owns per-channel
             tolerance routing, numeric comparison and result aggregation.
    """

    def __init__(self, channels=None, default_channel=None,
                 rtol: float = 1e-5, atol: float = 1e-8):
        """
        @param channels dict|None: ``{channel_name: {"rtol":…, "atol":…,
               "data_filter":…}}`` overrides; unset keys fall back to
               ``default_channel``.
        @param default_channel dict|None: Tolerance spec applied to channels
               not listed in ``channels``.
        @param rtol float: Final fallback relative tolerance (default 1e-5).
        @param atol float: Final fallback absolute tolerance (default 1e-8).
        @note Parameters are strict: unknown/misspelled config keys fail loudly.
        """
        super().__init__()
        self.channel_specs: Dict[str, Dict[str, Any]] = dict(channels or {})
        self.default_spec: Dict[str, Any] = dict(default_channel or {})
        self.rtol = rtol
        self.atol = atol

    @abstractmethod
    def extract(self, ctx: CompareContext) -> Dict[str, ChannelData]:
        """
        @brief Extract per-channel numeric data from the upstream inputs.
        @param ctx CompareContext: Invocation context (paths resolved).
        @return dict: ``{channel_name: ChannelData}``
        @raises Exception: Extraction failures propagate; the framework turns
                them into ``ComparisonResult.error``.
        """

    # ------------------------------------------------------------------
    # Framework-owned comparison pipeline
    # ------------------------------------------------------------------
    def compare(self, ctx: CompareContext) -> ComparisonResult:  # type: ignore[override]
        result = ComparisonResult(
            file1=ctx.baseline,
            file2=ctx.actual,
        )
        try:
            channels_data = self.extract(ctx)
            if not channels_data:
                raise ValueError(
                    f"{self.__class__.__name__}.extract() returned no channels"
                )
        except Exception as exc:
            self.logger.error("Channel extraction failed: %s", exc)
            result.error = f"Channel extraction failed: {exc}"
            result.identical = False
            result.command_output = getattr(self, "_last_command_output", None)
            return result

        channel_results = []
        aggregated_differences = []
        error_stats: Dict[str, Any] = {}

        for name, data in channels_data.items():
            spec = self._spec_for(name)
            rtol = spec.get("rtol", self.rtol)
            atol = spec.get("atol", self.atol)
            filter_func = parse_data_filter(spec.get("data_filter"), logger=self.logger)

            try:
                res = compare_numeric(
                    data.expected, data.actual,
                    rtol=rtol, atol=atol,
                    filter_func=filter_func, collect_stats=True,
                )
            except Exception as exc:
                # e.g. size mismatch between expected/actual arrays
                self.logger.error("Channel '%s' comparison failed: %s", name, exc)
                diff = Difference(
                    position=f"channel {name}",
                    expected="comparable numeric arrays",
                    actual=str(exc),
                    diff_type="channel_error",
                )
                channel_results.append(ChannelResult(
                    name=name, passed=False, rtol=rtol, atol=atol,
                    stats={"error": str(exc)}, differences=[diff],
                ))
                aggregated_differences.append(diff)
                continue

            # Framework-owned canonical stats and plugin-owned extra_stats
            # are kept in SEPARATE namespaces: a plugin must never be able to
            # overwrite canonical metrics such as max_abs_error.
            stats: Dict[str, Any] = {
                "total": res.total,
                "mismatched": res.mismatched,
                "max_abs_error": res.max_abs_error,
                "max_rel_error": res.max_rel_error,
                "mean_abs_error": res.mean_abs_error,
                "rms_abs_error": res.rms_abs_error,
            }

            passed = res.mismatched == 0
            differences = []
            if not passed:
                diff = Difference(
                    position=f"channel {name}",
                    expected=f"within rtol={rtol:g}, atol={atol:g}",
                    actual=(
                        f"{res.mismatched}/{res.total} values mismatched "
                        f"(max_abs={self._fmt(res.max_abs_error)}, "
                        f"max_rel={self._fmt(res.max_rel_error)})"
                    ),
                    diff_type="channel_mismatch",
                )
                differences.append(diff)
                aggregated_differences.append(diff)

            channel_results.append(ChannelResult(
                name=name, passed=passed, rtol=rtol, atol=atol,
                stats=stats, extra_stats=data.extra_stats,
                differences=differences,
            ))
            error_stats[name] = stats

        result.channels = channel_results
        result.identical = all(ch.passed for ch in channel_results)
        result.differences = aggregated_differences
        result.error_stats = error_stats or None
        result.command_output = getattr(self, "_last_command_output", None)
        return result

    def _spec_for(self, name: str) -> Dict[str, Any]:
        """Resolve the tolerance spec for a channel (declared -> default)."""
        return dict(self.default_spec) | dict(self.channel_specs.get(name, {}))

    @staticmethod
    def _fmt(value) -> str:
        """Format an optional float for difference messages."""
        if value is None:
            return "n/a"
        if isinstance(value, float) and (np.isinf(value) or np.isnan(value)):
            return str(value)
        return f"{value:.6g}"
