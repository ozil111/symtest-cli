---
name: cli-test-framework
description: >-
  This skill should be used when writing functional tests for CLI programs,
  defining acceptance criteria, or using the symtest-cli / symtest framework.
  It covers JSON/YAML test case authoring, multi-step sequence tests,
  numerical golden file comparison (HDF5/CSV/XML), parallel execution, and
  targeted re-runs with --last-failed and --resume. Trigger when the task
  involves creating test configurations for command-line tools, writing
  acceptance specs as structured assertions, or running regression tests
  with symtest.
---

# CLI Test Framework (symtest-cli)

## Overview

CLI Test Framework (`symtest-cli`) is a functional testing framework for
command-line programs. It uses a single JSON or YAML configuration file to
describe both the execution workflow and the acceptance criteria. This skill
provides the knowledge needed to author test configurations and run tests.

**Config DSL (Schema v2, 1.4+)**: each test case is layered — execution
semantics live in `execution` (single-command shorthand or `execution.steps`),
validation semantics in top-level `expected`, scheduling semantics
(`depends_on`, `resources`) in `scheduling`. The pre-1.4 flat layout
(`command`/`args`/`steps`/`depends_on` at case top level) was removed; convert
legacy configs with `symtest migrate`.

## When to Use

- Writing functional/regression tests for CLI programs
- Defining machine-readable acceptance criteria for a feature
- Comparing numerical output files (HDF5, CSV) against golden baselines
- Setting up parallel test execution or CI integration

## Core Workflows

### Workflow 1: Authoring Test Cases / Acceptance Criteria

1. Identify the program under test: its `execution.command`, `execution.args`,
   and expected outputs.
2. Choose a test mode:
   - **Single command** — one command, one set of assertions. Use
     `assets/templates/test_cases_simple.json` as the starting point.
   - **Step sequence** — ordered steps with fail-fast. Use
     `assets/templates/test_cases_steps.json` when a test requires multiple
     commands in sequence (e.g., preprocess → solve → postprocess). Steps live
     in `execution.steps`.
3. Fill in the `expected` assertions:
   - `return_code` — expected exit code (default 0).
   - `output_contains` — list of strings that must appear in stdout.
   - `output_matches` — regex pattern for stdout.
   - `compare_files` — file comparison assertions (see Workflow 3).
4. Add metadata: `tags` for filtering, `description` for context. Put
   `timeout` for long-running commands and `retry_count` for flaky tests
   inside `execution`; declare `depends_on`/`resources` in `scheduling`.
5. Validate the configuration:
   ```bash
   symtest validate test_cases.json
   ```
6. Run:
   ```bash
   symtest run test_cases.json
   ```

For all available fields and their meanings, consult
`references/field_reference.md`. For complete usage details (setup plugins,
TUI, resource scheduling, etc.), consult `references/user_manual.md`.

### Workflow 2: Numerical Golden File Testing

For scientific computing (FEM solvers, etc.), file comparison is the primary
acceptance criterion. Use `assets/templates/test_cases_golden_file.json` as a
starting point.

1. Declare `compare_files` in the `expected` block:
   ```json
   "compare_files": [
     {
       "actual": "output.h5",
       "baseline": "baseline/golden.h5",
       "type": "h5",
       "rtol": 1e-5,
       "atol": 1e-8,
       "tables": ["/stress", "/displacement"]
     }
   ]
   ```
2. Choose the comparator `type`: `text`, `json`, `csv`, `xml`, `h5`, `binary`,
   or `script`. Omit `type` to auto-detect by file extension.
   If the `type` is not one of the above, it refers to a **user-defined
   comparator**. User-defined comparators are loaded from
   `<workspace>/comparators/*_comparator.py`. When troubleshooting a
   custom `type`, check that directory first — verify the plugin file
   exists and its class imports succeed (use `from symtest.file_comparator...`,
   not other package names). To author a new one, start from
   `assets/templates/my_analysis_comparator.py` (see
   `references/user_manual.md` → "Custom File Comparator").
