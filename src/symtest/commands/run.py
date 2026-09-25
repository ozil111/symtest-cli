#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""``symtest run`` subcommand: run options, runner selection and reporting.

Extracted from ``cli.py`` so the CLI entry point stays a thin
parser + dispatch layer.
"""

import json
import logging
import sys
from pathlib import Path

from ..reporting.diagnosis import attach_next_action_hints
from ..runners import JSONRunner, ParallelJSONRunner, ParallelYAMLRunner, YAMLRunner
from ..utils.report_generator import ReportGenerator
from ..utils.junit_xml_writer import write_junit_xml

logger = logging.getLogger("symtest.commands.run")


def _parse_vars(var_list):
    """Parse ``['solver=/path', 'model=./m.dat']`` → ``{'solver': '/path', ...}``."""
    variables = {}
    for item in var_list or []:
        if '=' not in item:
            logger.warning("Ignoring invalid --var '%s' (expected KEY=VALUE)", item)
            continue
        key, _, value = item.partition('=')
        variables[key.strip()] = value.strip()
    return variables


def _confirm_baseline_update(args) -> bool:
    """Require an explicit confirmation before baseline files may be replaced.

    Interactive CLI users type ``yes``. Automation must pass ``--yes`` so a
    non-interactive process never hangs while waiting for input.
    """
    if not getattr(args, 'update_baseline', False):
        return True
    if getattr(args, 'yes', False):
        return True

    if not sys.stdin.isatty():
        logger.error(
            "--update-baseline can overwrite reference files. "
            "Re-run with --yes in non-interactive environments."
        )
        return False

    try:
        response = input(
            "WARNING: --update-baseline may overwrite reference files when "
            "comparisons fail.\nType 'yes' to continue: "
        )
    except (EOFError, KeyboardInterrupt):
        logger.warning("Baseline update cancelled.")
        return False

    if response.strip().lower() != "yes":
        logger.warning("Baseline update cancelled.")
        return False
    return True


def run_tests(args):
    """Run tests based on command line arguments"""
    # Resolve config_file relative to workspace if specified, otherwise cwd.
    # This matches BaseRunner's resolution (workspace / config_file).
    workspace_path = Path(args.workspace) if args.workspace else Path.cwd()
    config_file = (workspace_path / args.config_file).resolve()

    if not config_file.exists():
        logger.error("Configuration file not found: %s", config_file)
        return False

    if not _confirm_baseline_update(args):
        return False

    # Determine file type
    file_ext = config_file.suffix.lower()

    # Use getattr for backward compatibility with external callers that
    # construct Namespace objects without the newer arguments.
    history_dir = getattr(args, 'history_dir', None)
    regression_threshold = getattr(args, 'regression_threshold', 1.5)
    var_list = getattr(args, 'var', [])
    variables = _parse_vars(var_list)
    update_baseline = getattr(args, 'update_baseline', False)
    update_history = getattr(args, 'update_history', False)
    error_analysis = getattr(args, 'error_analysis', False)
    error_analysis_all = getattr(args, 'error_analysis_all', False)
    if error_analysis_all:
        error_analysis = True
    last_failed = getattr(args, 'last_failed', False)
    resume = getattr(args, 'resume', False)
    plugin_dirs = getattr(args, 'plugin_dirs', None)

    try:
        if args.parallel:
            # Format-aware parallel runner selection
            if file_ext in ['.json']:
                runner = ParallelJSONRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    max_workers=args.workers,
                    execution_mode=args.execution_mode,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    history_dir=history_dir,
                    regression_threshold=regression_threshold,
                    variables=variables,
                    update_baseline=update_baseline,
                    update_history=update_history,
                    error_analysis=error_analysis,
                    error_analysis_all=error_analysis_all,
                    last_failed=last_failed,
                    resume=resume,
                    plugin_dirs=plugin_dirs,
                )
            elif file_ext in ['.yaml', '.yml']:
                runner = ParallelYAMLRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    max_workers=args.workers,
                    execution_mode=args.execution_mode,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    history_dir=history_dir,
                    regression_threshold=regression_threshold,
                    variables=variables,
                    update_baseline=update_baseline,
                    update_history=update_history,
                    error_analysis=error_analysis,
                    error_analysis_all=error_analysis_all,
                    last_failed=last_failed,
                    resume=resume,
                    plugin_dirs=plugin_dirs,
                )
            else:
                logger.error("Unsupported configuration file format for parallel mode: %s", file_ext)
                return False
        else:
            # Use appropriate single-threaded runner
            if file_ext in ['.json']:
                runner = JSONRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    history_dir=history_dir,
                    regression_threshold=regression_threshold,
                    variables=variables,
                    update_baseline=update_baseline,
                    update_history=update_history,
                    error_analysis=error_analysis,
                    error_analysis_all=error_analysis_all,
                    last_failed=last_failed,
                    resume=resume,
                    plugin_dirs=plugin_dirs,
                )
            elif file_ext in ['.yaml', '.yml']:
                runner = YAMLRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    history_dir=history_dir,
                    regression_threshold=regression_threshold,
                    variables=variables,
                    update_baseline=update_baseline,
                    update_history=update_history,
                    error_analysis=error_analysis,
                    error_analysis_all=error_analysis_all,
                    last_failed=last_failed,
                    resume=resume,
                    plugin_dirs=plugin_dirs,
                )
            else:
                logger.error("Unsupported configuration file format: %s", file_ext)
                return False

        # Run tests
        logger.info("Running tests from: %s", config_file)
        if args.parallel:
            logger.info("Parallel mode: %s, workers: %s", args.execution_mode, args.workers or "auto")

        success = runner.run_tests()

        # Output results using ReportGenerator and honor --output-format
        if hasattr(runner, 'results'):
            results = runner.results

            # ── Reporting 装配点（原则 5）：next_action_hint 在报告输出前
            # 按 failure_kind 填充，orchestration 只产出失败结论 ──
            attach_next_action_hints(
                results,
                update_baseline=bool(getattr(args, 'update_baseline', False)),
                config_path=str(config_file),
            )

            output_format = getattr(args, 'output_format', 'text')

            if output_format == 'json':
                print(json.dumps(results, indent=2, ensure_ascii=False))
            elif output_format == 'html':
                report_gen = ReportGenerator(results, '')
                text_report = report_gen.generate_report()
                html = _format_results_html(results, text_report)
                print(html)
            else:
                report_gen = ReportGenerator(results, '')
                report_gen.print_report()

        # --- JUnit XML output (supplementary, works alongside any --output-format) ---
        junit_xml_path = getattr(args, 'junit_xml', None)
        if junit_xml_path and hasattr(runner, 'results'):
            suite_name = config_file.stem
            write_junit_xml(runner.results, junit_xml_path, suite_name=suite_name)
            logger.info("JUnit XML report written to: %s", junit_xml_path)

        return success

    except Exception as e:
        logger.error("Error running tests: %s", e)
        if args.debug:
            import traceback
            traceback.print_exc()
        return False


def _format_results_html(results, text_report):
    """Format test results as a basic HTML page."""
    escaped_report = text_report.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    pass_pct = (results['passed'] / max(results['total'], 1)) * 100
    xfailed = results.get('xfailed', 0)
    xpassed = results.get('xpassed', 0)
    extras = ""
    if xfailed:
        extras += f" | XFailed: <span class=\"xfailed\">{xfailed}</span>"
    if xpassed:
        extras += f" | XPassed: <span class=\"xpassed\">{xpassed} (unexpected!)</span>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Test Results</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; }}
  .summary {{ margin-bottom: 1em; }}
  .passed {{ color: green; }}
  .failed {{ color: red; }}
  .xfailed {{ color: orange; }}
  .xpassed {{ color: red; font-weight: bold; }}
  pre {{ background: #f5f5f5; padding: 1em; border-radius: 4px; }}
</style>
</head>
<body>
<h1>CLI Test Results</h1>
<div class="summary">
  <p>Total: {results['total']} | Passed: <span class="passed">{results['passed']}</span> | Failed: <span class="failed">{results['failed']}</span>{extras}</p>
  <p>Pass rate: {pass_pct:.1f}%</p>
</div>
<pre>{escaped_report}</pre>
</body>
</html>"""


