"""Unit tests for the compare_files assertion and supporting helpers."""

import os
import tempfile

import pytest

from cli_test_framework.core.assertions import Assertions, _detect_file_type
from cli_test_framework.core.execution import validate_result, _dispatch_file_compare
from cli_test_framework.core.assertions import Assertions as AS  # alias for dispatch tests


# ---------------------------------------------------------------------------
# _detect_file_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, expected",
    [
        ("out.h5", "h5"),
        ("output.hdf5", "h5"),
        ("data.hdf", "h5"),
        ("report.json", "json"),
        ("table.csv", "csv"),
        ("data.tsv", "csv"),
        ("config.xml", "xml"),
        ("page.html", "xml"),
        ("page.htm", "xml"),
        ("log.txt", "text"),
        ("server.log", "text"),
        ("run.out", "text"),
        ("script.py", "text"),
    ],
)
def test_detect_file_type_known_extensions(path, expected):
    assert _detect_file_type(path) == expected


def test_detect_file_type_case_insensitive():
    assert _detect_file_type("OUT.H5") == "h5"
    assert _detect_file_type("Report.JSON") == "json"


def test_detect_file_type_unknown_extension():
    assert _detect_file_type("data.bdf") == "binary"
    assert _detect_file_type("mesh.inp") == "binary"
    assert _detect_file_type("nofile") == "binary"


# ---------------------------------------------------------------------------
# Assertions.compare_files – identical files
# ---------------------------------------------------------------------------

def test_compare_files_identical_text():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "hello\nworld\n")
        result = Assertions.compare_files(a, b, file_type="text")
        assert result["identical"] is True


def test_compare_files_identical_auto_detect():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "same\n")
        result = Assertions.compare_files(a, b)  # auto from .txt
        assert result["identical"] is True


# ---------------------------------------------------------------------------
# Assertions.compare_files – different files
# ---------------------------------------------------------------------------

def test_compare_files_different_raises():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "X\n", "Y\n")
        with pytest.raises(AssertionError, match="File comparison failed"):
            Assertions.compare_files(a, b, file_type="text")


def test_compare_files_different_message_contains_details():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "expected\n", "actual\n")
        with pytest.raises(AssertionError) as exc:
            Assertions.compare_files(a, b, file_type="text")
        msg = str(exc.value)
        assert a in msg or os.path.basename(a) in msg
        assert "expected" in msg or "actual" in msg


# ---------------------------------------------------------------------------
# Assertions.compare_files – missing / error
# ---------------------------------------------------------------------------

def test_compare_files_missing_actual():
    with tempfile.TemporaryDirectory() as d:
        b = os.path.join(d, "baseline.txt")
        with open(b, "w") as f:
            f.write("x\n")
        with pytest.raises(AssertionError, match="File comparison error"):
            Assertions.compare_files(
                os.path.join(d, "nonexistent.txt"), b, file_type="text"
            )


# ---------------------------------------------------------------------------
# Assertions.compare_files – workspace path resolution
# ---------------------------------------------------------------------------

def test_compare_files_resolves_relative_paths():
    with tempfile.TemporaryDirectory() as d:
        _write_two(d, "actual.txt", "baseline.txt", "same\n")
        # relative paths
        result = Assertions.compare_files(
            "actual.txt", "baseline.txt", workspace=d, file_type="text"
        )
        assert result["identical"] is True


def test_compare_files_does_not_override_absolute_paths():
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "a.txt")
        b = os.path.join(d, "b.txt")
        with open(a, "w") as f:
            f.write("same\n")
        with open(b, "w") as f:
            f.write("same\n")
        # workspace is passed but paths are already absolute
        result = Assertions.compare_files(a, b, workspace="/nonexistent", file_type="text")
        assert result["identical"] is True


# ---------------------------------------------------------------------------
# Assertions.compare_files – comparator kwargs passthrough
# ---------------------------------------------------------------------------

def test_compare_files_passes_kwargs_to_comparator():
    """rtol/atol are forwarded to the H5 comparator (should not error)."""
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "same\n")
        # rtol / atol are H5-specific; TextComparator ignores unknown kwargs
        result = Assertions.compare_files(a, b, file_type="text", rtol=1e-5, atol=1e-8)
        assert result["identical"]


