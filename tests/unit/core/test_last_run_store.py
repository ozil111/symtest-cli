"""Unit tests for last_run_store (--last-failed persistence)."""
import os
import tempfile

import pytest

from cli_test_framework.core.last_run_store import (
    load_last_run,
    save_last_run,
    update_last_run,
    get_last_failed_names,
    get_last_run_summary,
    LAST_RUN_DIR,
    LAST_RUN_FILENAME,
)


class TestLastRunStore:
    @pytest.fixture
    def workspace(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_load_empty_workspace(self, workspace):
        """Loading a workspace with no last_run.json returns empty dict."""
        data = load_last_run(workspace)
        assert data == {}

    def test_save_and_load(self, workspace):
        data_in = {"case_a": {"status": "passed"}, "case_b": {"status": "failed"}}
        save_last_run(workspace, data_in)
        data_out = load_last_run(workspace)
        assert data_out == data_in

    def test_file_path_location(self, workspace):
        save_last_run(workspace, {"x": {"status": "passed"}})
        expected_path = os.path.join(workspace, LAST_RUN_DIR, LAST_RUN_FILENAME)
        assert os.path.exists(expected_path)

    def test_update_last_run_overwrites_existing(self, workspace):
        # Setup initial state
        initial = {"case_a": {"status": "failed"}, "case_b": {"status": "failed"}}
        save_last_run(workspace, initial)

        # Run: case_a now passes, case_b still fails
        update_last_run(workspace, [
            {"name": "case_a", "status": "passed"},
            {"name": "case_b", "status": "failed"},
        ])
        data = load_last_run(workspace)
        assert data["case_a"]["status"] == "passed"
        assert data["case_b"]["status"] == "failed"

    def test_update_last_run_preserves_unrun_cases(self, workspace):
        # Setup initial state with 3 cases
        initial = {
            "case_a": {"status": "failed"},
            "case_b": {"status": "failed"},
            "case_c": {"status": "passed"},
        }
        save_last_run(workspace, initial)

        # Run only case_a (e.g. via -t filter)
        update_last_run(workspace, [{"name": "case_a", "status": "passed"}])
        data = load_last_run(workspace)

        # case_a updated to passed
        assert data["case_a"]["status"] == "passed"
        # case_b and case_c preserved from previous run
        assert data["case_b"]["status"] == "failed"
        assert data["case_c"]["status"] == "passed"

    def test_get_last_failed_names(self, workspace):
        save_last_run(workspace, {
            "case_a": {"status": "passed"},
            "case_b": {"status": "failed"},
            "case_c": {"status": "timeout"},
            "case_d": {"status": "passed"},
        })
        failed = get_last_failed_names(workspace)
        assert set(failed) == {"case_b", "case_c"}

    def test_get_last_failed_names_empty(self, workspace):
        """No last_run.json → empty list."""
        assert get_last_failed_names(workspace) == []

    def test_get_last_failed_names_all_pass(self, workspace):
        save_last_run(workspace, {
            "case_a": {"status": "passed"},
            "case_b": {"status": "passed"},
        })
        assert get_last_failed_names(workspace) == []

    def test_get_last_run_summary(self, workspace):
        save_last_run(workspace, {
            "a": {"status": "passed"},
            "b": {"status": "failed"},
            "c": {"status": "passed"},
            "d": {"status": "timeout"},
        })
        s = get_last_run_summary(workspace)
        assert s["total"] == 4
        assert s["passed"] == 2

    def test_get_last_run_summary_empty(self, workspace):
        s = get_last_run_summary(workspace)
        assert s == {"total": 0, "passed": 0, "failed": 0, "xfailed": 0, "xpassed": 0, "timeout": 0}

    # ── xfail semantics ──

    def test_get_last_failed_names_excludes_xfailed(self, workspace):
        """xfailed cases should NOT be in --last-failed (they're expected failures)."""
        save_last_run(workspace, {
            "case_a": {"status": "xfailed"},
            "case_b": {"status": "failed"},
            "case_c": {"status": "xpassed"},
        })
        failed = get_last_failed_names(workspace)
        assert set(failed) == {"case_b", "case_c"}

    def test_get_last_failed_names_includes_xpassed(self, workspace):
        """xpassed IS a failure, should be in --last-failed."""
        save_last_run(workspace, {
            "case_a": {"status": "xpassed"},
            "case_b": {"status": "xfailed"},
        })
        failed = get_last_failed_names(workspace)
        assert set(failed) == {"case_a"}

    def test_get_last_run_summary_xfail_counts(self, workspace):
        save_last_run(workspace, {
            "a": {"status": "xfailed"},
            "b": {"status": "xfailed"},
            "c": {"status": "xpassed"},
            "d": {"status": "failed"},
        })
        s = get_last_run_summary(workspace)
        assert s["total"] == 4
        assert s["passed"] == 0
        assert s["xfailed"] == 2
        assert s["xpassed"] == 1
        assert s["failed"] >= 2  # xpassed(1) + failed(1) = 2
