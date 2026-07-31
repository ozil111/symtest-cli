from unittest.mock import patch

from cli_test_framework.core import process_worker


def passed_result(name="case", output="ok\n"):
    return {
        "name": name,
        "status": "passed",
        "message": "",
        "command": "cmd",
        "output": output,
        "return_code": 0,
        "duration": 0.1,
    }


def failed_result(name="case"):
    return {
        "name": name,
        "status": "failed",
        "message": "bad return code",
        "command": "cmd",
        "output": "err\n",
        "return_code": 2,
        "duration": 0.2,
    }


def test_run_test_in_process_executes_single_case(caplog):
    case = {
        "name": "single",
        "command": "echo",
        "args": ["ok"],
        "expected": {"return_code": 0},
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.return_value = passed_result("single")
        result = process_worker.run_test_in_process(1, case, "workspace")

    execute.assert_called_once()
    assert result["status"] == "passed"
    assert "Process Worker 1" in caplog.text


def test_run_test_in_process_prints_single_case_failure(caplog):
    case = {
        "name": "single",
        "command": "tool",
        "args": [],
        "expected": {"return_code": 0},
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.return_value = failed_result("single")
        result = process_worker.run_test_in_process(2, case, "workspace")

    assert result["status"] == "failed"
    assert "Error for single" in caplog.text


def test_run_sequence_in_process_aggregates_successful_steps():
    case = {
        "name": "sequence",
        "steps": [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["two"], "expected": {"return_code": 0}},
        ],
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.side_effect = [
            passed_result("step1", "one\n"),
            passed_result("step2", "two\n"),
        ]
        result = process_worker.run_test_in_process(3, case, "workspace")

    assert result["status"] == "passed"
    assert result["output"] == "one\ntwo\n"
    assert result["return_code"] == 0
    assert execute.call_count == 2


def test_run_sequence_in_process_stops_on_first_failure():
    case = {
        "name": "sequence",
        "steps": [
            {"command": "echo", "args": ["one"], "expected": {"return_code": 0}},
            {"command": "tool", "args": ["fail"], "expected": {"return_code": 0}},
            {"command": "echo", "args": ["three"], "expected": {"return_code": 0}},
        ],
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.side_effect = [
            passed_result("step1", "one\n"),
            failed_result("step2"),
        ]
        result = process_worker.run_test_in_process(4, case, "workspace")

    assert result["status"] == "failed"
    assert result["return_code"] == 2
    assert "Failed at step 2/3" in result["message"]
    assert execute.call_count == 2


def test_single_case_retry_count_is_passed_through():
    """``retry_count`` from the serialized case dict must reach
    the ``TestCaseData`` that is handed to ``execute_single_test_case``."""
    case = {
        "name": "flaky",
        "command": "tool",
        "args": [],
        "expected": {"return_code": 0},
        "retry_count": 3,
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.return_value = passed_result("flaky")
        process_worker.run_test_in_process(5, case, "workspace")

    execute.assert_called_once()
    call_case = execute.call_args[0][0]
    assert call_case["retry_count"] == 3


def test_single_case_default_retry_count():
    """When ``retry_count`` is absent, it should default to 0."""
    case = {
        "name": "stable",
        "command": "tool",
        "args": [],
        "expected": {"return_code": 0},
    }

    with patch.object(process_worker, "execute_single_test_case") as execute:
        execute.return_value = passed_result("stable")
        process_worker.run_test_in_process(6, case, "workspace")

    call_case = execute.call_args[0][0]
    assert call_case["retry_count"] == 0

