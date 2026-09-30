#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""``symtest schema`` subcommand: print the JSON Schema for test
configuration files (machine-readable contract for generating configs).
"""

import json

from ..config.config_schema import get_config_schema


def run_schema(args=None) -> None:
    """Print the JSON Schema for test configuration files."""
    print(json.dumps(get_config_schema(), indent=2, ensure_ascii=False))


def register_parser(subparsers):
    """Register the ``schema`` subcommand on the root parser."""
    subparsers.add_parser(
        'schema',
        help='Print the JSON Schema for test configuration files '
             '(machine-readable contract for generating configs)',
    )
