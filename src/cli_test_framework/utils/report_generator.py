import logging

logger = logging.getLogger("cli_test_framework.utils.report_generator")


def _format_flaky_label(detail: dict) -> str:
    """Build a flaky/retry label if applicable."""
    attempts = detail.get("attempts", 1)
    status = detail.get("status", "")
    if attempts > 1:
        if status == "passed" and detail.get("flaky"):
            return f", flaky: passed on attempt {attempts}"
        elif status != "passed":
            return f", failed after {attempts} attempts"
    return ""


class ReportGenerator:
    def __init__(self, results: dict, file_path: str):
        self.results = results
        self.file_path = file_path

    def generate_report(self) -> str:
        xfailed = self.results.get("xfailed", 0)
        xpassed = self.results.get("xpassed", 0)

        report = "Test Results Summary:\n"
        report += f"Total Tests: {self.results['total']}\n"
        report += f"Passed: {self.results['passed']}\n"
        report += f"Failed: {self.results['failed']}\n"
        if xfailed:
            report += f"XFailed: {xfailed}\n"
        if xpassed:
            report += f"XPassed: {xpassed} (unexpected!)\n"
        if self.results.get("updated", 0) > 0:
            report += f"Baseline Updated: {self.results['updated']}\n"
        if self.results.get("history_reset"):
            report += f"History Reset: {self.results.get('history_cleared', 0)} case(s) cleared\n"
        total_duration = sum(d.get('duration', 0) for d in self.results['details'])
        report += f"Total Duration: {total_duration:.2f}s\n\n"

        report += "Detailed Results:\n"
        for detail in self.results['details']:
            status = detail['status']
            if status == 'passed':
                status_icon = "✓"
            elif status == 'xfailed':
                status_icon = "✓"
            elif status == 'xpassed':
                status_icon = "✗"
            else:
                status_icon = "✗"
            duration = detail.get('duration', 0)
            flaky_label = _format_flaky_label(detail)
            xfail_suffix = ""
            if status == 'xfailed':
                reason = detail.get('xfail_reason', '')
                xfail_suffix = f", expected failure" + (f": {reason}" if reason else "")
            elif status == 'xpassed':
                xfail_suffix = ", UNEXPECTED PASS — remove xfail marker!"
            report += f"{status_icon} {detail['name']} ({duration:.2f}s{flaky_label}{xfail_suffix})\n"
            if detail.get('description'):
                report += f"   Description: {detail['description']}\n"
            if detail.get('message') and status != 'passed':
                report += f"   -> {detail['message']}\n"

        # 添加失败案例的详细输出信息（含 xfailed、xpassed、timeout 等非通过状态）
        failed_tests = [detail for detail in self.results['details'] if detail['status'] != 'passed']
        if failed_tests:
            report += "\n" + "="*50 + "\n"
            report += "NON-PASSED TEST CASES DETAILS:\n"
            report += "="*50 + "\n\n"

            for i, failed_test in enumerate(failed_tests, 1):
                report += f"{i}. Test: {failed_test['name']}\n"
                report += "-" * 40 + "\n"

                # Description
                if failed_test.get('description'):
                    report += f"Description: {failed_test['description']}\n"

                # Expected
                if failed_test.get('expected'):
                    import json as _json
                    report += f"Expected: {_json.dumps(failed_test['expected'], indent=2, ensure_ascii=False)}\n"

                # Failure kind
                if failed_test.get('failure_kind'):
                    report += f"Failure Kind: {failed_test['failure_kind']}\n"

                # Failed step
                if failed_test.get('failed_step'):
                    report += f"Failed Step: {failed_test['failed_step']}\n"

                # 添加执行的命令
                if failed_test.get('command'):
                    report += f"Command: {failed_test['command']}\n"

                # 添加返回码
                if failed_test.get('return_code') is not None:
                    report += f"Return Code: {failed_test['return_code']}\n"

                # 添加失败原因
                if failed_test.get('message'):
                    report += f"Error Message: {failed_test['message']}\n"

                # 添加 compare_failures 结构化信息
                compare_failures = failed_test.get('compare_failures', [])
                if compare_failures:
                    report += "\nCompare Failures:\n"
                    for cf in compare_failures:
                        report += f"  - actual: {cf.get('actual')}, baseline: {cf.get('baseline')}\n"
                        report += f"    type: {cf.get('type', 'unknown')}\n"
                        ds = cf.get('diff_summary', {})
                        if ds:
                            report += f"    total_differences: {ds.get('total_differences')}\n"
                            if ds.get('max_rel_error') is not None:
                                report += f"    max_rel_error: {ds['max_rel_error']:.6g} at {ds.get('max_rel_error_at')}\n"
                            if ds.get('max_abs_error') is not None:
                                report += f"    max_abs_error: {ds['max_abs_error']:.6g} at {ds.get('max_abs_error_at')}\n"
                        # ── Error analysis (full-dataset streaming stats) ──
                        es = cf.get('error_stats')
                        if es:
                            report += "    error_stats:\n"
                            for key, val in es.items():
                                if isinstance(val, float):
                                    report += f"      {key}: {val:.6g}\n"
                                else:
                                    report += f"      {key}: {val}\n"
                        diffs = cf.get('differences', [])
                        if diffs:
                            report += "    sample differences:\n"
                            for d in diffs[:5]:
                                report += f"      {d.get('position')}: expected={d.get('expected')}, actual={d.get('actual')}\n"
                            if len(diffs) > 5:
                                report += f"      ... and {len(diffs) - 5} more\n"
                        # ── Comparator Output (script/custom comparators) ──
                        cmd_out = cf.get('command_output')
                        if cmd_out:
                            cmd_lines = str(cmd_out).splitlines()
                            if cmd_lines:
                                report += "    Comparator Output:\n"
                                report += "-" * 28 + "\n"
                                limit = 20
                                for line in cmd_lines[:limit]:
                                    report += f"      {line}\n"
                                if len(cmd_lines) > limit:
                                    report += f"      ... and {len(cmd_lines) - limit} more lines\n"
                                report += "-" * 28 + "\n"
                        report += "\n"

                # 添加步骤结果
                step_results = failed_test.get('step_results', [])
                if step_results:
                    report += "\nStep Results:\n"
                    for sr in step_results:
                        status_icon = "✓" if sr.get('status') == 'passed' else "✗"
                        report += f"  {status_icon} Step {sr.get('step')}: {sr.get('status')} ({sr.get('duration', 0):.2f}s)\n"
                        if sr.get('message'):
                            report += f"     -> {sr['message']}\n"

                # 添加 baseline_updated 信息
                baseline_updated = failed_test.get('baseline_updated', [])
                if baseline_updated:
                    report += "\nBaseline Updated:\n"
                    for bu in baseline_updated:
                        report += f"  - {bu}\n"

                # 添加命令的完整输出（这是最重要的部分）
                # 当 xfail_quiet 为 True 且状态为 xfailed 时，跳过 Command Output
                is_xfail_quiet = (
                    failed_test.get('status') == 'xfailed'
                    and failed_test.get('xfail_quiet')
                )
                if failed_test.get('output') and not is_xfail_quiet:
                    report += f"\nCommand Output:\n"
                    report += "=" * 30 + "\n"
                    report += f"{failed_test['output']}\n"
                    report += "=" * 30 + "\n"

                # 添加错误堆栈信息（如果有的话）
                if failed_test.get('error_trace'):
                    report += f"Error Trace:\n{failed_test['error_trace']}\n"

                # 添加执行时间（如果有的话）
                if failed_test.get('duration'):
                    report += f"Duration: {failed_test['duration']:.2f}s\n"

                # 添加 flaky/attempts 信息
                attempts = failed_test.get('attempts', 1)
                if attempts > 1:
                    report += f"Attempts: {attempts}"
                    if failed_test.get('flaky'):
                        report += " (flaky)"
                    report += "\n"

                report += "\n"

        return report

    def save_report(self) -> None:
        report = self.generate_report()
        with open(self.file_path, 'w', encoding='utf-8') as f:
            f.write(report)

    def print_report(self) -> None:
        report = self.generate_report()
        logger.info(report)