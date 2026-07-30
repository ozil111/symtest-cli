# CLI Test Framework

A lightweight automated testing framework for command-line applications. Define test cases in JSON/YAML, run all validations with a single command.

Particularly suited for scientific computing — deep HDF5 support with regex table matching, data filtering, and tolerance-based comparison, making simulation result verification effortless.

## Why this exists

This project started as a regression testing tool for finite-element solver software. In that world, checking the exit code is never enough — each test may run multiple commands, generate numerical result files, compare HDF5/CSV outputs with tolerances, and guard against performance regressions over time.

What we found along the way is that the framework naturally fits a **TDD + AI collaboration** workflow:

1. **Model the test** — define a test's inputs, commands, and expected behavior in a clean JSON/YAML config
2. **Declare acceptance criteria** — `return_code`, `output_contains`, `compare_files` with tolerances — this is your contract
3. **Run it** — the framework executes the commands, compares outputs against baselines, and produces a structured result
4. **Feed the result to AI** — when a test fails, the structured diff (what failed, how, with tolerance details) gives an LLM everything it needs to propose a fix
5. **Iterate** — `--last-failed` re-runs only the broken cases; `--resume` skips already-passed steps in long sequences; the loop tightens to seconds

This turns the test suite into a **machine-readable goal specification** — define "correct" once, then let AI iterate against that definition. The framework bridges the gap between human intent and automated verification.

At its core, the CLI Test Framework remains focused on what it was built for: **scientific computing regression testing**. But the TDD + AI loop works for any CLI tool — scripts, compilers, simulators, data pipelines, anything that runs from a terminal.

## Highlights

- **Golden File Assertion** — `compare_files` embedded in test `expected`, compares output files against baselines with tolerance
- **Parallel Execution** — multi-thread / multi-process, 3–5× speedup
- **Resource-Aware Scheduling** — automatic CPU core management, prevents solver thread runaway
- **Sequence Steps** — multi-step execution within a single test case, fail-fast
- **Configuration Splitting & Inheritance** — `import` sub-files, `extends` base templates — keep large test suites DRY
- **TUI Interactive Manager** — browse, search, edit, and run test cases from the terminal without leaving your editor
- **AI-Friendly Iteration** — `--last-failed` re-runs only broken cases; `--resume` skips passed steps; `--update-baseline` refreshes golden files; `xfail` marks known bugs
- **File Comparison** — text / JSON / CSV / XML / HDF5 / binary, with standalone CLI and embedded assertion support
- **Filtered Execution** — run specific test cases by name, tag, or both (AND logic)
- **JUnit XML Output** — CI-ready reports for GitLab CI / Jenkins / CircleCI
- **Custom Comparator Plugins** — drop `*_comparator.py` into your workspace; call any external analysis script via `type: script`

## Quick Start

```bash
pip install cli-test-framework
```

### 30-Second Setup

1. Create `test_cases.json`:

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

2. Run:

```bash
cli-test run test_cases.json
```

### Golden File Comparison in Tests

Run a simulation, then compare its output file against a reference:

```json
{
    "test_cases": [
        {
            "name": "FEA displacement check",
            "command": "my_solver",
            "args": ["--input", "case1.dat", "--output", "out.h5"],
            "expected": {
                "return_code": 0,
                "compare_files": [
                    {
                        "actual": "out.h5",
                        "baseline": "ref/golden.h5",
                        "rtol": 1e-5,
                        "atol": 1e-8,
                        "tables": ["NASTRAN/RESULT/NODAL/DISPLACEMENT"]
                    }
                ]
            }
        }
    ]
}
```

- `actual` — file produced by the command
- `baseline` — reference file to compare against
- `type` — comparator type (auto-detected from extension if omitted: `.h5`→h5, `.json`→json, `.csv`→csv, `.xml`→xml, `.txt`→text)
- all other keys are forwarded as comparator parameters (`rtol`, `atol`, `tables`, `table_regex`, `data_filter`, `encoding`, `structure_only`, `delimiter`, `compare_mode`, `key_field`, etc.)

Multiple files and mixed assertion types coexist naturally:

```json
{
    "expected": {
        "return_code": 0,
        "output_contains": ["simulation finished"],
        "compare_files": [
            {"actual": "out.h5",  "baseline": "ref/disp.h5",      "rtol": 1e-5},
            {"actual": "report.csv", "baseline": "ref/expected.csv", "rtol": 1e-6}
        ]
    }
}
```

