"""JUnit XML report writer for CLI Test Framework.

Generates JUnit-format XML compatible with GitLab CI, Jenkins, CircleCI, etc.
"""

import socket
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _xml_escape(text: str) -> str:
    """Escape text for safe embedding in XML (handles control characters)."""
    if text is None:
        return ""
    return "".join(
        ch if ord(ch) >= 0x20 or ch in "\t\n\r" else "?"
        for ch in str(text)
    )


def write_junit_xml(
    results: Dict[str, Any],
    filepath: str,
    suite_name: Optional[str] = None,
    classname: Optional[str] = None,
) -> None:
    """Write JUnit XML report for CI tools.

    Args:
        results: The ``BaseRunner.results`` dict after ``run_tests()``.
        filepath: Output path for the XML file.
        suite_name: Name of the testsuite element. Defaults to ``"cli_tests"``.
        classname: ``classname`` attribute for each testcase. Defaults to suite_name.
    """
    details: List[Dict[str, Any]] = results.get("details", [])
    total = len(details)
    total_time = 0.0

    suite_name = suite_name or "cli_tests"
    classname = classname or suite_name

    # First pass: count failures/errors/skipped and total time
    failures_count = 0
    errors_count = 0
    skipped_count = 0
    for detail in details:
        duration = detail.get("duration", 0.0)
        total_time += duration
        status = detail.get("status", "failed")

        if status in ("passed", "xfailed"):
            pass
        elif status == "xpassed":
            failures_count += 1
        elif status in ("timeout",):
            errors_count += 1
        elif status == "failed":
            message = str(detail.get("message", ""))
            if "Execution error" in message:
                errors_count += 1
            else:
                failures_count += 1
        else:
            errors_count += 1

        if status == "xfailed":
            skipped_count += 1

    # Build XML tree
    root = ET.Element("testsuite", {
        "name": suite_name,
        "tests": str(total),
        "failures": str(failures_count),
        "errors": str(errors_count),
        "skipped": str(skipped_count),
        "time": f"{total_time:.3f}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
    })

    for detail in details:
        duration = detail.get("duration", 0.0)
        tc = ET.SubElement(root, "testcase", {
            "name": detail.get("name", "unknown"),
            "classname": classname,
            "time": f"{duration:.3f}",
        })

        status = detail.get("status", "failed")
        message = str(detail.get("message", ""))
        output = str(detail.get("output", ""))

        if status in ("passed",):
            # No child element = passed in JUnit convention
            pass
        elif status == "xfailed":
            # Expected failure → skipped in JUnit
            reason = detail.get("xfail_reason", "") or ""
            ET.SubElement(tc, "skipped", {
                "message": _xml_escape(reason or "Expected failure"),
            })
        elif status == "xpassed":
            # Unexpected pass → failure
            full_text = f"UNEXPECTED PASS: marked as expected_failure but passed.\n{message}\n\n--- Command Output ---\n{output}" if output else f"UNEXPECTED PASS: marked as expected_failure but passed.\n{message}"
            ET.SubElement(tc, "failure", {
                "message": _xml_escape(message or "UNEXPECTED PASS (xpassed)"),
                "type": "AssertionError",
            }).text = _xml_escape(full_text)
        elif status in ("timeout",):
            ET.SubElement(tc, "error", {
                "message": _xml_escape(message or "Test timed out"),
                "type": "TimeoutExpired",
            }).text = _xml_escape(f"{message}\n\n--- Command Output ---\n{output}" if output else message)
        elif status == "failed":
            full_text = f"{message}\n\n--- Command Output ---\n{output}" if output else message
            if "Execution error" in message:
                ET.SubElement(tc, "error", {
                    "message": _xml_escape(message),
                    "type": "RuntimeError",
                }).text = _xml_escape(full_text)
            else:
                ET.SubElement(tc, "failure", {
                    "message": _xml_escape(message),
                    "type": "AssertionError",
                }).text = _xml_escape(full_text)
        else:
            ET.SubElement(tc, "error", {
                "message": _xml_escape(message or f"Unknown status: {status}"),
                "type": "UnknownStatus",
            }).text = _xml_escape(output)

    # Write
    tree = ET.ElementTree(root)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode")
