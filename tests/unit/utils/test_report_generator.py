from cli_test_framework.utils.report_generator import ReportGenerator


def test_generate_report_summarizes_passed_and_failed_results():
    generator = ReportGenerator(
        {
            "total": 2,
            "passed": 1,
            "failed": 1,
            "details": [
                {"name": "ok", "status": "passed"},
                {
                    "name": "bad",
                    "status": "failed",
                    "message": "expected output",
                    "command": "tool --flag",
                    "return_code": 2,
                    "output": "stderr text",
                    "duration": 0.12,
                },
            ],
        },
        "unused.txt",
    )

    report = generator.generate_report()

    assert "Total Tests: 2" in report
    assert "Passed: 1" in report
    assert "Failed: 1" in report
    assert "ok" in report
    assert "NON-PASSED TEST CASES DETAILS" in report
    assert "Command: tool --flag" in report
    assert "Return Code: 2" in report
    assert "stderr text" in report


def test_save_report_writes_utf8_file(tmp_path):
    report_path = tmp_path / "report.txt"
    generator = ReportGenerator(
        {"total": 1, "passed": 1, "failed": 0, "details": []},
        str(report_path),
    )

    generator.save_report()

    assert "Total Tests: 1" in report_path.read_text(encoding="utf-8")


def test_print_report_outputs_generated_report(caplog):
    generator = ReportGenerator(
        {"total": 0, "passed": 0, "failed": 0, "details": []},
        "unused.txt",
    )

    generator.print_report()

    assert "Test Results Summary" in caplog.text

