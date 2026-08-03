"""Unit tests for ValidationError and structured assertion data."""
import os
import tempfile

import pytest

from symtest.core.assertions import (
    Assertions,
    ValidationError,
    _build_diff_summary,
)
from symtest.core.execution import validate_result
from symtest.file_comparator.result import Difference


# ---------------------------------------------------------------------------
# _build_diff_summary
# ---------------------------------------------------------------------------

class TestBuildDiffSummary:
    def test_empty_differences(self):
        class FakeResult:
            differences = []

        summary = _build_diff_summary(FakeResult())
        assert summary["total_differences"] == 0
        assert summary["max_rel_error"] is None
        assert summary["max_abs_error"] is None

    def test_no_differences_list(self):
        class FakeResult:
            differences = None

        summary = _build_diff_summary(FakeResult())
        assert summary["total_differences"] == 0

    def test_numeric_differences_extract_errors(self):
        class FakeResult:
            differences = [
                Difference(position="row 1, col 1", expected="100", actual="110", diff_type="cell_mismatch"),
                Difference(position="row 5, col 3", expected="5.0", actual="5.5", diff_type="cell_mismatch"),
            ]

        summary = _build_diff_summary(FakeResult())
        assert summary["total_differences"] == 2
        # row 1: abs_err=10, rel_err=0.1
        # row 5: abs_err=0.5, rel_err=0.1
        # max_abs = 10, max_rel = 0.1
        assert summary["max_abs_error"] == pytest.approx(10.0)
        assert summary["max_rel_error"] == pytest.approx(0.1)
        assert summary["max_abs_error_at"] == "row 1, col 1"

    def test_non_numeric_differences_ignored(self):
        class FakeResult:
            differences = [
                Difference(position="line 3", expected="hello", actual="world", diff_type="content"),
            ]

        summary = _build_diff_summary(FakeResult())
        assert summary["total_differences"] == 1
        assert summary["max_rel_error"] is None
        assert summary["max_abs_error"] is None


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class TestValidationError:
    def test_is_assertion_error(self):
        """ValidationError is a subclass of AssertionError for backward compat."""
        err = ValidationError("test")
        assert isinstance(err, AssertionError)

    def test_carries_failure_kind(self):
        err = ValidationError("test", failure_kind="file_compare")
        assert err.failure_kind == "file_compare"

    def test_carries_compare_failures(self):
        cf = [{"actual": "a.txt", "baseline": "b.txt"}]
        err = ValidationError("test", compare_failures=cf)
        assert err.compare_failures == cf

    def test_carries_baseline_updated(self):
        bu = ["baseline/out.csv"]
        err = ValidationError("test", baseline_updated=bu)
        assert err.baseline_updated == bu

    def test_empty_defaults(self):
        err = ValidationError()
        assert err.failure_kind == ""
        assert err.compare_failures == []
        assert err.baseline_updated == []


# ---------------------------------------------------------------------------
# Assertions.compare_files structured response
# ---------------------------------------------------------------------------

class TestCompareFilesStructuredResponse:
    def test_identical_returns_structured_dict(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("same\n")
            with open(b, "w") as f:
                f.write("same\n")
            result = Assertions.compare_files(a, b, file_type="text")
            assert isinstance(result, dict)
            assert result["identical"] is True
            assert result["error"] is None
            assert result["actual"] == a
            assert result["baseline"] == b
            assert "diff_summary" in result
            assert "differences" in result

    def test_different_raises_validation_error(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("content_a\n")
            with open(b, "w") as f:
                f.write("content_b\n")
            with pytest.raises(ValidationError) as exc:
                Assertions.compare_files(a, b, file_type="text")
            assert exc.value.failure_kind == "file_compare"
            assert len(exc.value.compare_failures) >= 1

    def test_compare_failures_contain_diff_summary(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("A\n")
            with open(b, "w") as f:
                f.write("B\n")
            with pytest.raises(ValidationError) as exc:
                Assertions.compare_files(a, b, file_type="text")
            cf = exc.value.compare_failures[0]
            assert "diff_summary" in cf
            assert "differences" in cf

    def test_update_baseline_copies_file(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "actual.txt")
            b = os.path.join(d, "baseline.txt")
            with open(a, "w") as f:
                f.write("new_content\n")
            with open(b, "w") as f:
                f.write("old_content\n")
            result = Assertions.compare_files(a, b, file_type="text", update_baseline=True)
            assert result["identical"] is True
            assert result["baseline_updated"] is True
            # Verify baseline was overwritten
            with open(b, "r") as f:
                assert f.read() == "new_content\n"

    def test_update_baseline_when_already_identical(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("same\n")
            with open(b, "w") as f:
                f.write("same\n")
            result = Assertions.compare_files(a, b, file_type="text", update_baseline=True)
            assert result["identical"] is True
            assert result["baseline_updated"] is False


# ---------------------------------------------------------------------------
# validate_result collection mode
# ---------------------------------------------------------------------------

class TestValidateResultCollectionMode:
    def _mini_result(self, **kw):
        return {
            "name": kw.get("name", "test"),
            "status": kw.get("status", "failed"),
            "message": "",
            "command": "cmd",
            "output": kw.get("output", ""),
            "return_code": kw.get("return_code", 0),
            "duration": 0.0,
        }

    def test_collects_all_failures(self):
        """validate_result should collect all failures, not fail-fast."""
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("X\n")
            with open(b, "w") as f:
                f.write("Y\n")
            with pytest.raises(ValidationError) as exc:
                validate_result(
                    {
                        "return_code": 0,
                        "output_contains": ["missing_string"],
                        "compare_files": [
                            {"actual": a, "baseline": b, "type": "text"}
                        ],
                    },
                    self._mini_result(output="hello", return_code=1),
                    workspace=d,
                )
            err = exc.value
            # Should report both return_code AND output_contains AND file_compare failures
            msg = str(err)
            assert "return code" in msg.lower()
            assert "contain" in msg.lower()
            assert "File comparison failed" in msg

    def test_first_failure_sets_failure_kind(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("content\n")
            with open(b, "w") as f:
                f.write("content\n")
            with pytest.raises(ValidationError) as exc:
                validate_result(
                    {
                        "return_code": 0,
                        "output_contains": ["nonexistent"],
                        "compare_files": [
                            {"actual": a, "baseline": b, "type": "text"}
                        ],
                    },
                    self._mini_result(output="hello", return_code=0),
                    workspace=d,
                )
            assert exc.value.failure_kind == "output_contains"

    def test_compare_files_as_first_failure(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.txt")
            b = os.path.join(d, "b.txt")
            with open(a, "w") as f:
                f.write("X\n")
            with open(b, "w") as f:
                f.write("Y\n")
            with pytest.raises(ValidationError) as exc:
                validate_result(
                    {"compare_files": [{"actual": a, "baseline": b, "type": "text"}]},
                    self._mini_result(return_code=0),
                    workspace=d,
                )
            assert exc.value.failure_kind == "file_compare"
            assert len(exc.value.compare_failures) > 0
