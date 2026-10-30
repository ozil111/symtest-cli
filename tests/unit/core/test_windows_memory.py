# -*- coding: utf-8 -*-
"""Tests for symtest.core.system_memory."""
import sys

import pytest

from symtest.core.system_memory import MemorySnapshot, read_memory_snapshot


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
class TestWindowsSnapshot:
    def test_snapshot_usable(self):
        snap = read_memory_snapshot()
        assert snap.usable
        assert snap.total_physical_bytes > 0
        assert snap.avail_physical_bytes > 0
        assert snap.total_physical_bytes >= snap.avail_physical_bytes
        # Commit fields: margin non-negative, limit covers margin
        assert snap.avail_commit_bytes >= 0
        assert snap.commit_limit_bytes is not None
        assert snap.commit_limit_bytes >= snap.avail_commit_bytes

    def test_snapshot_frozen_dataclass(self):
        snap = read_memory_snapshot()
        with pytest.raises(Exception):
            snap.avail_physical_bytes = 0


class TestSnapshotFallbacks:
    def test_non_windows_returns_unusable(self, monkeypatch):
        monkeypatch.setattr("os.name", "posix")
        snap = read_memory_snapshot()
        assert not snap.usable
        assert snap.avail_physical_bytes is None

    def test_api_failure_returns_unusable(self, monkeypatch):
        import symtest.core.system_memory as mod

        def _boom():
            raise OSError("api failure")

        monkeypatch.setattr(mod, "_read_windows_snapshot", _boom)
        snap = read_memory_snapshot()
        assert not snap.usable
        assert snap.avail_physical_bytes is None
        # 不得以 0 伪装成功
        assert snap.total_physical_bytes is None

    def test_usable_property_requires_avail(self):
        assert MemorySnapshot().usable is False
        assert MemorySnapshot(
            total_physical_bytes=100, avail_physical_bytes=1,
        ).usable is True
