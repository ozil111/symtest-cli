"""Unit tests for workspace plugin discovery in ComparatorFactory."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

from symtest.file_comparator.factory import ComparatorFactory


# Minimal autonomous-lane plugin body: implements the v2 root contract
# (compare(ctx) -> ComparisonResult).  The legacy read_content/compare_content
# stubs are no longer required — that is exactly what the v2 breaking change
# removed.
_PLUGIN_BODY = """
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult

class {cls}(BaseComparator):
    def compare(self, ctx):
        result = ComparisonResult(
            file1=str(ctx.baseline or ""),
            file2=str(ctx.actual or ""),
        )
        result.identical = True
        return result
"""


def _write_plugin(tmpd: str, filename: str, cls: str) -> Path:
    plugin_file = Path(tmpd) / filename
    plugin_file.write_text(_PLUGIN_BODY.format(cls=cls), encoding="utf-8")
    return plugin_file


class TestWorkspacePluginDiscovery:
    """Test set_plugin_dirs, _load_from_dirs, and env-var input discovery."""

    def teardown_method(self):
        ComparatorFactory.reset()

    def test_set_plugin_dirs_and_discovery(self):
        """A *_comparator.py in a plugin dir is auto-registered."""
        with tempfile.TemporaryDirectory() as tmpd:
            _write_plugin(tmpd, "demo_comparator.py", "DemoComparator")
            ComparatorFactory.set_plugin_dirs([tmpd])
            assert "demo" in ComparatorFactory.get_available_comparators()

    def test_env_var_discovery(self):
        """Plugin dirs in CLITEST_PLUGIN_DIRS env var are discovered."""
        with tempfile.TemporaryDirectory() as tmpd:
            _write_plugin(tmpd, "envtest_comparator.py", "EnvtestComparator")
            ComparatorFactory.reset()
            os.environ["CLITEST_PLUGIN_DIRS"] = tmpd
            try:
                assert "envtest" in ComparatorFactory.get_available_comparators()
            finally:
                del os.environ["CLITEST_PLUGIN_DIRS"]

    def test_set_plugin_dirs_before_init(self):
        """Calling set_plugin_dirs before first create_comparator still works."""
        with tempfile.TemporaryDirectory() as tmpd:
            _write_plugin(tmpd, "early_comparator.py", "EarlyComparator")
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
        """reset() clears comparators, initialized flag and plugin_dirs;
        it never touches os.environ (CLITEST_PLUGIN_DIRS is user-owned)."""
        with tempfile.TemporaryDirectory() as tmpd:
            _write_plugin(tmpd, "reset_test_comparator.py", "ResetTestComparator")
            ComparatorFactory.set_plugin_dirs([tmpd])
            assert "resettest" in ComparatorFactory.get_available_comparators()
            ComparatorFactory.reset()
            assert "resettest" not in ComparatorFactory.get_available_comparators()

    def test_framework_never_writes_environ(self):
        """set_plugin_dirs / discovery must not mutate os.environ.

        Process workers receive plugin dirs via the pool initializer —
        the framework has no business writing to the process environment.
        """
        with tempfile.TemporaryDirectory() as tmpd:
            _write_plugin(tmpd, "noenv_comparator.py", "NoenvComparator")
            environ_before = dict(os.environ)
            ComparatorFactory.set_plugin_dirs([tmpd])
            ComparatorFactory.get_available_comparators()
            ComparatorFactory.reset()
            assert os.environ == environ_before
            assert "CLITEST_PLUGIN_DIRS" not in os.environ
