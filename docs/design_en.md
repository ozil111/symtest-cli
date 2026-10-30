# SymTest Design Document

> **Maintenance principle (single source of truth)**: this document does not mirror
> code structure — it no longer maintains directory trees, class signatures,
> function inventories, dataclass field definitions, or anything else that rots as
> the code evolves. Directory layout and APIs live in `src/symtest/` sources and
> their docstrings; usage examples live in `examples/`.
> This document only carries what cannot be read out of code: architecture
> layering, responsibility boundaries, key flow semantics, extension contracts,
> design decisions, and the architecture invariants.

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  CLI Entry Layer    symtest run / find / validate / schema / │
│                     compare-files                             │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Business Layer    Runners (sequential / parallel / DAG /    │
│                    resource-aware) · File Comparators        │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Config Pipeline   raw JSON/YAML → expand_imports            │
│                    → resolve_inheritance → apply_variables   │
│                    → substitute_placeholders                 │
│                    → parse_test_cases                        │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Core Layer        TestCase model · assertion engine ·       │
│                    single-test execution · Runner bases ·    │
│                    Setup plugins · .symtest state stores ·   │
│                    path resolution · reporting · JUnit XML   │
└─────────────────────────────────────────────────────────────┘
```

The framework is divided into four layers: **CLI Entry Layer**,
**Runner / Comparator Business Layer**, **Config Pipeline Layer**, and
**Core Foundation Layer**.

Layers are not free-to-wire: cross-layer data flow and dependency directions are
governed by the §10 architecture invariants. Resolve feature ownership
against them first.

## 2. Module Map

Responsibilities by package (file-level details and public APIs live in source):

| Package | Responsibility |
|---|---|
| `cli.py` / `commands/` | Sub-command entry points, argument assembly, logging activation |
| `core/` | TestCase model, assertion engine, single-test execution, Runner bases (sequential / parallel / DAG), `.symtest` state stores, Setup plugin system |
| `config/` | Config IO, shared preparation pipeline (`prepared.py`), dual-form JSON Schema contract & validation (draft 2020-12, `config_schema.py`), import expansion, extends inheritance, variable & placeholder substitution |
| `runners/` | Thin wrapper runners: Config/JSON/YAML × sequential/parallel |
| `file_comparator/` | Comparator family + factory + workspace plugin discovery (see §6) |
| `utils/` | Path resolution, report generation, JUnit XML output, project-level default configuration (`.symtest/symtest.json`) |

### 2.1 Entry Points

| Command | Mapping |
|---|---|
| `symtest run` | `symtest.cli:run_tests` |
| `symtest find` | `symtest.commands.find:run_find` |
| `symtest validate` | `symtest.cli:run_validate` |
| `symtest schema` | `symtest.cli:run_schema` |
| `symtest compare` | `symtest.cli:run_compare` |
| `compare-files` | `symtest.commands.compare:main` (standalone entry, shares argument assembly and execution logic with `symtest compare`; kept for legacy users and Windows console-script usage) |

## 3. Config Pipeline

Raw templates and heirs may provide partial `execution` dictionaries. Their
schema reuses the complete execution field constraints and defers only the
required `command/args` checks. Supplied steps remain complete because lists
are replaced as a whole. `load_config(..., workspace=...)` forwards the workspace
to preparation, and `find` passes its CLI workspace explicitly. Imported file
read errors, including YAML parser errors, are normalized at the file boundary
into diagnostics carrying the failing file and its referring file.

The single source of truth for the configuration contract is
`config/config_schema.py` (JSON Schema draft 2020-12, two variants):

- **Raw form** (`CONFIG_SCHEMA`): original config files as written by
  users / AI agents. `abstract` templates and `extends` heirs may omit
  required execution fields — completeness is enforced after expansion.
  `symtest schema` exports this variant.
- **Expanded form** (`EXPANDED_CONFIG_SCHEMA`): the effective config after
  import / extends / variables have all been resolved. Every executable
  case must be complete.

The three entry points (`validate` / `run` / `find`) share one preparation
pipeline, `config/prepared.py:prepare_config()`; structural failures stop
processing of the affected input (later stages never see malformed dicts):

```
raw JSON/JSONC/YAML file (.jsonc is preprocessed by config/jsonc.py: comments and trailing commas are stripped)
    │
    ▼
