#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SymTest - Command Line Interface

Thin entry point: root parser construction + command dispatch only.
Per-command argument definitions and handlers live in ``symtest.commands.*``;
each command module exposes ``register_parser(subparsers)`` and a handler.
"""

import argparse
import logging
import sys

from .commands import compare as compare_cmd
from .commands import find as find_cmd
from .commands import migrate as migrate_cmd
from .commands import run as run_cmd
from .commands import schema as schema_cmd
from .commands import validate as validate_cmd
from .logging_config import setup_console_logging

logger = logging.getLogger("symtest.cli")

# Re-exported handlers: ``symtest.cli`` remains the public import surface
# (docs reference these names; tests and external callers patch/use them).
run_tests = run_cmd.run_tests
run_find = find_cmd.run_find
run_validate = validate_cmd.run_validate
run_schema = schema_cmd.run_schema
run_migrate = migrate_cmd.run_migrate
run_compare = compare_cmd.run_compare
# Private helpers kept importable from cli for backward compatibility.
_parse_vars = run_cmd._parse_vars
_confirm_baseline_update = run_cmd._confirm_baseline_update
_format_results_html = run_cmd._format_results_html

_EPILOG = """
Examples:
  symtest run test_cases.json
  symtest run test_cases.json --parallel --workers 4
  symtest run test_cases.yaml --workspace /path/to/project
  symtest find main_config.json "login"
  symtest validate main_config.json
  symtest migrate old.json --output new.json
  symtest compare file1.json file2.json
  symtest compare file1.txt file2.txt --output-format json
"""


def create_parser():
    """Create the root argument parser and register all subcommands."""
    parser = argparse.ArgumentParser(
        description="Regression testing for command-line applications and scientific workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    run_cmd.register_parser(subparsers)
    find_cmd.register_parser(subparsers)
    validate_cmd.register_parser(subparsers)
    schema_cmd.register_parser(subparsers)
    migrate_cmd.register_parser(subparsers)
    compare_cmd.register_parser(subparsers)

    return parser


def _to_exit_code(result) -> int:
    """Single exit-code conversion point for all sub-command handlers.

    Handlers return either a bool (``False`` = failure → 1), an int exit
    code directly (commands with richer semantics, e.g. ``find``:
    0 = match, 1 = no match, 2 = error), or ``None`` (treated as success,
    e.g. ``schema``). No branch in ``main`` should convert codes itself.
    """
    if result is None:
        return 0
    if isinstance(result, bool):
        return 0 if result else 1
    return int(result)


def main():
    """Main entry point for the CLI"""
    parser = create_parser()
    args = parser.parse_args()

    # Activate console logging (stderr) and honour verbosity flags.
    level = logging.DEBUG if (
        getattr(args, 'debug', False) or getattr(args, 'verbose', False)
    ) else logging.INFO
    setup_console_logging(level=level)

    handlers = {
        # 'run': 0 = all passed, 1 = test failures, 2 = config/framework errors
        'run': run_tests,
        # 'find': grep-style exit codes: 0 = match, 1 = no match, 2 = error
        'find': run_find,
        # 'validate': 0 = valid, 1 = validation errors found
        'validate': run_validate,
        'schema': run_schema,
        # 'migrate': 0 = migrated, 1 = input/format errors
        'migrate': run_migrate,
        'compare': run_compare,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(_to_exit_code(handler(args)))


if __name__ == '__main__':
    main()
