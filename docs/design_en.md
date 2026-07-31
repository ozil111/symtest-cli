# CLI Test Framework Design Document

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Entry                                │
│     symtest run / tui / validate / schema / compare-files       │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
       │          │          │          │          │
┌──────▼──────┐ ┌▼───────┐ ┌▼───────┐ ┌▼───────┐ ┌▼──────────────┐
│  TUI Manager│ │ Runner │ │ Config │ │ File   │ │  Schema Output │
│  ┌────────┐ │ │ System │ │Validate│ │Comparator│┌────────────┐ │
│  │CaseMgr │ │ │┌Base─┐│ │┌──────┐│ │┌Base─┐ ││JSON Schema │ │
│  │App     │ │ ││Runr ││ ││validate│ ││Comp │ ││  Output    │ │
│  │Controller│ │├JSON││ ││_config││ ││├Text│ │└────────────┘ │
│  │Screens │ │ ││Runr ││ │└──────┘│ ││├Json│ │               │
│  │Widgets │ │ │├YAML││ │         │ ││├Csv │ │               │
│  └────────┘ │ ││Runr ││ │         │ ││├XML │ │               │
│             │ │└Paral││ │         │ ││├H5  │ │               │
└──────┬──────┘ │ │Runr─┼─┘         │ ││├Bin │ │               │
       │        │ │├P-JS│           │ ││├Scpt│ │               │
       │        │ ││OnRnr│          │ │└────┘ │               │
       │        │ │└P-YA│           │ │Factory│               │
       │        │ │MLRnr│           │ │+ Plugin│               │
       │        │ └─────┘           │ └───────┘               │
       │        └───────────────────┘                         │
       │                  │                                   │
┌──────▼──────────────────▼───────────────────────────────────┐
│                       Core Layer                             │
│  TestCase │ Assertions │ ConfigLoader │ Execution │ Setup    │
│  ParallelRunner │ HistoryStore │ LastRunStore │ SequenceState│
│  PathResolver │ ReportGenerator │ JUnitXMLWriter            │
└─────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                    Config Pipeline                           │
│  raw JSON/YAML → expand_imports → resolve_inheritance        │
│  → apply_variables → substitute_placeholders → parse_test_cases│
└─────────────────────────────────────────────────────────────┘
```

The framework is divided into four layers: **CLI Entry Layer** (including TUI), **Runner / Comparator Business Layer**, **Config Pipeline Layer**, and **Core Foundation Layer**.

## 2. Module Responsibilities

### 2.1 Directory Structure

```
src/symtest/
├── __init__.py                  # Package entry, exports public API
├── cli.py                       # symtest command entry (6 subcommands)
├── logging_config.py            # Unified logging configuration
├── core/                        # Core abstractions and base components
│   ├── base_runner.py           # BaseRunner abstract base class
│   ├── parallel_runner.py       # ParallelRunner parallel base + AtomicSemaphore
│   ├── config_loader.py         # Unified config parsing + sequence execution
│   ├── execution.py             # Single test execution + retry + file compare assertions
│   ├── process_worker.py        # Multi-process worker
│   ├── assertions.py            # Assertion engine (including compare_files)
│   ├── setup.py                 # Setup plugin system
│   ├── test_case.py             # TestCase / TestCaseStep data classes
│   ├── history_store.py         # .symtest runtime history storage
│   ├── last_run_store.py        # --last-failed state storage
│   ├── sequence_state.py        # --resume step-level resume
│   └── types.py                 # TypedDict type definitions
├── config/                      # Config pipeline
│   ├── config_io.py             # load_config / save_config / validate_config
│   ├── config_schema.py         # JSON Schema (draft 2020-12)
│   ├── import_expander.py       # Recursive import reference expansion
│   └── inheritance_expander.py  # extends inheritance + variable substitution
├── runners/                     # Concrete runners
│   ├── config_runner.py         # ConfigRunner (generic sequential runner)
│   ├── parallel_config_runner.py# ParallelConfigRunner (generic parallel runner)
│   ├── json_runner.py           # JSONRunner (thin wrapper)
│   ├── yaml_runner.py           # YAMLRunner (thin wrapper)
│   ├── parallel_json_runner.py  # ParallelJSONRunner (thin wrapper)
│   └── parallel_yaml_runner.py  # ParallelYAMLRunner (thin wrapper)
├── file_comparator/             # File comparison subsystem
│   ├── base_comparator.py       # BaseComparator abstract base class
│   ├── result.py                # ComparisonResult / Difference
│   ├── factory.py               # ComparatorFactory factory + plugin discovery
│   ├── text_comparator.py       # Text comparison
│   ├── json_comparator.py       # JSON comparison
│   ├── csv_comparator.py        # CSV comparison
│   ├── xml_comparator.py        # XML comparison
│   ├── binary_comparator.py     # Binary comparison
│   ├── h5_comparator.py         # HDF5 comparison
│   ├── script_comparator.py     # External script comparison
│   └── comparators/             # Empty directory for workspace plugins
├── commands/                    # CLI subcommands
│   └── compare.py               # compare-files entry
├── utils/                       # Utility modules
│   ├── path_resolver.py         # Path resolution
│   ├── report_generator.py      # Report generation
│   └── junit_xml_writer.py      # JUnit XML report
└── tui/                         # Textual terminal UI
    ├── app.py                   # CaseManagerApp + run_tui()
    ├── controllers/
    │   └── case_controller.py   # CaseController (CRUD + search + run)
    ├── screens/
    │   ├── case_list.py         # CaseListScreen (main screen)
    │   └── case_editor.py       # CaseEditorScreen (edit form)
    └── widgets/
        ├── case_table.py        # CaseTable (DataTable wrapper)
        ├── search_bar.py        # SearchBar (multi-mode search)
        ├── expected_editor.py   # ExpectedEditor (expected editing)
        └── steps_editor.py      # StepsEditor (sequence step editing)
