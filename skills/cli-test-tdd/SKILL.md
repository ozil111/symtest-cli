---
name: cli-test-tdd
description: >-
  Test-driven development workflow for command-line programs using the
  cli-test framework. Use when writing regression tests for CLI tools,
  validating numeric/file outputs against baselines with tolerances, running
  tests and diagnosing failures, or managing golden (baseline) files.
---

# cli-test Skill — AI Onboarding Manual

`cli-test` is a CLI testing framework that executes commands and validates
results with structured assertions (exit code, output content, file
comparison with numeric tolerances).

## Command Cheat Sheet

```bash
cli-test run <config>                              # full suite, text report
cli-test run <config> --output-format json         # structured JSON (AI must use this)
cli-test run <config> -t "<case>"                  # single case by name (repeatable)
cli-test run <config> --last-failed                # re-run only last-failed cases
cli-test run <config> --resume                     # resume sequence cases from failed step
cli-test run <config> --resume -t "<case>"         # combine: resume + single-case filter
cli-test run <config> --update-baseline            # accept current outputs as baselines
cli-test validate <config> --output-format json    # static config check
cli-test schema                                    # print JSON Schema
```

Exit codes: `0` = all passed, `1` = test failures, `2` = framework/config error.

## JSON Result Fields

`cli-test run --output-format json` outputs:

```json
{
  "total": 3, "passed": 2, "failed": 1, "updated": 0,
  "details": [ { "...one result per case..." } ]
}
```

Per-case fields you will use:

| Field | Meaning |
|---|---|
| `status` | `passed` / `failed` / `timeout` |
| `failure_kind` | `return_code` / `output_contains` / `output_matches` / `file_compare` / `timeout` / `execution_error` — **branch on this, not on `message`** |
| `expected` | Echo of the expected block — compare against actuals without re-reading config |
| `assertion_results` | Per-assertion pass/fail detail (which `output_contains` string was missing) |
| `stdout` / `stderr` | Separated, trimmed output channels |
| `compare_failures[].diff_summary` | `total_differences`, `max_rel_error`, `max_abs_error` |
| `compare_failures[].differences` | Sample diffs (capped at 50; `differences_total` has true count) |
| `failed_step` / `step_results` | For sequence cases: which step failed; skipped steps marked `"resumed": true` |
| `next_action_hint` | `{action, command, reason}` — framework's suggested next step |
| `flaky` / `attempts` | Retry behavior; `flaky: true` = passed only after retries |

## Project Workflow

The standard entry point is a script like `python test.py` supporting:

```bash
python test.py                                     # full suite
python test.py --test-target BS-U_01               # single case
python test.py --last-failed                       # only last-failed cases
python test.py --test-target BS-U_01 --resume      # resume from failed step
python test.py --tag smoke                         # tag filter
```

Standard AI workflow:

1. Run full suite once → inspect JSON results
2. For each failed case: branch on `failure_kind` → diagnose → fix
3. Verify: `--last-failed` or `-t "<case>"` for narrow re-runs
4. Once all pass, run full suite once to confirm no regressions

## Failure Diagnosis

Branch on `failure_kind`:

| `failure_kind` | Meaning | Action |
|---|---|---|
| `return_code` | Exit code mismatch | Read `stderr`; fix the program, or update `expected.return_code` |
| `output_contains` | Required string missing | `assertion_results[].text` names the missing string; check `stdout` vs `stderr` |
| `output_matches` | Regex didn't match | Simplify the regex or inspect `stdout` |
| `file_compare` | Produced file differs from baseline | Check `compare_failures[].diff_summary`: small `max_rel_error` → numeric noise; large → real change |
| `timeout` | Command exceeded timeout | Increase `timeout` or investigate the hang |
| `execution_error` | Command couldn't start | Check command exists and paths resolve correctly |

`next_action_hint.action` gives the same guidance in one token:
`update_baseline` / `update_expected` / `increase_timeout` / `investigate`.

## Step-Level Resume (`--resume`)

When a sequence test case fails, `--resume` skips already-passed steps and
continues from the failed one.

How it works:
- After each step passes, state + stdout are persisted to `.cli-test/sequence_state/<case_name>.json`
- On `--resume`, a config hash (command/args/expected of all steps) is computed
- Hash matches → passed steps are skipped, `combined_output` is rebuilt from cached outputs
- Full case passes → state file is deleted
- Hash mismatch (config changed) → automatic full re-run

**Trust model**: pure-trust. No workspace artifact validation. Using `--resume`
implies the user asserts input files haven't changed.

## Authoring Configs

Minimal example (JSON; YAML same structure):

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
- `name`, `command`, `args`, `expected` are required per case
- Relative paths resolve against the **workspace** (not config file dir, not CWD)
- `compare_files` extras (`rtol`, `atol`, `encoding`, `tables`, `data_filter`, ...)
  are forwarded to the comparator; type is auto-detected from extension
- Multi-step: use `steps: [{command, args, expected}, ...]` instead of top-level
  `command`/`args`; case-level `expected` is evaluated once after all steps pass
- `{placeholder}` strings are substituted via `--var KEY=VALUE` at runtime

Always run `cli-test schema` before authoring if unsure — the schema is the
authoritative, version-matched contract.

## Safety Rules (non-negotiable)

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

## Numeric Tolerance Failures (special handling)

When `failure_kind` is `file_compare` and `diff_summary` shows errors in a
gray zone (e.g. `max_rel_error` in 0.1%–5% range):

- **Do not blindly adjust tolerances or update baselines.** First report the
  error magnitude and distribution to the user (extract from
  `compare_failures[].differences`).
- This could be a real bug (program needs fixing) or an intentional behavior
  change (baseline should be updated).
- Before updating a baseline, the user must confirm "this error is physically acceptable."
