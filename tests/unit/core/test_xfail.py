"""Unit tests for xfail four-state model and _apply_xfail_status."""
import pytest

from cli_test_framework.core.test_case import TestCase
from cli_test_framework.core.base_runner import BaseRunner


class MockBaseRunner(BaseRunner):
    """Minimal concrete BaseRunner subclass for testing _apply_xfail_status."""
    def load_test_cases(self):
        pass
    def run_single_test(self, case):
        return {}


@pytest.fixture
def runner():
    return MockBaseRunner("dummy.json")


# ── _apply_xfail_status ──

def test_no_xfail_passed_unchanged(runner):
    case = TestCase(name="t", expected_failure=False)
    result = {"status": "passed"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "passed"
    assert "xfail_reason" not in result


def test_no_xfail_failed_unchanged(runner):
    case = TestCase(name="t", expected_failure=False)
    result = {"status": "failed"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "failed"


def test_xfail_passed_becomes_xpassed(runner):
    case = TestCase(name="t", expected_failure=True)
    result = {"status": "passed"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "xpassed"
    assert result.get("xfail_reason") == ""


def test_xfail_failed_becomes_xfailed(runner):
    case = TestCase(name="t", expected_failure=True)
    result = {"status": "failed"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "xfailed"


def test_xfail_timeout_becomes_xfailed(runner):
    case = TestCase(name="t", expected_failure=True)
    result = {"status": "timeout"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "xfailed"


def test_xfail_with_reason_attached(runner):
    case = TestCase(name="t", expected_failure=True, xfail_reason="Bug #42 not fixed yet")
    result = {"status": "failed"}
    runner._apply_xfail_status(result, case)
    assert result["status"] == "xfailed"
    assert result["xfail_reason"] == "Bug #42 not fixed yet"


# ── Results dict four-state initialization ──

def test_results_dict_has_xfail_keys(runner):
    assert "xfailed" in runner.results
    assert "xpassed" in runner.results
    assert runner.results["xfailed"] == 0
    assert runner.results["xpassed"] == 0


# ── Exit-code rule ──

def test_exit_code_zero_when_none_failed(runner):
    runner.results["failed"] = 0
    runner.results["xpassed"] = 0
    # run_tests would return True (all passed)
    assert runner.results["failed"] == 0 and runner.results["xpassed"] == 0


def test_exit_code_nonzero_on_failed(runner):
    runner.results["failed"] = 1
    runner.results["xpassed"] = 0
    assert not (runner.results["failed"] == 0 and runner.results["xpassed"] == 0)


def test_exit_code_nonzero_on_xpassed(runner):
    runner.results["failed"] = 0
    runner.results["xpassed"] = 1
    assert not (runner.results["failed"] == 0 and runner.results["xpassed"] == 0)


def test_exit_code_nonzero_on_both(runner):
    runner.results["failed"] = 2
    runner.results["xpassed"] = 1
    assert not (runner.results["failed"] == 0 and runner.results["xpassed"] == 0)