```

### 2.2 Entry Points

| Command | Mapping |
|---|---|
| `symtest run` | `symtest.cli:run_tests` |
| `symtest tui` | `symtest.tui.app:run_tui` |
| `symtest validate` | `symtest.cli:run_validate` |
| `symtest schema` | `symtest.cli:run_schema` |
| `symtest compare` | `symtest.cli:run_compare` |

## 3. Config Pipeline

Configuration files go through a five-step pipeline during loading:

```
raw JSON/YAML file
    │
    ▼
expand_imports()          # Recursively expand import references (merge setup, inject tags)
    │
    ▼
resolve_inheritance()     # Resolve extends chains (deep-merge, remove abstract)
    │
    ▼
apply_variables()         # Inject --var global variables + case-level variables
    │
    ▼
substitute_placeholders() # Recursively replace {placeholder} tokens
    │
    ▼
parse_test_cases()        # Convert to List[TestCase] (command path resolution)
```

### 3.1 Import Expansion (`import_expander.py`)

Main config files can reference sub-config files via `"import"`:

```json
{
  "test_cases": [
    { "import": "cases/text_tests.json", "tags": ["text", "fast"] },
    { "import": "cases/json_tests.yaml" },
    { "name": "inline_case", "command": "echo", ... }
  ]
}
```

- Recursively expands all imports, inlining them into the main config
- Import-level tags are injected into each case from the imported file
- setup blocks are deep-merged
- Circular import detection

### 3.2 Inheritance Expansion (`inheritance_expander.py`)

The `extends` field enables test-case template inheritance:

```json
{
  "test_cases": [
    { "name": "_base", "abstract": true, "timeout": 3600, "expected": {"return_code": 0} },
    { "name": "my_test", "extends": "_base", "command": "solver", ... }
  ]
}
```

- Deep-merge (dict) / whole-replace (list) strategy
- `abstract: true` templates are excluded from execution
- `variables` collected along the extends chain are substituted at resolve time
- Circular extends detection

### 3.3 Config Validation (`config_io.py`)

The `symtest validate` subcommand checks configuration without running tests:

- Error-level (affects `valid`): JSON/YAML syntax, required fields, import target existence, circular imports, extends target existence, circular extends
- Warning-level (does not affect `valid`): command executability (PATH lookup), `compare_files` baseline file existence

## 4. Core Class Design

### 4.1 Runner Inheritance Hierarchy

```
BaseRunner (ABC)
├── ConfigRunner              # Generic sequential runner (injectable config_loader)
│   ├── JSONRunner            # Thin wrapper (injects json.load)
│   └── YAMLRunner            # Thin wrapper (injects yaml.safe_load)
└── ParallelRunner
    └── ParallelConfigRunner  # Generic parallel runner (injectable config_loader)
        ├── ParallelJSONRunner   # Thin wrapper
        └── ParallelYAMLRunner   # Thin wrapper