3. Set numerical tolerance: `rtol` (relative) and `atol` (absolute).
4. Use `--error-analysis` to get full statistics (max error, RMSE, etc.) on
   failure.
5. When results intentionally change and new output is correct, update baselines:
   ```bash
   symtest run test_cases.json --update-baseline --yes
   ```
   Always review updated baselines and keep them in version control.

## Decision Guide

### JSON vs YAML config
- Use **JSON** for machine-generated configs or when strict schema matters.
- Use **YAML** for human-authored configs (more readable, supports comments).
- Both are fully equivalent in functionality.

### Single command vs step sequence
- **Single command**: one program invocation, one result to check
  (`execution.command` form).
- **Step sequence** (`execution.steps`): multiple ordered commands, fail-fast.
  Use when output of step N is input to step N+1.

### When to use `import` (config splitting)
- When the config grows large (>30 cases) or cases naturally group by module.
- Place sub-files in a `cases/` directory and reference via `{"import": "..."}`.
- Import-level `tags` inject into all imported cases.

### When to use `extends` (config inheritance)
- When multiple cases share the same structure with only minor differences.
- Define an `abstract: true` base case, then `extends` it.
- Use `variables` for parameterization (`{placeholder}` substitution).

### When to use `expected_failure` (xfail)
- Use for a known defect that is intentionally not part of the current
  implementation scope—for example, a compatibility issue blocked on an
  external dependency.
- `xfailed` (fails as expected) does not affect the exit code and is not
  selected by `--last-failed`.
- `xpassed` (unexpectedly passes) is treated as a failure and prompts removal
  of the xfail mark.

## Running Tests

### Basic
```bash
symtest run test_cases.json
symtest run test_cases.yaml
```

### Filtering
```bash
# By name (multiple allowed)
symtest run test_cases.json -t case1 -t case2

# By tag (OR relationship)
symtest run test_cases.json --tag smoke --tag regression

# Name + tag (AND)
symtest run test_cases.json -t case1 --tag fast
```

### Iteration
```bash
# Only re-run last failed cases
symtest run test_cases.json --last-failed

# Resume sequence tests from failed step
symtest run test_cases.json -t long_case --resume
```

### Parallel
```bash
symtest run test_cases.json --parallel --workers 4
symtest run test_cases.json --parallel --execution-mode process
```

### Output
```bash
# Machine-readable JSON
symtest run test_cases.json --output-format json

# JUnit XML for CI
symtest run test_cases.json --junit-xml report.xml
```

### Variables
```bash
symtest run test_cases.json --var solver=/opt/solver --var model=case1.dat
```

## Python API

```python
from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner

runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,
    execution_mode="thread",
    history_dir="./hist",
    variables={"solver": "/opt/solver"},
)
success = runner.run_tests()

for detail in runner.results["details"]:
    print(detail["name"], detail["status"], detail.get("failure_kind"))
```

For a complete project entry script with all CLI options, copy and adapt
`assets/full_runner_example.py`.

## References

- `references/field_reference.md` — Quick field lookup table for test case
  configuration. Consult this when filling in or verifying config fields.
- `references/user_manual.md` — Complete framework manual covering all
  features (setup plugins, TUI, resource scheduling, history, custom
  comparators, extension development). Consult for advanced or uncommon
  features not covered in this file.

## Assets

- `assets/templates/test_cases_simple.json` — Minimal single-command test.
- `assets/templates/test_cases_simple.yaml` — YAML version of the above.
- `assets/templates/test_cases_steps.json` — Multi-step sequence test.
- `assets/templates/test_cases_golden_file.json` — Numerical golden file test
  with HDF5/CSV comparison.
- `assets/templates/my_analysis_comparator.py` — Minimal runnable template
  for a user-defined custom comparator plugin.
- `assets/full_runner_example.py` — Full project entry script with all CLI
  options, report generation, and JUnit XML output.