# ---------------------------------------------------------------------------
# validate_result – compare_files branch
# ---------------------------------------------------------------------------

def _mini_result(status="failed", output="", return_code=0, **kw):
    """Minimal TestResultData."""
    return {
        "name": kw.get("name", "test"),
        "status": status,
        "message": "",
        "command": "cmd",
        "output": output,
        "return_code": return_code,
        "duration": 0.0,
    }


def test_validate_result_compare_files_passes():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "out.txt", "ref.txt", "content\n")
        result = validate_result(
            {"compare_files": [{"actual": "out.txt", "baseline": "ref.txt", "type": "text"}]},
            _mini_result(),
            workspace=d,
        )
        # no exception → pass; returns per-assertion detail
        assert result == [
            {
                "assertion": "compare_files",
                "passed": True,
                "compare_failures": [],
                "baseline_updated": [],
                "message": "",
            }
        ]


def test_validate_result_compare_files_fails():
    with tempfile.TemporaryDirectory() as d:
        _write_two(d, "out.txt", "ref.txt", "A\n", "B\n")
        with pytest.raises(AssertionError, match="File comparison failed"):
            validate_result(
                {"compare_files": [{"actual": "out.txt", "baseline": "ref.txt", "type": "text"}]},
                _mini_result(),
                workspace=d,
            )


def test_validate_result_multiple_compare_files_specs():
    with tempfile.TemporaryDirectory() as d:
        _write_two(d, "a1.txt", "b1.txt", "x\n")
        _write_two(d, "a2.txt", "b2.txt", "y\n")
        # Both pass
        validate_result(
            {
                "compare_files": [
                    {"actual": "a1.txt", "baseline": "b1.txt", "type": "text"},
                    {"actual": "a2.txt", "baseline": "b2.txt", "type": "text"},
                ]
            },
            _mini_result(),
            workspace=d,
        )


def test_validate_result_compare_files_fails_on_second():
    with tempfile.TemporaryDirectory() as d:
        _write_two(d, "a1.txt", "b1.txt", "x\n")
        _write_two(d, "a2.txt", "b2.txt", "X\n", "Y\n")
        with pytest.raises(AssertionError):
            validate_result(
                {
                    "compare_files": [
                        {"actual": "a1.txt", "baseline": "b1.txt", "type": "text"},
                        {"actual": "a2.txt", "baseline": "b2.txt", "type": "text"},
                    ]
                },
                _mini_result(),
                workspace=d,
            )


# ---------------------------------------------------------------------------
# validate_result – backward compatibility
# ---------------------------------------------------------------------------

def test_validate_result_no_compare_files_still_works():
    """Old-style expected dict without compare_files must pass unchanged."""
    result = validate_result(
        {"return_code": 0, "output_contains": ["hello"]},
        _mini_result(output="hello world", return_code=0),
    )
    assert result == [
        {"assertion": "return_code", "passed": True},
        {"assertion": "output_contains", "passed": True, "text": "hello"},
    ]


def test_validate_result_compare_files_with_existing_assertions():
    """compare_files can coexist with return_code and output_contains."""
    with tempfile.TemporaryDirectory() as d:
        _write_two(d, "out.txt", "ref.txt", "content\n")
        validate_result(
            {
                "return_code": 0,
                "output_contains": ["done"],
                "compare_files": [
                    {"actual": "out.txt", "baseline": "ref.txt", "type": "text"}
                ],
            },
            _mini_result(output="processing done", return_code=0),
            workspace=d,
        )


# ---------------------------------------------------------------------------
# _dispatch_file_compare
# ---------------------------------------------------------------------------

def test_dispatch_extracts_fields_and_forwards_kwargs(monkeypatch):
    """Verify that _dispatch_file_compare correctly separates known keys from
    extra kwargs and calls Assertions.compare_files."""
    calls = []

    def fake_compare_files(_self, actual_path, baseline_path, file_type, workspace, **kwargs):
        calls.append((actual_path, baseline_path, file_type, workspace, kwargs))
        return {"identical": True, "baseline_updated": False}

    monkeypatch.setattr(
        "cli_test_framework.core.execution.Assertions.compare_files",
        fake_compare_files,
    )
    _dispatch_file_compare(
        {
            "actual": "out.h5",
            "baseline": "ref.h5",
            "type": "h5",
            "rtol": 1e-5,
            "atol": 1e-8,
            "tables": ["/GRID"],
            "data_filter": ">0",
        },
        workspace="/ws",
        assertions=AS(),
    )
    assert len(calls) == 1
    actual_path, baseline_path, file_type, workspace, kwargs = calls[0]
    assert actual_path == "out.h5"
    assert baseline_path == "ref.h5"
    assert file_type == "h5"
    assert workspace == "/ws"
    assert kwargs == {"rtol": 1e-5, "atol": 1e-8, "tables": ["/GRID"], "data_filter": ">0", "update_baseline": False}


