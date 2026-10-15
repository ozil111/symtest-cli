"""Project-level default configuration for ``symtest run``.

A project may provide a ``.symtest/symtest.json`` file in its workspace
storing per-project defaults for frequently used ``run`` options (default
config file, parallel settings, history dir, error analysis, dependency
expansion and report paths).

Option precedence is: command line > project config > built-in defaults.
Loading never raises: missing, unreadable, unknown or wrong-typed entries
are warned about and ignored so a bad config file never blocks a run.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("symtest.utils.project_config")

PROJECT_CONFIG_RELATIVE_PATH = Path(".symtest") / "symtest.json"

# Built-in fallback when neither the command line nor the project config
# provides a test configuration file.
DEFAULT_CONFIG_FILE = "test_cases.json"

# Known keys per group, with the expected JSON type.
_RUN_KEYS = {
    "config_file": str,
    "parallel": bool,
    "workers": int,
    "execution_mode": str,
    "history_dir": str,
    "regression_threshold": float,
    "with_deps": bool,
    "error_analysis": bool,
    "error_analysis_all": bool,
}
_REPORT_KEYS = {
    "text": str,
    "html": str,
    "junit": str,
}
_GROUP_KEYS = {
    "run": _RUN_KEYS,
    "report": _REPORT_KEYS,
}


def _type_matches(value, expected):
    """JSON-type check that keeps ``int`` and ``bool`` strictly apart."""
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def load_project_config(workspace_path):
    """Load ``.symtest/symtest.json`` from *workspace_path*.

    Returns a cleaned dict (empty when the file is missing, unreadable or
    not an object). Unknown sections/keys and wrong-typed values are warned
    about and ignored; unknown keys do not abort the run.
    """
    path = Path(workspace_path) / PROJECT_CONFIG_RELATIVE_PATH
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable project config %s: %s", path, exc)
        return {}

    if not isinstance(raw, dict):
        logger.warning("Ignoring project config %s: top level must be a JSON object", path)
        return {}

    for key in sorted(set(raw) - set(_GROUP_KEYS)):
        logger.warning("Unknown section '%s' in project config %s (ignored)", key, path)

    cleaned = {}
    for group, keys in _GROUP_KEYS.items():
        section = raw.get(group)
        if section is None:
            continue
        if not isinstance(section, dict):
            logger.warning("Ignoring project config %s: '%s' section must be an object", path, group)
            continue
        cleaned_section = {}
        for key, value in section.items():
            expected = keys.get(key)
            if expected is None:
                logger.warning("Unknown key '%s.%s' in project config %s (ignored)", group, key, path)
            elif not _type_matches(value, expected):
                logger.warning("Ignoring '%s.%s' in project config %s: expected %s",
                               group, key, path, expected.__name__)
            else:
                cleaned_section[key] = value
        cleaned[group] = cleaned_section
    return cleaned


def merge_project_config(args, project_config, workspace_path):
    """Apply project defaults onto ``args`` for options not set on the command line.

    Command line values win (non-``None`` tri-state), then project config
    values, then built-in defaults. ``args.config_file`` always receives a
    concrete fallback so callers can treat it as a plain string afterwards.
    """
    run_cfg = project_config.get("run") or {}
    report_cfg = project_config.get("report") or {}

    def resolve(cli_value, cfg_value, builtin):
        if cli_value is not None:
            return cli_value
        if cfg_value is not None:
            return cfg_value
        return builtin

    args.config_file = resolve(getattr(args, 'config_file', None),
                               run_cfg.get("config_file"), DEFAULT_CONFIG_FILE)
    args.parallel = resolve(getattr(args, 'parallel', None),
                            run_cfg.get("parallel"), False)
    args.workers = resolve(getattr(args, 'workers', None),
                           run_cfg.get("workers"), None)
    args.execution_mode = resolve(getattr(args, 'execution_mode', None),
                                  run_cfg.get("execution_mode"), 'thread')
    args.history_dir = resolve(getattr(args, 'history_dir', None),
                               run_cfg.get("history_dir"), None)
    args.regression_threshold = resolve(getattr(args, 'regression_threshold', None),
                                        run_cfg.get("regression_threshold"), 1.5)
    args.with_deps = resolve(getattr(args, 'with_deps', None),
                             run_cfg.get("with_deps"), False)
    args.error_analysis = resolve(getattr(args, 'error_analysis', None),
                                  run_cfg.get("error_analysis"), False)
    args.error_analysis_all = resolve(getattr(args, 'error_analysis_all', None),
                                      run_cfg.get("error_analysis_all"), False)

    args.text_report = resolve(getattr(args, 'text_report', None),
                               report_cfg.get("text"), None)
    args.html_report = resolve(getattr(args, 'html_report', None),
                               report_cfg.get("html"), None)
    args.junit_xml = resolve(getattr(args, 'junit_xml', None),
                             report_cfg.get("junit"), None)
    return args


def resolve_path(value, workspace_path):
    """Resolve a report path against *workspace_path* unless absolute."""
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(Path(workspace_path) / path)