raw-form schema validation  # every loaded file (incl. imported sub-files):
                           # field names / types / value ranges /
                           # execution-form exclusivity / unknown fields
    │
    ▼
expand_imports()           # Recursively expand import references (merge setup, inject tags)
    │
    ▼
duplicate-name check       # extends references must be unambiguous
    │
    ▼
resolve_inheritance()      # Resolve extends chains (deep-merge, remove abstract)
    │
    ▼
apply_variables()          # Inject --var global variables + case-level variables,
                           # recursively replace {placeholder} tokens
    │
    ▼
expanded-form validation   # every executable case must be complete after expansion
    │
    ▼
semantic checks            # error-level: depends_on graph (existence / self-ref /
                           # cycles), outputs path boundaries; warning-level:
                           # command executability, baseline existence, outputs conflicts
    │
    ▼
parse_test_cases()         # Convert to List[TestCase] (command path resolution)
```

Adding a new ordinary config field now only requires defining its validity in
the schema and implementing its conversion in the parser — `validate` picks up
the check automatically; no separate field-rule list is maintained.

### 3.1 Import Expansion (`import_expander.py`)

Main config files reference sub-config files via `"import"`:

- Recursively expands all imports, inlining them into the main config
- Import-level tags are injected into each case from the imported file
- setup blocks are deep-merged
- Circular import detection

Config shapes and usage examples live in `examples/`.

### 3.2 Inheritance Expansion (`inheritance_expander.py`)

The `extends` field enables test-case template inheritance:

- Deep-merge (dict) / whole-replace (list) strategy
- `abstract: true` templates are excluded from execution
- `variables` collected along the extends chain are substituted at resolve time
- Circular extends detection

### 3.3 Config Validation & Shared Preparation Pipeline (`prepared.py` / `config_io.py`)

`validate_config()` delegates to `prepare_config()`; the `run` loading stage
and `find` (via `load_config()`) go through the same pipeline. An invalid
config yields identical errors from `validate` and `run`, and `run` exits
before executing any command. Diagnostics carry the file path and field path
(jsonschema `json_path`); errors inside imported sub-files are localized to
the exact file and field.

- Error-level (affects `valid`): JSON/YAML syntax; raw/expanded schema checks
  (required fields, types, value ranges, execution-form exclusivity, unknown
  fields); import target existence; circular imports; duplicate case names;
  extends target existence; circular inheritance; post-expansion case
  completeness; `outputs` path boundaries; depends_on target existence /
  self-reference / cycles
- Warning-level (does not affect `valid`): `command` executability (PATH
  lookup), `compare_files` baseline file existence, multiple cases declaring
  the same outputs path without depends_on

## 4. Execution Semantics

> This chapter records cross-module behavioral contracts only; class attributes,
> method signatures and defaults live in source.

### 4.1 Runner Template and Status Mapping

- Fixed template flow: `load_test_cases()` → filter (exact name / tag intersection / `--last-failed`) → `setup_all()` → per-case execution → xfail status mapping → history & last-run update → `teardown_all()` (reverse order; cleanup continues even on errors)
- JSON/YAML runners differ only by injected config_loader; common logic lives in the generic sequential / parallel runners
- xfail: when `expected_failure=True`, `passed → xpassed` (unexpected pass, counted as a suite failure); any non-passed status → `xfailed` (expected failure, not counted)
- JUnit XML status mapping: `xfailed → <skipped>`, `xpassed → <failure>`, `timeout → <error>`, `failed` split into `<failure>` / `<error>` by message type
- History: duration uses cumulative average update; regression is checked against the prior average before writing; memory peaks are recorded independently (`last_peak_memory_bytes` / `max_peak_memory_bytes` / `peak_memory_count` / `peak_memory_source`, bytes) for any run with a valid measurement (including failed / timeout), scheduling estimates use the historical maximum; `--update-history` clears the whole record (duration + memory)
- `--last-failed`: each run overwrites only the statuses of executed cases; subset runs never lose states of unexecuted cases

### 4.2 Two Case Modes

Single-command mode (`command + args + expected`) or steps-sequence mode;
each step is an atomic "execute + judge" pair (command / args / timeout /
retry_count / expected). The full field set lives in `core/test_case.py` and the
JSON Schema; it is not restated here.

### 4.3 Parallelism and Resource Scheduling

- LPT strategy: long tasks first; with history enabled, historical `avg_duration` takes precedence over declared `estimated_time` (entries with memory-only records and no duration fields are tolerated, treated as 0)
- `AtomicSemaphore` resource pool: `safe_capacity = max(1, cpu_count − 2)`; per-case acquire/release by `cpu_cores`
- Relative CPU cores assigned proportionally by weight; auto-injects `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `NPROC`
- Environment variable precedence: `os.environ` < scheduler injection < case-level env (via subprocess, never mutating global `os.environ`)
- Thread mode shares memory with result/print locks; process mode isolates via process workers; sequential fallback available

