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


# ── error_analysis_all (--error-analysis-all) ──

def _make_passed_detail_with_error_stats():
    """构造一个带有 error_stats 的通过用例 detail dict"""
    return {
        "name": "pass_csv",
        "status": "passed",
        "duration": 0.5,
        "assertion_results": [
            {
                "assertion": "compare_files",
                "passed": True,
                "actual": "data_actual.csv",
                "baseline": "data_base.csv",
                "type": "csv",
                "error_stats": {
                    "total_numeric_cells": 4,
                    "mismatched_cells": 0,
                    "max_abs_error": 1.2e-7,
                    "max_abs_error_at": "row 2, column 3",
                    "max_rel_error": 3.4e-9,
                    "max_rel_error_at": "row 1, column 1",
                    "mean_abs_error": 2.5e-8,
                    "rms_abs_error": 5.0e-8,
                },
            }
        ],
    }


def test_error_analysis_all_reports_stats_for_passed():
    """--error-analysis-all 时，通过用例应输出 error_stats"""
    generator = ReportGenerator(
        {
            "total": 1, "passed": 1, "failed": 0,
            "error_analysis_all": True,
            "details": [_make_passed_detail_with_error_stats()],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "pass_csv" in report
    assert "error_stats:" in report
    assert "total_numeric_cells: 4" in report
    assert "mismatched_cells: 0" in report
    assert "max_abs_error: 1.2e-07" in report
    assert "max_abs_error_at: row 2, column 3" in report
    assert "max_rel_error: 3.4e-09" in report
    assert "mean_abs_error: 2.5e-08" in report
    assert "rms_abs_error: 5e-08" in report


def test_error_analysis_all_disabled_omits_stats_for_passed():
    """未启用 --error-analysis-all 时，通过用例不应输出 error_stats"""
    generator = ReportGenerator(
        {
            "total": 1, "passed": 1, "failed": 0,
            "error_analysis_all": False,
            "details": [_make_passed_detail_with_error_stats()],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "pass_csv" in report
    assert "error_stats" not in report


# ── channel sub-results (data-lane comparators) ──

def _make_failed_detail_with_channels():
    """构造一个带通道子结果的失败用例 detail dict（extractor 比较器形态）"""
    return {
        "name": "channel_case",
        "status": "failed",
        "failure_kind": "file_compare",
        "compare_failures": [
            {
                "actual": "out.dat",
                "baseline": "ref.dat",
                "type": "my_extractor",
                "diff_summary": {"total_differences": 1},
                "error_stats": {
                    "S11": {"total": 4, "mismatched": 0, "max_abs_error": 1e-9},
                    "S33": {"total": 4, "mismatched": 2, "max_abs_error": 543.0},
                },
                "channels": [
                    {
                        "name": "S11",
                        "passed": True,
                        "rtol": 1e-5,
                        "atol": 1e-8,
                        "stats": {"total": 4, "mismatched": 0, "max_abs_error": 1e-9},
                        "differences": [],
                    },
                    {
                        "name": "S33",
                        "passed": False,
                        "rtol": 1e-5,
                        "atol": 600.0,
                        "stats": {"total": 4, "mismatched": 2, "max_abs_error": 543.0},
                        "differences": [
                            {"position": "channel S33", "expected": "within rtol=1e-05, atol=600",
                             "actual": "2/4 values mismatched", "diff_type": "channel_mismatch"},
                        ],
                    },
                ],
                "differences": [
                    {"position": "channel S33", "expected": "within rtol=1e-05, atol=600",
                     "actual": "2/4 values mismatched", "diff_type": "channel_mismatch"},
                ],
            }
        ],
    }


def test_channel_results_rendered_per_channel():
    """失败报告应逐通道展示 pass/fail、容差与统计"""
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 1,
            "details": [_make_failed_detail_with_channels()],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "channels:" in report
    assert "channel 'S11': PASS" in report
    assert "channel 'S33': FAIL" in report
    assert "atol=600" in report
    assert "max_abs_error: 543" in report
    assert "channel S33" in report


def test_nested_autonomous_error_stats_not_treated_as_channels():
    """自主比较器的嵌套 error_stats（{group: {...}}）不得被猜测为通道结果：
    不渲染通道块，仅做通用扁平渲染。"""
    detail = {
        "name": "autonomous_nested",
        "status": "failed",
        "compare_failures": [
            {
                "actual": "out.dat",
                "baseline": "ref.dat",
                "type": "my_analysis",
                "diff_summary": {},
                # Channel-SHAPED nested dict from an autonomous comparator —
                # must NOT be interpreted as channel output.
                "error_stats": {
                    "geometry": {"max_deviation": 0.5, "elements": 1024},
                    "solver": {"iterations": 42, "converged": False},
                },
                "channels": [],  # explicitly no channel results
                "differences": [],
            }
        ],
    }
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 1,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    # Flat generic rendering — no channel inference from dict shape
    assert "channel '" not in report
    assert "channels:" not in report
    assert "error_stats:" in report
    assert "geometry:" in report
    assert "solver:" in report
    assert "iterations" in report


def test_flat_error_stats_rendered_when_no_channels():
    """无通道结果时，扁平 error_stats 走通用渲染（fallback 规则）。"""
    detail = {
        "name": "flat_stats",
        "status": "failed",
        "compare_failures": [
            {
                "actual": "out.dat",
                "baseline": "ref.dat",
                "type": "csv",
                "diff_summary": {},
                "error_stats": {
                    "total_numeric_cells": 4,
                    "mismatched_cells": 1,
                    "max_abs_error": 0.25,
                },
                "channels": [],
                "differences": [],
            }
        ],
    }
    generator = ReportGenerator(
        {
            "total": 1, "passed": 0, "failed": 1,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "error_stats:" in report
    assert "total_numeric_cells: 4" in report
    assert "max_abs_error: 0.25" in report
    assert "channel '" not in report


def test_channel_results_rendered_for_passed_with_error_analysis_all():
    """--error-analysis-all 时通过用例也应渲染通道子结果"""
    detail = {
        "name": "ok_channels",
        "status": "passed",
        "assertion_results": [
            {
                "assertion": "compare_files",
                "passed": True,
                "error_stats": None,
                "channels": [
                    {
                        "name": "U1",
                        "passed": True,
                        "rtol": 1e-5,
                        "atol": 1e-8,
                        "stats": {"total": 10, "mismatched": 0},
                        "differences": [],
                    },
                ],
            }
        ],
    }
    generator = ReportGenerator(
        {
            "total": 1, "passed": 1, "failed": 0,
            "error_analysis_all": True,
            "details": [detail],
        },
        "unused.txt",
    )
    report = generator.generate_report()
    assert "channel 'U1': PASS" in report
    assert "total: 10" in report


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

