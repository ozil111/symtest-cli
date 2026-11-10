# -*- coding: utf-8 -*-
"""Tests for the Linux system-memory snapshot (/proc + cgroup v2 limits).

解析与钳制逻辑用假数据全覆盖（平台无关）；真实 /proc smoke 仅在
Linux 上运行。
"""
import sys

import pytest

import symtest.core.system_memory as mod
from symtest.core.system_memory import read_memory_snapshot

KB = 1024


def _write_meminfo(path, total_kb, avail_kb=None):
    lines = [f"MemTotal:       {total_kb} kB"]
    if avail_kb is not None:
        lines.append(f"MemAvailable:   {avail_kb} kB")
    lines.append("MemFree:         1 kB")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_group(root, rel, max_content=None, current_bytes=None):
    """在假 cgroup 树中建组；max_content 为 "max" 或字节数。"""
    group = root / rel if rel else root
    group.mkdir(parents=True, exist_ok=True)
    if max_content is not None:
        (group / "memory.max").write_text(f"{max_content}\n", encoding="utf-8")
    if current_bytes is not None:
        (group / "memory.current").write_text(f"{current_bytes}\n",
                                              encoding="utf-8")


def _linux_snapshot(tmp_path, total_kb, avail_kb, rel="", groups=()):
    """构造假 meminfo + 假 cgroup 树后读取 Linux 快照。"""
    meminfo = tmp_path / "meminfo"
    _write_meminfo(meminfo, total_kb, avail_kb)
    root = tmp_path / "cgroup2"
    root.mkdir()
    for g in groups:
        _make_group(root, g["rel"], g.get("max"), g.get("current"))
    import unittest.mock as mock

    with mock.patch.object(mod, "_MEMINFO_PATH", meminfo), \
            mock.patch.object(mod, "_CGROUP_ROOT", root), \
            mock.patch.object(mod, "_own_cgroup_relpath", lambda: rel):
        return mod._read_linux_snapshot()


class TestParseMeminfo:
    def test_parses_kb_values(self):
        text = ("MemTotal:       160043936 kB\n"
                "MemAvailable:    8536808 kB\n"
                "Buffers:              64 kB\n")
        values = mod._parse_meminfo(text)
        assert values["MemTotal"] == 160043936
        assert values["MemAvailable"] == 8536808
        assert values["Buffers"] == 64

    def test_ignores_non_numeric_and_garbage_lines(self):
        text = ("MemTotal: 1024 kB\n:weird:\n"
                "Slab: not-a-number\nHugePages_Total:  0\n")
        values = mod._parse_meminfo(text)
        assert values["MemTotal"] == 1024
        assert "Slab" not in values
        assert values["HugePages_Total"] == 0


class TestSnapshotWithoutCgroupLimit:
    def test_plain_snapshot_maps_single_budget(self, tmp_path):
        """无限额：余量 = MemAvailable，commit 字段映射为同一预算。"""
        snap = _linux_snapshot(tmp_path, 16000000, 9000000)
        assert snap.usable
        assert snap.total_physical_bytes == 16000000 * KB
        assert snap.avail_physical_bytes == 9000000 * KB
        assert snap.avail_commit_bytes == 9000000 * KB
        assert snap.commit_limit_bytes == 16000000 * KB

    def test_unlimited_max_values_are_skipped(self, tmp_path):
        """memory.max = "max"（无限额）的层不参与钳制。"""
        snap = _linux_snapshot(
            tmp_path, 16000000, 9000000, rel="a/b",
            groups=[
                {"rel": "a", "max": "max", "current": 100000 * KB},
                {"rel": "a/b", "max": "max", "current": 50000 * KB},
            ],
        )
        assert snap.avail_physical_bytes == 9000000 * KB
        assert snap.total_physical_bytes == 16000000 * KB

    def test_missing_memavailable_treated_as_zero(self, tmp_path):
        snap = _linux_snapshot(tmp_path, 1024, avail_kb=None)
        assert snap.usable
        assert snap.avail_physical_bytes == 0


