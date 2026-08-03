# Test Case Field Reference

## Top-level Config Structure

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `setup` | object | No | Global setup config (env vars, plugins) |
| `test_cases` | array | Yes | List of test cases and/or `import` entries |

## Test Case Fields

### Core

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Test case name (unique identifier) |
| `command` | string | Yes* | Command to execute (*not needed if `extends` or `steps`) |
| `args` | array | No | Command arguments list |
| `description` | string | No | Test case description |
| `timeout` | int/null | No | Timeout in seconds (default 3600, null = unlimited) |
| `retry_count` | int | No | Auto-retry count on failure (default 0) |
| `tags` | array | No | Tags for filtering (e.g., `["smoke", "fast"]`) |

### Inheritance

| Field | Type | Description |
|-------|------|-------------|
| `abstract` | bool | If true, this is a template (not executed) |
| `extends` | string | Name of base case to inherit from |
| `variables` | object | Case-level placeholder variables for `{key}` substitution |

### xfail (Expected Failure)

| Field | Type | Description |
|-------|------|-------------|
| `expected_failure` | bool | Mark as expected-to-fail |
| `xfail_reason` | string | Reason text shown in report |
| `xfail_quiet` | bool | Suppress command output in xfailed report |

### Resources

| Field | Type | Description |
|-------|------|-------------|
| `resources.cpu_cores` | int | CPU cores needed (default 1) |
| `resources.estimated_time` | int | Estimated duration in seconds (for LPT scheduling) |
| `resources.min_memory_mb` | int | Estimated memory in MB (logging only) |
| `resources.priority` | int | Priority 0-10 (informational) |

### expected (Assertions)

| Field | Type | Description |
|-------|------|-------------|
| `expected.return_code` | int | Expected exit code |
| `expected.output_contains` | array | Strings that must appear in stdout |
| `expected.output_matches` | string | Regex pattern for stdout |
| `expected.compare_files` | array | File comparison rules (see below) |

### compare_files entries

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `actual` | string | Yes | Actual output file path |
| `baseline` | string | Yes | Baseline/reference file path |
| `type` | string | No | Comparator type. Built-in: text/json/csv/xml/h5/binary/script. Custom types map to user plugins in `<workspace>/comparators/*_comparator.py` — when troubleshooting an unknown type, inspect those plugin files first. |
| `start_line` | int | No | Start line (1-based) |
| `end_line` | int | No | End line (1-based) |
| `start_column` | int | No | Start column (1-based) |
| `end_column` | int | No | End column (1-based) |
| `rtol` | float | No | Relative tolerance (csv/h5) |
| `atol` | float | No | Absolute tolerance (csv/h5) |
| `tables` | array | No | HDF5 table paths to compare |
| `encoding` | string | No | Text encoding (default utf-8) |
| `error_analysis` | bool | No | Enable full error statistics (csv/h5) |

### steps (Sequence Mode)

Each step has: `command`, `args`, `expected`, `timeout`, `retry_count`.
Case-level `expected` runs only if all steps pass.

### import (Config Splitting)

```json
{"import": "cases/sub_tests.json", "tags": ["module"]}
```
- Path relative to main config file's directory.
- `tags` inject into all imported cases (merged with case-level tags).
- Supports nested imports; circular references are detected.

## Result Status Values

| Status | Meaning | Exit Code Impact |
|--------|---------|------------------|
| `passed` | All assertions passed | Success |
| `failed` | Assertion(s) failed | Failure |
| `timeout` | Exceeded timeout | Failure |
| `xfailed` | Expected failure (failed as expected) | Success |
| `xpassed` | Unexpected pass (xfail marked but passed) | Failure |

## failure_kind Values

| Value | Meaning |
|-------|---------|
| `return_code` | Exit code mismatch |
| `output_contains` | Missing expected string in output |
| `output_matches` | Regex pattern not matched |
| `file_compare` | File comparison failed |
| `timeout` | Command timed out |
| `execution_error` | Command could not be executed |
