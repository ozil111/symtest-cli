"""JSON Schema (draft 2020-12) for cli-test configuration files.

Single source of truth for AI agents (and humans) that *generate* test
configs.  Exposed via ``cli-test schema``.

Keep in sync with:
- ``core.config_loader.parse_test_cases`` (accepted fields)
- ``config.config_io.validate_config`` (required fields)
- ``docs/user_manual.md`` (documented behavior)
"""

from __future__ import annotations

import copy
from typing import Any, Dict

CONFIG_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "cli-test configuration",
    "description": (
        "Test suite configuration for the cli-test framework. "
        "YAML files follow the same structure (YAML is a JSON superset)."
    ),
    "type": "object",
    "required": ["test_cases"],
    "additionalProperties": False,
    "properties": {
        "setup": {
            "type": "object",
            "additionalProperties": False,
            "description": "Suite-level setup applied before any test runs.",
            "properties": {
                "environment_variables": {
                    "type": "object",
                    "description": "Environment variables injected into every test command.",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
        "test_cases": {
            "type": "array",
            "description": "List of test cases, sequence cases, or import references.",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/singleCase"},
                    {"$ref": "#/$defs/sequenceCase"},
                    {"$ref": "#/$defs/importRef"},
                ],
            },
        },
    },
    "$defs": {
        "expected": {
            "type": "object",
            "additionalProperties": False,
            "description": (
                "Assertions evaluated after the command finishes. "
                "All declared assertions must pass; the combined "
                "stdout+stderr output is used for output assertions."
            ),
            "properties": {
                "return_code": {
                    "type": ["integer", "null"],
                    "description": "Expected process exit code.",
                },
                "output_contains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Strings that must each appear in the command output.",
                },
                "output_matches": {
                    "type": ["string", "null"],
                    "description": "Regex (re.search) the command output must match.",
                },
                "compare_files": {
                    "type": "array",
                    "description": "File comparison assertions against golden/baseline files.",
                    "items": {"$ref": "#/$defs/compareSpec"},
                },
            },
        },
        "compareSpec": {
            "type": "object",
            "required": ["actual", "baseline"],
            "additionalProperties": True,
            "description": (
                "One file comparison rule. Keys other than actual/baseline/type/"
                "start_line/end_line/start_column/end_column are forwarded to the "
                "comparator as kwargs (e.g. rtol, atol, encoding, tables, data_filter)."
            ),
            "properties": {
                "actual": {
                    "type": "string",
                    "description": "File produced by the test command (relative paths resolve against the workspace).",
                },
                "baseline": {
                    "type": "string",
                    "description": "Golden/reference file (relative paths resolve against the workspace).",
                },
                "type": {
                    "type": "string",
                    "description": (
                        "Comparator type. Built-ins: text, json, csv, xml, h5, binary. "
                        "Omit to auto-detect from the file extension. "
                        "Custom registered comparator types are also allowed."
                    ),
                },
                "start_line": {"type": "integer", "minimum": 1, "description": "Only compare from this line (1-based)."},
                "end_line": {"type": "integer", "minimum": 1, "description": "Only compare up to this line (1-based)."},
                "start_column": {"type": "integer", "minimum": 1, "description": "Only compare from this column (1-based)."},
                "end_column": {"type": "integer", "minimum": 1, "description": "Only compare up to this column (1-based)."},
            },
        },
        "resources": {
            "type": "object",
            "additionalProperties": False,
            "description": "Optional scheduling hints (parallel mode).",
            "properties": {
                "estimated_time": {"type": "number", "description": "Estimated duration in seconds; used for LPT ordering."},
                "min_memory_mb": {"type": "number", "description": "Soft memory hint to avoid OOM."},
                "priority": {"type": "integer", "description": "Higher value => higher priority."},
                "cpu_cores": {"type": "integer", "minimum": 1, "description": "CPU cores required by this task."},
            },
        },
        "step": {
            "type": "object",
            "required": ["command", "args", "expected"],
            "additionalProperties": False,
            "properties": {
                "command": {"type": "string"},
                "args": {
                    "type": "array",
                    "items": {"type": ["string", "number", "boolean"]},
                },
                "expected": {"$ref": "#/$defs/expected"},
                "timeout": {"type": ["number", "null"], "description": "Per-step timeout in seconds."},
                "retry_count": {"type": "integer", "minimum": 0, "description": "Per-step retry count on failure."},
            },
        },
        "singleCase": {
            "type": "object",
            "required": ["name", "command", "args", "expected"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "description": "Unique test case name."},
                "command": {
                    "type": "string",
                    "description": (
                        "Command to execute. May include leading arguments "
                        "(e.g. 'python ./run.py'); the framework splits and "
                        "path-resolves them."
                    ),
                },
                "args": {
                    "type": "array",
                    "items": {"type": ["string", "number", "boolean"]},
                },
                "expected": {"$ref": "#/$defs/expected"},
                "description": {"type": ["string", "null"]},
                "timeout": {
                    "type": ["number", "null"],
                    "description": "Timeout in seconds (default 3600); null = no limit.",
                },
                "retry_count": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Retries after the first failure; passing after retry marks the result flaky.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for --tag filtering.",
                },
                "resources": {"$ref": "#/$defs/resources"},
                "expected_failure": {
                    "type": "boolean",
                    "description": (
                        "Mark this case as an expected failure (xfail). "
                        "When true, a failure counts as XFailed (not a suite failure); "
                        "an unexpected pass counts as XPassed (suite failure)."
                    ),
                },
                "xfail_reason": {
                    "type": "string",
                    "description": "Optional reason displayed in the report alongside XFailed results.",
                },
            },
        },
        "sequenceCase": {
            "type": "object",
            "required": ["name", "steps"],
            "additionalProperties": False,
            "description": (
                "Multi-step case: steps run in order with fail-fast semantics. "
                "The case-level 'expected' is evaluated once after all steps pass."
            ),
            "properties": {
                "name": {"type": "string"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/step"},
                },
                "expected": {
                    "$ref": "#/$defs/expected",
                    "description": "Optional case-level assertions (e.g. compare_files on produced files), evaluated after all steps pass.",
                },
                "description": {"type": ["string", "null"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "resources": {"$ref": "#/$defs/resources"},
                "expected_failure": {
                    "type": "boolean",
                    "description": (
                        "Mark this case as an expected failure (xfail). "
                        "When true, a failure counts as XFailed (not a suite failure); "
                        "an unexpected pass counts as XPassed (suite failure)."
                    ),
                },
                "xfail_reason": {
                    "type": "string",
                    "description": "Optional reason displayed in the report alongside XFailed results.",
                },
            },
        },
        "importRef": {
            "type": "object",
            "required": ["import"],
            "additionalProperties": False,
            "description": "Inline another config file (path relative to this file).",
            "properties": {
                "import": {"type": "string"},
            },
        },
    },
}


def get_config_schema() -> Dict[str, Any]:
    """Return a deep copy of the config JSON Schema (safe to mutate)."""
    return copy.deepcopy(CONFIG_SCHEMA)
