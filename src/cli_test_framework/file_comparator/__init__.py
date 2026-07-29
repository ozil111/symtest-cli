"""
File comparison module for cli-test-framework.
This module provides functionality for comparing different types of files.
"""

from .factory import ComparatorFactory
from .result import ComparisonResult
from .base_comparator import BaseComparator

__all__ = ['ComparatorFactory', 'ComparisonResult', 'BaseComparator']