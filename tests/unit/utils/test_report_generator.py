from symtest.utils.report_generator import ReportGenerator


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


# ── xfail_quiet ──

def _make_xfailed_detail(*, xfail_quiet=True):
    """Helper: 构造一个 xfailed 用例的 detail dict"""
    return {
        "name": "known_bug",
        "status": "xfailed",
        "xfail_reason": "Bug #42",
        "xfail_quiet": xfail_quiet,
        "command": "solver --input bug.dat",
        "return_code": 1,
        "message": "expected failure",
        "output": "VERY LONG SOLVER OUTPUT\n" * 100,
    }


def test_xfail_quiet_suppresses_command_output():
    """xfail_quiet=True 时报告中不应出现 Command Output 块"""
    detail = _make_xfailed_detail(xfail_quiet=True)
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 0,
            "xfailed": 1, "xpassed": 0,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "Command Output:" not in report
    assert "NON-PASSED TEST CASES DETAILS" in report  # 详情区仍然存在


def test_xfail_quiet_still_shows_metadata():
    """xfail_quiet=True 时仍保留元信息（Command、Return Code、xfail_reason 等）"""
    detail = _make_xfailed_detail(xfail_quiet=True)
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 0,
            "xfailed": 1, "xpassed": 0,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "Command: solver --input bug.dat" in report
    assert "Return Code: 1" in report
    assert "expected failure" in report
    assert "Bug #42" in report


def test_xfail_not_quiet_shows_command_output():
    """xfail_quiet 未设置（默认）时，Command Output 照常输出（向后兼容）"""
    detail = {
        "name": "known_bug",
        "status": "xfailed",
        "xfail_reason": "Bug #42",
        "command": "solver --input bug.dat",
        "return_code": 1,
        "output": "solver log output",
    }
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 0,
            "xfailed": 1, "xpassed": 0,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "Command Output:" in report
    assert "solver log output" in report


def test_xfail_quiet_false_explicitly_shows_command_output():
    """xfail_quiet=False 显式设置时，Command Output 应照常输出"""
    detail = _make_xfailed_detail(xfail_quiet=False)
    detail["output"] = "expected output text"
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 0,
            "xfailed": 1, "xpassed": 0,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "Command Output:" in report
    assert "expected output text" in report

