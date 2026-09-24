## Tests Structure

- `unit/`: core and runner unit tests (`core/`, `runners/`, `commands/`).
- `integration/`: end-to-end style checks (file_compare, parallel, path_handling, etc).
- `demos/`: manual/interactive scripts, not run in CI by default.

## Run Commands

- Run all configured scopes: `python -m tests.run_all --scope all`
- Unit only: `python -m tests.run_all --scope unit`
- Integration only: `python -m tests.run_all --scope integration`
- Filter with pytest args: `python -m tests.run_all --scope integration --extra "-k h5"`

`demos/` scripts are standalone (e.g., `python tests/demos/h5_filter_demo.py`).

