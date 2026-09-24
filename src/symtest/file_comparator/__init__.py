"""
File comparison module for symtest.

Public plugin contract (v2, three lanes):
- ``ComparatorBase``      — root contract: ``compare(ctx) -> ComparisonResult``
- ``CompareContext``      — invocation context (paths resolved by framework)
- ``FileComparator``      — file lane (read_content/compare_content two-file model)
- ``ExtractorComparator`` — data lane (extract channels, framework owns verdict)
- ``ChannelData`` / ``ChannelResult`` — channel payload / per-channel sub-result
- ``compare_numeric`` / ``NumericComparisonStats`` / ``parse_data_filter`` —
  shared numeric core, public API for data-lane plugins
"""

from .factory import ComparatorFactory
from .result import ComparisonResult, Difference, ChannelResult
from .base_comparator import ComparatorBase, CompareContext
from .file_comparator_base import FileComparator
from .extractor_comparator import ExtractorComparator, ChannelData
from .numeric_compare import (
    compare_numeric,
    NumericComparisonStats,
    parse_data_filter,
)

# Historical alias: BaseComparator now names the root contract class
# ComparatorBase.  (Breaking: the legacy two-file template moved to
# FileComparator; plugins overriding compare_files must migrate.)
BaseComparator = ComparatorBase

__all__ = [
    'ComparatorFactory',
    'ComparisonResult',
    'Difference',
    'ChannelResult',
    'ChannelData',
    'ComparatorBase',
    'BaseComparator',
    'CompareContext',
    'FileComparator',
    'ExtractorComparator',
    'compare_numeric',
    'NumericComparisonStats',
    'parse_data_filter',
]