**Windows memory-aware scheduling — opportunistic admission** (enabled for thread mode on Windows when `--history-dir` is set or `min_memory_mb` is declared; otherwise the original CPU-only path is kept unchanged):

- Demand estimate priority: explicit `min_memory_mb` > historical max peak × safety factor (default 1.2, configurable via `memory_margin`) > configurable default demand (`memory_default_demand_mb`, default 4096 MB); no more whole-pool exclusive runs
- `JointResourceManager` joint pool: CPU tokens + a system snapshot (`GlobalMemoryStatusEx` available physical memory, `GetPerformanceInfo` commit margin) are evaluated atomically under a single lock — eliminating the partial-holding deadlock of "holding CPU while waiting for memory and vice versa"
- **Admission criteria** (all must hold to start): CPU tokens suffice; under potential peak crowding, at least the minimum startup interval (`memory_min_start_interval_s`, default 1s) has elapsed since the previous grant (staggered starts, avoiding thundering herds that all see the same headroom); commit margin ≥ the new task's estimated demand + commit reserve (`memory_commit_reserve_mb`, default 2048 MB); available physical memory ≥ the physical watermark (`memory_physical_watermark_mb`, default 2048 MB, an independent pressure check not tied to the demand). The commit and physical budgets are modelled separately and never mixed
- **No double counting**: full future peaks are no longer reserved for running tasks — memory already in use shows up naturally in the system headroom; the residual risk of a running task growing again is explicitly accepted (occasional OOM allowed, zero-failure not guaranteed). Measurements proved the old "full reservations + snapshot backstop" policy squeezed 2/4-worker concurrency down to 1 on a 31.8 GiB machine
- Under memory pressure only new admissions are paused; running tasks continue. Waiters reuse already granted tickets under the lock, preventing duplicate charges when polling timeouts race with release; waiters blocked by the startup interval wake on the remaining interval
- Denial reasons (with key numbers: demand / reserve / headroom / watermark) come from the actual decision path and are stored on `waiter.deny_reason` plus the scheduler log for acceptance attribution
- Physical watermark validation: when total physical memory is known, a nonzero watermark must be strictly below it; otherwise initialization raises `ValueError` instead of waiting forever. Lower `memory_physical_watermark_mb`, or set it to 0 to disable this check.
- Memory shortage queues instead of downgrading (the CPU 10s-downgrade heuristic does not apply to memory); unknown demand (`None`) or demand plus commit reserve beyond the system commit limit (structurally unsatisfiable, e.g. a small pagefile) skip the commit check and run (physical watermark and startup interval still apply), leaving the problem to the case's own failure rather than queueing forever
- All descendants in a Job share the launcher's command deadline. After pipe EOF, execution still waits for the group to finish; reaching the deadline terminates the group and reports a timeout.
- These parameters are `symtest.json` run-section config keys (no CLI flags in the first version); process mode does not participate in resource scheduling (unchanged behavior)

