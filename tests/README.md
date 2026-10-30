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

Windows memory admission integration tests in
`integration/parallel/test_parallel_runner.py` cover real Job peak collection
and history updates, admission under simulated commit pressure, impossible
commit demand including the reserve, and rejection of physical watermarks at
or above total RAM. Small-machine cases also verify that lowering the watermark
or setting it to zero permits execution. They use injected snapshots rather
than exhausting host memory.


Conditional startup spacing tests cover immediate admission with ample commit
headroom, staggered grants when overlapping peaks may crowd, removal of spacing
after active tasks finish, and a batch of twelve short commands without per-case
one-second delays.
