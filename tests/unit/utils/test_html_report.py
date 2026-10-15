"""结构化 HTML 报告生成器（utils/html_report.py）的单元测试。"""

import json
import re
from html import unescape as html_unescape

from symtest.utils.html_report import generate_html_report


def _base_results(**overrides):
    results = {"total": 2, "passed": 2, "failed": 0, "details": []}
    results.update(overrides)
    return results


def _passed_detail(**overrides):
    detail = {
        "name": "T00a_hyper",
        "status": "passed",
        "duration": 56.77,
        "description": "刚体平移测试",
        "tags": ["hyper", "fast"],
        "command": "python run.py",
    }
    detail.update(overrides)
    return detail


# ── 摘要与一览表 ──


def test_summary_numbers_and_pass_rate_rendered():
    results = _base_results(
        total=4, passed=3, failed=1,
        details=[_passed_detail(), _passed_detail(name="b"), _passed_detail(name="c"),
                 _passed_detail(name="d", status="failed")],
    )
    html = generate_html_report(results)
    assert "<div class=\"num\">4</div>" in html
    assert "<div class=\"num\">3</div>" in html
    assert "Pass rate 75.0%" in html


def test_description_shown_in_summary_row():
    """description 必须出现在一览行（与 name 同级），而不是埋在详情里。"""
    html = generate_html_report(_base_results(details=[_passed_detail()]))
    assert "刚体平移测试" in html
    assert 'class="desc"' in html


def test_tags_and_duration_in_summary_row():
    html = generate_html_report(_base_results(details=[_passed_detail()]))
    assert "hyper" in html
    assert "56.77s" in html


def test_details_collapsed_by_default():
    """每个用例是 <details class="case">，浏览器默认收起。"""
    html = generate_html_report(_base_results(details=[_passed_detail()]))
    assert '<details class="case passed"' in html
    assert "data-status=" in html
    # 不应在 HTML 属性上写 open（默认全收起）
    assert not re.search(r"<details class=\"case[^\"]*\"[^>]*\bopen\b", html)


def test_failed_nav_present_only_with_failures():
    all_passed = generate_html_report(_base_results(details=[_passed_detail()]))
    assert "Failed cases:" not in all_passed

    failed_detail = _passed_detail(name="bad_case", status="failed")
    with_failure = generate_html_report(_base_results(
        total=2, passed=1, failed=1,
        details=[_passed_detail(), failed_detail],
    ))
    assert "Failed cases:" in with_failure
    assert 'href="#case-1"' in with_failure


def test_toolbar_and_inline_js_present():
    html = generate_html_report(_base_results(details=[_passed_detail()]))
    assert "expandAll(true)" in html
    assert "setFilter(" in html
    assert "<script>" in html


# ── 转义 ──


def test_user_data_is_html_escaped():
    evil = "<script>alert(1)</script>"
    detail = _passed_detail(name=evil, description=evil)
    html = generate_html_report(_base_results(details=[detail]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ── 通过用例的误差统计（--error-analysis-all） ──


def _assertion_with_stats(**overrides):
    entry = {
        "assertion": "compare_files",
        "passed": True,
        "actual": "T00a_uel_elements.csv",
        "baseline": "T00a_elements.csv",
        "error_stats": {
            "total_numeric_cells": 306,
            "mismatched_cells": 0,
            "max_abs_error": 5.7e-09,
        },
    }
    entry.update(overrides)
    return entry


def test_passed_error_stats_only_with_error_analysis_all():
    detail = _passed_detail(assertion_results=[_assertion_with_stats()])
    without = generate_html_report(_base_results(details=[detail]))
    assert "error_stats:" not in without

    with_stats = generate_html_report(_base_results(
        error_analysis_all=True, details=[detail]))
    assert "error_stats:" in with_stats
    assert "total_numeric_cells" in with_stats
    # 文件对标签：多个并列的 error_stats 块可归属到具体文件
    assert "baseline: T00a_elements.csv" in with_stats
    assert "actual: T00a_uel_elements.csv" in with_stats


def test_passed_channels_rendered_per_channel():
    entry = _assertion_with_stats(
        error_stats=None,
        channels=[{"name": "U1", "passed": True, "rtol": 1e-5, "atol": 1e-8,
                   "stats": {"total": 10, "mismatched": 0}, "differences": []}],
    )
    detail = _passed_detail(assertion_results=[entry])
    html = generate_html_report(_base_results(
        error_analysis_all=True, details=[detail]))
    assert "channel 'U1'" in html
    assert "PASS" in html


# ── 非通过用例的失败详情 ──


def _failed_detail(**overrides):
    detail = {
        "name": "bad_case",
        "status": "failed",
        "duration": 12.5,
        "description": "失败用例",
        "message": "comparison failed: max_rel_error exceeded",
        "failure_kind": "file_compare",
        "command": "solver --run",
        "return_code": 1,
        "compare_failures": [{
            "actual": "out.csv",
            "baseline": "ref.csv",
            "type": "csv",
            "diff_summary": {"total_differences": 3,
                             "max_rel_error": 0.5, "max_rel_error_at": "row 2"},
            "differences": [{"position": "row 2, column 1",
                             "expected": "1.0", "actual": "2.0"}],
        }],
        "output": "LONG SOLVER LOG\n" * 200,
    }
    detail.update(overrides)
    return detail


def test_failed_case_renders_failure_sections():
    html = generate_html_report(_base_results(
        total=1, passed=0, failed=1, details=[_failed_detail()]))
    assert "comparison failed" in html
    assert "Compare Failures:" in html
    assert "baseline: ref.csv" in html
    assert "max_rel_error" in html
    assert "LONG SOLVER LOG" in html
    assert '<details class="sub"><summary>Command Output</summary>' in html


def test_xfail_quiet_suppresses_command_output():
    detail = _failed_detail(status="xfailed", xfail_reason="Bug #42",
                            xfail_quiet=True)
    html = generate_html_report(_base_results(
        total=1, passed=0, failed=0, xfailed=1, details=[detail]))
    assert "Command Output" not in html
    assert "Bug #42" in html


def test_step_results_rendered():
    detail = _failed_detail(step_results=[
        {"step": 1, "status": "passed", "duration": 1.0, "message": ""},
        {"step": 2, "status": "failed", "duration": 2.0, "message": "boom"},
    ])
    html = generate_html_report(_base_results(
        total=1, passed=0, failed=1, details=[detail]))
    assert "Step 1: passed" in html
    assert "Step 2: failed" in html
    assert "boom" in html


def test_expected_block_rendered_as_json():
    detail = _passed_detail(expected={"return_code": 0,
                                      "compare_files": [{"type": "csv"}]})
    html = generate_html_report(_base_results(details=[detail]))
    assert "return_code" in html
    # JSON 可被解析（转义未破坏结构）
    m = re.search(r'<pre class="scroll small">(\{.*?\})</pre>', html, re.S)
    assert m
    payload = json.loads(html_unescape(m.group(1)))
    assert payload["return_code"] == 0
    assert payload["compare_files"][0]["type"] == "csv"


def test_float_formatting_matches_text_report():
    """浮点统计与文本报告同款 %.6g 格式。"""
    entry = _assertion_with_stats(error_stats={"max_abs_error": 1.23e-07})
    detail = _passed_detail(assertion_results=[entry])
    html = generate_html_report(_base_results(
        error_analysis_all=True, details=[detail]))
    assert "1.23e-07" in html
