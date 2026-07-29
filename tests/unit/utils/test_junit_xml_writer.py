"""Unit tests for junit_xml_writer module."""

import xml.etree.ElementTree as ET
from pathlib import Path

from cli_test_framework.utils.junit_xml_writer import write_junit_xml, _xml_escape


# ---------------------------------------------------------------------------
# _xml_escape
# ---------------------------------------------------------------------------

def test_xml_escape_handles_none():
    assert _xml_escape(None) == ""


def test_xml_escape_strips_control_chars():
    assert _xml_escape("\x00hello\x1f") == "?hello?"


def test_xml_escape_preserves_valid_chars():
    assert _xml_escape("hello\nworld\t!") == "hello\nworld\t!"


def test_xml_escape_handles_non_string():
    assert _xml_escape(42) == "42"


# ---------------------------------------------------------------------------
# write_junit_xml
# ---------------------------------------------------------------------------

def test_all_passed(tmp_path):
    results = {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "details": [
            {"name": "test_a", "status": "passed", "message": "", "command": "cmd",
             "output": "ok", "return_code": 0, "duration": 0.1},
            {"name": "test_b", "status": "passed", "message": "", "command": "cmd",
             "output": "ok", "return_code": 0, "duration": 0.2},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.tag == "testsuite"
    assert suite.get("tests") == "2"
    assert suite.get("failures") == "0"
    assert suite.get("errors") == "0"
    assert len(suite.findall("testcase")) == 2
    # Passed cases have no child elements
    for tc in suite.findall("testcase"):
        assert len(tc) == 0


def test_failure_generates_failure_element(tmp_path):
    results = {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "details": [
            {"name": "bad_test", "status": "failed",
             "message": "expected 'hello'", "command": "echo x",
             "output": "x", "return_code": 0, "duration": 0.5},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("tests") == "1"
    assert suite.get("failures") == "1"
    assert suite.get("errors") == "0"

    tc = suite.find("testcase")
    failure = tc.find("failure")
    assert failure is not None
    assert failure.get("type") == "AssertionError"
    assert "expected 'hello'" in (failure.text or "")


def test_timeout_generates_error_element(tmp_path):
    results = {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "details": [
            {"name": "slow_test", "status": "timeout",
             "message": "Timeout reached! Killed after 10 seconds.",
             "command": "slow_cmd", "output": "partial output...",
             "return_code": -1, "duration": 10.0},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("failures") == "0"
    assert suite.get("errors") == "1"

    tc = suite.find("testcase")
    error = tc.find("error")
    assert error is not None
    assert error.get("type") == "TimeoutExpired"
    assert "partial output..." in (error.text or "")


def test_execution_error_generates_error_element(tmp_path):
    results = {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "details": [
            {"name": "crash_test", "status": "failed",
             "message": "Execution error: process died",
             "command": "bad_cmd", "output": "segfault",
             "return_code": 139, "duration": 0.3},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("failures") == "0"
    assert suite.get("errors") == "1"

    tc = suite.find("testcase")
    error = tc.find("error")
    assert error is not None
    assert error.get("type") == "RuntimeError"


def test_mixed_statuses(tmp_path):
    results = {
        "total": 4,
        "passed": 1,
        "failed": 3,
        "details": [
            {"name": "ok", "status": "passed", "message": "", "command": "",
             "output": "", "return_code": 0, "duration": 0.1},
            {"name": "fail", "status": "failed", "message": "mismatch",
             "command": "", "output": "", "return_code": 1, "duration": 0.2},
            {"name": "timeout", "status": "timeout", "message": "timed out",
             "command": "", "output": "", "return_code": -1, "duration": 1.0},
            {"name": "exec_err", "status": "failed",
             "message": "Execution error: oom",
             "command": "", "output": "", "return_code": 1, "duration": 0.3},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("tests") == "4"
    assert suite.get("failures") == "1"   # only the plain "failed"
    assert suite.get("errors") == "2"     # timeout + execution error

    failure_names = {
        tc.get("name")
        for tc in suite.findall("testcase")
        if tc.find("failure") is not None
    }
    error_names = {
        tc.get("name")
        for tc in suite.findall("testcase")
        if tc.find("error") is not None
    }
    assert failure_names == {"fail"}
    assert error_names == {"timeout", "exec_err"}


def test_default_suite_name(tmp_path):
    results = {
        "total": 0, "passed": 0, "failed": 0, "details": [],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("name") == "cli_tests"


def test_custom_classname(tmp_path):
    results = {
        "total": 1, "passed": 1, "failed": 0,
        "details": [
            {"name": "tc", "status": "passed", "message": "", "command": "",
             "output": "", "return_code": 0, "duration": 0.05},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), classname="custom.Class")

    tree = ET.parse(str(path))
    tc = tree.getroot().find("testcase")
    assert tc.get("classname") == "custom.Class"


def test_output_includes_xml_header(tmp_path):
    results = {
        "total": 0, "passed": 0, "failed": 0, "details": [],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    raw = Path(path).read_text(encoding="utf-8")
    assert raw.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_time_aggregation(tmp_path):
    results = {
        "total": 2, "passed": 2, "failed": 0,
        "details": [
            {"name": "a", "status": "passed", "message": "", "command": "",
             "output": "", "return_code": 0, "duration": 1.5},
            {"name": "b", "status": "passed", "message": "", "command": "",
             "output": "", "return_code": 0, "duration": 2.5},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert float(suite.get("time")) == 4.0


def test_timestamp_present(tmp_path):
    results = {
        "total": 0, "passed": 0, "failed": 0, "details": [],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("timestamp") is not None


def test_hostname_present(tmp_path):
    results = {
        "total": 0, "passed": 0, "failed": 0, "details": [],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path))

    tree = ET.parse(str(path))
    suite = tree.getroot()
    import socket
    assert suite.get("hostname") == socket.gethostname()


# ── xfail / xpassed JUnit mapping ──

def test_xfailed_maps_to_skipped(tmp_path):
    results = {
        "total": 1, "passed": 0, "failed": 0,
        "details": [
            {"name": "xfail_test", "status": "xfailed",
             "message": "Expected failure: file compare mismatch",
             "xfail_reason": "Bug #42", "command": "", "output": "",
             "return_code": 1, "duration": 0.5},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("skipped") == "1"
    assert suite.get("failures") == "0"
    assert suite.get("errors") == "0"

    tc = suite.find("testcase")
    skipped = tc.find("skipped")
    assert skipped is not None
    assert skipped.get("message") == "Bug #42"


def test_xpassed_maps_to_failure(tmp_path):
    results = {
        "total": 1, "passed": 0, "failed": 1,
        "details": [
            {"name": "xpass_test", "status": "xpassed",
             "message": "UNEXPECTED PASS", "command": "", "output": "",
             "return_code": 0, "duration": 0.1},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("skipped") == "0"
    assert suite.get("failures") == "1"

    tc = suite.find("testcase")
    failure = tc.find("failure")
    assert failure is not None
    assert "UNEXPECTED PASS" in (failure.text or "")


def test_mixed_xfail_statuses(tmp_path):
    results = {
        "total": 4, "passed": 1, "failed": 1,
        "details": [
            {"name": "ok", "status": "passed", "message": "", "command": "",
             "output": "", "return_code": 0, "duration": 0.1},
            {"name": "fail", "status": "failed", "message": "mismatch",
             "command": "", "output": "", "return_code": 1, "duration": 0.2},
            {"name": "xpassed", "status": "xpassed", "message": "UNEXPECTED",
             "command": "", "output": "", "return_code": 0, "duration": 0.1},
            {"name": "xfailed", "status": "xfailed",
             "message": "Expected: file mismatch", "xfail_reason": "Known issue",
             "command": "", "output": "", "return_code": 1, "duration": 0.3},
        ],
    }
    path = tmp_path / "report.xml"
    write_junit_xml(results, str(path), suite_name="demo")

    tree = ET.parse(str(path))
    suite = tree.getroot()
    assert suite.get("tests") == "4"
    assert suite.get("failures") == "2"  # failed + xpassed
    assert suite.get("skipped") == "1"   # xfailed
