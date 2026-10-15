# SymTest development guidelines

## Scope and validation

- Keep changes tied to real SymTest use cases and follow nearby conventions.
- Run commands from this repository using a Python environment with the
  project's development dependencies installed (`pip install -e ".[dev]"`).
- Run tests relevant to the change. The unified entry point is
  `python -m tests.run_all --scope unit|integration|e2e|all`;
  use `--extra` for targeted pytest arguments. See `tests/README.md`.
- Do not update numerical baselines merely to make a comparison pass.

## Documentation is part of delivery

For each development task, review the final diff and update affected documentation,
skill guidance, and examples before declaring the task complete. This is part of
the development task and does not require a separate user reminder.

| Change | Files to review and update when affected |
| --- | --- |
| User-visible behavior, CLI options, configuration, defaults, or public Python API | `docs/user_manual.md` and `docs/user_manual_en.md` |
| Architecture, interfaces, execution flow, or design decisions | `docs/design.md` and `docs/design_en.md` |
| Agent workflows, configuration authoring, or recommended usage | `skill/SKILL.md` |
| Official Python runner entry point or recommended API usage | `examples/full_runner_example.py` |
| Installation, quick start, or project overview | `README.md` and `README_cn.md` |

- Keep Chinese and English documentation semantically consistent.
- Update only affected sections; do not modify every document mechanically.
- Document the final implemented behavior, including relevant limits and defaults.
- When changing the Python runner example, validate the affected usage.
- `skill/SKILL.md` teaches consumers how to use SymTest; development maintenance
  rules belong here.

## Skill asset synchronization

These files have a single authoritative source:

| Source | Generated copy |
| --- | --- |
| `docs/user_manual_en.md` | `skill/references/user_manual.md` |
| `examples/full_runner_example.py` | `skill/assets/full_runner_example.py` |

Edit the source, never the generated copy. After source edits, run:

```bash
python tools/sync_skill_assets.py
python tools/sync_skill_assets.py --check
```

The check must pass before delivery, even if the task does not change the sources.
CI also checks these pairs. The script checks copy consistency, not the semantic
accuracy of documentation or translations.

## Completion report

Report relevant validation results and documentation synchronization status.
Mention which documentation, skill, or examples were updated; briefly explain
why unchanged categories were unaffected. Disclose any checks that could not run.
