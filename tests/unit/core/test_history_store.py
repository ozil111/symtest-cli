# -*- coding: utf-8 -*-
"""Tests for core/history_store.py"""

import json
import os
import tempfile

import pytest

from symtest.core.history_store import (
    SYMTEST_FILENAME,
    check_regression,
    ensure_symtest,
    load_history,
    reset_cases,
    save_history,
    update_case,
    update_case_memory,
)


class TestEnsureSymtest:
    def test_creates_file_if_missing(self, tmp_path):
        hist_dir = str(tmp_path / "hist")
        ensure_symtest(hist_dir)
        path = os.path.join(hist_dir, SYMTEST_FILENAME)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == 1
        assert data["cases"] == {}

    def test_does_not_overwrite_existing(self, tmp_path):
        hist_dir = str(tmp_path / "hist")
        ensure_symtest(hist_dir)
        # Write custom data
        path = os.path.join(hist_dir, SYMTEST_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "cases": {"a": {"avg_duration": 1, "last_duration": 1, "run_count": 1}}}, f)
        # Call again — should NOT overwrite
        ensure_symtest(hist_dir)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "a" in data["cases"]


class TestLoadSaveHistory:
    def test_load_auto_init(self, tmp_path):
        hist_dir = str(tmp_path / "hist")
        assert not os.path.exists(os.path.join(hist_dir, SYMTEST_FILENAME))
        data = load_history(hist_dir)
        assert data["cases"] == {}
        # File should now exist
        assert os.path.exists(os.path.join(hist_dir, SYMTEST_FILENAME))

    def test_roundtrip(self, tmp_path):
        hist_dir = str(tmp_path / "hist")
        history = {"version": 1, "cases": {"x": {"avg_duration": 5.0, "last_duration": 5.0, "run_count": 1}}}
        save_history(hist_dir, history)
        loaded = load_history(hist_dir)
        assert loaded == history

    def test_load_handles_missing_cases_key(self, tmp_path):
        hist_dir = str(tmp_path / "hist")
        os.makedirs(hist_dir, exist_ok=True)
        path = os.path.join(hist_dir, SYMTEST_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1}, f)
        data = load_history(hist_dir)
        assert data["cases"] == {}


class TestUpdateCase:
    def test_first_run(self):
        history = {"version": 1, "cases": {}}
        update_case(history, "case_a", 3.0)
        assert history["cases"]["case_a"]["avg_duration"] == 3.0
        assert history["cases"]["case_a"]["last_duration"] == 3.0
        assert history["cases"]["case_a"]["run_count"] == 1

    def test_cumulative_average(self):
        history = {"version": 1, "cases": {
            "case_a": {"avg_duration": 4.0, "last_duration": 4.0, "run_count": 2}
        }}
        # (4.0 * 2 + 7.0) / 3 = 5.0
        update_case(history, "case_a", 7.0)
        assert history["cases"]["case_a"]["avg_duration"] == pytest.approx(5.0)
        assert history["cases"]["case_a"]["last_duration"] == 7.0
        assert history["cases"]["case_a"]["run_count"] == 3

    def test_multiple_cases(self):
        history = {"version": 1, "cases": {}}
        update_case(history, "a", 1.0)
        update_case(history, "b", 10.0)
        assert len(history["cases"]) == 2
        assert history["cases"]["a"]["avg_duration"] == 1.0
        assert history["cases"]["b"]["avg_duration"] == 10.0


class TestCheckRegression:
    def test_no_history_returns_none(self):
        history = {"version": 1, "cases": {}}
        assert check_regression(history, "unknown", 5.0) is None

    def test_no_regression(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 10.0, "last_duration": 10.0, "run_count": 5}
        }}
        # 12.0 < 10.0 * 1.5 = 15.0
        assert check_regression(history, "a", 12.0) is None

    def test_regression_detected(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 10.0, "last_duration": 10.0, "run_count": 5}
        }}
        # 18.0 > 10.0 * 1.5 = 15.0
        result = check_regression(history, "a", 18.0)
        assert result is not None
        assert "a" in result
        assert "1.80x" in result

    def test_custom_threshold(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 10.0, "last_duration": 10.0, "run_count": 5}
        }}
        # 18.0 > 10.0 * 1.5, but NOT > 10.0 * 2.0
        assert check_regression(history, "a", 18.0, threshold=2.0) is None
        # 25.0 > 10.0 * 2.0
        assert check_regression(history, "a", 25.0, threshold=2.0) is not None

    def test_zero_avg_returns_none(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 0.0, "last_duration": 0.0, "run_count": 1}
        }}
        assert check_regression(history, "a", 5.0) is None

    def test_exact_threshold_not_triggered(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 10.0, "last_duration": 10.0, "run_count": 5}
        }}
        # 15.0 == 10.0 * 1.5, NOT strictly greater
        assert check_regression(history, "a", 15.0) is None


class TestUpdateCaseMemory:
    def test_first_measurement(self):
        history = {"version": 1, "cases": {}}
        update_case_memory(history, "case_a", 500, "windows_job_commit")
        rec = history["cases"]["case_a"]
        assert rec["last_peak_memory_bytes"] == 500
        assert rec["max_peak_memory_bytes"] == 500
        assert rec["peak_memory_count"] == 1
        assert rec["peak_memory_source"] == "windows_job_commit"

    def test_max_tracked_across_runs(self):
        history = {"version": 1, "cases": {}}
        update_case_memory(history, "a", 500)
        update_case_memory(history, "a", 300)
        update_case_memory(history, "a", 800)
        rec = history["cases"]["a"]
        assert rec["last_peak_memory_bytes"] == 800
        # 调度估算使用历史最大值：偶发高峰不被平均稀释
        assert rec["max_peak_memory_bytes"] == 800
        assert rec["peak_memory_count"] == 3

    def test_invalid_peak_ignored(self):
        history = {"version": 1, "cases": {}}
        update_case_memory(history, "a", None)
        update_case_memory(history, "a", 0)
        update_case_memory(history, "a", -100)
        assert history["cases"] == {}

    def test_merges_into_existing_duration_record(self):
        history = {"version": 1, "cases": {
            "a": {"avg_duration": 5.0, "last_duration": 5.0, "run_count": 2}
        }}
        update_case_memory(history, "a", 500, "windows_job_commit")
        rec = history["cases"]["a"]
        assert rec["avg_duration"] == 5.0  # 耗时字段不受影响
        assert rec["max_peak_memory_bytes"] == 500


class TestMemoryOnlyRecordCompat:
    """只有内存字段、没有耗时字段的记录（失败 case 先行记录峰值）。"""

    def _memory_only_history(self):
        return {"version": 1, "cases": {
            "a": {"last_peak_memory_bytes": 500,
                  "max_peak_memory_bytes": 500,
                  "peak_memory_count": 1,
                  "peak_memory_source": "windows_job_commit"},
        }}

    def test_update_case_tolerates_missing_duration_fields(self):
        history = self._memory_only_history()
        update_case(history, "a", 3.0)
        rec = history["cases"]["a"]
        assert rec["avg_duration"] == 3.0
        assert rec["run_count"] == 1
        assert rec["max_peak_memory_bytes"] == 500  # 内存字段保留

    def test_check_regression_tolerates_missing_duration(self):
        history = self._memory_only_history()
        assert check_regression(history, "a", 100.0) is None

    def test_reset_cases_removes_memory_only_record(self):
        history = self._memory_only_history()
        cleared = reset_cases(history, {"a"})
        assert cleared == 1
        assert history["cases"] == {}
