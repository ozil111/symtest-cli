#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file base_comparator.py
@brief Root comparator contract: ``compare(ctx) -> ComparisonResult``
@author Xiaotong Wang
@date 2025

Plugin contract v2 (three lanes, breaking change vs. the legacy two-file
``BaseComparator``):

- :class:`~symtest.file_comparator.file_comparator_base.FileComparator`
  — **file lane**: two-file comparison; implements ``read_content`` /
  ``compare_content`` (text/json/csv/xml/h5/binary).
- :class:`~symtest.file_comparator.extractor_comparator.ExtractorComparator`
  — **data lane**: plugin extracts ``{channel: ChannelData}``; verdict is
  owned by the framework via per-channel numeric tolerance.
- direct subclasses — **autonomous lane**: the plugin owns the verdict and
  returns a fully populated ``ComparisonResult`` (``script`` comparator,
  analysis-style plugins such as ``hourglass_tangent``).

All lanes share the same invocation convention: the framework builds a
:class:`CompareContext` and calls :meth:`ComparatorBase.compare`.  Path-like
constructor parameters listed in ``path_params`` are resolved relative to the
workspace by the framework *before* the comparator is constructed — plugins
must not resolve paths against ``os.getcwd()`` themselves.

**Configuration invariant (single source of truth)**: comparator
configuration lives ONLY in constructor-captured instance state; it is
normalized/resolved by the framework before construction.
:class:`CompareContext` carries invocation-level context, never a second
mutable copy of comparator configuration.

**Strict configuration**: comparator constructors declare their parameters
explicitly; unknown/misspelled parameters fail loudly at construction
(factory raises a ``TypeError`` identifying the comparator type and its
supported parameters).  A comparator may opt into free-form configuration by
declaring its own ``**params`` catch-all — silence is always an explicit
design choice of the plugin, never a framework default.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, Optional

from .result import ComparisonResult


@dataclass
class CompareContext:
    """
    @brief Invocation context handed to every comparator's ``compare()``.
    @details Carries *invocation-level* context only.  Comparator
             configuration (script paths, tolerances, thresholds, ...) is
             owned by the comparator's constructor state — resolved and
             validated before construction.  A configuration value must have
             exactly one authoritative source.

    @param workspace str|None: Workspace root; the framework already resolved
           ``actual``/``baseline`` and ``path_params``-declared constructor
           parameters against it before construction.
    @param actual str|None: Path produced by the test command (``None`` for
           comparators without a two-file input — never faked with "").
    @param baseline str|None: Golden/reference path (``None`` when absent).
    @param params dict: Invocation-level parameters for the file lane
           (``start_line``/``end_line``/``start_column``/``end_column``,
           already converted to 0-based).  Deliberately does NOT duplicate
           comparator configuration.
    @param error_analysis bool: Whether streaming error statistics were
           requested (``--error-analysis``).
    """
    workspace: Optional[str] = None
    actual: Optional[str] = None
    baseline: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    error_analysis: bool = False


class ComparatorBase(ABC):
    """
    @brief Root abstract class for all comparators (all three lanes).
    @details Deliberately minimal: only members that genuinely apply to every
             lane live here.  File-specific concerns (encoding, chunk size,
             window ranges) belong to :class:`FileComparator` and below.

             The only contract is :meth:`compare`.  Subclasses declare
             ``path_params`` so the framework can resolve workspace-relative
             path arguments *before construction*; plugins never resolve
             paths themselves.
    """

    #: Constructor parameter names that hold filesystem paths.  The framework
    #: resolves each of them relative to the workspace (when not absolute)
    #: before invoking the constructor.  ``actual``/``baseline`` are always
    #: resolved and need not be listed here.
    path_params: tuple = ()

    #: Explicit comparator type name override (factory registration).
    #: ``None`` falls back to the class-name convention (trailing
    #: ``Comparator`` suffix stripped, lowercased).
    comparator_type: Optional[str] = None

    def __init__(self):
        """Initialize shared infrastructure (per-class logger only)."""
        self.logger = logging.getLogger(
            f"file_comparator.{type(self).__name__}"
        )

    @abstractmethod
    def compare(self, ctx: CompareContext) -> ComparisonResult:
        """
        @brief Run the comparison and return a fully populated result.
        @param ctx CompareContext: Invocation context (paths already resolved).
        @return ComparisonResult: Result with ``identical``/``differences`` and
                optionally ``error``/``error_stats``/``channels``/
                ``command_output`` populated.  ``file1``/``file2`` are ``None``
                when the comparison has no two-file input.
        """


# Historical import-path alias: plugins written against the old API used
# ``from symtest.file_comparator.base_comparator import BaseComparator``.
# The name now refers to the same root contract; the *interface* change
# (read_content/compare_content → compare, strict constructor parameters)
# is the intentional breaking part.
BaseComparator = ComparatorBase