The startup interval applies only while tasks are active and their summed estimated peaks plus the new demand and commit reserve exceed current commit headroom. Ample headroom or an empty active set permits immediate admission. This conservative signal may double-count allocated memory; it triggers spacing, never a hard reservation. With active tasks and unknown demand or headroom, spacing is retained conservatively.

### 4.4 DAG Dependency Scheduling Semantics

- Non-empty `depends_on` automatically switches to topological mode; no deps walks a zero-overhead fast path
- Kahn in-degree + ready queue; successors submitted immediately once deps are satisfied
- Semantics: dependency satisfied = `passed` or `xfailed`; `failed` / `xpassed` triggers BFS cascade-skip of all downstream cases
- `skipped` is NOT counted as `failed`; listed separately in reports
- The sequential runner executes in topological order as well, skipping invalid downstream
- Name filtering does not expand the dependency closure by default: when a selected case's dependency is not selected, the dependency edge drops silently with a WARNING; `--with-deps` expands the `depends_on` transitive closure of `test_case_filter` before filtering (tag filtering never expands; `--last-failed` does not expand implicitly)

### 4.5 Single Test Execution

PathResolver resolves (system commands pass-through, shell builtins wrapped for
the platform, compound commands split) → declared-output cleanup (files declared via `execution.outputs` are deleted
before the subprocess starts; only files may be declared — directories and the
workspace root are always rejected; resolved
paths must stay inside the workspace, deletion failure fails loudly as an execution
error; runs on every attempt, and steps skipped by `--resume` are naturally not
cleaned) → subprocess-isolated execution (captures
stdout / stderr / returncode / duration; when Windows measurement is enabled, the process group runs inside a Job Object created suspended → assigned → resumed, capturing the group's commit-memory peak `PeakJobMemoryUsed`; on timeout `TerminateJobObject` kills the whole group; measurement failure falls back to the plain subprocess path with the peak left unknown) → assertions (return_code / contains /
matches / compare_files) → retries on failure up to `retry_count` → kills the
whole process group on timeout → structured result with `next_action_hint`.

The process-group memory peak is an **execution fact** (Principle 2), optionally
carried on results as `peak_memory_bytes` / `peak_memory_source` (Windows
commit-memory basis, NOT physical-memory peak; fields are absent when no valid
measurement exists — never 0-for-unknown). Aggregation: retry takes the maximum
across attempts; a sequence takes the maximum across actually-executed steps
(steps run serially, no summation; steps skipped by `--resume` contribute no
fabricated data).

### 4.6 Assertions and File Comparison Integration

- `compare_files` is a first-class assertion dispatched via ComparatorFactory (see §6)
- All assertions are optional; unspecified fields are not validated
- `--error-analysis` provides streaming error statistics for CSV/H5 numeric comparisons: `total_numeric_cells` / `mismatched_cells` / `max_abs_error` / `max_rel_error` / `mean_abs_error` / `rms_abs_error`

## 5. Runtime State Persistence (`.symtest/`)

| State | Content | Update timing / semantics |
|---|---|---|
| Project defaults `symtest.json` | `run` group run options + `report` group report paths | Read once at run start (CLI > project config > built-in defaults); read-only, never updated during a run |
| History | per-case `avg_duration` / `last_duration` / `run_count` + optional memory fields (`last_peak_memory_bytes` / `max_peak_memory_bytes` / `peak_memory_count` / `peak_memory_source`) | Duration: cumulative average after runs, regression-checked before writing (passed cases only); memory: recorded for any run with a valid measurement, scheduling estimates use the historical max |
| `last_run.json` | case → last status | Overwrites executed cases; unexecuted retain old status |
| `sequence_state/<case>.json` | SHA-256 config hash (steps + case expected), set of passed steps | Saved after each passing step; cleaned up after full pass |
| `sequence_state/cache/*.log` | Step output cache | Kept in sync; spliced back on resume |