class TestSnapshotWithCgroupLimit:
    def test_tightest_group_margin_clamps_available(self, tmp_path):
        """组余量小于 MemAvailable 时取最紧的组余量。"""
        snap = _linux_snapshot(
            tmp_path, 16000000, 9000000, rel="a/b",
            groups=[
                {"rel": "a", "max": 8000000 * KB, "current": 3000000 * KB},
                {"rel": "a/b", "max": 6000000 * KB, "current": 2000000 * KB},
            ],
        )
        # 最紧层：a/b 余 4000000 KiB（a 余 5000000 KiB，宿主机余 9000000 KiB）
        assert snap.avail_physical_bytes == 4000000 * KB
        assert snap.avail_commit_bytes == 4000000 * KB
        # 总量与"提交上限"均钳制到最小组限额
        assert snap.commit_limit_bytes == 6000000 * KB
        assert snap.total_physical_bytes == 6000000 * KB

    def test_host_available_smaller_than_group_margin(self, tmp_path):
        """宿主机余量更紧时（其他消费者占用）以 MemAvailable 为准。"""
        snap = _linux_snapshot(
            tmp_path, 16000000, 1000000, rel="a",
            groups=[{"rel": "a", "max": 8000000 * KB, "current": 1000000 * KB}],
        )
        assert snap.avail_physical_bytes == 1000000 * KB

    def test_missing_memory_current_treated_as_zero_usage(self, tmp_path):
        """组缺 memory.current：按 0 使用计算余量。"""
        snap = _linux_snapshot(
            tmp_path, 16000000, 9000000, rel="a",
            groups=[{"rel": "a", "max": 3000000 * KB, "current": None}],
        )
        assert snap.avail_physical_bytes == 3000000 * KB

    def test_unlimited_ancestor_limited_child(self, tmp_path):
        """祖先无限额、子组有限额：仍按子组钳制。"""
        snap = _linux_snapshot(
            tmp_path, 16000000, 9000000, rel="a/b",
            groups=[
                {"rel": "a", "max": None, "current": 100 * KB},
                {"rel": "a/b", "max": 2000000 * KB, "current": 500000 * KB},
            ],
        )
        assert snap.avail_physical_bytes == 1500000 * KB
        assert snap.total_physical_bytes == 2000000 * KB

    def test_over_limit_group_clamps_to_zero(self, tmp_path):
        snap = _linux_snapshot(
            tmp_path, 16000000, 9000000, rel="a",
            groups=[{"rel": "a", "max": 1000000 * KB, "current": 1200000 * KB}],
        )
        assert snap.avail_physical_bytes == 0
        assert snap.usable  # 快照只描述事实，判定交给调度层


class TestSnapshotFailures:
    def test_missing_memtotal_raises(self, tmp_path):
        import unittest.mock as mock

        meminfo = tmp_path / "meminfo"
        _write_meminfo(meminfo, 0)  # MemTotal 缺失
        meminfo.write_text("MemFree: 1 kB\n", encoding="utf-8")
        with mock.patch.object(mod, "_MEMINFO_PATH", meminfo), \
                mock.patch.object(mod, "_own_cgroup_relpath",
                                  lambda: None):
            with pytest.raises(ValueError):
                mod._read_linux_snapshot()

    def test_non_v2_cgroup_lines_not_recognized(self, tmp_path):
        import unittest.mock as mock

        proc = tmp_path / "self.cgroup"
        proc.write_text(
            "2:memory:/user.slice\n1:name=systemd:/init\n",
            encoding="utf-8",
        )
        with mock.patch.object(mod, "_SELF_CGROUP_PATH", proc):
            assert mod._own_cgroup_relpath() is None

    def test_v2_root_group_returns_empty_relpath(self, tmp_path):
        import unittest.mock as mock

        proc = tmp_path / "self.cgroup"
        proc.write_text("0::/\n", encoding="utf-8")
        with mock.patch.object(mod, "_SELF_CGROUP_PATH", proc):
            assert mod._own_cgroup_relpath() == ""

    def test_api_failure_returns_unusable_snapshot(self, monkeypatch):
        def _boom():
            raise OSError("read failure")

        monkeypatch.setattr(mod, "_read_linux_snapshot", _boom)
        monkeypatch.setattr("os.name", "posix")
        snap = read_memory_snapshot()
        assert not snap.usable
        assert snap.avail_physical_bytes is None
        assert snap.total_physical_bytes is None


@pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
class TestRealProcSmoke:
    def test_real_snapshot_usable(self):
        snap = read_memory_snapshot()
        assert snap.usable
        assert snap.total_physical_bytes > 0
        assert snap.avail_physical_bytes >= 0
        assert snap.total_physical_bytes >= snap.avail_physical_bytes
        # Linux 单一预算：commit 字段与物理余量/总量一一对应
        assert snap.avail_commit_bytes == snap.avail_physical_bytes
        assert snap.commit_limit_bytes == snap.total_physical_bytes
