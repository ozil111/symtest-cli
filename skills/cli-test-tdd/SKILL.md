---
name: cli-test-tdd
description: >-
  Test-driven development workflow for command-line programs using the
  cli-test framework. Use when writing regression tests for CLI tools,
  validating numeric/file outputs against baselines with tolerances, running
  tests and diagnosing failures, or managing golden (baseline) files.
---

# cli-test TDD Skill

`cli-test` is a CLI testing framework that executes commands and validates
results with structured assertions (exit code, output content, file
comparison with numeric tolerances). All machine-facing output is JSON on
stdout; logs go to stderr and never pollute the JSON.

## When to use

- Testing a command-line program end-to-end (exit code + output + produced files).
- Golden-file / baseline regression testing (CSV, JSON, H5, XML, text, binary).
- Numeric result validation with tolerances (`rtol`/`atol`) instead of exact diffs.
- Any TDD loop where the "test" is "run a program, check its output".

Do NOT use it for unit tests of Python functions — use pytest directly.

## Command cheat sheet

```bash
cli-test run <config>                          # run all cases (text report)
cli-test run <config> --output-format json     # machine-readable results (ALWAYS use this)
cli-test run <config> -t "<case name>"         # run one case by name (repeatable)
cli-test run <config> --last-failed            # re-run only cases that failed last time
cli-test run <config> --update-baseline        # accept current outputs as new baselines
cli-test validate <config> --output-format json  # static config check (errors + warnings)
cli-test schema                                # JSON Schema for config files
```

Exit codes: `0` = all passed, `1` = test failures, `2` = framework/config error.

## The TDD loop

### RED — write a failing test

1. **Get the schema first**: run `cli-test schema` and follow it exactly when
   authoring the config. Do not invent fields.
2. Add a test case describing the desired behavior (see "Authoring configs").
3. Run `cli-test validate <config> --output-format json`. Fix every `errors`
   entry; treat `warnings` (missing baseline, command not found) as errors
   unless clearly intentional.
4. Run the case and confirm it fails **for the expected reason**:
   ```bash
   cli-test run <config> -t "<case name>" --output-format json
   ```
   Check `failure_kind` in the result — a test that fails because the config
   itself is wrong (e.g. `execution_error`) is not a valid RED state.

### GREEN — make it pass

1. Modify the program under test.
2. Re-run with `cli-test run <config> --last-failed --output-format json`.
3. If it still fails, diagnose from the structured result (see "Failure
   playbook") and iterate. Do not re-run the full suite until all previously
   failed cases pass.

### ACCEPT — baseline changes (golden-file tests only)

If `failure_kind` is `file_compare` and the difference is the **intended**
new behavior, accept it:

```bash
cli-test run <config> --update-baseline -t "<case name>"
```

This is a deliberate, case-scoped action — see "Safety rules" below.

## Authoring configs

Minimal example (JSON; YAML uses the same structure):

```json
{
  "test_cases": [
    {
      "name": "solve_small_model",
      "command": "python",
      "args": ["solver.py", "model.dat"],
      "timeout": 120,
      "expected": {
        "return_code": 0,
        "output_contains": ["converged"],
        "compare_files": [
          {"actual": "out/stress.csv", "baseline": "baseline/stress.csv", "rtol": 1e-5}
        ]
      }
    }
  ]
}
```

Key rules:

- `name`, `command`, `args`, `expected` are required per case.
- Relative paths in `actual`/`baseline` resolve against the **workspace**
  (the directory where `cli-test` runs, or `--workspace`).
- `compare_files` extras (`rtol`, `atol`, `encoding`, `tables`, `data_filter`,
  ...) are forwarded to the comparator; `type` auto-detects from extension.
- Multi-step cases use `steps: [{command, args, expected}, ...]` instead of
  top-level `command`/`args`; the case-level `expected` is evaluated once
  after all steps pass.
- `{placeholder}` strings are substituted from `--var KEY=VALUE` at runtime.

Always run `cli-test schema` before authoring if unsure — the schema is the
authoritative, version-matched contract.

## Reading JSON results

`cli-test run --output-format json` prints:

```json
{
  "total": 3, "passed": 2, "failed": 1, "updated": 0,
  "details": [ { "...one result per case..." } ]
}
```

Per-case fields you will actually use:

| Field | Meaning |
|---|---|
| `status` | `passed` / `failed` / `timeout` |
| `failure_kind` | `return_code` / `output_contains` / `output_matches` / `file_compare` / `timeout` / `execution_error` — branch on this, not on `message` |
| `expected` | Echo of the expected block — compare against actuals without re-reading the config |
| `assertion_results` | Per-assertion pass/fail detail, e.g. which of 3 `output_contains` strings failed |
| `stdout` / `stderr` | Separated, trimmed channels (`output` is the combined legacy field) |
| `compare_failures[].diff_summary` | `total_differences`, `max_rel_error`, `max_abs_error` (+ positions) |
| `compare_failures[].differences` | Sample of differing cells/lines (capped; `differences_total` has the real count) |
| `failed_step` / `step_results` | For sequence cases: which step failed |
| `next_action_hint` | `{action, command, reason}` — the framework's suggested next step |
| `flaky` / `attempts` | Retry behavior; `flaky: true` = passed only after retry |

## Failure playbook

Branch on `failure_kind`:

| `failure_kind` | What it means | What to do |
|---|---|---|
| `return_code` | Exit code differs | Read `stderr`; fix the program, or update `expected.return_code` if the new behavior is intended |
| `output_contains` | A required string is missing from output | `assertion_results[].text` names the missing string; check `stdout` vs `stderr` for where it went |
| `output_matches` | Regex did not match | Simplify the regex or inspect actual `stdout` |
| `file_compare` | Produced file differs from baseline | Inspect `compare_failures[].diff_summary`: small `max_rel_error` → likely numeric noise (consider tolerance); large/structural → real behavior change |
| `timeout` | Command exceeded `timeout` | Increase `timeout` in the case, or investigate the hang |
| `execution_error` | Command could not start | Check the command exists and paths resolve against the workspace |

`next_action_hint.action` gives the same guidance in one token:
`update_baseline`, `update_expected`, `increase_timeout`, `investigate`.
`next_action_hint.command` is a ready-to-run cli-test command (already
includes the config path and `-t "<case>"`).

## Safety rules (non-negotiable)

1. **Never run `--update-baseline` without explicit user confirmation.**
   Updating a baseline redefines "correct". Before proposing it, show the user
   `diff_summary` (`max_rel_error`, `total_differences`) and state why the new
   output is the intended behavior.
2. **Never batch-accept baselines to make a suite green.** Accept case by
   case, only after each diff is understood.
3. **Do not weaken assertions to force a pass** (deleting `output_contains`
   entries, loosening `rtol`) without telling the user why.
4. A test that fails with `execution_error` or a config mistake is not a
   valid RED state — fix the config first.