```

The difference between JSON and YAML runners is only the config loader. Common logic is unified in ConfigRunner / ParallelConfigRunner.

#### BaseRunner

The abstract base class for all Runners, defining the template workflow for test execution.

```python
class BaseRunner(ABC):
    def __init__(self, config_file: str, workspace: Optional[str] = None,
                 test_case_filter: Optional[List[str]] = None,
                 test_case_tag_filter: Optional[List[str]] = None,
                 history_dir: Optional[str] = None,
                 regression_threshold: float = 1.5,
                 update_baseline: bool = False,
                 update_history: bool = False,
                 error_analysis: bool = False,
                 last_failed: bool = False,
                 resume: bool = False,
                 plugin_dirs: Optional[List[str]] = None)
```

**Template method `run_tests()`**:

```
load_test_cases() → _apply_test_case_filter() → setup_manager.setup_all()
    → [run_single_test(case) for case in test_cases]  # Sequential execution
    → _update_history()  → _save_last_run()
    → setup_manager.teardown_all()
```

**Key attributes**:

| Attribute | Type | Description |
|---|---|---|
| `workspace` | `Path` | Working directory |
| `test_cases` | `List[TestCase]` | Loaded test cases |
| `results` | `Dict` | Run results `{total, passed, failed, xfailed, xpassed, updated, details}` |
| `assertions` | `Assertions` | Assertion engine instance |
| `setup_manager` | `SetupManager` | Setup manager |
| `history_dir` | `Optional[str]` | `.symtest` history directory |
| `regression_threshold` | `float` | Regression detection threshold, default 1.5 |
| `update_baseline` | `bool` | Auto-update baseline on comparison failure |
| `update_history` | `bool` | Clear history before recording |
| `error_analysis` | `bool` | CSV/H5 numerical error statistics |
| `last_failed` | `bool` | Run only previously failed cases |
| `resume` | `bool` | Resume sequence from last failed step |

**Abstract methods**:

| Method | Responsibility |
|---|---|
| `load_test_cases()` | Parse config file, populate `self.test_cases` |
| `run_single_test(case)` | Execute a single test, return result dictionary |

**Filtering `_apply_test_case_filter()`**:

Supports three filter modes (combinable):
- `test_case_filter`: exact name match
- `test_case_tag_filter`: tag-based match (intersection logic)
- `last_failed`: reads previously failed case names from `.cli-test/last_run.json`

**xfail mechanism `_apply_xfail_status()`**:

When `case.expected_failure=True`:
- `passed` → `xpassed` (unexpected pass; counted as a suite failure)
- any non-passed status → `xfailed` (expected failure; not counted as a failure)

#### ParallelRunner

Inherits BaseRunner, overrides `run_tests()` with a parallel version.

```python
class ParallelRunner(BaseRunner):
    def __init__(self, config_file, workspace=None,
                 max_workers=None, execution_mode="thread", ...)
```

- Thread mode: `ThreadPoolExecutor`, shared memory, supports resource scheduling
- Process mode: `ProcessPoolExecutor` + `process_worker.run_test_in_process()`, process isolation
- Thread safety: `_results_lock` / `_print_lock` protect shared state
- Fallback method: `run_tests_sequential()`

#### ParallelConfigRunner

Extends ParallelRunner with **resource-aware scheduling**:

1. After loading cases, sort by `estimated_time` in descending order (LPT strategy); if `history_dir` is enabled, prioritize `.symtest` historical `avg_duration` for sorting
2. Create `AtomicSemaphore(safe_capacity)` resource pool, `safe_capacity = max(1, cpu_count - 2)`
3. Before each case executes, acquire `cpu_cores` semaphores; release after execution
4. Automatically inject `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `NPROC` environment variables
5. `_assign_relative_cpu_cores()`: proportionally assign CPU cores based on `estimated_time` and `min_memory_mb` weights

### 4.2 TestCase Data Model

