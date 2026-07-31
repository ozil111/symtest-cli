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
    save_history,
    update_case,
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