### Project Entry Script

For projects that need custom environment setup, pre-configured defaults, or multi-format reporting, copy `examples/full_runner_example.py` to your project root and rename it (e.g., `run_tests.py`). It provides a full-featured Python entry point that auto-detects JSON/YAML configs and supports all CLI parameters (`--last-failed`, `--resume`, `--update-baseline`, `--junit-xml`, `--workers`, `--var`, etc.) — ideal for team-shared workflows.

```bash
python run_tests.py test_cases.json --workers 4 --junit-xml report.xml
```

## Core Use Cases

### Regression Testing for Scientific Computing

Define solver tests with multi-format golden file comparisons. When an algorithm change shifts numerical results, `--update-baseline` refreshes baselines while git keeps you safe. `--history-dir` tracks runtime trends and warns on regressions.

```bash
cli-test run fea_cases.json --history-dir ./hist --regression-threshold 2.0
```

### TDD + AI Collaboration Loop

Write a test first, define what "correct" means, run it. The framework's structured output — failure kind, detailed diffs, tolerance violations — turns test failures into precise prompts for an LLM. After the AI proposes a fix, re-verify with `--last-failed` to confirm only the broken cases pass.

```bash
cli-test run solver_tests.json                        # 3 fail
# ... AI fixes code based on structured failure output ...
cli-test run solver_tests.json --last-failed           # verify only those 3
cli-test run solver_tests.json                         # full regression check
```

### CI/CD Integration

Validate configurations in CI before running tests (`cli-test validate config.json --output-format json`), then execute with JUnit XML output. Parallel execution with `--workers` keeps pipelines fast.

```yaml
# .gitlab-ci.yml
test:
  script:
    - cli-test validate test_cases.json
    - cli-test run test_cases.json --parallel --workers 4 --junit-xml report.xml
  artifacts:
    reports:
      junit: report.xml
```

### Iterative Debugging with Long-Running Tests

For multi-step simulation workflows where each step takes minutes: `--resume` skips passed steps and continues from the failure point. `--last-failed` narrows the scope. `--update-baseline` refreshes expected outputs after a legitimate change.

```bash
# After step 4 of 8 fails in BS-U_01:
cli-test run config.json -t BS-U_01 --resume            # ~0.14s instead of 72s
```

### Managing Large Test Suites

As tests grow into the hundreds, split them across files with `import`, share common structure via `extends` + `abstract`, use `--tag` for batch filtering, and browse/edit interactively with the TUI.

```json
{
    "test_cases": [
        { "import": "cases/text_tests.json", "tags": ["text"] },
        { "import": "cases/h5_tests.json",   "tags": ["h5", "fast"] }
    ]
}
```

```bash
cli-test tui main_config.json
```

## Python API

```python
from cli_test_framework.runners import JSONRunner, ParallelJSONRunner

# Sequential
runner = JSONRunner(config_file="test_cases.json")
success = runner.run_tests()

# Parallel
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,
    execution_mode="thread",
    history_dir="./hist",
    last_failed=False,
    resume=False,
    update_baseline=False,
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()

# Access results
runner.results["total"]
runner.results["passed"]
runner.results["failed"]
for detail in runner.results["details"]:
    print(detail["name"], detail["status"], detail.get("duration"))
```

## Standalone File Comparison CLI

```bash
compare-files result1.h5 result2.h5 --h5-table-regex "output_.*" --h5-rtol 1e-5
compare-files data1.csv data2.csv --csv-rtol 1e-4 --csv-data-filter '>1e-6'
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

📖 **Full Documentation**: [docs/user_manual_en.md](docs/user_manual_en.md)

## Contributing

We welcome contributions of all kinds:

- **Code** — bug fixes, new features, documentation improvements. Fork the repo, make your changes, and open a PR. Make sure tests pass first:

  ```bash
  python tests/run_all.py
  ```

- **Custom Comparators & Plugins** — built a comparator for your domain-specific data format? We'd love to include it in the official plugin collection. Drop a PR or open an issue to discuss.

- **Use Cases & Experience Reports** — found an interesting way to use the framework? Working with a particular solver or simulation pipeline? Share your workflow in an issue — real-world stories help us improve the framework in the right direction.

- **Issues** — bug reports, feature requests, or just questions. All are welcome.

## License

MIT
