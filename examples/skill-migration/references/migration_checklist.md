# Migration Review Checklist (v1 flat → v2 layered)

Apply every item to the migrated config. Items are ordered by how often they
cause silent behavior changes.

## 1. What `symtest migrate` already handled (verify, don't redo)

| v1 field | v2 location | Verified |
|----------|-------------|----------|
| `command`, `args`, `timeout`, `retry_count`, `env` | `execution.*` | ☐ |
| `steps` (case top level) | `execution.steps` | ☐ |
| `expected` | top level (unchanged) | ☐ |
| `depends_on`, `resources` | `scheduling.depends_on`, `scheduling.resources` | ☐ |
| `name`, `description`, `tags`, `expected_failure`, `xfail_reason`, `xfail_quiet`, `abstract`, `extends`, `variables`, `import` | top level (unchanged) | ☐ |
| `setup` | suite top level (unchanged) | ☐ |

Signs of a bad migration: a case with both `execution.command` and
`execution.steps`; `steps` left at case top level; `depends_on` left at case
top level (it will be silently ignored by the v2 parser — downstream cases
will run before their dependencies).

## 2. Custom comparators (requires judgment)

- `expected.compare_files[].type` values outside
  `text/json/csv/xml/h5/binary/script` resolve to workspace plugins in
  `<workspace>/comparators/*_comparator.py`.
- Verify each referenced plugin still exists and imports cleanly
  (`from symtest.file_comparator...`, not other package names).
- Extra keys in a compare spec are forwarded to the comparator as kwargs;
  migration preserves them verbatim — confirm the plugin still accepts them.
- Script comparators (`type: script`) keep their `script`/`case_dir`/`cwd`/
  `pass_*`/`fail_*` keys unchanged; no action unless paths were relative to a
  directory that moved.

## 3. Complex inheritance (`extends`)

- v1 and v2 both deep-merge dict fields and whole-replace lists, but the
  merge now happens on the layered shape:
  - a child's `execution.args` replaces the parent's list — the parent's
    `execution.command` is inherited only if the child does not set
    `execution.command`;
  - a child overriding `args` must keep them inside `execution`;
  - a child overriding `depends_on` must move it into `scheduling`.
- After migration, re-read every `extends` chain and confirm the intended
  parent fields still land in the child. A child that overrode `command` in
  v1 but kept `args` from the parent must end up with
  `execution: {command: <child>, args: <inherited>}` — verify the merge
  result, not just the child block.
- `abstract: true` bases are not executed; confirm they still carry the
  fields their children expect (now inside `execution`/`scheduling`).

## 4. Variables and placeholders

- `variables` stay at case top level; `{placeholder}` substitution covers
  strings anywhere in the config, including `execution.command`,
  `execution.args`, `execution.env`, and `expected.compare_files[].baseline`.
- Confirm no placeholder ended up split across the v1→v2 boundary in a way
  that changes meaning (e.g. a variable that supplied the whole `command`
  string now sits in `execution.command` — same behavior).

## 5. Setup environment semantics

- `setup.environment_variables` are injected into every test command and are
  unchanged by migration.
- Case-level `env` moved into `execution.env`. Semantics (subprocess-only,
  overrides scheduler-injected `OMP_NUM_THREADS`/`MKL_NUM_THREADS`/`NPROC`,
  deep-merged through `extends`) are unchanged — but verify no case relied on
  a top-level `env` key that migrate could not distinguish from metadata.

## 6. Import structures

- `migrate` follows imports recursively: default mode writes `<stem>.v2<ext>`
  copies and rewrites import paths; `--in-place` overwrites each file in
  place. Verify every file reachable via `import` was migrated (the command
  prints one output path per migrated file).
- Import-level `tags` injection still works in v2; confirm split files no
  longer rely on v1-only top-level case fields.
- Circular imports remain an error (validation stage), unchanged.

## 7. Wire-shape consumers (tooling around symtest)

Anything that reads or writes configs programmatically must handle the v2
shape. Audit for:

- Home-grown scripts generating configs with top-level `command`/`args` —
  they now produce invalid configs; regenerate from templates instead.
- Scripts that consumed `TestCase.to_dict()` output — it now returns the v2
  layered form.
- CI pipelines that post-process result JSON are unaffected (result wire
  format unchanged).

## 8. Final gates

- ☐ `symtest validate <migrated config>` passes with no errors
- ☐ Legacy vs migrated produce identical outcomes on a representative run
  (statuses, compared files)
- ☐ All imported sub-files migrated
- ☐ Custom comparator plugins verified
- ☐ Stale v1 files removed or moved out of tooling's discovery path
