#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CLI Test Framework - Command Line Interface

This module provides the main command-line interface for the CLI Testing Framework.
"""

import argparse
import json
import sys
import os
import logging
from pathlib import Path

from .logging_config import setup_console_logging
from .runners import JSONRunner, ParallelJSONRunner, ParallelYAMLRunner, YAMLRunner
from .utils.report_generator import ReportGenerator
from .utils.junit_xml_writer import write_junit_xml

logger = logging.getLogger("cli_test_framework.cli")


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


def create_parser():
    """Create and configure the argument parser"""
    parser = argparse.ArgumentParser(
        description="CLI Testing Framework - A powerful tool for testing command-line applications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cli-test run test_cases.json
  cli-test run test_cases.json --parallel --workers 4
  cli-test run test_cases.yaml --workspace /path/to/project
  cli-test tui test_cases.json
  cli-test validate main_config.json
  cli-test compare file1.json file2.json
  cli-test compare file1.txt file2.txt --output-format json
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # ---- Run command ----
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
    run_parser.add_argument('--resume', action='store_true',
                           help='Resume sequence test cases from last failed step '
                                '(trusts workspace artifacts are unchanged)')
    run_parser.add_argument('--error-analysis', action='store_true',
                           help='Enable streaming error statistics for numerical file comparisons '
                                '(CSV/H5): total_numeric_cells, mismatched_cells, '
                                'max_abs/rel_error, mean/rms_abs_error')
    run_parser.add_argument('--plugin-dir', action='append', default=None,
                           dest='plugin_dirs',
                           help='Add a directory for workspace-level comparator plugins '
                                '(can be used multiple times). '
                                'The workspace/comparators/ directory is always auto-detected.')

    # ---- TUI command ----
    tui_parser = subparsers.add_parser(
        'tui', help='Launch interactive TUI for managing test cases'
    )
    tui_parser.add_argument(
        'config_file', help='Path to the test configuration file (JSON or YAML)'
    )
    tui_parser.add_argument(
        '--workspace', '-w', help='Working directory'
    )
    tui_parser.add_argument(
        '--update-baseline', action='store_true',
        help='On comparison failure, overwrite baseline files with actual output'
    )

    # ---- Validate command ----
    validate_parser = subparsers.add_parser(
        'validate', help='Validate test configuration without running tests'
    )
    validate_parser.add_argument(
        'config_file', help='Path to the test configuration file (JSON or YAML)'
    )
    validate_parser.add_argument(
        '--workspace', '-w', help='Working directory'
    )
    validate_parser.add_argument(
        '--output-format', choices=['text', 'json'], default='text',
        help='Output format for validation results (default: text)'
    )

    # ---- Schema command ----
    subparsers.add_parser(
        'schema',
        help='Print the JSON Schema for test configuration files '
             '(machine-readable contract for generating configs)',
    )

    # ---- Compare command ----
    compare_parser = subparsers.add_parser('compare', help='Compare two files')
    compare_parser.add_argument('file1', help='Path to the first file')
    compare_parser.add_argument('file2', help='Path to the second file')
    compare_parser.add_argument('--start-line', type=int, default=1, help='Starting line number (1-based)')
    compare_parser.add_argument('--end-line', type=int, help='Ending line number (1-based)')
    compare_parser.add_argument('--start-column', type=int, default=1, help='Starting column number (1-based)')
    compare_parser.add_argument('--end-column', type=int, help='Ending column number (1-based)')
    compare_parser.add_argument('--file-type', help='Type of the files to compare', default='auto')
    compare_parser.add_argument('--encoding', default='utf-8', help='File encoding for text files')
    compare_parser.add_argument('--chunk-size', type=int, default=8192, help='Chunk size for binary comparison')
    compare_parser.add_argument('--output-format', choices=['text', 'json', 'html'], default='text',
                               help='Output format for the comparison result')
    compare_parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    compare_parser.add_argument('--debug', action='store_true', help='Enable debug mode with detailed logging')
    compare_parser.add_argument('--similarity', action='store_true',
                               help='When comparing binary files, compute and show similarity index')
    compare_parser.add_argument('--num-threads', type=int, default=4, help='Number of threads for parallel processing')

    # CSV comparison options
    csv_group = compare_parser.add_argument_group('CSV comparison options')
    csv_group.add_argument('--csv-rtol', type=float, default=1e-5,
                          help='Relative tolerance for numerical comparison in CSV files')
    csv_group.add_argument('--csv-atol', type=float, default=1e-8,
                          help='Absolute tolerance for numerical comparison in CSV files')
    csv_group.add_argument('--csv-delimiter', default=',', help='CSV field delimiter (default: comma)')
    csv_group.add_argument('--csv-quotechar', default='"',
                          help='Character used for quoting fields in CSV (default: double quote)')
    csv_group.add_argument('--csv-data-filter', type=str,
                          help='Data filter to apply before comparison. '
                               "Example: '>1e-6', '<=0.01', 'abs>1e-9'. "
                               'Filters out numeric cells that do not meet the criteria '
                               'from BOTH files before comparison.')

    # JSON comparison options
    json_group = compare_parser.add_argument_group('JSON comparison options')
    json_group.add_argument('--json-compare-mode', choices=['exact', 'key-based'], default='exact',
                           help='JSON comparison mode: exact (default) or key-based')
    json_group.add_argument('--json-key-field', help='Key field(s) to use for key-based JSON comparison')

    # H5 comparison options
    h5_group = compare_parser.add_argument_group('HDF5 comparison options')
    h5_group.add_argument('--h5-table', help='Comma-separated list of table names to compare in HDF5 files')
    h5_group.add_argument('--h5-table-regex',
                         help='Comma-separated list of regular expression patterns to match table names in HDF5 files')
    h5_group.add_argument('--h5-structure-only', action='store_true',
                         help='Only compare HDF5 file structure without comparing content')
    h5_group.add_argument('--h5-show-content-diff', action='store_true',
                         help='Show detailed content differences when content differs')
    h5_group.add_argument('--h5-rtol', type=float, default=1e-5,
                         help='Relative tolerance for numerical comparison in HDF5 files')
    h5_group.add_argument('--h5-atol', type=float, default=1e-8,
                         help='Absolute tolerance for numerical comparison in HDF5 files')
    h5_group.add_argument('--h5-data-filter', type=str,
                         help='Data filter to apply before comparison')
    h5_group.add_argument('--h5-no-expand-path', dest='h5_expand_path', action='store_false',
                         help='Do not expand HDF5 group paths to compare all sub-items')

    return parser


def run_tests(args):
    """Run tests based on command line arguments"""
    # Resolve config_file relative to workspace if specified, otherwise cwd.
    # This matches BaseRunner's resolution (workspace / config_file).
    workspace_path = Path(args.workspace) if args.workspace else Path.cwd()
    config_file = (workspace_path / args.config_file).resolve()

    if not config_file.exists():
        logger.error("Configuration file not found: %s", config_file)
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
    error_analysis = getattr(args, 'error_analysis', False)
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
                    error_analysis=error_analysis,
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
                    error_analysis=error_analysis,
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
                    error_analysis=error_analysis,
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
                    error_analysis=error_analysis,
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


def run_compare(args):
    """Execute file comparison via the compare subcommand."""
    from .commands.compare import run_comparison
    exit_code = run_comparison(args)
    return bool(exit_code == 0)


def run_tui(args):
    """Launch the TUI manager."""
    from .tui.app import run_tui as _run_tui

    update_baseline = getattr(args, 'update_baseline', False)
    _run_tui(args.config_file, args.workspace, update_baseline=update_baseline)


def run_validate(args):
    """Validate test configuration without running tests."""
    from .config.config_io import validate_config

    workspace_path = Path(args.workspace) if args.workspace else Path.cwd()
    config_file = (workspace_path / args.config_file).resolve()

    if not config_file.exists():
        logger.error("Configuration file not found: %s", config_file)
        return False

    logger.info("Validating configuration: %s", config_file)
    report = validate_config(config_file, args.workspace)

    output_format = getattr(args, 'output_format', 'text')

    if output_format == 'json':
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        # Print summary
        summary = report["summary"]
        print(f"\n  [OK] Loaded {summary['cases']} test cases from {summary['files']} file(s)\n")

        if report["errors"]:
            for err in report["errors"]:
                print(f"  [FAIL] {err}")
            print()
        else:
            print("  [OK] All required fields present")
            print("  [OK] No circular imports detected")

        if report.get("warnings"):
            print()
            for warn in report["warnings"]:
                print(f"  [WARN] {warn}")
            print()

        if summary.get("files_loaded"):
            print("\n  Files:")
            for f in summary["files_loaded"]:
                print(f"    - {f}")
        print()

    return report["valid"]


def run_schema() -> None:
    """Print the JSON Schema for test configuration files."""
    from .config.config_schema import get_config_schema

    print(json.dumps(get_config_schema(), indent=2, ensure_ascii=False))


def main():
    """Main entry point for the CLI"""
    parser = create_parser()
    args = parser.parse_args()

    # Activate console logging (stderr) and honour verbosity flags.
    level = logging.DEBUG if (
        getattr(args, 'debug', False) or getattr(args, 'verbose', False)
    ) else logging.INFO
    setup_console_logging(level=level)

    if args.command == 'run':
        success = run_tests(args)
        # 0 = all passed, 1 = test failures, 2 = config/framework errors
        sys.exit(0 if success else 1)
    elif args.command == 'tui':
        run_tui(args)
    elif args.command == 'validate':
        success = run_validate(args)
        # 0 = valid, 1 = validation errors found
        sys.exit(0 if success else 1)
    elif args.command == 'schema':
        run_schema()
        sys.exit(0)
    elif args.command == 'compare':
        success = run_compare(args)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
