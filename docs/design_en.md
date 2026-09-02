# CLI Test Framework Design Document

> **Maintenance principle (single source of truth)**: this document does not mirror
> code structure — it no longer maintains directory trees, class signatures,
> function inventories, dataclass field definitions, or anything else that rots as
> the code evolves. Directory layout and APIs live in `src/symtest/` sources and
> their docstrings; usage examples live in `examples/`.
> This document only carries what cannot be read out of code: architecture
> layering, responsibility boundaries, key flow semantics, extension contracts,
> design decisions, and the architecture constitution.

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  CLI Entry Layer    symtest run / tui / validate / schema /  │
│                     compare-files (+ TUI interface)          │
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

The framework is divided into four layers: **CLI Entry Layer** (including TUI),
**Runner / Comparator Business Layer**, **Config Pipeline Layer**, and
**Core Foundation Layer**.

Layers are not free-to-wire: cross-layer data flow and dependency directions are
governed by the §10 Core Architecture Constitution. Resolve feature ownership
against it first.

## 2. Module Map

Responsibilities by package (file-level details and public APIs live in source):

| Package | Responsibility |
|---|---|
| `cli.py` / `commands/` | Sub-command entry points, argument assembly, logging activation |
| `core/` | TestCase model, assertion engine, single-test execution, Runner bases (sequential / parallel / DAG), `.symtest` state stores, Setup plugin system |
| `config/` | Config IO, JSON Schema validation (draft 2020-12), import expansion, extends inheritance, variable & placeholder substitution |
| `runners/` | Thin wrapper runners: Config/JSON/YAML × sequential/parallel |
| `file_comparator/` | Comparator family + factory + workspace plugin discovery (see §6) |
| `utils/` | Path resolution, report generation, JUnit XML output |
| `tui/` | Interactive Textual case management (see §7) |

### 2.1 Entry Points

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

### 3.3 Config Validation (`config_io.py`)

The `symtest validate` subcommand checks configuration without running tests:

- Error-level (affects `valid`): JSON/YAML syntax, required fields, import target existence, circular imports, extends target existence, circular extends
- Warning-level (does not affect `valid`): command executability (PATH lookup), `compare_files` baseline file existence

## 4. Execution Semantics

> This chapter records cross-module behavioral contracts only; class attributes,
> method signatures and defaults live in source.

### 4.1 Runner Template and Status Mapping

- Fixed template flow: `load_test_cases()` → filter (exact name / tag intersection / `--last-failed`) → `setup_all()` → per-case execution → xfail status mapping → history & last-run update → `teardown_all()` (reverse order; cleanup continues even on errors)
- JSON/YAML runners differ only by injected config_loader; common logic lives in the generic sequential / parallel runners
- xfail: when `expected_failure=True`, `passed → xpassed` (unexpected pass, counted as a suite failure); any non-passed status → `xfailed` (expected failure, not counted)
- JUnit XML status mapping: `xfailed → <skipped>`, `xpassed → <failure>`, `timeout → <error>`, `failed` split into `<failure>` / `<error>` by message type
- History: cumulative average update; regression is checked against the prior average before writing; `--update-history` clears then records
- `--last-failed`: each run overwrites only the statuses of executed cases; subset runs never lose states of unexecuted cases

### 4.2 Two Case Modes

Single-command mode (`command + args + expected`) or steps-sequence mode;
each step is an atomic "execute + judge" pair (command / args / timeout /
retry_count / expected). The full field set lives in `core/test_case.py` and the
JSON Schema; it is not restated here.

### 4.3 Parallelism and Resource Scheduling