def register_parser(subparsers):
    """Register the ``run`` subcommand on the root parser."""
    run_parser = subparsers.add_parser('run', help='Run test cases from a configuration file')
    run_parser.add_argument('config_file', help='Path to the test configuration file (JSON or YAML)')
    run_parser.add_argument('--workspace', '-w', help='Working directory for test execution')
    run_parser.add_argument('--parallel', '-p', action='store_true', help='Run tests in parallel')
    run_parser.add_argument('--workers', type=int, help='Number of parallel workers (default: CPU count)')
    run_parser.add_argument('--execution-mode', choices=['thread', 'process'], default='thread',
                           help='Parallel execution mode (default: thread)')
    run_parser.add_argument('--output-format', choices=['text', 'json', 'html'], default='text',
                           help='Output format for test results')
    run_parser.add_argument('--test-case', '-t', action='append', default=None,
                           help='Run only specified test case(s) by name (can be used multiple times)')
    run_parser.add_argument('--tag', action='append', default=None,
                           help='Run only test cases with matching tag(s) (can be used multiple times)')
    run_parser.add_argument('--history-dir',
                           help='Directory for .symtest runtime history (enables smart scheduling & regression detection)')
    run_parser.add_argument('--regression-threshold', type=float, default=1.5,
                           help='Warn if a case runs N times slower than historical average (default: 1.5)')
    run_parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    run_parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    run_parser.add_argument('--junit-xml', dest='junit_xml',
                           help='Write JUnit XML report to the specified file path')
    run_parser.add_argument('--var', action='append', default=[],
                           metavar='KEY=VALUE',
                           help='Set a variable for config placeholder substitution, '
                                'e.g. --var solver=/path/to/solver '
                                '(can be used multiple times)')
    run_parser.add_argument('--last-failed', action='store_true',
                           help='Run only test cases that failed in the previous run')
    run_parser.add_argument('--update-baseline', action='store_true',
                           help='On comparison failure, overwrite baseline files with actual output')
    run_parser.add_argument('--yes', '-y', action='store_true',
                           help='Confirm potentially destructive actions without prompting '
                                '(required with --update-baseline in non-interactive environments)')
    run_parser.add_argument('--update-history', action='store_true',
                           help='Clear .symtest runtime history for run-involved cases before '
                                'recording this run (requires --history-dir)')
    run_parser.add_argument('--resume', action='store_true',
                           help='Resume sequence test cases from last failed step '
                                '(trusts workspace artifacts are unchanged)')
    run_parser.add_argument('--error-analysis', action='store_true',
                           help='Enable streaming error statistics for numerical file comparisons '
                                '(CSV/H5): total_numeric_cells, mismatched_cells, '
                                'max_abs/rel_error, mean/rms_abs_error')
    run_parser.add_argument('--error-analysis-all', action='store_true',
                           help='Like --error-analysis, but also report error statistics for '
                                'PASSED file comparisons in the report (implies --error-analysis)')
    run_parser.add_argument('--plugin-dir', action='append', default=None,
                           dest='plugin_dirs',
                           help='Add a directory for workspace-level comparator plugins '
                                '(can be used multiple times). '
                                'The workspace/comparators/ directory is always auto-detected.')
