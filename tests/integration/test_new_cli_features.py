"""Integration tests for new CLI flags: --last-failed, --update-baseline, validate --output-format."""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from symtest.core.last_run_store import (
    save_last_run,
    load_last_run,
    get_last_failed_names,
)
from symtest.core.base_runner import BaseRunner


class TestLastFailedFiltering:
    """Integration test for --last-failed filtering in BaseRunner."""

    def test_last_failed_filters_to_previous_failures(self):
        """When last_run.json has failures, --last-failed filters them."""
        with tempfile.TemporaryDirectory() as d:
            # Setup last_run with mixed results
            save_last_run(d, {
                "case_a": {"status": "passed"},
                "case_b": {"status": "failed"},
                "case_c": {"status": "timeout"},
                "case_d": {"status": "passed"},
            })
            failed_names = get_last_failed_names(d)
            assert set(failed_names) == {"case_b", "case_c"}

    def test_last_failed_empty_when_no_history(self):
        with tempfile.TemporaryDirectory() as d:
            assert get_last_failed_names(d) == []

    def test_last_failed_empty_when_all_pass(self):
        with tempfile.TemporaryDirectory() as d:
            save_last_run(d, {
                "a": {"status": "passed"},
                "b": {"status": "passed"},
            })
            assert get_last_failed_names(d) == []


class TestUpdateBaselineWorkflow:
    """Integration test for --update-baseline flag."""

    def test_update_baseline_overwrites_file(self):
        with tempfile.TemporaryDirectory() as d:
            actual = os.path.join(d, "result.csv")
            baseline = os.path.join(d, "baseline.csv")
            with open(actual, "w") as f:
                f.write("new,data,100\n")
            with open(baseline, "w") as f:
                f.write("old,data,50\n")

            from symtest.core.assertions import Assertions
            result = Assertions.compare_files(actual, baseline, file_type="csv", update_baseline=True)

            assert result["identical"] is True
            assert result["baseline_updated"] is True

            # Verify baseline was overwritten
            with open(baseline, "r") as f:
                assert "new,data,100" in f.read()


class TestValidateJsonOutput:
    """Integration test for validate --output-format json."""

    def test_validate_produces_machine_readable_output(self):
        """validate_config returns a dict with 'valid', 'errors', 'summary' keys."""
        with tempfile.TemporaryDirectory() as d:
            config_path = os.path.join(d, "config.json")
            config = {
                "test_cases": [
                    {
                        "name": "valid_case",
                        "command": "echo",
                        "args": ["hello"],
                        "expected": {"return_code": 0},
                    }
                ]
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            from symtest.config.config_io import validate_config
            report = validate_config(config_path)

            assert "valid" in report
            assert "errors" in report
            assert "summary" in report
            assert report["valid"] is True
            assert report["errors"] == []
            assert report["summary"]["cases"] == 1

    def test_validate_reports_missing_fields(self):
        with tempfile.TemporaryDirectory() as d:
            config_path = os.path.join(d, "bad_config.json")
            config = {
                "test_cases": [
                    {"name": "bad_case"}  # missing command, args, expected
                ]
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            from symtest.config.config_io import validate_config
            report = validate_config(config_path)

            assert report["valid"] is False
            assert len(report["errors"]) > 0
            # JSON serializable
            dumped = json.dumps(report, indent=2)
            parsed = json.loads(dumped)
            assert parsed["valid"] is False