- LPT strategy: long tasks first; with history enabled, historical `avg_duration` takes precedence over declared `estimated_time`
- `AtomicSemaphore` resource pool: `safe_capacity = max(1, cpu_count − 2)`; per-case acquire/release by `cpu_cores`
- Relative CPU cores assigned proportionally by weight; auto-injects `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `NPROC`
- Environment variable precedence: `os.environ` < scheduler injection < case-level env (via subprocess, never mutating global `os.environ`)
- Thread mode shares memory with result/print locks; process mode isolates via process workers; sequential fallback available

### 4.4 DAG Dependency Scheduling Semantics

- Non-empty `depends_on` automatically switches to topological mode; no deps walks a zero-overhead fast path
- Kahn in-degree + ready queue; successors submitted immediately once deps are satisfied
- Semantics: dependency satisfied = `passed` or `xfailed`; `failed` / `xpassed` triggers BFS cascade-skip of all downstream cases
- `skipped` is NOT counted as `failed`; listed separately in reports
- The sequential runner executes in topological order as well, skipping invalid downstream

### 4.5 Single Test Execution

PathResolver resolves (system commands pass-through, shell builtins wrapped for
the platform, compound commands split) → subprocess-isolated execution (captures
stdout / stderr / returncode / duration) → assertions (return_code / contains /
matches / compare_files) → retries on failure up to `retry_count` → kills the
whole process group on timeout → structured result with `next_action_hint`.

Today these behaviors are aggregated in one place; 1.4 rearranges them into
Executor / Validator / Orchestration per the §10 Constitution (migration details
in docs/design_1_4.md).

### 4.6 Assertions and File Comparison Integration

- `compare_files` is a first-class assertion dispatched via ComparatorFactory (see §6)
- All assertions are optional; unspecified fields are not validated
- `--error-analysis` provides streaming error statistics for CSV/H5 numeric comparisons: `total_numeric_cells` / `mismatched_cells` / `max_abs_error` / `max_rel_error` / `mean_abs_error` / `rms_abs_error`

## 5. Runtime State Persistence (`.symtest/`)

| State | Content | Update timing / semantics |
|---|---|---|
| History | per-case `avg_duration` / `last_duration` / `run_count` | Cumulative average after runs; regression-checked before writing |
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

### 6.2 Factory and Plugin Discovery

- `file_type` values: `text` / `json` / `csv` / `xml` / `h5` / `binary` / `script`; factory dispatches by type, supports dynamic registration and global reset (for tests)
- Plugin discovery sources: built-in `*_comparator.py` auto-discovery, automatic scan of `workspace/comparators/`, `--plugin-dir` CLI parameter, `CLITEST_PLUGIN_DIRS` environment variable (for process-mode workers)
- Naming convention: `*_comparator.py` + `*Comparator` class name

### 6.3 Script Comparison Protocol (external contract)

- Runs `<interpreter> <script> <actual> <baseline>` as a subprocess
- Default exit code 0 → pass; optional `pass_pattern` / `fail_pattern` regexes refine the verdict on stdout
- Timeout configurable

## 7. TUI Subsystem

Textual-based terminal UI: App + Controller (load / create / update / delete /
run_single / save actions) + list/edit screens + table wrapper, multi-mode
search bar (name / command / tag), expected editor, steps editor.

Key bindings: `q` / Ctrl+Q quit, `r` refresh, `e` edit, `f` run single, `/`
search, `a` add, `d` delete, `s` save.

TUI and runners share the same parser; relaxed display shapes are handled on the
TUI side itself (§10 Principle 6).

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
| `.symtest/` directory | Non-intrusive to the user's directory view; JSON format for easy debugging; state files centrally managed |
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
| TUI based on Textual | Leverages a mature terminal UI framework for interactive case management |
| JUnit XML output | Compatible with GitLab CI / Jenkins / CircleCI and other major CI system test report formats |
| Centralized logging | All diagnostic messages go through Python's `logging` module; CLI entry activates console output; library users enable as needed |

---

## 10. Core Architecture Constitution

> **Status and force**: ratified at Symtest 1.4 Phase 0 review. This section is the
> project's core architectural contract with supreme authority over all future
> features — resolve ownership against this constitution before writing any code.
> Amending it requires explicitly naming the clause being relaxed/waived and the
> rationale in the change description. Pre-ratification evolution history lives in
> the development-phase document docs/design_1_4.md.

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
                                          console / JSON / JUnit / AI diagnosis
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
TestResult ──▶ Reporter ──┬── console
                          ├── JSON
                          ├── JUnit
                          └── AI diagnosis
```

The only legal input of a Reporter is a Result type; `next_action_hint` belongs
to result consumers (diagnosis) and must not exist in the execution layer.

#### Principle 6 — The core model does not depend on presentation

`core` must never import: `cli` / `tui` / `reporter` / AI-specific adapters.

One parser for the whole system: TUI and runners use the same parser; a "TUI
mode back door" (e.g., relaxed validation when workspace=None) is forbidden;
relaxed shapes are handled on the TUI side itself.

### 10.3 Module Dependency Direction

Allowed:

- `orchestration` imports `execution` / `validation` (it is the sole composer);
- `reporting` imports only result types
  (ExecutionResult / ValidationResult / TestResult).

Forbidden:

- `execution` and `validation` must not import each other;
- the `executor` must not import `assertions` / validation-side modules;
- the `validator` must not launch the process under test (see Principle 3);
- `core` must not import `cli` / `tui` / `reporter`.

### 10.4 Ownership Quick Reference

For any new requirement, ask ownership first:

| Question | Ownership |
|---|---|
| Add GPU resource requirements? | SchedulingSpec |
| Add stderr regex assertion? | ExpectationSpec / Validator |
| Support Docker command execution? | Executor |
| AI tells me what to do next? | Result consumer / diagnosis |

Litmus test: if arguments like "does this go into execution, the runner, or the
testcase?" keep recurring, the constitution is not being applied correctly — go
back to 10.2 and check clause by clause.

### 10.5 Making the Constitution Enforceable

The constitution is not a documentation-only convention; it comes with
architecture guard tests enforced by CI:

- Assert the import graph: e.g., imports of `execution/executor.py` must not
  contain `assertions` / `validation`; `core/**` must not import `cli` /
  `tui` / `reporter`;
- Guard tests are part of the regular regression suite
  (`python tests\run_all.py`); violations fail the build;
- Conflict resolution order: guard tests > this text > personal preference.

### 10.6 Current Gap to This Constitution

Known deviations of the current implementation from this constitution as of
ratification (1.4 Phase 0). Each item converges during the corresponding 1.4
phase (migration details in docs/design_1_4.md):

| Current state | Violated | Convergence |
|---|---|---|
| `execution.py::validate_result` lives in the execution layer | Principle 2 | Phase 2: move to `validation/validator.py` |
| `next_action_hint` built in the execution layer | Principle 5 | Phase 2: move to `reporting/diagnosis.py` |
| Retry loop inside the executor | Principles 2 / 4 | Phase 2: lift to orchestration |
| update_baseline writes files inside validation | Principle 3 | Phase 2: runner-side independent accept step |
| `parse_test_cases` TUI-mode back door | Principle 6 | Phase 2: remove; single parser |
