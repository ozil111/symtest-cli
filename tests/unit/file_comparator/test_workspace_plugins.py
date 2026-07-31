"""Unit tests for workspace plugin discovery in ComparatorFactory."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

from symtest.file_comparator.factory import ComparatorFactory


class TestWorkspacePluginDiscovery:
    """Test set_plugin_dirs, _load_from_dirs, and env var cross-process."""

    def teardown_method(self):
        ComparatorFactory.reset()

    def test_set_plugin_dirs_and_discovery(self):
        """A *_comparator.py in a plugin dir is auto-registered."""
        with tempfile.TemporaryDirectory() as tmpd:
            plugin_file = Path(tmpd) / "demo_comparator.py"
            plugin_file.write_text("""
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult

class DemoComparator(BaseComparator):
    def read_content(self, fp, **kw):
        return None
    def compare_content(self, c1, c2):
        return True, [], False
""", encoding="utf-8")

            ComparatorFactory.set_plugin_dirs([tmpd])
            assert "demo" in ComparatorFactory.get_available_comparators()

    def test_env_var_discovery(self):
        """Plugin dirs in CLITEST_PLUGIN_DIRS env var are discovered."""
        with tempfile.TemporaryDirectory() as tmpd:
            plugin_file = Path(tmpd) / "envtest_comparator.py"
            plugin_file.write_text("""
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult

class EnvtestComparator(BaseComparator):
    def read_content(self, fp, **kw):
        return None
    def compare_content(self, c1, c2):
        return True, [], False
""", encoding="utf-8")

            ComparatorFactory.reset()
            os.environ["CLITEST_PLUGIN_DIRS"] = tmpd
            try:
                assert "envtest" in ComparatorFactory.get_available_comparators()
            finally:
                del os.environ["CLITEST_PLUGIN_DIRS"]

    def test_set_plugin_dirs_before_init(self):
        """Calling set_plugin_dirs before first create_comparator still works."""
        with tempfile.TemporaryDirectory() as tmpd:
            plugin_file = Path(tmpd) / "early_comparator.py"
            plugin_file.write_text("""
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult

class EarlyComparator(BaseComparator):
    def read_content(self, fp, **kw):
        return None
    def compare_content(self, c1, c2):
        return True, [], False
""", encoding="utf-8")

            ComparatorFactory.reset()
            ComparatorFactory.set_plugin_dirs([tmpd])
            # set_plugin_dirs before create_comparator should NOT trigger load yet
            # (_initialized is False at this point)
            available = ComparatorFactory.get_available_comparators()
            assert "early" in available

    def test_empty_dirs_no_error(self):
        """Empty or non-existent plugin dirs should not raise."""
        ComparatorFactory.set_plugin_dirs(["/nonexistent/path_xyz"])
        ComparatorFactory.get_available_comparators()  # must not raise

    def test_reset_clears_everything(self):
        """reset() clears comparators, initialized flag, plugin_dirs, env var."""
        with tempfile.TemporaryDirectory() as tmpd:
            plugin_file = Path(tmpd) / "reset_test_comparator.py"
            plugin_file.write_text("""
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult

class ResetTestComparator(BaseComparator):
    def read_content(self, fp, **kw):
        return None
    def compare_content(self, c1, c2):
        return True, [], False
""", encoding="utf-8")

            ComparatorFactory.set_plugin_dirs([tmpd])
            assert "resettest" in ComparatorFactory.get_available_comparators()
            ComparatorFactory.reset()
            assert "resettest" not in ComparatorFactory.get_available_comparators()
            assert "CLITEST_PLUGIN_DIRS" not in os.environ
