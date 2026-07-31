# CLI Test Framework

[中文](README_cn.md) | English

> **Note:** This project was formerly known as `cli-test-framework`.
> Since version 1.3.0 it is released as
> [`symtest-cli`](https://pypi.org/project/symtest-cli/); the old package name
> is no longer updated. Install with:
>
> ```bash
> pip install symtest-cli
> ```

A feature-focused automated testing framework for command-line applications.
It is built for regression suites that need more than an exit-code check:
multi-step commands, numerical result comparison, large configuration sets,
parallel execution, and CI-ready reports.

The project grew out of finite-element solver development, where a single test
may run several programs, produce HDF5 or CSV results, compare them with
tolerances, and track execution time across revisions.

## What it solves

CLI Test Framework keeps the execution workflow and its acceptance criteria in
one JSON or YAML configuration:

- **Execute workflows** — single commands or fail-fast step sequences, with
  timeouts, retries, variables, tags, and expected-failure support.
- **Verify results** — return codes, output text and regular expressions, plus
  text, JSON, CSV, XML, HDF5, binary, and custom-script file comparisons.
- **Manage large suites** — split configurations with `import`, reuse templates
  with `extends`, filter by name or tag, and inspect cases across files in the
  optional TUI.
- **Iterate and integrate** — parallel execution, `--last-failed`, step-level
  `--resume`, runtime history, structured reports, and JUnit XML output.

The emphasis is practical: features are added to solve test workflows that
occur in real CLI and scientific-computing projects.

## Installation

Python 3.9 or newer is required.

```bash
pip install symtest-cli
```

YAML and the TUI are optional:

```bash
pip install "symtest-cli[yaml]"
pip install "symtest-cli[tui]"
pip install "symtest-cli[all]"
```

The default installation includes HDF5 and numerical comparison support.

## Quick start

Create `test_cases.json`:

```json
{
  "test_cases": [
    {
      "name": "hello",
      "command": "echo",
      "args": ["Hello World"],
      "tags": ["smoke"],
      "expected": {
        "return_code": 0,
        "output_contains": ["Hello World"]
      }
    }
  ]
}
```

Run it:

```bash
symtest run test_cases.json
```

Validate a configuration without executing it:

```bash
symtest validate test_cases.json
```

## Numerical golden-file testing

File comparisons can be part of a test's acceptance criteria. Comparator
parameters such as tolerances, table selection, filters, and encodings are
declared next to the command:

```json
{
  "test_cases": [
    {
      "name": "FEA displacement check",
      "command": "my_solver",
      "args": ["--input", "case1.dat", "--output", "out.h5"],
      "expected": {
        "return_code": 0,
        "output_contains": ["simulation finished"],
        "compare_files": [
          {
            "actual": "out.h5",
            "baseline": "ref/golden.h5",
            "rtol": 1e-5,
            "atol": 1e-8,
            "tables": ["NASTRAN/RESULT/NODAL/DISPLACEMENT"]
          },
          {
            "actual": "summary.csv",
            "baseline": "ref/summary.csv",
            "rtol": 1e-6
          }
        ]
      }
    }
  ]
}
```

The comparator type is inferred from the extension when `type` is omitted.
Built-in types are `text`, `json`, `csv`, `xml`, `h5`, `binary`, and `script`.
Workspace comparators can be added without changing the framework.

To intentionally accept changed outputs, use `--update-baseline`. Because this
can overwrite reference files, interactive runs require typing `yes`;
non-interactive runs must explicitly add `--yes`:

```bash
symtest run test_cases.json --update-baseline
symtest run test_cases.json --update-baseline --yes   # automation / CI
```

Keep baselines under version control and review every update.

## Multi-step and iterative workflows

A case may contain an ordered `steps` list. Execution stops at the first failed
step. For long workflows, `--resume` reuses saved state and skips steps that
already passed:

```bash
symtest run solver_tests.json
symtest run solver_tests.json --last-failed
symtest run solver_tests.json -t long_case --resume
```

`--resume` deliberately trusts that workspace artifacts have not changed
between runs.

## Large test suites and the optional TUI

Large suites can be divided into sub-configurations:

```json
{
  "test_cases": [
    {"import": "cases/text_tests.json", "tags": ["text"]},
    {"import": "cases/h5_tests.json", "tags": ["h5", "regression"]}
  ]
}
```

The optional TUI provides one searchable view across imported files. It is
intended as an aid for locating cases and reviewing scenario coverage in large
projects, rather than a requirement for normal test execution.

```bash
symtest tui main_config.json
```

## Parallel execution and resources

```bash
symtest run test_cases.json --parallel --workers 4
symtest run test_cases.json --parallel --execution-mode process
```

Thread mode currently supports CPU-token allocation, solver thread environment
variables, and longest-processing-time-first scheduling using estimates or
runtime history. Process mode provides execution isolation but does not yet use
the resource scheduler. Memory enforcement, priority semantics, and broader
resource scheduling remain active areas of development.

## CI and reports

```bash
symtest run test_cases.json \
  --parallel --workers 4 \
  --junit-xml report.xml
```

The current suite contains 750 unit, integration, and end-to-end tests with 83%
line coverage. CI exercises Windows and Linux across Python 3.9 through 3.13.

## Python API

```python
from symtest.runners import JSONRunner, ParallelJSONRunner

runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,
    execution_mode="thread",
    history_dir="./hist",
    variables={"solver": "/opt/solver/bin/solver"},
)

success = runner.run_tests()
for detail in runner.results["details"]:
    print(detail["name"], detail["status"], detail.get("duration"))
```

## Standalone file comparison

```bash
compare-files result1.h5 result2.h5 --h5-table-regex "output_.*" --h5-rtol 1e-5
compare-files data1.csv data2.csv --csv-rtol 1e-4 --csv-data-filter ">1e-6"
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

## AI-assisted TDD, as a side benefit

The same configuration can serve as a machine-readable acceptance contract.
Structured validation failures, comparison details, and targeted reruns work
well in an AI-assisted TDD loop:

```text
define acceptance criteria
    → run the relevant cases
    → inspect the structured failure
    → change the implementation
    → rerun with --last-failed
    → run the full regression suite
```

This is a useful consequence of explicit tests and structured results, not a
requirement for using the framework.

## Documentation

- [User manual](docs/user_manual_en.md)
- [Design document](docs/design_en.md)
- [Plugin examples](examples/plugins/README.md)

## Development

Install the package with all optional and test dependencies:

```bash
pip install -e ".[dev]"
python -m pytest tests/unit tests/integration tests/e2e
```

Bug fixes, comparator plugins, documentation improvements, and reports from
real-world test workflows are welcome.

## License

MIT