```python
@dataclass
class TestCaseStep:
    command: str
    args: List[str]
    expected: Dict[str, Any]
    timeout: Optional[float] = None
    retry_count: int = 0

@dataclass
class TestCase:
    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    expected: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    timeout: Optional[float] = None
    resources: Optional[Dict[str, Any]] = None
    steps: Optional[List[TestCaseStep]] = None
    tags: List[str] = field(default_factory=list)
    retry_count: int = 0
    expected_failure: bool = False
    xfail_reason: str = ""
    xfail_quiet: bool = False
```

Two modes:
- **Single command mode**: `command` + `args` + `expected`
- **Step sequence mode**: `steps` list, each step contains `command` + `args` + `expected`

New fields:
- `tags`: tag-based filtering
- `retry_count`: failure retry count
- `expected_failure` / `xfail_reason` / `xfail_quiet`: expected failure markers

### 4.3 Assertions

```python
class Assertions:
    def return_code_equals(self, actual, expected) -> None    # Exact match
    def contains(self, output, expected_text) -> None         # Substring match
    def matches(self, output, expected_patterns) -> None      # Regex match
    def compare_files(self, actual_path, baseline_path, ...)  # File comparison assertion
```

Assertion logic: return code exact match, `contains` does substring matching, `matches` does regex matching. All assertions are optional; unspecified fields are not validated.

`compare_files` invokes ComparatorFactory at the assertion level, making file comparison a first-class assertion.

### 4.4 Setup Plugin System

```python
class BaseSetup(ABC):
    def __init__(self, config: Dict)
    @abstractmethod
    def setup(self) -> None
    @abstractmethod
    def teardown(self) -> None

class EnvironmentSetup(BaseSetup):
    # setup(): Set environment variables (save old values)
    # teardown(): Restore environment variables

class SetupManager:
    def add_setup(self, setup: BaseSetup) -> None
    def setup_all(self) -> None      # Execute in addition order
    def teardown_all(self) -> None   # Execute in reverse order, ensuring cleanup continues even on errors
```

**Config file integration**: `load_setup_from_config()` automatically creates EnvironmentSetup from the `setup.environment_variables` field in JSON/YAML and registers it.

### 4.5 PathResolver

```python
class PathResolver:
    SYSTEM_COMMANDS = {'echo', 'python', 'node', 'java', ...}

    def resolve_command(self, command: str) -> str
    def resolve_path(self, path: str) -> str
    def split_command(self, cmd_str: str) -> Tuple[str, List[str]]
```

Responsibilities:
- System commands are returned as-is; non-system commands are resolved relative to workspace path
- Shell builtins (echo/cd/export etc.) are automatically wrapped with the platform shell
- Compound commands (e.g., `"python ./script.py"`) are split and resolved separately

### 4.6 Execution

`execute_single_test_case(case, workspace)` — Independent execution function for a single test:

1. PathResolver resolves command and arguments
2. `subprocess.run()` executes, capturing stdout/stderr/returncode
3. `validate_result()` validates each item (return_code / contains / matches / compare_files)
4. Supports automatic failure retry (`retry_count` times)
5. On timeout, kills the entire process group
6. Returns structured result (including `next_action_hint` suggesting the next action)

### 4.7 HistoryStore

`.symtest` runtime history storage module for persisting per-case runtime, supporting smart scheduling and regression detection.

```python
# .symtest file format (JSON):
# {
#   "version": 1,
#   "cases": {
#     "case_name": {
#       "avg_duration": 3.5,    # Cumulative average duration
#       "last_duration": 3.2,   # Last run duration
#       "run_count": 5           # Number of runs
#     }
#   }
# }
```

Core interfaces:

| Function | Description |
|---|---|
| `ensure_symtest(history_dir)` | Create `.symtest` if not present |
| `load_history(history_dir)` | Read `.symtest` |
| `save_history(history_dir, history)` | Write back `.symtest` |
| `update_case(history, name, duration)` | Cumulative average update |
| `reset_cases(history, case_names)` | Clear specified case history entries |
| `check_regression(history, name, duration, threshold)` | Regression detection |

### 4.8 LastRunStore

`--last-failed` state storage module (`core/last_run_store.py`):

```python
# Storage location: <workspace>/.cli-test/last_run.json
# {
#   "case_name": {"status": "passed"},
#   ...
# }
```

Core interfaces:

| Function | Description |
|---|---|
| `update_last_run(workspace, results)` | Overwrite last-run state with current results |
| `get_last_failed_names(workspace)` | Return names of previously failed/timed-out/xpassed cases |
| `get_last_run_summary(workspace)` | Return summary statistics of the last run |

Each run **overwrites** the status of executed cases; unexecuted cases retain their previous status.

### 4.9 SequenceState

`--resume` step-level resume module (`core/sequence_state.py`):

```python
# State file: <workspace>/.cli-test/sequence_state/<case_name>.json
# Output cache: <workspace>/.cli-test/sequence_state/cache/<case_name>.step<N>.log
```

Core interfaces:

| Function | Description |
|---|---|
| `compute_config_hash(steps, case_expected)` | Compute SHA-256 of step configuration (detect config changes) |
| `save_sequence_state(workspace, case_name, state)` | Save step state |
| `load_sequence_state(workspace, case_name)` | Load step state |
| `save_step_output(workspace, case_name, step_idx, output)` | Cache step output |
| `load_step_output(workspace, case_name, step_idx)` | Read cached output |
| `delete_sequence_state(workspace, case_name)` | Clean up after full pass |

**Trust model**: `--resume` trusts that workspace artifacts have not been modified; no artifact validation is performed.

### 4.10 ReportGenerator

```python
class ReportGenerator:
    def print_report(self) -> None                   # Terminal output
    def generate_report(self) -> str                 # Return text string
    def generate_json_report(self) -> str            # JSON format
    def generate_html_report(self) -> str            # HTML format
```

### 4.11 JUnitXMLWriter

```python
def write_junit_xml(results: Dict, filepath: str,
                    suite_name: Optional[str] = None,
                    classname: Optional[str] = None) -> None
```

Generates JUnit XML reports compatible with GitLab CI / Jenkins / CircleCI.

Status mapping:
- `passed` → no child element (JUnit passed convention)
- `xfailed` → `<skipped>` (expected failure)
- `xpassed` → `<failure>` (unexpected pass, marked as assertion failure)
- `timeout` → `<error>` (timeout)
- `failed` → `<failure>` or `<error>` depending on message type

## 5. File Comparison Subsystem

### 5.1 Class Hierarchy

```
BaseComparator (ABC)
├── TextComparator       # Line-level comparison based on difflib
│   ├── JsonComparator   # Compare after aligning by key field
│   ├── CsvComparator    # CSV structured comparison
│   └── XmlComparator    # XML structured comparison
├── H5Comparator         # HDF5 scientific data comparison
├── BinaryComparator     # Binary stream chunking + LCS similarity
└── ScriptComparator     # Delegates comparison to an external script
```

### 5.2 BaseComparator

```python
class BaseComparator(ABC):
    def __init__(self, encoding="utf-8", chunk_size=8192, verbose=False)

    @abstractmethod
    def read_content(self, file_path, start_line, end_line, start_column, end_column)

    @abstractmethod
    def compare_content(self, content1, content2) -> Tuple[bool, List[Difference]]

    def compare_files(self, file1, file2, start_line, end_line,
                      start_column, end_column) -> ComparisonResult
```

### 5.3 ComparatorFactory

```python
class ComparatorFactory:
    @staticmethod
    def create_comparator(file_type: str, **kwargs) -> BaseComparator
    @staticmethod
    def register_comparator(file_type, comparator_class)
    @staticmethod
    def set_plugin_dirs(dirs)              # Set workspace plugin directories
    @staticmethod
    def get_available_comparators()        # Get list of registered comparators
    @staticmethod
    def reset()                            # Reset all state (for testing)
```

**Plugin discovery mechanism**:

1. Automatically discover built-in `*_comparator.py` modules
2. Scan `workspace/comparators/` directory (automatic)
3. `--plugin-dir` CLI parameter for additional directories
4. `CLITEST_PLUGIN_DIRS` environment variable (used by process-mode workers)
5. Plugin naming convention: `*_comparator.py` + `*Comparator` class name

`file_type` values: `"text"` / `"json"` / `"csv"` / `"xml"` / `"h5"` / `"binary"` / `"script"`

### 5.4 ScriptComparator

A new comparator type that delegates comparison to an external script:

```json
{
  "type": "script",
  "script": "analyze.py",
  "actual": "output.dat",
  "baseline": "baseline.dat",
  "pass_pattern": "PASS",
  "fail_pattern": "(MISMATCH|FAILED)"
}
```

- Executes `python script.py <actual> <baseline>` as a subprocess
- Default exit code 0 → pass
- Optional `pass_pattern` / `fail_pattern` regexes match stdout to refine verdict
- Supports `timeout` control

### 5.5 ComparisonResult

```python
class ComparisonResult:
    file1: str
    file2: str
    identical: bool
    differences: List[Difference]
    error: Optional[str]
    command_output: Optional[str]    # ScriptComparator output
    # Supports output: str() / to_json() / to_html()
```

### 5.6 Error Analysis

`--error-analysis` provides streaming error statistics for CSV/H5 numerical comparisons:
- `total_numeric_cells`: total numeric cells compared
- `mismatched_cells`: mismatched cell count
- `max_abs_error` / `max_rel_error`: maximum absolute/relative error
- `mean_abs_error` / `rms_abs_error`: mean absolute error / RMS error

## 6. TUI Subsystem

Terminal-based interactive interface built on [Textual](https://textual.textualize.io/).

```
symtest tui test_cases.json --workspace /path/to/project
```

### 6.1 Architecture

```
CaseManagerApp (Textual App)
├── CaseController              # Business logic layer
│   ├── load()                  # Load config file
│   ├── create_case()           # Create case
│   ├── update_case()           # Update case
│   ├── delete_case()           # Delete case
│   ├── run_single()            # Run single case
│   └── save()                  # Save config
├── Screens
│   ├── CaseListScreen          # Main screen: case list + search + actions
│   └── CaseEditorScreen        # Edit form: single command / sequence steps
└── Widgets
    ├── CaseTable               # DataTable wrapper (name/command/status columns)
    ├── SearchBar               # Name/command/tag multi-mode search
    ├── ExpectedEditor          # Expected assertion config editor
    └── StepsEditor             # Multi-step sequence editor
```

### 6.2 Key Bindings

| Key | Action |
|---|---|
| `q` / `Ctrl+Q` | Quit |
| `r` | Refresh list |
| `e` | Edit selected case |
| `f` | Run selected case |
| `/` | Search |
| `a` | Add new case |
| `d` | Delete selected case |
| `s` | Save config |

## 7. Data Flow

### 7.1 Test Execution Flow

```
Config file (JSON/YAML)
       │
       ▼
  expand_imports()           # Import reference expansion
       │
       ▼
  resolve_inheritance()      # extends inheritance resolution
       │
       ▼
  apply_variables()          # Global + case-level variable injection
       │
       ▼
  substitute_placeholders()  # {placeholder} replacement
       │
       ▼
  parse_test_cases()         # Parse into List[TestCase]
       │
       ▼
  _apply_test_case_filter()  # Filter by name/tags/--last-failed
       │
       ▼
  setup_manager.setup_all()  # Environment variables + custom plugins
       │
       ▼
  [if history_dir] load .symtest → read historical avg_duration (for scheduling sort)
       │
       ▼
  ┌──────────────────────────────────────┐
  │  for each TestCase:                  │
  │    PathResolver resolves command     │
  │    subprocess.run() executes         │
  │    validate_result() validates       │
  │      ├── return_code_equals          │
  │      ├── contains (substring)        │
  │      ├── matches (regex)             │
  │      └── compare_files (file comp.)  │
  │    [if failed & retry_count > 0] retry│
  │    Collect to results["details"]     │
  └──────────────────────────────────────┘
       │
       ▼
  _apply_xfail_status()      # xfail status mapping
       │
       ▼
  _update_history()          # Regression detection + update .symtest
       │
       ▼
  _save_last_run()           # Write .cli-test/last_run.json
       │
       ▼
  setup_manager.teardown_all() # Reverse cleanup
       │
       ▼
  ReportGenerator / write_junit_xml()   # text / json / html / JUnit XML
```

### 7.2 Parallel Execution Flow

```
ParallelConfigRunner.run_tests()
       │
       ▼
  LPT sort (historical avg_duration preferred, fallback to estimated_time desc)
       │
       ▼
  _assign_relative_cpu_cores()  # Proportional CPU core assignment by weight
       │
       ▼
  ┌──────────────────────────────────────┐
  │  ThreadPoolExecutor.map():           │
  │    AtomicSemaphore.acquire(cores)    │
  │    Inject OMP/MKL/NPROC env vars     │
  │    execute_single_test_case()        │
  │    AtomicSemaphore.release(cores)    │
  │    _update_results() (thread-safe)   │
  └──────────────────────────────────────┘
```

### 7.3 File Comparison Flow

```
symtest compare file1 file2 [options]
       │
       ▼
  Auto-detect / specify --file-type
       │
       ▼
  ComparatorFactory.create_comparator(file_type, **kwargs)
       │
       ▼
  comparator.compare_files(file1, file2, ...)
       │
       ├── read_content() × 2
       ├── compare_content()
       └── ComparisonResult
       │
       ▼
  format_result(result, --output-format)  # text / json / html
```

### 7.4 --resume Checkpoint Flow

```
Sequence test case execution
       │
       ▼
  [--resume enabled] compute_config_hash(steps)
       │
       ▼
  load_sequence_state()  → Check if config hash matches
       │
       ├── Match → Skip passed steps, splice cached outputs
       └── Mismatch → Full execution
       │
       ▼
  Each step passed → save_sequence_state() + save_step_output()
       │
       ▼
  All passed → delete_sequence_state() (cleanup)
```

## 8. Extension Points

| Extension Point | Base Class | Purpose |
|---|---|---|
| New config format | `BaseRunner` | Support new test definition formats (e.g., XML, TOML) |
| Custom Setup | `BaseSetup` | Database initialization, service start/stop, etc. |
| Custom assertions | Extend `Assertions` | Specific business validation logic |
| New comparator | `BaseComparator` | Support new file formats; place in `comparators/` for auto-discovery |
| New Runner | `ParallelRunner` / `BaseRunner` | Custom parallel scheduling strategies |
| TUI extensions | `CaseController` / Widgets | Extend the terminal management interface |

## 9. Design Decisions

| Decision | Reason |
|---|---|
| Runner uses Template Method pattern | Unified execution flow (load → filter → setup → run → history → last-run → teardown), subclasses only implement config parsing and single test execution |
| Config pipeline processing | import/extends/variables are orthogonal concerns; each step has a single responsibility and can be independently tested and composed |
| JSON/YAML runners unified into ConfigRunner | Eliminates code duplication by injecting a `config_loader` to adapt different formats |
| Setup reverse-order teardown | Stack-like semantics: dependencies initialized later are cleaned up first |
| Semaphore-based CPU core management | More fine-grained than thread pool worker count; allows different cases to declare different core requirements |
| LPT scheduling strategy | Long tasks start first, reducing tail latency; prioritizes `.symtest` historical data |
| Cumulative average history update | Simple and intuitive; single anomalies are naturally diluted over many runs |
| Regression check before update | Compare against old average first, then update; ensures comparison is against the "historical baseline" |
| `.symtest` hidden file + `.cli-test/` directory | Non-intrusive to the user's directory view; JSON format for easy debugging; state files centrally managed |
| Environment variable injection | Scientific computing solvers often ignore Python-level thread control |
| Comparator factory + plugin discovery | Creates comparators by file type; workspace `comparators/` directory for auto-discovered plugins |
| subprocess isolated execution | Each test case runs in an independent subprocess, ensuring tests don't affect each other |
| xfail mechanism | Supports expected-failure tests (non-blocking in CI), alerts on unexpected passes |
| --last-failed overwrite strategy | Only overwrites status of executed cases; avoids losing state of unexecuted cases during subset runs |
| --resume pure trust model | No artifact validation; user guarantees workspace is unchanged, simplifying implementation |
| retry_count retry mechanism | Handles transient network glitches or race conditions; auto-retries on first failure |
| --update-baseline | Automatically overwrites baseline files with actual output on comparison failure; ideal for batch baseline updates |
| next_action_hint structured suggestions | Failed results include actionable suggestions (update_baseline / update_expected / increase_timeout / investigate), convenient for AI consumption |
| TUI based on Textual | Leverages a mature terminal UI framework for interactive case management |
| JUnit XML output | Compatible with GitLab CI / Jenkins / CircleCI and other major CI system test report formats |
| Centralized logging | All diagnostic messages go through Python's `logging` module; CLI entry activates console output; library users enable as needed |