def test_dispatch_omits_type_when_absent(monkeypatch):
    calls = []

    def fake_compare_files(_self, actual_path, baseline_path, file_type, workspace=None, **kwargs):
        calls.append((actual_path, baseline_path, file_type))
        return {"identical": True, "baseline_updated": False}

    monkeypatch.setattr(
        "cli_test_framework.core.execution.Assertions.compare_files",
        fake_compare_files,
    )
    _dispatch_file_compare(
        {"actual": "a.csv", "baseline": "b.csv"},
        workspace=None,
        assertions=AS(),
    )
    assert calls[0][2] is None  # file_type


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_two(tmpdir, name_a, name_b, content_a, content_b=None):
    """Create two files in *tmpdir*, return their absolute paths."""
    if content_b is None:
        content_b = content_a
    pa = os.path.join(tmpdir, name_a)
    pb = os.path.join(tmpdir, name_b)
    with open(pa, "w") as f:
        f.write(content_a)
    with open(pb, "w") as f:
        f.write(content_b)
    return pa, pb


# ---------------------------------------------------------------------------
# Assertions.compare_files – start_line / end_line / start_column / end_column
# ---------------------------------------------------------------------------


def test_compare_files_passes_start_line_to_comparator():
    """start_line is extracted from kwargs, 1-based→0-based, passed to
    comparator.compare_files() as method-level param."""
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "line1\nline2\nline3\n")
        # start_line=2 (1-based) → line index 1 (0-based) → skip "line1"
        result = Assertions.compare_files(a, b, file_type="text", start_line=2)
        assert result["identical"] is True


def test_compare_files_passes_start_line_and_end_line():
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "a.txt")
        b = os.path.join(d, "b.txt")
        content_a = "line1\nline2\nline3\nline4\n"
        content_b = "line1\ndifferent\nline3\nline4\n"
        with open(a, "w") as f:
            f.write(content_a)
        with open(b, "w") as f:
            f.write(content_b)
        # line 2 differs but start_line=3, end_line=4 → only compare 3-4
        result = Assertions.compare_files(
            a, b, file_type="text", start_line=3, end_line=4
        )
        assert result["identical"] is True


def test_compare_files_start_line_detects_diff_in_range():
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "a.txt")
        b = os.path.join(d, "b.txt")
        with open(a, "w") as f:
            f.write("A1\nB1\nC1\n")
        with open(b, "w") as f:
            f.write("A2\nB2\nC2\n")
        # Only compare line 1 → should differ
        with pytest.raises(AssertionError, match="File comparison failed"):
            Assertions.compare_files(
                a, b, file_type="text", start_line=1, end_line=1
            )


def test_compare_files_start_column_and_end_column():
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "abcdef\n")
        # start_column=3, end_column=4 → only compare "cd" (indices 2-3)
        result = Assertions.compare_files(
            a, b, file_type="text", start_column=3, end_column=4
        )
        assert result["identical"] is True


def test_compare_files_start_line_default_1_becomes_0():
    """start_line=1 (default 1-based) → 0-based index 0 → entire file."""
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "same\n")
        result = Assertions.compare_files(
            a, b, file_type="text", start_line=1
        )
        assert result["identical"] is True


def test_compare_files_range_params_not_leak_to_constructor():
    """start_line, end_line, start_column, end_column must NOT be passed
    to ComparatorFactory.create_comparator() (the constructor)."""
    with tempfile.TemporaryDirectory() as d:
        a, b = _write_two(d, "a.txt", "b.txt", "content\n")
        # If start_line leaks to constructor, TextComparator would fail.
        result = Assertions.compare_files(
            a, b, file_type="text",
            start_line=1, end_line=1, start_column=1, end_column=1,
        )
        assert result["identical"] is True
