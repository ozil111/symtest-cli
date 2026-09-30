#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""``symtest validate`` subcommand: validate a test configuration
without running tests.

Extracted from ``cli.py`` so the CLI entry point stays a thin
parser + dispatch layer.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("symtest.commands.validate")


def run_validate(args):
    """Validate test configuration without running tests."""
    workspace_path = Path(args.workspace) if args.workspace else Path.cwd()
    config_file = (workspace_path / args.config_file).resolve()

    if not config_file.exists():
        logger.error("Configuration file not found: %s", config_file)
        return False

    logger.info("Validating configuration: %s", config_file)
    # Imported inside the function so tests can patch
    # ``symtest.config.config_io.validate_config``.
    from ..config.config_io import validate_config

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


def register_parser(subparsers):
    """Register the ``validate`` subcommand on the root parser."""
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