**Resume semantics**: `--resume` compares the config hash — on match it skips
already-passed steps and splices cached outputs; on mismatch it reruns
everything. Pure trust model: workspace artifacts are not validated; the user
guarantees they are unmodified.

## 6. File Comparison Subsystem

### 6.1 Comparator Layering

- Text-family comparators share a difflib line-level base; json / csv / xml are structured specializations (key alignment / column structure / DOM alignment)
- h5 targets scientific datasets; binary uses stream chunking + LCS similarity; script delegates to an external program
- All return a ComparisonResult (identical / differences / error / script command_output), renderable as text / json / html; supports row/column windowing before comparison

#### 6.1.1 Window and numeric comparison semantics (file lane)

- Row/column windows are uniformly **0-based, end-inclusive** (`start_line`/`end_line`/`start_column`/`end_column`); the assertion layer converts the user's 1-based input. CSV column windows select **CSV fields** (not character columns); the H5 chunked large-dataset branch applies the same window as the in-memory branch. Difference positions (`line N` / `row N, column M` / `row N`) are offset back to original file coordinates by the lane base class
- H5 scalar (0-d) datasets participate in numeric comparison; a dataset read failure is recorded as a `diff_type="error"` difference and fails the comparison — never a silent pass
- The raw and expanded schemas share the boolean constraint for `allow_nonfinite`; comparator constructors and the shared numeric core also check Python API inputs without truthiness conversion. The CSV text fast path parses every cell containing an exponent or NaN/Inf hint, or at least 309 characters, covering overflow from long mantissas and underscore spellings; enabling error statistics does not change the verdict. Data-lane precedence, including `script_extract`, is per-channel → `default_channel` → comparator parameter → `false`.
- The shared numeric core `compare_numeric` preserves integer types per element, including the full int64 / uint64 ranges and mixed integer/float sequences. Integer differences use Python integers to avoid overflow; integer/float pairs use the float's actual represented value when computing the difference. Integers are not converted to float64 before verdict calculation, and unrelated cells cannot force a floating fallback. Pure floating arrays retain NumPy vectorized comparison. Tolerances and reported error magnitudes use floating-point numbers; precision already lost in caller-created floating arrays cannot be recovered. CSV cells parse integers first; H5 / the data lane can supply integer arrays directly
- **Non-finite values are rejected by default**: any cell where either side is NaN or ±Inf is a mismatch (difference `diff_type="non_finite_value"`) — NaN/Inf in solver output usually indicates a failed solve, and "matches the baseline" must not be conflated with "is a valid result". Set `allow_nonfinite=true` explicitly (CSV/H5 comparator parameter, data-lane comparator parameter with per-channel override) to restore the legacy semantics where `NaN == NaN` and same-sign `±Inf` count as equal; opposite-sign infinities remain mismatches. The rule lives in the shared numeric core and applies uniformly across CSV (including the streaming/in-memory text fast paths and `1e999` overflow text), H5 (including the chunked large-dataset branch), and the data lane; a `data_filter` can never pre-exclude non-finite cells — NaN dropped by a filter condition is still force-compared and fails
- CSV error statistics accumulate the same per-row numeric comparisons used for the verdict, without collecting and recomparing raw numeric values. Comparison streams record by record (compare_files override): the row window applies by record index, and row-count mismatches are determined and reported using record counts inside the window once both streams are drained. Added or removed records outside the window do not affect the verdict. A starting record index greater than or equal to either file's total record count returns an out-of-range error (including empty files). Memory is independent of file size (O(one row)). The Python API (read_content/compare_content) keeps the in-memory path for direct callers; both paths share the same per-row verdict logic
- `--error-analysis` statistics cover all compared numeric cells, including H5 chunked large datasets (no early return on the first difference when stats are requested)

### 6.2 Factory and Plugin Discovery

