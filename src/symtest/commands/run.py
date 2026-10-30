#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""``symtest run`` subcommand: run options, runner selection and reporting.

Extracted from ``cli.py`` so the CLI entry point stays a thin
parser + dispatch layer.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from ..reporting.diagnosis import attach_next_action_hints
from ..runners import JSONRunner, ParallelJSONRunner, ParallelYAMLRunner, YAMLRunner
from ..utils.project_config import (
    ProjectConfigError,
    load_project_config,
    merge_project_config,
    resolve_path,
)
from ..utils.report_generator import ReportGenerator
from ..utils.html_report import generate_html_report
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

    # Project-level defaults: CLI values win, then the selected defaults
    # file (.symtest/symtest.json by default, replaced entirely by an
    # explicit --defaults FILE), then built-in defaults. --no-config skips
    # any defaults file and applies built-in defaults only. An explicit
    # --defaults file is validated strictly and aborts the run on problems,
    # so it can never silently fall back to another set of settings.
    if getattr(args, 'no_config', False):
        logger.info("--no-config: ignoring project configuration")
        merge_project_config(args, {}, workspace_path)
    else:
        try:
            project_config = load_project_config(
                workspace_path,
                explicit_path=getattr(args, 'defaults', None),
            )
        except ProjectConfigError as exc:
            logger.error("%s", exc)
            return False
        merge_project_config(args, project_config, workspace_path)

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
    with_deps = getattr(args, 'with_deps', False)
    plugin_dirs = getattr(args, 'plugin_dirs', None)

    # 机会式内存准入参数（symtest.json run 段；CLI 第一版不提供旗标）。
    # None → 不传，由 runner 应用内置默认值。
    memory_keys = (
        'memory_margin', 'memory_commit_reserve_mb',
        'memory_physical_watermark_mb', 'memory_default_demand_mb',
        'memory_min_start_interval_s',
    )
    memory_kwargs = {
        key: getattr(args, key)
        for key in memory_keys
        if getattr(args, key, None) is not None
    }

    try:
        if args.parallel:
            # Format-aware parallel runner selection
            if file_ext in ['.json', '.jsonc']:
                runner = ParallelJSONRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    max_workers=args.workers,
                    execution_mode=args.execution_mode,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    with_deps=with_deps,
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
                    **memory_kwargs,
                )
            elif file_ext in ['.yaml', '.yml']:
                runner = ParallelYAMLRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    max_workers=args.workers,
                    execution_mode=args.execution_mode,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    with_deps=with_deps,
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
                    **memory_kwargs,
                )
            else:
                logger.error("Unsupported configuration file format for parallel mode: %s", file_ext)
                return False
        else:
            # Use appropriate single-threaded runner
            if file_ext in ['.json', '.jsonc']:
                runner = JSONRunner(
                    config_file=str(config_file),
                    workspace=args.workspace,
                    test_case_filter=args.test_case,
                    test_case_tag_filter=args.tag,
                    with_deps=with_deps,
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
                    with_deps=with_deps,
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

            output_format = getattr(args, 'output_format', 'none')

            # Channel separation: the console is the log channel only
            # (progress + summary from the runner's logging). Reports reach
            # stdout solely via an explicit --output-format, or are written
            # to files via --text-report / --html-report / --junit-xml.
            # Redirected pipes/files default to the ANSI codepage on Windows
            # (e.g. GBK), which cannot encode status symbols like "✓";
            # degrade to replacement instead of crashing the whole run.
            if output_format != 'none' and hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(errors="replace")
            if output_format == 'json':
                print(json.dumps(results, indent=2, ensure_ascii=False))
            elif output_format == 'html':
                print(generate_html_report(results))
            elif output_format == 'text':
                print(ReportGenerator(results, '').generate_report())

        # --- JUnit XML output (supplementary, works alongside any --output-format) ---
        junit_xml_path = getattr(args, 'junit_xml', None)
        if junit_xml_path and hasattr(runner, 'results'):
            suite_name = config_file.stem
            resolved_junit = resolve_path(junit_xml_path, workspace_path)
            Path(resolved_junit).parent.mkdir(parents=True, exist_ok=True)
            write_junit_xml(runner.results, resolved_junit, suite_name=suite_name)
            logger.info("JUnit XML report written to: %s", resolved_junit)

        # --- HTML report output (supplementary, works alongside any --output-format) ---
        html_report_path = getattr(args, 'html_report', None)
        if html_report_path and hasattr(runner, 'results'):
            resolved_html = resolve_path(html_report_path, workspace_path)
            Path(resolved_html).parent.mkdir(parents=True, exist_ok=True)
            with open(resolved_html, 'w', encoding='utf-8') as f:
                f.write(generate_html_report(runner.results))
            logger.info("HTML report written to: %s", resolved_html)

        # --- Text report output (supplementary, works alongside any --output-format) ---
        text_report_path = getattr(args, 'text_report', None)
        if text_report_path and hasattr(runner, 'results'):
            resolved_text = resolve_path(text_report_path, workspace_path)
            Path(resolved_text).parent.mkdir(parents=True, exist_ok=True)
            ReportGenerator(runner.results, resolved_text).save_report()
            logger.info("Text report written to: %s", resolved_text)

        return success

    except Exception as e:
        logger.error("Error running tests: %s", e)
        if args.debug:
            import traceback
            traceback.print_exc()
        return False


def register_parser(subparsers):
    """Register the ``run`` subcommand on the root parser."""
    run_parser = subparsers.add_parser('run', help='Run test cases from a configuration file')
    run_parser.add_argument('config_file', nargs='?', default=None,
                            help='Path to the test configuration file (JSON/JSONC or YAML); '
                                 'omitted: value from project config, otherwise test_cases.json')
    run_parser.add_argument('--workspace', '-w', help='Working directory for test execution '
                                                      '(project config is read from here too)')
    run_parser.add_argument('--parallel', '-p', action=argparse.BooleanOptionalAction, default=None,
                            help='Run tests in parallel (default: from project config, otherwise off)')
    run_parser.add_argument('--workers', type=int, default=None,
                            help='Number of parallel workers (default: from project config, otherwise CPU count)')
    run_parser.add_argument('--execution-mode', choices=['thread', 'process'], default=None,
                            help='Parallel execution mode (default: from project config, otherwise thread)')
    run_parser.add_argument('--output-format', choices=['none', 'text', 'json', 'html'],
                           default='none',
                           help='Report output channel: none (default, console shows '
                                'logs only), text, json or html. text/json/html print '
                                'the report to stdout (redirectable to a file)')
    run_parser.add_argument('--test-case', '-t', action='append', default=None,
                           help='Run only specified test case(s) by name (can be used multiple times)')
    run_parser.add_argument('--tag', action='append', default=None,
                           help='Run only test cases with matching tag(s) (can be used multiple times)')
    run_parser.add_argument('--history-dir',
                           help='Directory for .symtest runtime history (enables smart scheduling '
                                '& regression detection; default: from project config)')
    run_parser.add_argument('--regression-threshold', type=float, default=None,
                           help='Warn if a case runs N times slower than historical average '
                                '(default: from project config, otherwise 1.5)')
    run_parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    run_parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    run_parser.add_argument('--junit-xml', dest='junit_xml',
                           help='Write JUnit XML report to the specified file path '
                                '(default: from project config)')
    run_parser.add_argument('--text-report', dest='text_report',
                            help='Save the text report to the specified file path '
                                 '(supplementary, console output is unaffected; '
                                 'default: from project config; relative paths are '
                                 'resolved against --workspace)')
    run_parser.add_argument('--html-report', dest='html_report',
                            help='Write a self-contained collapsible HTML report to the '
                                 'specified file path (supplementary, console output '
                                 'is unaffected; default: from project config; relative '
                                 'paths are resolved against --workspace)')
    config_group = run_parser.add_mutually_exclusive_group()
    config_group.add_argument('--defaults', default=None, metavar='FILE',
                              help='Use an explicit defaults file (same format as '
                                   '.symtest/symtest.json) instead of the default project '
                                   'config; the file replaces .symtest/symtest.json entirely '
                                   'for this run. Relative paths resolve against --workspace. '
                                   'A missing file, broken JSON or unknown/invalid keys abort '
                                   'the run (no silent fallback)')
    config_group.add_argument('--no-config', dest='no_config', action='store_true',
                              help='Ignore the project configuration (.symtest/symtest.json) '
                                   'for this run and use built-in defaults')
    run_parser.add_argument('--var', action='append', default=[],
                           metavar='KEY=VALUE',
                           help='Set a variable for config placeholder substitution, '
                                'e.g. --var solver=/path/to/solver '
                                '(can be used multiple times)')
    run_parser.add_argument('--last-failed', action='store_true',
                           help='Run only test cases that failed in the previous run')
    run_parser.add_argument('--with-deps', action=argparse.BooleanOptionalAction, default=None,
                            help='When filtering by test case name, automatically include '
                                 'their transitive depends_on dependencies in the run '
                                 '(default: from project config, otherwise off)')
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
    run_parser.add_argument('--error-analysis', action=argparse.BooleanOptionalAction, default=None,
                           help='Enable streaming error statistics for numerical file comparisons '
                                '(CSV/H5): total_numeric_cells, mismatched_cells, '
                                'max_abs/rel_error, mean/rms_abs_error '
                                '(default: from project config, otherwise off)')
    run_parser.add_argument('--error-analysis-all', action=argparse.BooleanOptionalAction, default=None,
                           help='Like --error-analysis, but also report error statistics for '
                                'PASSED file comparisons in the report (implies --error-analysis) '
                                '(default: from project config, otherwise off)')
    run_parser.add_argument('--plugin-dir', action='append', default=None,
                           dest='plugin_dirs',
                           help='Add a directory for workspace-level comparator plugins '
                                '(can be used multiple times). '
                                'The workspace/comparators/ directory is always auto-detected.')
