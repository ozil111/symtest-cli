## Tests Structure

- `unit/`: core and runner unit tests (`core/`, `runners/`, `commands/`).
- `integration/`: end-to-end style checks (file_compare, parallel, path_handling, etc).
- `demos/`: manual/interactive scripts, not run in CI by default.

## Run Commands

Before delivery, check the skill copies (also checked by CI):

```bash
python tools/sync_skill_assets.py --check
```

If they differ, edit the authoritative sources and run
`python tools/sync_skill_assets.py`. See `AGENTS.md` for the documentation
maintenance rules. Run Python in an environment with the project's development
dependencies installed (`pip install -e ".[dev]"`).

- Run all configured scopes: `python -m tests.run_all --scope all`
- Unit only: `python -m tests.run_all --scope unit`
- Integration only: `python -m tests.run_all --scope integration`
- Filter with pytest args: `python -m tests.run_all --scope integration --extra "-k h5"`

`demos/` scripts are standalone (e.g., `python tests/demos/h5_filter_demo.py`).