- `file_type` values: `text` / `json` / `csv` / `xml` / `h5` / `binary` / `script`; factory dispatches by type, supports dynamic registration and global reset (for tests)
- Plugin discovery sources: built-in `*_comparator.py` auto-discovery, automatic scan of `workspace/comparators/`, `--plugin-dir` CLI parameter, `CLITEST_PLUGIN_DIRS` environment variable (for process-mode workers)
- Naming convention: `*_comparator.py` + `*Comparator` class name

### 6.3 Script Comparison Protocol (external contract)

- Runs `<interpreter> <script> <actual> <baseline>` as a subprocess
- Default exit code 0 → pass; optional `pass_pattern` / `fail_pattern` regexes refine the verdict on stdout
- Timeout configurable

## 7. Case Search Command (find)

Replaces the search capability of the retired TUI: `symtest find` goes through
exactly the same loading path as the runners (`load_config` auto-expands
imports + resolves inheritance; `parse_test_cases` is the single system-wide
parser), then matches cases in three modes (substring / fuzzy / regex, across
name / command / args / tags / description) with optional tag filtering and
JSON output (for AI / scripts). Exit codes follow grep semantics: 0 = match,
1 = no match, 2 = error.

The TUI's other responsibility (graphical case authoring/editing for people
unfamiliar with writing configs) is now covered by the official skill
(`skill/` at the repository root): AI coding assistants author/modify
JSON/YAML configs directly from skill knowledge, with lower learning cost and
no interactive UI maintenance burden.

## 8. Extension Points

