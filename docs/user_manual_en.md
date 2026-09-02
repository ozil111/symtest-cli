# CLI Test Framework User Manual

## Table of Contents

- [Installation](#installation)
- [Test Case Definition](#test-case-definition)
- [Case-Level Environment Variables](#case-level-environment-variables-env)
- [Configuration Splitting](#configuration-splitting)
- [Configuration Inheritance](#configuration-inheritance)
- [Configuration Validation](#configuration-validation)
- [TUI Interactive Manager](#tui-interactive-manager)
- [Running Tests](#running-tests)
- [Project Entry Script](#project-entry-script)
- [Placeholders (Variable Substitution)](#placeholders-variable-substitution)
- [Tag Filtering](#tag-filtering)
- [Setup Module](#setup-module)
- [Parallel Testing](#parallel-testing)
- [Sequential Step Testing](#sequential-step-testing)
- [Resource-Aware Scheduling](#resource-aware-scheduling)
- [History & Regression Detection](#history--regression-detection)
- [JUnit XML Report](#junit-xml-report)
- [Logging Configuration](#logging-configuration)
- [File Comparison](#file-comparison)
- [Extension Development](#extension-development)
- [Running Framework Tests](#running-framework-tests)

## Installation

```bash
pip install symtest-cli
```

Requirement: Python >= 3.9

YAML support is available as an optional dependency:

```bash
pip install "symtest-cli[yaml]"
```

Install YAML, TUI, and all other optional features together:

```bash
pip install "symtest-cli[all]"
```

HDF5 file comparison depends on `h5py` (installed with the framework). If you need to use other comparison features without HDF5, you can uninstall it separately, but HDF5 comparison will become unavailable.

## Test Case Definition

> **Schema v2 (1.4)**: The config uses a layered DSL — execution-related fields (`command`, `args`, `timeout`, `retry_count`, `env`, `steps`) live in the `execution` block, scheduling-related fields (`depends_on`, `resources`) live in the `scheduling` block, and `expected` stays at the top level. The old flat layout was removed; use `symtest migrate` to migrate.

### JSON Format

```json
{
    "test_cases": [
        {
            "name": "Test Name",
            "execution": {
                "command": "echo",
                "args": ["Hello"],
                "timeout": 60,
                "retry_count": 0
            },
            "scheduling": {
                "resources": {
                    "cpu_cores": 2,
                    "estimated_time": 300,
                    "min_memory_mb": 1024,
                    "priority": 5
                }
            },
            "expected": {
                "return_code": 0,
                "output_contains": ["Hello"],
                "output_matches": ".*regex.*",
                "compare_files": [
                    {
                        "actual": "output.txt",
                        "baseline": "baseline.txt",
                        "type": "text"
                    }
                ]
            }
        },
        {
            "name": "Known Failure Test",
            "execution": {
                "command": "echo",
                "args": ["should_fail"]
            },
            "expected_failure": true,
            "xfail_reason": "Bug #42 not yet fixed",
            "expected": { "return_code": 1 }
        }
    ]
}
```

### YAML Format

```yaml
test_cases:
  - name: Test Name
    execution:
      command: echo
      args: ["Hello"]
      timeout: 60
      retry_count: 0
    scheduling:
      resources:
        cpu_cores: 2
        estimated_time: 300
        min_memory_mb: 1024
        priority: 5
    expected:
      return_code: 0
      output_contains:
        - "Hello"
      output_matches: ".*regex.*"
      compare_files:
        - actual: output.txt
          baseline: baseline.txt
          type: text

  - name: Known Failure Test
    execution:
      command: echo
      args: ["should_fail"]
    expected_failure: true
    xfail_reason: "Bug #42 not yet fixed"
    xfail_quiet: true
    expected:
      return_code: 1
```

### Expected Failure (xfail)

When a known defect prevents a test case from passing, you can mark `expected_failure: true`. The framework distinguishes between "expected failures" and "unexpected passes":

| Scenario | Status | Exit Code Impact | Description |
|---|---|---|---|
| xfail + indeed failed | `xfailed` | Not counted as failure | Report shows `xfail_reason`; details displayed normally (can suppress Command Output via `xfail_quiet`) |
| xfail + unexpectedly passed | `xpassed` | **Counted as failure** | Report highlights "remove xfail marker" |

This is consistent with pytest's xfail semantics. When used with `--last-failed`, xfailed cases are excluded from rerun; xpassed cases are included.

```json
{
    "name": "KnownBug",
    "execution": {
        "command": "solver",
        "args": ["--input", "bug_case.dat"]
    },
    "expected_failure": true,
    "xfail_reason": "Bug #42: Boundary condition error, fix expected in v2.1",
    "expected": { "return_code": 1 }
}
```

When xfailed case output is extremely verbose (e.g., hundreds of lines of solver logs) and repetitive, add `xfail_quiet: true` to keep **only the reason and command, omitting Command Output** from the report. Other metadata (Description, Expected, Command, Return Code, Error Message, Compare Failures, Step Results, etc.) is still displayed normally:

```json
{
    "name": "KnownBug (quiet mode)",
    "execution": {
        "command": "solver",
        "args": ["--input", "bug_case.dat"]
    },
    "expected_failure": true,
    "xfail_reason": "Bug #42: Boundary condition error, fix expected in v2.1",
    "xfail_quiet": true,
    "expected": { "return_code": 1 }
}
```

### Test Dependencies (depends_on)

When test cases have ordering dependencies (e.g., D requires A, B, and C to generate data first), declare them via `depends_on`. The framework automatically schedules execution in DAG topological order:

**Parallel mode**: A, B, and C run concurrently. D is submitted only after all three pass. If a dependency fails, its downstream cases are auto-skipped (cascade skip).

**Sequential mode**: The framework reorders cases topologically, ensuring dependencies run first. Downstream cases are skipped on dependency failure.

**JSON example**:

```json
{
    "test_cases": [
        { "name": "A", "execution": { "command": "python", "args": ["gen_a.py"] }, "expected": {"return_code": 0} },
        { "name": "B", "execution": { "command": "python", "args": ["gen_b.py"] }, "expected": {"return_code": 0} },
        { "name": "C", "execution": { "command": "python", "args": ["gen_c.py"] }, "expected": {"return_code": 0} },
        {
            "name": "D",
            "execution": { "command": "python", "args": ["merge.py"] },
            "scheduling": { "depends_on": ["A", "B", "C"] },
            "expected": {"return_code": 0, "compare_files": [{"file": "output.h5", "type": "hdf5"}]}
        }
    ]
}
```

**YAML example**:

```yaml
test_cases:
  - name: A
    execution:
      command: python
      args: ["gen_a.py"]
    expected: { return_code: 0 }

  - name: B
    execution:
      command: python
      args: ["gen_b.py"]
    expected: { return_code: 0 }

  - name: C
    execution:
      command: python
      args: ["gen_c.py"]
    expected: { return_code: 0 }

  - name: D
    execution:
      command: python
      args: ["merge.py"]
    scheduling:
      depends_on: [A, B, C]
    expected:
      return_code: 0
      compare_files:
        - file: output.h5
          type: hdf5
```

**Scheduling semantics**:

| Dependency Status | Downstream Behavior |
|---|---|
| `passed` or `xfailed` | Dependency "satisfied", downstream runs normally |
| `failed` or `xpassed` | Dependency "unsatisfied", downstream marked `skipped` with cascade skip |
| Circular dependency | Configuration validation error, execution blocked |

`skipped` is NOT counted as `failed`; shown separately as `Skipped: N` in the report summary.

**Constraints**:
- Dependency names must exist in the same config file's `test_cases`
- Self-dependency is not allowed (`depends_on: ["self"]`)
- Circular dependencies are not allowed (A → B → A)
- `depends_on` and `steps` are independent—`depends_on` is a case-level concept, `steps` is an intra-case step-level concept
- Zero-overhead fast path when no dependencies are declared

### Field Descriptions

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Test case name |
| `execution.command` | Yes | Command to execute (supports commands with arguments as a single string, e.g., `python ./run.py`; the framework auto-splits and resolves the path) |
| `execution.args` | No | List of command arguments |
| `description` | No | Test case description |
| `execution.timeout` | No | Timeout in seconds, default 3600; set `null` for no limit |
| `execution.retry_count` | No | Number of automatic retries on failure, default 0 (no retry). In single-command mode, applies to the entire case; in step mode, applies per step. If a case passes after retry, results are marked `flaky: true` |
| `tags` | No | Tag list for batch filtering (e.g., `["smoke", "fast"]`) |
| `scheduling.resources` | No | Resource configuration, see [Resource-Aware Scheduling](#resource-aware-scheduling) |
| `expected_failure` | No | Mark as expected failure (xfail). When `true`, failure is counted as XFailed (no exit code impact); unexpected pass is counted as XPassed (treated as failure) |
| `xfail_reason` | No | Reason text for xfail, displayed in the report (e.g., "Bug #42 not yet fixed") |
| `xfail_quiet` | No | When `true`, suppress Command Output (stdout/stderr) for xfailed cases in the report; only command, return code, and failure reason metadata retained |
| `scheduling.depends_on` | No | List of test case names this case depends on (e.g., `["A", "B"]`). The case will wait until all dependencies pass before executing. On dependency failure, the case and its downstream are auto-skipped. Works with both parallel and sequential runners |
| `execution.env` | No | Case-level environment variable mapping (e.g. `{"MYAPP_SCALE": "1.0"}`), defined inside `execution`, injected into the subprocess only when this case runs (all steps in sequence mode). See [Case-Level Environment Variables](#case-level-environment-variables-env) |
| `expected.return_code` | No | Expected return code |
| `expected.output_contains` | No | List of strings the output must contain |
| `expected.output_matches` | No | Regex pattern the output must match (single string) |
| `expected.compare_files` | No | File comparison assertions list, see below |

### File Comparison Assertions (compare_files)

Declare one or more file comparison rules in `expected.compare_files`. The framework automatically uses the corresponding comparator to diff the actual output file against the baseline after command execution. The test passes only when all comparisons pass; these coexist with `return_code`, `output_contains`, and other assertions.

Fields for each comparison rule:

| Field | Required | Description |
|---|---|---|
| `actual` | Yes | Path to the file produced by the test command (relative paths resolved against workspace) |
| `baseline` | Yes | Path to the baseline/reference file (relative paths resolved against workspace) |
| `type` | No | Comparator type: `text`, `json`, `csv`, `xml`, `h5`, `binary`; auto-detected by extension if omitted |
| `start_line` | No | Starting line number (1-based), compare from this line onward |
| `end_line` | No | Ending line number (1-based), compare up to this line |
| `start_column` | No | Starting column number (1-based), compare from this column onward |
| `end_column` | No | Ending column number (1-based), compare up to this column |
| Others | No | Passed through to the corresponding comparator, e.g., `rtol`, `atol`, `encoding`, `tables`, `data_filter` |

```json
"expected": {
    "return_code": 0,
    "compare_files": [
        {
            "actual": "result.h5",
            "baseline": "baseline/result.h5",
            "type": "h5",
            "rtol": 1e-5,
            "atol": 1e-8,
            "tables": ["/stress", "/displacement"]
        },
        {
            "actual": "summary.csv",
            "baseline": "baseline/summary.csv"
        }
    ]
}
```

## Case-Level Environment Variables (env)

Use the `env` field inside `execution` (same level as `command` and `steps`) to inject environment variables into a single case's subprocess. The variables apply only to that case (all steps in sequence mode) and do not affect other cases.

### JSON

```json
{
    "name": "Case-level env test",
    "execution": {
        "command": "solver",
        "args": ["-i", "input.dat"],
        "env": {
            "MYAPP_SCALE": "1.0",
            "OMP_NUM_THREADS": "8"
        }
    },
    "expected": { "return_code": 0 }
}
```

### YAML

```yaml
- name: Case-level env test
  execution:
    command: solver
    args: ["-i", "input.dat"]
    env:
      MYAPP_SCALE: "1.0"
  expected: { return_code: 0 }
```

### Sequence Mode

`env` is defined inside `execution` (same level as `steps`) and applies to **all steps** of that case:

```json
{
    "name": "multi-step with env",
    "execution": {
        "env": { "MYAPP_SCALE": "1.0" },
        "steps": [
            { "command": "python", "args": ["./step1.py"], "expected": { "return_code": 0 } },
            { "command": "python", "args": ["./step2.py"], "expected": { "return_code": 0 } }
        ]
    }
}
```

### Semantics

| Aspect | Behavior |
|---|---|
| Injection mechanism | Injected via subprocess `env`, never mutates the global `os.environ`; process-isolated and thread-safe |
| Precedence | `os.environ` (incl. `setup.environment_variables`) < scheduler-injected (`OMP/MKL/NPROC`) < **case `env` (highest)** — case env can override `OMP_NUM_THREADS` |
| Scope | Current case only, no cross-case pollution (unlike global `setup.environment_variables`) |
| Placeholders | Auto-supported; `"env": {"SCALE": "{scale}"}` is substituted via `variables`/`--var` |
| Inheritance (extends) | Auto-supported; `env` is a dict, deep-merged with child keys overriding parent |
| Value type | Strings; numeric/boolean values are coerced with `str()` at parse time |

## Configuration Splitting

When a test project grows to dozens or even hundreds of test cases, a single config file becomes hard to maintain. The configuration splitting mechanism lets you break a large file into multiple sub-files by module/feature and assemble them via `import` references, which are merged at load time automatically.

### Main Configuration File

In the main config file, reference sub-files via the `"import"` field. `import` is a special element in the `test_cases` array; the framework **expands and replaces** it with the sub-file's test cases at load time:

```json
{
    "setup": {
        "environment_variables": {
            "PYTHONPATH": "./src"
        }
    },
    "test_cases": [
        {
            "name": "Inline Test Case",
            "execution": {
                "command": "echo",
                "args": ["hello"]
            },
            "expected": { "return_code": 0 }
        },
        { "import": "cases/text_tests.json", "tags": ["text"] },
        { "import": "cases/json_tests.yaml" },
        { "import": "cases/h5_tests.json", "tags": ["h5", "fast"] }
    ]
}
```

> **Note**: `import` paths are resolved relative to the **directory of the main config file**, not the current working directory (cwd). This ensures portability — split relationships are unaffected regardless of which directory tests are run from.

### Sub-File Format

Sub-files have the same structure as the main file, with a top-level `test_cases` array (and optional `setup`):

```json
{
    "test_cases": [
        {
            "name": "text_identical",
            "execution": {
                "command": "python",
                "args": ["./compare_text.py"]
            },
            "expected": { "return_code": 0 },
            "tags": ["text"]
        },
        {
            "name": "text_diff",
            "execution": {
                "command": "python",
                "args": ["./compare_text.py", "--mode", "diff"]
            },
            "expected": { "return_code": 1 },
            "tags": ["text"]
        }
    ]
}
```

### Import-Level Tags

When all cases in a sub-file share the same tags (e.g., `"text"`), there is no need to repeat `tags` in every case. Simply add `tags` to the `import` entry, and the framework automatically injects them into every case imported from that file:

```json
{ "import": "cases/text_tests.json", "tags": ["text", "fast"] }
```

**Merge Rules**:

| Scenario | Result |
|---|---|
| import has tags, sub-case has none | Sub-case inherits all import tags |
| import has tags, sub-case also has tags | Merged and deduplicated; import tags first, sub-case's own tags after |
| import has no tags | Behavior unchanged, backward compatible |

> Nested imports (sub-files that further import other files) also follow this rule — outer import tags are injected into **all** recursively expanded cases.

### How It Works

1. **Expanded at load time**: The Runner automatically expands imports after reading the config file and before parsing `TestCase` objects. Completely transparent to the Runner and execution engine — no changes to test cases or Runner code needed.
2. **Recursive expansion**: Sub-files can continue to `import` other files, supporting multiple nesting levels.
3. **Circular reference protection**: The framework maintains a set of loaded file paths and raises a clear error when circular references are detected.
4. **Backward compatible**: Config files without `import` fields behave exactly as before — zero migration cost.

### Cross-Format Support

A JSON main config can import YAML sub-files, and vice versa. The framework auto-selects the parser based on the sub-file extension (`.json` / `.yaml` / `.yml`).

### Setup Merge Rules

If both the main file and sub-file define `setup`, they are deep-merged:
- **Same-name variable conflicts**: Sub-file `setup` overrides the main file's same-name fields.
- **Environment variables**: Merged into one dict, with sub-file taking priority.

```json
// Main file setup
{ "environment_variables": { "BASE": "from_main", "OVERRIDE": "from_main" } }

// Sub-file setup
{ "environment_variables": { "SUB_KEY": "from_sub", "OVERRIDE": "from_sub" } }

// Merged result
{ "environment_variables": {
    "BASE": "from_main",
    "SUB_KEY": "from_sub",
    "OVERRIDE": "from_sub"  // sub-file overrides
} }
```

### Incremental Migration

No need to migrate everything at once:
1. Run `validate` to confirm existing configs are correct (see [Configuration Validation](#configuration-validation))
2. Gradually move parts of a large file into sub-files and reference them with `import`
3. Inline cases and `import` references can coexist in the same `test_cases` array

## Configuration Inheritance

When many test cases are structurally similar (differing only in paths, parameters, etc.), use `extends` + `abstract` + `variables` to eliminate duplicate configuration.

### Syntax

Test cases support three new inheritance-related fields:

| Field | Type | Description |
|-------|------|-------------|
| `abstract` | `boolean` | When `true`, acts as a template (base class) and is not executed |
| `extends` | `string` | Name of the base test case to inherit from; supports chained inheritance |
| `variables` | `object` | Case-level placeholder variables for `{key}` substitution |

### Basic Usage

```json
{
  "test_cases": [
    {
      "name": "_base_echo",
      "abstract": true,
      "execution": {
        "command": "echo",
        "args": ["{msg}"]
      },
      "expected": {
        "output_contains": ["{msg}"]
      },
      "variables": {
        "msg": "hello"
      }
    },
    {
      "name": "test_hello",
      "extends": "_base_echo"
    },
    {
      "name": "test_world",
      "extends": "_base_echo",
      "variables": {
        "msg": "world"
      }
    }
  ]
}
```

When expanded, `test_hello` inherits all fields from the base (`execution.command`, `execution.args`, `expected`), and the placeholder `{msg}` is replaced by `variables.msg` → `"hello"`. `test_world` overrides `variables.msg` to `"world"`.

### Merge Rules

Inheritance uses a **deep merge for dicts, full replacement for lists** strategy:

- **dict fields** (e.g., `expected`, `variables`): Recursively merged; subclass fields override parent's same-name keys
- **list fields** (e.g., `args`, `steps`, `tags`): Subclass replaces parent's entire list; no appending

```json
{
  "name": "_base",
  "abstract": true,
  "expected": {
    "return_code": 0,
    "output_contains": ["base"]
  },
  "tags": ["a", "b"],
  "extends": "_base",
  "expected": {
    "output_contains": ["child"]
  },
  "tags": ["c"]
}
```

Merged result: `expected.return_code` = `0` (from parent), `expected.output_contains` = `["child"]` (subclass replaces entire list), `tags` = `["c"]` (entire list replaced).

The `abstract` field takes the subclass's own value (default `false`) and is **not inherited** from the parent, preventing subclasses from accidentally becoming abstract templates.

### Chained Inheritance

Multi-level inheritance is supported (A → B → C):

```json
{
  "name": "_A", "abstract": true,
  "execution": { "command": "python", "args": ["-c"] }, "expected": {},
  "variables": {"a": "1"}
}
{
  "name": "_B", "abstract": true, "extends": "_A",
  "expected": {"output_contains": ["b"]},
  "variables": {"b": "2"}
}
{
  "name": "C", "extends": "_B",
  "variables": {"c": "3"},
  "execution": { "args": ["print('{a} {b} {c}')"] }
}
```

Circular inheritance is automatically detected at load time and reported as an error.

### Variable Substitution Priority

Placeholder substitution has two layers:

1. **Case-level `variables`**: Deep-merged from the inheritance chain (subclass overrides parent), applied first to the merged case content
2. **Global `--var`**: Passed via CLI (`--var KEY=VALUE`), applied after case-level variables; **global takes priority when keys conflict**

```bash
symtest run config.json --var solver=/path/to/solver
```

The `setup` block uses only global `--var` substitution (no case-level variables).

### validate Checks

`symtest validate` performs additional checks on inherited configurations:

- Whether the `extends` target exists
- Whether a circular inheritance chain exists
- `abstract` cases are not counted as executable
- `extends` cases skip required-field checks (content comes from parent)

### TUI Editing Limitation

> **Note**: The TUI does not currently support editing inherited cases. Expanded inherited cases can be viewed and run in the TUI, but please edit the JSON/YAML source files directly to make modifications.

## Configuration Validation

The `validate` command checks configuration file correctness without running tests, suitable for CI pipeline config validation.

### Usage

```bash
# Validate a single config file
symtest validate test_cases.json

# Validate a main config with imports (auto-expands and checks all sub-files)
symtest validate main_config.json

# Specify working directory
symtest validate test_cases.json --workspace /path/to/project

# Output JSON format (for AI/script parsing)
symtest validate test_cases.json --output-format json
```

### What Gets Checked

| Check | Description |
|---|---|
| Syntax correctness | Whether JSON/YAML is valid (implicitly checked on load) |
| Required fields | Whether each case has `name`, `execution.command`, `execution.args`, `expected` (each step in sequence mode) |
| Import references | Whether referenced sub-files exist |
| Circular references | Whether an A→B→A cycle exists in the import chain |

### Output Examples

On success:
```
  [OK] Loaded 15 test cases from 3 file(s)
  [OK] All required fields present
  [OK] No circular imports detected

  Files:
    - /project/main_config.json
    - /project/cases/text_tests.json
    - /project/cases/json_tests.yaml
```

On error:
```
  [OK] Loaded 3 test cases from 1 file(s)
  [FAIL] case 'bad_case': missing required field 'expected'
  [FAIL] Import target not found: /project/cases/nonexistent.json
```

## TUI Interactive Manager

When a large project splits cases across many JSON/YAML sub-configurations, locating cases and reviewing scenario coverage across files becomes difficult. The TUI (Terminal User Interface) provides one view over all imported configurations for browsing, global search, and coverage review, with editing and case execution available when needed. It is an aid for large suites, not a requirement for normal test execution.

### Installation

The TUI depends on the `textual` library and is provided as an optional, on-demand dependency:

```bash
# Install with TUI support
pip install "symtest-cli[tui]"

# Or install textual separately on top of an existing framework
pip install textual
```

If `textual` is not installed and you run `symtest tui`, the framework displays a friendly installation prompt.

### Launching

```bash
# Open TUI to edit test cases
symtest tui test_cases.json

# YAML files are also supported
symtest tui test_cases.yaml

# Specify working directory
symtest tui test_cases.json --workspace /path/to/project

# Open a main config with imports (auto-expands all cases from sub-files)
symtest tui main_config.json
```

The TUI auto-expands `import` references via the [Configuration Splitting](#configuration-splitting) mechanism at startup, loading all cases into the interface for unified management.

### Interface Overview

The TUI shows the **Test Case List main screen** on startup:

- **Top status bar**: Current filename, total case count
- **Search bar**: Press `/` to focus the search box; supports substring/fuzzy/regex modes
- **Case table**: Six columns (Index, Name, Command, Tags, Timeout, Mode); keyboard-navigable
- **Bottom shortcut bar**: Shows all available actions

### Keyboard Shortcuts

| Shortcut | Function |
|---|---|
| `a` | Add a new test case |
| `e` | Edit selected test case |
| `d` | Delete selected test case |
| `u` | Duplicate selected test case (name gets `_copy` suffix) |
| `r` | Run selected test case and display results |
| `F6` / `Ctrl+S` | Save changes to file |
| `/` | Focus search box |
| `Esc` | Clear search, restore full list |
| `Alt+S` | Toggle substring search mode (case-insensitive) |
| `Alt+F` | Toggle fuzzy search mode (tolerates typos and abbreviations) |
| `Alt+R` | Toggle regex search mode |
| `q` / `Ctrl+Q` | Quit |
| `↑` / `↓` / `j` / `k` | Move cursor up/down |

Search matches against `name`, `command`, `args`, `tags`, `description` and other fields simultaneously; matches are highlighted in the table.

### Editing a Test Case

Select a case and press `e` to enter edit mode. The edit form has two modes based on the case type:

#### Single-Command Mode

The edit form includes the following fields:

| Field | Description |
|---|---|
| `Name` | Case name (required) |
| `Command` | Command to execute |
| `Args` | Command arguments, one per line |
| `Tags` | Tag list, one per line |
| `Description` | Case description |
| `Timeout` | Timeout in seconds |
| Expected | Nested sub-form for expected assertions (see below) |

#### Step Sequence Mode

When a case contains multiple ordered steps, switch to this mode. Each step has its own `Command`, `Args`, `Expected`, and `Timeout`. Supports adding, deleting, editing, and reordering steps.

Switch between modes via keyboard shortcuts within the edit interface; a confirmation prompt appears to prevent data loss.

### Editing the `expected` Field

The `expected` field is a nested dictionary; the editor provides structured input:

| Field | Input Method |
|---|---|
| `return_code` | Numeric input box |
| `output_contains` | Multi-line text input, one match string per line |
| `output_matches` | Regex text input |
| `compare_files` | One JSON object per line, e.g., `{"actual":"out.txt","baseline":"base.txt","type":"text"}` |

Beyond the known fields above, you can add custom key=value pairs via the `+ Add` button (value is a string or JSON text). See [Test Case Definition](#test-case-definition) for more details.

### Running a Test Case

Select a case in the list and press `r` to invoke the framework execution engine and run it in real time. A result panel pops up showing:

- Pass/fail status
- Return code
- Duration
- Command output (stdout/stderr)

The result panel is display-only and does not modify the config file.

### Saving

All add/edit/delete operations on test cases are performed **in memory** and are not immediately written to disk.

- Press `F6` or `Ctrl+S` to **save**: writes all current cases back to the original config file.
- Use `save_as` to **save as** a new file (via the interface menu).

Unsaved changes prompt a confirmation dialog when quitting the TUI.

## Running Tests

### Command Line

```bash
# Run JSON tests
symtest run test_cases.json

# Run YAML tests
symtest run test_cases.yaml

# Run a main config with import splitting (auto-expands sub-files)
symtest run main_config.json

# Specify working directory
symtest run test_cases.json --workspace /path/to/project

# Run in parallel
symtest run test_cases.json --parallel --workers 4

# Specify parallel mode
symtest run test_cases.json --parallel --execution-mode process

# Run only specified cases
symtest run test_cases.json -t test_name_1 -t test_name_2

# Filter by tag
symtest run test_cases.json --tag smoke
symtest run test_cases.json --tag smoke --tag regression

# Filter by name and tag simultaneously (AND relationship)
symtest run test_cases.json -t test_name_1 --tag smoke

# Verbose output
symtest run test_cases.json --verbose

# Debug mode
symtest run test_cases.json --debug

# Output format
symtest run test_cases.json --output-format json|html|text

# Enable history (smart scheduling + regression detection)
symtest run test_cases.json --history-dir ./hist

# Custom regression threshold (default 1.5x)
symtest run test_cases.json --history-dir ./hist --regression-threshold 2.0

# Output JUnit XML report (consumable by Jenkins/GitLab CI etc.)
symtest run test_cases.json --junit-xml report.xml

# Run only last-failed cases (overwritten on each run)
symtest run test_cases.json --last-failed

# Resume: skip passed steps, continue from failed step
symtest run test_cases.json --resume
symtest run test_cases.json --resume -t long_pipeline

# Update baseline files on comparison failure (type yes interactively)
symtest run test_cases.json --update-baseline

# Non-interactive environments must confirm explicitly
symtest run test_cases.json --update-baseline --yes

# Enable error analysis (full stats output for numerical comparisons)
symtest run test_cases.json --error-analysis
```

### Run Only Last-Failed Cases (--last-failed)

`--last-failed` automatically filters to cases that **truly failed** in the previous run (`failed`, `timeout`, and `xpassed`). Ideal for AI iterative fixing scenarios: after fixing one round of code, only verify the previously failed cases without a full rerun (a full FEM run could take hours).

**xfail semantics**: Cases marked `expected_failure` that fail (`xfailed`) are _expected behavior_ and are **not** selected by `--last-failed` for rerun. However, if an xfail-marked case unexpectedly passes (`xpassed`), it is treated as a true failure and **is** selected.

**How it works**:
- After each run, the framework records each case's status in `<workspace>/.symtest/last_run.json`
- Recording uses **overwrite-update**: cases run this time get new results overwriting old ones; un-run cases retain their previous status
- This means a fixed case won't show as "failed" in the next display
- If the file doesn't exist (first run), `--last-failed` warns and runs all cases normally

```bash
# First run: all 10 cases, 3 fail
symtest run config.json

# After fixing code, rerun only those 3 failures
symtest run config.json --last-failed

# If all 3 pass, run once more to confirm no regressions
symtest run config.json
```

**Interaction with `-t`**: `--last-failed` and `-t`/`--tag` can be used together; effects stack (AND relationship).

### Resume (--resume)

`--resume` is for **sequential step tests (sequence)**. It skips steps that passed in the previous run and continues directly from the failed step. Ideal for long-running multi-step cases — for example, in an FEM analysis where steps 1-3 passed (each taking tens of seconds or minutes), only step 4's assertion failed. `--resume` skips 1-3 and reruns only step 4.

**How it works**:
- After each step passes, the framework records step status in `<workspace>/.symtest/sequence_state/<case_name>.json` and caches output to the `cache/` subdirectory
- On the next `--resume`, a config hash (SHA256 of every step's command/args/expected/timeout/retry_count plus case-level expected) is computed and compared against saved state
- Hash match → skip passed steps, rebuild `combined_output` from cache (so case-level `expected` assertions run correctly)
- All steps pass → state file and cache automatically deleted to avoid stale data affecting subsequent runs
- Hash mismatch (config changed) → full rerun automatically, old state discarded

**Trust model**: `--resume` does **not verify workspace artifacts** (input files, files generated by prior steps, etc.). Using `--resume` means the user confirms input files are unmodified. If workspace contamination is suspected, rerun fully without `--resume`.

```bash
# First full run, long_pipeline step 4 fails (total 72s)
symtest run config.json

# After fixing, rerun only long_pipeline, skipping steps 1-3 (~0.14s only)
symtest run config.json -t long_pipeline --resume

# After all pass, do one full run to confirm no regressions
symtest run config.json
```

**Interaction with `-t`**: `--resume` is typically used with `-t` to first isolate a single failed case then resume from it. Without `-t`, all sequence cases with existing state will attempt to resume.

**Limitations**:
- Only applies to sequential step cases (`steps` mode); single-command mode ignored
- The state file's config hash is invalidated by any change to a step's command/args/expected/timeout/retry_count or case-level expected
- Cached output is primarily for rebuilding `combined_output`; the `output` field in the report still contains only the failed step's output

### Auto-Update Baseline Files (--update-baseline)

After algorithm improvements or parameter adjustments, you may expect output to change (and the new results to be more correct). `--update-baseline` automatically overwrites baseline files with actual output, avoiding manual copy-paste.

```bash
# Interactive runs ask you to type yes before execution
symtest run config.json --update-baseline

# Explicit confirmation for automation or CI
symtest run config.json --update-baseline --yes
```

**Behavior**:
- Interactive runs start only after the user types the full word `yes`
- Non-interactive runs do not wait for input and require `--yes`
- When file comparison fails, the `actual` file is copied to the `baseline` path
- That assertion is treated as **passed**; the case status is `passed`
- The report shows a `Baseline Updated` count and lists updated files
- Both text and JSON reports list all updated baseline paths

> **Note**: Confirmation happens before test execution, while the files to update are only known after comparison. Keep baselines under version control and review the report's `Baseline Updated` list. Passing `update_baseline=True` through the Python API is treated as explicit confirmation by the caller.

### Configuration Validation JSON Output

The `validate` command has a `--output-format json` option that produces machine-readable JSON reports, suitable for AI/script-based config validation:

```bash
symtest validate config.json --output-format json
```

Output example:
```json
{
  "valid": false,
  "errors": ["[main_config.json] case 'bad_case': missing required field 'expected'"],
  "summary": {"files": 1, "cases": 3, "files_loaded": ["/project/main_config.json"]}
}
```

### Python API

```python
from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner

# Sequential run
runner = JSONRunner(
    config_file="test_cases.json",
    workspace="/path/to/project",    # Optional, defaults to project root
    test_case_filter=["test_1"],     # Optional, run only specified cases
    test_case_tag_filter=["smoke"],  # Optional, run only cases with specified tags
    history_dir="./hist",            # Optional, enable history & regression detection
    regression_threshold=2.0,        # Optional, regression threshold multiplier, default 1.5
    update_baseline=False,           # Optional, auto-update baseline on comparison failure, default False
    last_failed=False,               # Optional, run only last-failed cases, default False
    resume=False,                    # Optional, resume sequence cases from last failed step, default False
)
success = runner.run_tests()

# YAML format
runner = YAMLRunner(config_file="test_cases.yaml")

# Parallel run (JSON)
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,                   # Optional, defaults to CPU core count
    execution_mode="thread",         # "thread" or "process"
    test_case_filter=["test_1"],
    history_dir="./hist",            # Optional, enable history & smart scheduling
    regression_threshold=2.0,        # Optional, regression threshold multiplier, default 1.5
    update_baseline=False,           # Optional
    last_failed=False,               # Optional
    resume=False,                    # Optional, resume sequence cases
)
success = runner.run_tests()

# Parallel run (YAML)
from symtest.runners import ParallelYAMLRunner
runner = ParallelYAMLRunner(
    config_file="test_cases.yaml",
    max_workers=4,
    execution_mode="thread",
)
success = runner.run_tests()
```

### Getting Results

```python
runner.run_tests()

# Summary
runner.results["total"]
runner.results["passed"]
runner.results["failed"]
runner.results["xfailed"]      # Expected failure (no exit code impact)
runner.results["xpassed"]      # Unexpected pass (counted as failure)
runner.results["updated"]      # Number of baseline files updated by --update-baseline

# Details — each result dict contains the following fields
for detail in runner.results["details"]:
    print(detail["name"])                     # Case name
    print(detail["status"])                   # "passed" / "failed" / "xfailed" / "xpassed" / "timeout"
    print(detail.get("message", ""))          # Failure reason
    print(detail.get("duration"))             # Duration (seconds)
    print(detail.get("xfail_reason", ""))     # xfail reason (only for xfailed/xpassed status)
    print(detail.get("expected"))             # Expected assertions (registered acceptance criteria)
    print(detail.get("description"))          # Case description
    print(detail.get("tags"))                 # Tag list
    print(detail.get("failure_kind"))         # Failure type: return_code/output_contains/
                                              #   output_matches/file_compare/timeout/
                                              #   execution_error
    print(detail.get("attempts", 1))          # Number of attempts (including retries)
    print(detail.get("flaky", False))         # Whether it passed only after retry
    print(detail.get("attempt_history", []))  # Status history for each attempt
    print(detail.get("failed_step"))          # Failed step number in step sequence
    print(detail.get("step_results", []))     # Detailed results for each step
    print(detail.get("compare_failures", [])) # Structured file comparison failure details
    print(detail.get("baseline_updated", [])) # List of updated baseline file paths
```

**Key Result Dictionary Fields**:

| Field | Type | Description |
|---|---|---|
| `status` | str | One of five states: `passed`, `failed`, `xfailed` (expected failure), `xpassed` (unexpected pass), `timeout` |
| `xfail_reason` | str | xfail reason text (from `xfail_reason` in config); only present for `xfailed`/`xpassed` status |
| `expected` | dict | Registered expected assertions (return_code, output_contains, compare_files, etc.) for reviewing acceptance criteria |
| `description` | str | Test case description text |
| `failure_kind` | str | Failure type enum; AI/scripts can choose repair strategies accordingly |
| `attempts` | int | Total attempts (including retries); `1` means passed on first try |
| `flaky` | bool | `true` if the case passed only after retry |
| `attempt_history` | list | Per-attempt `{attempt, status, message, duration}` |
| `step_results` | list | Per-step `{step, name, status, message, duration, command}` |
| `compare_failures` | list | Structured info for each failed file comparison (includes `diff_summary`, `differences`, `error_stats`, `actual`/`baseline` paths, tolerance params) |
| `baseline_updated` | list | Paths of baseline files overwritten by `--update-baseline` |

## Project Entry Script

If your test project has a complex structure (requiring preset environment variables, customized report paths, etc.), using `symtest run` directly may not be flexible enough. You can create a project entry script (e.g., `test.py` or `run_tests.py`) that calls the framework API from Python code.

### When to Use CLI Directly

| Scenario | Recommendation |
|---|---|
| Simple project, single config file | `symtest run config.json --workers 4` |
| One-off run, no special environment needs | `symtest run config.yaml --tag smoke` |
| CI pipeline | `symtest run config.json --junit-xml report.xml` |

### When to Wrap in an Entry Script

| Scenario | Recommendation |
|---|---|
| Need to set environment variables (e.g., inject venv PATH) | Entry script |
| Need to output multiple report formats simultaneously (text + JUnit XML) | Entry script |
| Team-shared fixed run parameters (workers, history-dir, etc.) | Entry script |
| Need to auto-select JSON/YAML runner by config file extension | Entry script |
| Windows console-script commands (e.g., `compare-files`) not found | Entry script (inject venv Scripts into PATH) |

### Entry Script Example

The framework provides an out-of-the-box example script `examples/full_runner_example.py`. Copy it to your project root and use it directly or customize as needed. It supports all the following CLI parameters:

| Parameter | Description |
|---|---|
| `config` (positional) | Test config file path (auto-detects .json / .yaml) |
| `--test-target` / `-t` | Filter cases by name |
| `--tag` | Filter cases by tag (OR relationship) |
| `--last-failed` | Run only last-failed cases |
| `--resume` | Resume sequence cases from last failed step |
| `--update-baseline` | Update baselines on comparison failure; requires interactive confirmation |
| `--yes` / `-y` | Skip the baseline confirmation for automation or CI |
| `--junit-xml` | JUnit XML report output path |
| `--report` | Text report output path, default `test_report.txt` |
| `--workers` / `-w` | Number of parallel workers, default 4 |
| `--execution-mode` | thread or process |
| `--workspace` | Working directory, defaults to script directory |
| `--var` | Template variable substitution, format `KEY=VALUE` |
| `--verbose` / `-v` | Verbose output (DEBUG-level logging) |

### Quick Start

1. Copy `examples/full_runner_example.py` to your project root, rename to `run_tests.py`
2. If you use a virtual environment and need console-script commands, uncomment the venv PATH injection code in the file
3. Adjust default parameters for your team's preference (e.g., `--workers` default value, `--history-dir` default path)
4. Run tests:

```bash
# Full run
python run_tests.py test_cases.json --workers 4

# Only last-failed cases
python run_tests.py test_cases.json --last-failed

# CI with JUnit report
python run_tests.py test_cases.json --junit-xml report.xml
```

### Windows WinError 2 Issue

If your test case `command` field references console-script commands (e.g., `compare-files`, `symtest` — entry points installed via pip), running the script via double-click or from an unactivated environment on Windows may cause subprocesses to fail finding these executables:

```
FileNotFoundError: [WinError 2] The system cannot find the file specified.
```

This is because these commands exist as `.exe` wrappers in `venv/Scripts/` and that directory is not in the subprocess PATH.

**Solution**: At the very top of your entry script (beginning of `main()` or at file level), prepend the venv `Scripts` directory to the `PATH` environment variable:

```python
import os

venv_scripts = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", ".venv", "Scripts"))
if os.path.isdir(venv_scripts):
    os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")
```

This code is already included in the example script `examples/full_runner_example.py` (commented out by default). Uncomment and adjust the path as needed.

## Placeholders (Variable Substitution)

When the same config file needs different parameters in different environments (e.g., solver path, model file path, etc.), use `{variable_name}` placeholders in the config and pass actual values via `--var` or `variables` at runtime.

### Writing Configs with Placeholders

JSON:

```json
{
    "test_cases": [
        {
            "name": "Solver Test",
            "execution": {
                "command": "{solver}",
                "args": ["--input", "{model}", "--output", "{output}"]
            },
            "expected": { "return_code": 0 }
        }
    ]
}
```

YAML:

```yaml
test_cases:
  - name: Solver Test
    execution:
      command: "{solver}"
      args: ["--input", "{model}", "--output", "{output}"]
    expected:
      return_code: 0
```

Placeholders `{variable_name}` can appear in any string value in the config file, including `command`, `args`, `name`, `expected.output_contains`, etc. Multiple placeholders in the same string are supported, e.g., `"{solver} --input {model}"`.

> **Safety design**: Only keys present in the `variables` dictionary are replaced. Unmatched `{xxx}` is left as-is without error. Therefore, regex patterns in `expected.output_matches` (like `{2,}`, `\d{4}`) are unaffected.

### Usage

#### CLI

```bash
# Single variable
symtest run test_cases.json --var solver=/opt/solver/bin/solver.exe

# Multiple variables
symtest run test_cases.json --var solver=/opt/solver/bin/solver.exe --var model=./data/model.dat

# Combined with parallel mode, tag filtering, etc.
symtest run test_cases.json --var solver=solver.exe --parallel --workers 4 --tag smoke
```

`--var` format is `KEY=VALUE`, usable multiple times. Separated by `=`; whitespace around key and value is auto-trimmed.

#### Python API

```python
from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner, ParallelYAMLRunner

# Sequential run
runner = JSONRunner(
    config_file="test_cases.json",
    variables={
        "solver": "/opt/solver/bin/solver.exe",
        "model": "./data/model.dat",
        "output": "./results/output.dat",
    },
)
success = runner.run_tests()

# Parallel run
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()

# YAML also supported
runner = YAMLRunner(
    config_file="test_cases.yaml",
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()
```

### Use Cases

| Scenario | Example |
|---|---|
| Different solver versions | `--var solver=v1.0/solver.exe` vs `--var solver=v2.0/solver.exe` |
| Different input data | `--var model=case_1.dat` vs `--var model=case_2.dat` |
| CI/CD environment adaptation | Local `/opt/solver.exe`, CI `/runner/solver.exe` |
| Cross-platform paths | Windows `--var solver=C:\solver.exe`, Linux `--var solver=/opt/solver.exe` |

## Tag Filtering

Tags allow classifying test cases and batch-filtering them at runtime. Tag filtering and name filtering can be used simultaneously (AND relationship — both conditions must be met).

### Defining Tags in Test Cases

JSON:

```json
{
    "test_cases": [
        {
            "name": "Quick Test",
            "execution": {
                "command": "echo",
                "args": ["hello"]
            },
            "tags": ["smoke", "fast"],
            "expected": { "return_code": 0 }
        },
        {
            "name": "Full Regression Test",
            "execution": {
                "command": "python",
                "args": ["long_test.py"]
            },
            "tags": ["regression", "slow"],
            "expected": { "return_code": 0 }
        }
    ]
}
```

YAML:

```yaml
test_cases:
  - name: Quick Test
    execution:
      command: echo
      args: ["hello"]
    tags: ["smoke", "fast"]
    expected:
      return_code: 0
```

`tags` is optional; defaults to an empty list if not specified. Each case can have multiple tags.

### Runtime Filtering

```bash
# Run only cases with the "smoke" tag
symtest run test_cases.json --tag smoke

# Run cases with "smoke" or "regression" tags (OR relationship)
symtest run test_cases.json --tag smoke --tag regression

# Combine name and tag filtering (AND relationship)
symtest run test_cases.json -t alpha --tag fast
```

### Python API

```python
runner = JSONRunner(
    config_file="test_cases.json",
    test_case_tag_filter=["smoke"],     # Run only cases with the smoke tag
)
success = runner.run_tests()

# Combine with name filtering
runner = JSONRunner(
    config_file="test_cases.json",
    test_case_filter=["alpha", "beta"],
    test_case_tag_filter=["fast"],
)
success = runner.run_tests()
```

## Setup Module

The Setup module performs initialization before tests and cleanup after tests.

### Environment Variables (Config File Approach)

JSON:

```json
{
    "setup": {
        "environment_variables": {
            "TEST_ENV": "development",
            "API_URL": "http://localhost:8080"
        }
    },
    "test_cases": [...]
}
```

YAML:

```yaml
setup:
  environment_variables:
    TEST_ENV: "development"
    API_URL: "http://localhost:8080"
test_cases:
  [...]
```

Environment variables in the config file are set before tests and restored to their original values after tests.

### Custom Setup Plugin

```python
from symtest import BaseSetup, JSONRunner

class DatabaseSetup(BaseSetup):
    def setup(self):
        # Initialization operations
        pass

    def teardown(self):
        # Cleanup operations (executed even if tests fail)
        pass

runner = JSONRunner("test_cases.json")
runner.setup_manager.add_setup(DatabaseSetup({"connection": "test_db"}))
success = runner.run_tests()
```

Multiple plugins execute `setup()` in addition order and `teardown()` in reverse order.

### Execution Order

1. Load setup configuration from config file (environment variables, etc.)
2. Execute `setup()` for all setup plugins (in addition order)
3. Run tests
4. Execute `teardown()` for all setup plugins (in reverse order, guaranteed to execute)

## Parallel Testing

```python
from symtest.runners import ParallelJSONRunner

runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,                # Maximum concurrency, defaults to CPU core count
    execution_mode="thread"       # "thread" or "process"
)
success = runner.run_tests()

# Fallback to sequential execution
runner.run_tests_sequential()
```

**Thread mode**: Shared memory, supports resource-aware scheduling (see next section).  
**Process mode**: Process isolation, does not support resource scheduling.

## Sequential Step Testing

A test case can contain multiple ordered steps. If any step fails, subsequent steps are skipped (fail-fast).

### JSON

```json
{
    "test_cases": [
        {
            "name": "Multi-step Test",
            "execution": {
                "steps": [
                    {
                        "command": "echo",
                        "args": ["step1"],
                        "expected": { "return_code": 0 }
                    },
                    {
                        "command": "echo",
                        "args": ["step2"],
                        "expected": { "return_code": 0 },
                        "retry_count": 2
                    }
                ]
            }
        }
    ]
}
```

### YAML

```yaml
test_cases:
  - name: Multi-step Test
    execution:
      steps:
        - command: echo
          args: ["step1"]
          expected:
            return_code: 0
        - command: echo
          args: ["step2"]
          expected:
            return_code: 0
```

Each step supports `command`, `args`, `expected`, `timeout`, and `retry_count` fields.

**Failure output trimming**: When a step fails in the sequence, the `output` field in the result dictionary **contains only the failed step's output** — not the concatenated output of all prior successful steps. This significantly reduces failure report size, ideal for AI quick diagnosis of failed steps.

**Step details**: View each step's individual status via `detail["step_results"]` (even if all passed), making it easy to understand the entire sequence's execution flow.

**Failure marking**: On failure, the `failed_step` field indicates the failed step number, e.g., "Failed at step 2/3".

**Resume**: After a sequence case fails, use `--resume` to skip already-passed steps and continue from the failed step, dramatically reducing iteration cost for long-running cases. See [Resume](#resume---resume) for details.

### Case-Level expected (Sequential Steps)

After all steps have passed, you can define additional case-level `expected` assertions to perform unified validation (e.g., file comparison) on files produced by all steps. The case-level `expected` field format is identical to single-command mode, supporting `return_code`, `output_contains`, `output_matches`, and `compare_files`.

```json
{
    "name": "Multi-step + File Comparison",
    "execution": {
        "steps": [
            {
                "command": "python",
                "args": ["./generate.py", "output.csv"],
                "expected": { "return_code": 0 }
            },
            {
                "command": "python",
                "args": ["./process.py", "output.csv"],
                "expected": { "return_code": 0, "output_contains": ["Done"] }
            }
        ]
    },
    "expected": {
        "compare_files": [
            {
                "actual": "output.csv",
                "baseline": "baseline/output.csv",
                "type": "csv",
                "rtol": 0.02,
                "start_line": 93,
                "end_line": 99
            }
        ]
    }
}
```

> **Note**: Case-level `expected` only runs after all steps pass. If any step fails, case-level assertions are not executed. When a case-level assertion fails, the error message includes a "Case-level assertion failed" prefix to distinguish it.

## Resource-Aware Scheduling

Only effective in thread mode. Configured via the `scheduling.resources` field; the framework automatically manages CPU core allocation.

```json
{
    "name": "Heavy_Simulation",
    "execution": {
        "command": "solver",
        "args": ["-i", "input.dat"],
        "timeout": 36000
    },
    "scheduling": {
        "resources": {
            "cpu_cores": 4,
            "estimated_time": 18000,
            "min_memory_mb": 16000,
            "priority": 10
        }
    },
    "expected": { "return_code": 0 }
}
```

| Field | Description |
|---|---|
| `cpu_cores` | Required CPU core count, default 1. The framework uses semaphores to control allocation; tasks exceeding the limit wait in queue |
| `estimated_time` | Estimated duration (seconds), used for LPT scheduling (long tasks start first) |
| `min_memory_mb` | Estimated memory (MB), currently used for log warnings only |
| `priority` | Priority 0-10, currently used for informational labeling only |

Framework behavior:
- Automatically detects CPU core count, reserving 2 cores for the system
- Automatically injects `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `NPROC` environment variables when a task starts, preventing solver thread runaway
- Schedules by `estimated_time` in descending order (LPT strategy); if `--history-dir` is enabled, prefers historical `avg_duration` for ordering

## History & Regression Detection

Use `--history-dir` to specify a directory where the framework maintains a `.symtest` file recording each case's historical run times.

### How It Works

1. **First run**: No `.symtest` in the directory; an empty file is auto-created; ordering still uses `estimated_time` from the config
2. **Subsequent runs**: Reads historical data from `.symtest`, preferring `avg_duration` for scheduling order
3. **Regression detection**: After each run, if any case's duration exceeds the historical average by the threshold multiplier (default 1.5), a warning is printed

### CLI Usage

```bash
# Enable history
symtest run test_cases.json --history-dir ./hist

# Custom regression threshold (warn only if 2x the average)
symtest run test_cases.json --history-dir ./hist --regression-threshold 2.0
```

### Python API

```python
from symtest.runners import JSONRunner, ParallelJSONRunner

# Sequential run + history
runner = JSONRunner(
    config_file="test_cases.json",
    history_dir="./hist",
    regression_threshold=2.0,  # Optional, default 1.5
)
success = runner.run_tests()

# Parallel run + history (scheduling also uses historical data)
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    history_dir="./hist",
)
success = runner.run_tests()
```

### .symtest File Format

```json
{
  "version": 1,
  "cases": {
    "case_name_1": {
      "avg_duration": 3.5,
      "last_duration": 3.2,
      "run_count": 5
    }
  }
}
```

| Field | Description |
|---|---|
| `avg_duration` | Cumulative average duration (seconds), used for scheduling and regression baseline |
| `last_duration` | Most recent run duration |
| `run_count` | Historical run count |

### Regression Warning Example

When a case's runtime exceeds the historical average by the threshold multiplier:

```
⚠ WARNING: Case 'heavy_simulation' regressed: 18.2s vs avg 10.5s (1.73x slower)
```

### Without History

When `--history-dir` is not provided, behavior is identical to before — no extra files are created.

### Reset History (--update-history)

When algorithm refactoring or environment changes make historical duration data no longer representative, `--update-history` clears the history entries for the cases involved in this run from `.symtest`, making this run the new baseline for regression detection.

```bash
# Clear history and make this run the new baseline (requires --history-dir)
symtest run config.json --history-dir ./hist --update-history
```

**Behavior**:
- Clears the history entries in `.symtest` for **the cases involved in this run**
- History data for cases not in this run is preserved
- No false positives from regression detection in this run (no historical baseline for comparison)
- The durations of passing cases in this run are recorded as a fresh starting point
- The report shows a `History Reset` count

> **Note**: Must be used with `--history-dir`. Reset scope is limited to the cases run this time; other cases' history data is unaffected.

## JUnit XML Report

Use `--junit-xml` to output a JUnit-format XML report alongside test execution, compatible with Jenkins, GitLab CI, CircleCI, and other CI tools.

### CLI Usage

```bash
symtest run test_cases.json --junit-xml report.xml
```

`--junit-xml` is a supplementary output, coexisting with `--output-format` (text/json/html) without affecting the console report.

### Python API

```python
from symtest import write_junit_xml

runner.run_tests()
write_junit_xml(runner.results, "report.xml", suite_name="my_suite")
```

Status mapping: `passed` → pass; `failed` → failure (assertion failure) or error (execution error); `timeout` → error; `xfailed` → **skipped** (expected failure, no build impact); `xpassed` → **failure** (unexpected pass, treated as build failure). Each testcase element includes command output and failure reason.

## Logging Configuration

All framework diagnostic and status information is output through Python's standard `logging` module, unified under the `symtest` namespace. Logs are written to **stderr** by default, keeping `stdout` clean for safe use with `--output-format json` for machine-readable output.

### CLI Log Level Control

Both `run` and `compare` subcommands support:

| Option | Description |
|---|---|
| `--verbose` / `-v` | Verbose output; log level raised to DEBUG |
| `--debug` | Debug mode; also raised to DEBUG, and prints full stack traces on error |

Default level is INFO, showing only key progress and errors; adding `--verbose` or `--debug` outputs command output, scheduling details, and other DEBUG-level information.

```bash
# Verbose mode (includes command output etc. at DEBUG level)
symtest run test_cases.json --verbose

# Debug mode (prints stack trace on error)
symtest run test_cases.json --debug
```

### Library Usage

When imported as a library, the framework only attaches a `NullHandler` by default, producing no output (following the polite library logging convention). To see logs, call `setup_console_logging()` to enable console output:

```python
import logging
from symtest.logging_config import setup_console_logging, get_logger

# Enable console logging (stderr), with optional level
setup_console_logging(level=logging.DEBUG)

logger = get_logger(__name__)   # Automatically under symtest namespace
logger.info("Custom log message")
```

### Output to Log File

The framework does not have a built-in `--log-file` option, but you can use Python's standard `logging` to add a file handler for the `symtest` logger:

```python
import logging
from symtest.logging_config import get_logger

file_handler = logging.FileHandler("run.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
)

# Add file handler to framework root logger; all child loggers inherit it
logging.getLogger("symtest").addHandler(file_handler)
```

The above code works both for library usage and in scripts alongside `symtest`. Console and file handlers can coexist.

## File Comparison

The framework provides standalone file comparison capabilities, supporting text, JSON, CSV, XML, HDF5, binary, and more formats. Usable via command-line tools or automatically invoked in test case `expected.compare_files` (see [File Comparison Assertions](#file-comparison-assertions-compare_files)).

### Command Line Tools

Two equivalent invocation methods with identical parameters:

```bash
# Standalone command
compare-files <file1> <file2> [options]

# symtest subcommand
symtest compare <file1> <file2> [options]
```

### Common Options

| Option | Description |
|---|---|
| `--file-type` | File type: `auto` (default), `text`, `json`, `csv`, `xml`, `h5`, `binary` |
| `--start-line` | Start line number (1-based), default 1 |
| `--end-line` | End line number (1-based) |
| `--start-column` | Start column number (1-based), default 1 |
| `--end-column` | End column number (1-based) |
| `--encoding` | Text encoding, default `utf-8` |
| `--output-format` | Output format: `text`, `json`, `html` |
| `--verbose` / `-v` | Verbose output |
| `--debug` | Debug mode |
| `--num-threads` | Number of parallel threads, default 4 |

### Text File Comparison

```bash
compare-files file1.txt file2.txt --start-line 10 --end-line 20
```

### JSON File Comparison

```bash
# Exact comparison (default)
compare-files data1.json data2.json

# Compare by key field
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

| Option | Description |
|---|---|
| `--json-compare-mode` | `exact` (default) or `key-based` |
| `--json-key-field` | Matching field for key-based mode, supports comma-separated multi-field |

### CSV File Comparison

```bash
# Basic comparison
compare-files data1.csv data2.csv

# Custom delimiter and numerical tolerance
compare-files data1.csv data2.csv --csv-delimiter ';' --csv-rtol 1e-4 --csv-atol 1e-6

# TSV files (auto-detected as csv type)
compare-files data1.tsv data2.tsv

# Data filtering (compare only numeric cells matching the condition)
compare-files data1.csv data2.csv --csv-data-filter '>1e-6'
compare-files data1.csv data2.csv --csv-data-filter 'abs>1e-9'
compare-files data1.csv data2.csv --csv-data-filter '<=0.01'
```

| Option | Description |
|---|---|
| `--csv-rtol` | Relative tolerance for numerics, default 1e-5 |
| `--csv-atol` | Absolute tolerance for numerics, default 1e-8 |
| `--csv-delimiter` | Field delimiter, default `,` |
| `--csv-quotechar` | Quote character, default `"` |
| `--csv-data-filter` | Data filter expression: `>`, `>=`, `<`, `<=`, `==`; supports `abs` prefix. Only compares numeric cells that **both files** satisfy the condition for |

CSV comparison compares cell by cell in row-column structure; numeric cells within tolerance are considered equal. After `--csv-data-filter` filtering, numeric cell pairs that don't satisfy the condition won't report differences. The difference report includes row/column count mismatches and cell inconsistencies, listing up to 10 entries.

#### Error Analysis (--error-analysis)

By default, CSV and HDF5 comparators stop reporting after finding 10 differences. When you need statistical insight into **all numeric cells**, enable streaming full statistics via `--error-analysis`.

When enabled, each failed file comparison appends `error_stats` to the Compare Failures section of the report:

| Statistic | Description |
|---|---|
| `total_numeric_cells` | Total number of numeric cells compared |
| `mismatched_cells` | Number of cells exceeding tolerance |
| `max_abs_error` | Maximum absolute error and its location |
| `max_rel_error` | Maximum relative error and its location |
| `mean_abs_error` | Mean absolute error |
| `rms_abs_error` | Root-mean-square absolute error (RMSE) |

Statistics are computed **in streaming fashion**, independent of the difference truncation, covering all numeric cells. By default only failed comparisons output statistics; passed comparisons do not.

To also output statistics for **passed** cases (e.g. to monitor tolerance headroom), use `--error-analysis-all` instead (it implicitly enables `--error-analysis`):

```bash
# Output error statistics for all cases (including passed ones)
symtest run config.json --error-analysis-all
```

When enabled, each **passed** case lists the above statistics in the Detailed Results section as `error_stats:`. For passed cases the statistics are also written to the `assertion_results[].error_stats` field of the `--output json` report for programmatic consumption. Statistics for passed cases are produced only when `--error-analysis-all` is enabled; otherwise behavior is unchanged.

**CLI Usage**:

```bash
# Enable error analysis
symtest run config.json --error-analysis

# Enable error analysis and also output statistics for passed cases
symtest run config.json --error-analysis-all

# Combine with comparison parameters
symtest run config.json --error-analysis --csv-rtol 1e-4 --csv-data-filter '>0'
```

**Python API**:

```python
# Enable in comparator
comparator = ComparatorFactory.create_comparator(
    "csv", rtol=1e-5, atol=1e-8, error_analysis=True
)
result = comparator.compare_files("data1.csv", "data2.csv")
print(result.error_stats)  # dict or None

# Enable via Assertions.compare_files
from symtest.core.assertions import Assertions
cf_result = Assertions.compare_files(
    "actual.csv", "baseline.csv",
    file_type="csv", rtol=1e-5, atol=1e-8,
    error_analysis=True,
)
print(cf_result["error_stats"])
```

> **Note**: `--error-analysis` only applies to numeric comparators (CSV, HDF5); text/JSON/XML/binary comparators ignore this parameter. When disabled, behavior is unchanged with no overhead.

### XML File Comparison

```bash
# Structural comparison (tags, attributes, text, child elements)
compare-files config1.xml config2.xml

# HTML files (auto-detected as xml type)
compare-files page1.html page2.html
```

XML comparison recursively compares tags, attributes, text content, and child element counts by DOM structure. The difference report locates specific paths (e.g., `/root/item[0]/@id`), listing up to 10 entries.

### HDF5 File Comparison

```bash
# Compare specified tables
compare-files data1.h5 data2.h5 --h5-table table1,table2

# Use regex to match table names
compare-files data1.h5 data2.h5 --h5-table-regex "result_.*"

# Comma-separated multiple regex patterns
compare-files data1.h5 data2.h5 --h5-table-regex "table1,table2,table3"

# Numerical tolerance
compare-files data1.h5 data2.h5 --h5-rtol 1e-5 --h5-atol 1e-8

# Data filtering (compare only data matching the condition)
compare-files data1.h5 data2.h5 --h5-data-filter '>1e-6'
compare-files data1.h5 data2.h5 --h5-data-filter 'abs>1e-9'
compare-files data1.h5 data2.h5 --h5-data-filter '<=0.01'

# Disable automatic group path expansion
compare-files data1.h5 data2.h5 --h5-table group1 --h5-no-expand-path
```

| Option | Description |
|---|---|
| `--h5-table` | Specify table names, comma-separated |
| `--h5-table-regex` | Regex pattern for table names, comma-separated multi-pattern |
| `--h5-structure-only` | Compare structure only, not content |
| `--h5-show-content-diff` | Show content difference details |
| `--h5-rtol` | Relative tolerance, default 1e-5 |
| `--h5-atol` | Absolute tolerance, default 1e-8 |
| `--h5-data-filter` | Data filter expression: `>`, `>=`, `<`, `<=`, `==`; supports `abs` prefix |
| `--h5-no-expand-path` | Disable automatic expansion of sub-items under group paths |

### Binary File Comparison

```bash
compare-files binary1.bin binary2.bin --similarity --chunk-size 16384
```

| Option | Description |
|---|---|
| `--similarity` | Calculate similarity index |
| `--chunk-size` | Read chunk size, default 8192 |

### Python API

```python
from symtest.file_comparator import ComparatorFactory

# Text comparison
comparator = ComparatorFactory.create_comparator("text", encoding="utf-8", verbose=True)
result = comparator.compare_files("file1.txt", "file2.txt")

# JSON comparison
comparator = ComparatorFactory.create_comparator("json", compare_mode="key-based", key_field="id")
result = comparator.compare_files("data1.json", "data2.json")

# CSV comparison
comparator = ComparatorFactory.create_comparator("csv", rtol=1e-5, atol=1e-8, delimiter=",")
result = comparator.compare_files("data1.csv", "data2.csv")

# CSV comparison (with error analysis)
comparator = ComparatorFactory.create_comparator("csv", rtol=1e-5, atol=1e-8, delimiter=",", error_analysis=True)
result = comparator.compare_files("data1.csv", "data2.csv")
print(result.error_stats)  # Full numeric statistics

# XML comparison
comparator = ComparatorFactory.create_comparator("xml", encoding="utf-8")
result = comparator.compare_files("config1.xml", "config2.xml")

# HDF5 comparison
comparator = ComparatorFactory.create_comparator("h5", tables=["table1"], rtol=1e-5)
result = comparator.compare_files("data1.h5", "data2.h5")

# Results
result.identical   # bool
result.differences # list
```

## Extension Development

### Custom Runner

```python
from symtest.core.base_runner import BaseRunner

class CustomRunner(BaseRunner):
    def load_test_cases(self):
        # Load test cases into self.test_cases
        pass

    def run_single_test(self, test_case):
        # Execute a single test, return result dictionary
        pass
```

### Custom Setup Plugin

```python
from symtest import BaseSetup

class MySetup(BaseSetup):
    def setup(self):
        # self.config gives access to the passed config dict
        pass

    def teardown(self):
        pass
```

### Custom File Comparator

The framework supports three ways to extend comparison capabilities:

#### Method 1: Workspace Plugin Directory (Recommended)

Create a `comparators/` directory under your workspace and place `*_comparator.py` files inside (following the same naming convention as built-in comparators). The framework auto-discovers and registers the `*Comparator` classes on first use.

```
your-workspace/
├── comparators/
│   └── my_analysis_comparator.py   # Auto-discovered by the framework
└── test_config.json
```

You can specify additional plugin directories via the CLI `--plugin-dir` parameter (usable multiple times):

```bash
symtest run test_config.json --plugin-dir ./extra_plugins
```

Plugins are also automatically inherited by process-mode child processes via the `CLITEST_PLUGIN_DIRS` environment variable.

**Plugin development notes**:
- Inherit from `symtest.file_comparator.BaseComparator`
- Class name must end with `Comparator` (e.g., `MyAnalysisComparator`)
- The registered type name = class name without `Comparator`, lowercased (e.g., `myanalysis`)
- Prefer overriding the `compare_files(file1, file2, **kwargs)` method over `read_content`/`compare_content` (if your comparator doesn't use the two-file model)
- Construct structured results via `from symtest.file_comparator import ComparisonResult, Difference`
- `extra_kwargs` are auto-passed from the config `compareSpec`

Use the registered type name directly in your config:

```json
{
  "type": "myanalysis",
  "actual": "optional_for_plugins",
  "baseline": "optional_for_plugins",
  "param1": "value1"
}
```

#### Method 2: Built-in `script` Type Comparator

For quickly integrating standalone analysis scripts without writing a comparator class:

```json
{
  "type": "script",
  "script": "analyze_xxx.py",
  "actual": "output.txt",
  "baseline": "baseline.txt",
  "cwd": ".",
  "pass_pattern": "RESULT: PASS",
  "fail_pattern": "RESULT: (MISMATCH|FAILED)",
  "pass_exit_code": 0,
  "timeout": 600
}
```

**Parameter Descriptions**:

| Parameter | Required | Default | Description |
|---|---|---|---|
| `script` | Yes | — | Script path (relative to workspace or absolute) |
| `actual` | No | — | First file argument passed to the script |
| `baseline` | No | — | Second file argument passed to the script |
| `cwd` | No | — | Script working directory |
| `interpreter` | No | `sys.executable` | Python interpreter |
| `pass_exit_code` | No | `0` | Exit code considered a pass |
| `pass_pattern` | No | — | stdout must match this regex to be considered a pass |
| `fail_pattern` | No | — | stdout matching this regex forces a failure (highest priority) |
| `timeout` | No | `3600` | Timeout in seconds |

**Judgment Logic**:
1. `fail_pattern` match → failure (highest priority)
2. `pass_pattern` set but not matched → failure
3. `pass_pattern` matched → use exit code to judge
4. No pattern → directly use exit code to judge

The script's stdout and stderr are fully captured in the `Comparator Output` section, displayed up to 20 lines in the rendered report.

#### Method 3: Manual Registration (Programmatic)

```python
from symtest.file_comparator import ComparatorFactory
from symtest.file_comparator.base_comparator import BaseComparator

class FooComparator(BaseComparator):
    # Implement read_content / compare_content etc.
    pass

ComparatorFactory.register_comparator("foo", FooComparator)

# Then usable in compare_files assertions or CLI --file-type foo
comparator = ComparatorFactory.create_comparator("foo")
```

#### Specialized Plugin Example: Hourglass Tangent Stiffness Analysis

`examples/plugins/hourglass_tangent_comparator.py` is a complete workspace plugin example demonstrating how to integrate a dedicated `analyze_*_tangent.py` analysis script into the framework:

```json
{
  "type": "hourglass_tangent",
  "script": "case/.../analyze_case01_tangent.py",
  "case_dir": "case/.../case01",
  "pass_threshold": 1e-6,
  "timeout": 600
}
```

**Features**:
- Calls the analysis script via subprocess (**zero changes** to analyze code), parses `RESULT:` lines and numerical metrics like `full_rel`/`aa_rel`/`hh_rel`/`asymmetry` from stdout using regex
- Constructs a structured `ComparisonResult`: `identical` determined by `full_rel < pass_threshold`; `differences` lists exceeded metrics; `error_stats` contains all numeric values
- Script stdout goes into the `Comparator Output` section

Usage: copy the plugin file into your workspace's `comparators/` directory for auto-discovery — no framework code changes needed.

> **More plugin development guidance**: See `examples/plugins/README.md`. Entry points (pip install → just works) will be supported in a future iteration.

### Assertions & File Comparison

The `Assertions` class provides static assertion methods; all checks in `expected` are performed by it:

```python
from symtest.core.assertions import Assertions

Assertions.return_code_equals(actual_code, 0)
Assertions.contains(output, "expected text")
Assertions.matches(output, r".*regex.*")
Assertions.compare_files("actual.txt", "baseline.txt", file_type="text", workspace="/ws")

# Enable error analysis (CSV/H5 only)
Assertions.compare_files("actual.h5", "baseline.h5", file_type="h5", workspace="/ws", rtol=1e-5, error_analysis=True)
```

`compare_files` auto-detects type by extension (`.h5/.hdf5/.hdf`→h5, `.json`→json, `.csv/.tsv`→csv, `.xml/.html/.htm`→xml, `.txt/.log/.out/.py`→text, everything else→binary); relative paths are resolved against `workspace`; extra parameters (including `error_analysis`) are passed through to the comparator.

On success, returns a structured dict (with `identical`, `actual`, `baseline`, `diff_summary`, `differences`, etc.); on failure, raises `ValidationError(AssertionError)` carrying `failure_kind` and a `compare_failures` list.

## Running Framework Tests

The project includes a unified test entry point `tests/run_all.py`. Use `--scope` to select the test range and `--extra` to pass arbitrary pytest arguments.

### Test Scopes

| Scope | Description | Corresponding Directory |
|---|---|---|
| `unit` | Unit tests (core, runners, etc.) | `tests/unit` |
| `integration` | Integration tests (file comparison, parallel, path handling, etc.) | `tests/integration` |
| `e2e` | End-to-end tests (user workflows) | `tests/e2e` |
| `all` | Run all of the above (default) | All three combined |

> Note: Scripts under `tests/demos/` are manual/interactive demos, not included in scope runs; they must be executed separately.

### Usage

```bash
# Run all tests (default)
python tests/run_all.py

# Developers can install all optional and test dependencies at once
pip install -e ".[dev]"

# Run unit tests only
python tests/run_all.py --scope unit

# Run integration tests only
python tests/run_all.py --scope integration

# Run end-to-end tests only
python tests/run_all.py --scope e2e

# Pass pytest arguments, e.g., filter by keyword
python tests/run_all.py --scope integration --extra "-k h5"

# Pass multiple pytest arguments
python tests/run_all.py --scope unit --extra "-v -k assertions"
```

`--extra` accepts a string that is split via `shlex` and appended to the pytest command line. The script invokes pytest through the current interpreter (`sys.executable -m pytest`), ensuring the activated environment is used rather than the first `pytest` found on PATH.

Activate your Python environment (e.g. conda) before running tests:

```bash
conda activate <your-env>
python tests/run_all.py
```