| Extension Point | Base Class | Purpose |
|---|---|---|
| New config format | `BaseRunner` | Support new test definition formats (e.g., XML, TOML) |
| Custom Setup | `BaseSetup` | Database initialization, service start/stop, etc. |
| Custom assertions | Extend `Assertions` | Specific business validation logic |
| New comparator | `BaseComparator` | Support new file formats; place in `comparators/` for auto-discovery |
| New Runner | `ParallelRunner` / `BaseRunner` | Custom parallel scheduling strategies |

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
| Regression check before update | Compare against old average first, then update; ensures comparison is against the "historical baseline" || `.symtest/` directory | Non-intrusive to the user's directory view; JSON format for easy debugging; state files centrally managed |
| Environment variable injection | Scientific computing solvers often ignore Python-level thread control |
| Comparator factory + plugin discovery | Creates comparators by file type; workspace `comparators/` directory for auto-discovered plugins |
| subprocess isolated execution | Each test case runs in an independent subprocess, ensuring tests don't affect each other |
| xfail mechanism | Supports expected-failure tests (non-blocking in CI), alerts on unexpected passes |
| --last-failed overwrite strategy | Only overwrites status of executed cases; avoids losing state of unexecuted cases during subset runs |
| --resume pure trust model | No artifact validation; user guarantees workspace is unchanged, simplifying implementation |
| retry_count retry mechanism | Handles transient network glitches or race conditions; auto-retries on first failure |
| DAG dependency scheduling | Kahn topology + ready queue; submits dependents immediately once deps are satisfied; cascade-skips downstream on dep failure; zero-overhead fast path when no deps declared |
| --update-baseline | Automatically overwrites baseline files with actual output on comparison failure; ideal for batch baseline updates |
| next_action_hint structured suggestions | Failed results include actionable suggestions (update_baseline / update_expected / increase_timeout / investigate), convenient for AI consumption |
| TUI removed; replaced by official skill + `symtest find` | Both TUI responsibilities have lighter replacements: case authoring/editing is done by AI assistants via the official skill; cross-file search is covered by the `find` command reusing the same parsing pipeline; removes the heavy textual dependency and interactive-UI maintenance burden |
| `execution.outputs` artifact cleanup hooked at the execute_command entry | Declare artifacts and delete them before the run, eliminating stale-artifact false passes. Cleanup is execution-environment preparation (same category as env injection) and belongs to the execution layer; `execute_command` is the single convergence point of all execution paths, so hooking there makes retry re-clean and resume skip (skipped steps never enter the function) hold automatically with zero orchestration-layer changes. Failures are loud (`execution_error`) so no silent false-pass channel remains. **Only files may be declared**: declaring a directory (e.g. an output tree) or the workspace root (`"."`) would recursively wipe unrelated files or even the entire workspace, so validation and runtime both reject it |
| JUnit XML output | Compatible with GitLab CI / Jenkins / CircleCI and other major CI system test report formats |
| Project-level default configuration (`.symtest/symtest.json`) | Frequently used run options (parallel, error analysis, dependency expansion, report paths) are stored per project so `symtest run` needs no repeated input. Three-level precedence (CLI > project config > built-in defaults) is implemented with tri-state booleans (argparse defaults to `None`; `--no-xxx` turns a flag off explicitly); unknown keys and bad JSON are handled tolerantly with a warning only — the config is a pure bonus and never blocks a run. Replaces per-repo entry scripts whose only job was storing default arguments |
| Console log/report channel separation | The console (stderr logging) carries progress and summary logs only. Reports reach stdout solely via an explicit `--output-format text/json/html` (redirectable to a file), with full details written to disk via `--text-report`/`--html-report`/`--junit-xml`. Fixes the channel confusion where the former `print_report` replayed the whole text report through `logger.info` — with `--error-analysis-all` the per-case error_stats flooded the terminal and buried the pass/failed summary |
| Windows Job Object measures process-group peaks | Create-suspended → assign → resume eliminates the descendant-escape race; the OS maintains the peak continuously, catching short spikes without sampling; `PeakJobMemoryUsed` is commit memory, honestly named `peak_memory_source=windows_job_commit`, never presented as a physical-memory peak |
| Joint atomic CPU+memory admission | Two independent semaphores allow a partial-holding deadlock ("holding CPU while waiting for memory and vice versa"); the joint pool evaluates pool tokens + system snapshot atomically under one lock (physical availability and commit margin are checked separately — they guard different failure modes) |
| Opportunistic memory admission (no full peak reservations) | The old policy requiring system headroom to cover all active reservations plus the new request double-counted allocated memory (measured to squeeze 2/4-worker concurrency to 1) and misused commit peaks for the physical-memory check. Opportunistic admission checks only the new task's own demand + reserve; memory in use shows up naturally in the system headroom; a minimum startup interval staggers grants only under potential peak crowding; occasional OOM is accepted, zero-failure is not guaranteed |
| Memory queues instead of downgrading | The CPU token timeout-downgrade is a throughput heuristic; downgraded memory launch is precisely the source of parallel OOM failures, so memory shortage waits indefinitely (periodic wake-ups re-evaluate external memory changes); only structurally unsatisfiable requests (demand plus commit reserve beyond the commit limit) skip the check and run |
| Memory history uses the maximum, not the average | Peaks are naturally monotone; an occasional spike diluted by averaging would OOM again at the next scheduling; estimates add a safety factor (default 1.2, configurable) |
| Memory measurement failure falls back to the plain path | Measurement is a bonus, not an acceptance criterion: on backend failure / non-Windows / process mode the peak stays unknown (None, never 0-for-unknown) and execution and verdict semantics are unchanged |

---

## 10. Architecture Invariants

> **Status**: established at Symtest 1.4 Phase 0 review. These invariants define
> module ownership and dependency direction. New features should preserve them
> unless a change explicitly documents why an invariant must evolve.

### 10.1 Data Flow Spine

```
TestCase (specification, never executes)
    ├── ExecutionSpec  ──▶ Executor.execute()                    ──▶ ExecutionResult
    ├── ExpectationSpec ─┐
    └── SchedulingSpec ──▶ Orchestration (when, which, retry)
                             │
           Validator.validate(ExpectationSpec, ExecutionResult)
                             ▼
                    ValidationResult ──▶ TestResult ──▶ Reporter
                                          stdout(text/json/html) / JUnit / AI diagnosis
```

One attempt = `Executor.execute → Validator.validate`; verdicts are aggregated
into TestResult by the orchestration layer.

### 10.2 Six Principles

#### Principle 1 — TestCase is a declaration; it executes nothing

`TestCase = specification`. Methods such as `test_case.run()` /
`test_case.validate()` / `test_case.update_baseline()` are forbidden. TestCase
only describes **what to execute** (ExecutionSpec), **how to judge** the result
(ExpectationSpec), **scheduling constraints** (SchedulingSpec), and metadata.

Conceptual layering ≠ the config DSL must mechanically mirror a class hierarchy:
`name/tags/description` may stay top-level to avoid verbosity; what must be split
out are execution semantics, validation semantics, and scheduling semantics.

#### Principle 2 — Execution does not know pass/fail

```
Executor: ExecutionSpec ──execute──▶ ExecutionResult
```

ExecutionResult carries execution facts only: `return_code / stdout / stderr /
duration / timed_out / error / artifacts`.

The Executor must never see: `expected_return_code / output_contains / baseline /
rtol / file comparison / xfail / next_action_hint`. Timeout reports only
`timed_out=True`; whether timeout counts as failure is decided by the Validator.

#### Principle 3 — Validation never runs the system under test, and is read-only

```
Validator: ExpectationSpec + ExecutionResult ──validate──▶ ValidationResult
```

The Validator must not `subprocess.Popen` the process under test, kill processes,
or retry.

**Exception clause (controlled waiver)**: comparators are internal tools of
validation; the `script` comparator runs a *comparison tool*, not the system
under test, and is explicitly exempted by this article.

**Baseline semantics**: the Validator always reads files read-only.
`--update-baseline` is executed by the runner as an independent accept step
(copy actual → baseline) after obtaining the ValidationResult.

#### Principle 4 — Orchestration composes; it does not implement low-level semantics

Runner / Scheduler / DAG / ParallelRunner decide when to execute, which case,
order, dependencies, concurrency, and the **retry policy** (one attempt =
`Executor.execute → Validator.validate`; the runner decides on rerun from the
verdict; flaky detection also lives here); but they must not implement subprocess
management, float comparison, or stdout matching themselves.

#### Principle 5 — Reporting can only consume Results

```
TestResult ──▶ Reporter ──┬── stdout (on-demand text/json/html)
                          ├── JUnit
                          └── AI diagnosis
```

The only legal input of a Reporter is a Result type; `next_action_hint` belongs
to result consumers (diagnosis) and must not exist in the execution layer.

#### Principle 6 — The core model does not depend on presentation

`core` must never import: `cli` / `reporter` / AI-specific adapters.

One parser for the whole system: no relaxed-parsing back door is allowed
(e.g., relaxed validation when workspace=None); relaxed shapes are normalized
by the caller before invoking the parser.

### 10.3 Module Dependency Direction

Allowed:

- `orchestration` imports `execution` / `validation` (it is the sole composer);
- `reporting` imports only result types
  (ExecutionResult / ValidationResult / TestResult).

Forbidden:

- `execution` and `validation` must not import each other;
- the `executor` must not import `assertions` / validation-side modules;
- the `validator` must not launch the process under test (see Principle 3);
- `core` must not import `cli` / `reporter`.

### 10.4 Ownership Quick Reference

For any new requirement, ask ownership first:

| Question | Ownership |
|---|---|
| Add GPU resource requirements? | SchedulingSpec |
| Add stderr regex assertion? | ExpectationSpec / Validator |
| Support Docker command execution? | Executor |
| AI tells me what to do next? | Result consumer / diagnosis |

Litmus test: if arguments like "does this go into execution, the runner, or the
testcase?" keep recurring, the invariants are not being applied correctly — go
back to 10.2 and check clause by clause.

### 10.5 Making the Invariants Enforceable

These invariants are not documentation-only; they come with
architecture guard tests enforced by CI:

- Assert the import graph: e.g., imports of `execution/executor.py` must not
  contain `assertions` / `validation`; `core/**` must not import `cli` /
  `reporter`;
- Guard tests are part of the regular regression suite
  (`python tests\run_all.py`); violations fail the build;
- Conflict resolution order: guard tests > this text > personal preference.
