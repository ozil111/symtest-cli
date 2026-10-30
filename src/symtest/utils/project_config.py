"""Project-level default configuration for ``symtest run``.

A project may provide a ``.symtest/symtest.json`` file in its workspace
storing per-project defaults for frequently used ``run`` options (default
config file, parallel settings, history dir, error analysis, dependency
expansion and report paths).

Option precedence is: command line > project config > built-in defaults.

Two loading modes exist for ``load_project_config``:

- Default (no *explicit_path*): read ``.symtest/symtest.json`` leniently —
  a missing, unreadable, unknown or wrong-typed entry is warned about and
  ignored so a bad config file never blocks a run.
- Explicit (``--defaults FILE`` on the CLI): *explicit_path* replaces the
  default file entirely (no stacking with ``.symtest/symtest.json``) and
  loading is strict — a missing file, broken JSON, a non-object top level,
  unknown sections/keys or wrong-typed values raise :class:`ProjectConfigError`
  so the run aborts instead of silently running with different settings.
"""


class ProjectConfigError(Exception):
    """Raised when an explicitly specified defaults file cannot be used."""


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
    # 机会式内存准入参数（Windows + thread 模式生效；CLI 第一版不提供
    # 旗标，仅 symtest.json run 段配置）
    "memory_margin": float,
    "memory_commit_reserve_mb": int,
    "memory_physical_watermark_mb": int,
    "memory_default_demand_mb": int,
    "memory_min_start_interval_s": float,
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


def load_project_config(workspace_path, explicit_path=None):
    """Load project defaults from ``.symtest/symtest.json``, or from *explicit_path*.

    Without *explicit_path* the default file is read leniently: missing,
    unreadable, unknown or wrong-typed entries are warned about and ignored
    (an empty dict is returned), never blocking a run.

    With *explicit_path* the given file replaces the default file entirely
    and loading is strict: any problem (missing file, broken JSON, non-object
    top level, unknown section/key, wrong-typed value) raises
    :class:`ProjectConfigError`. Relative *explicit_path* values are resolved
    against *workspace_path*; absolute paths are used as-is.

    Returns a cleaned dict with ``run`` / ``report`` sections.
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_absolute():
            path = Path(workspace_path) / path
        strict = True
    else:
        path = Path(workspace_path) / PROJECT_CONFIG_RELATIVE_PATH
        strict = False

    if not path.is_file():
        if strict:
            raise ProjectConfigError(f"defaults file not found: {path}")
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ProjectConfigError(f"cannot read defaults file {path}: {exc}") from exc
        logger.warning("Ignoring unreadable project config %s: %s", path, exc)
        return {}

    if not isinstance(raw, dict):
        if strict:
            raise ProjectConfigError(
                f"defaults file {path}: top level must be a JSON object")
        logger.warning("Ignoring project config %s: top level must be a JSON object", path)
        return {}

    unknown_sections = sorted(set(raw) - set(_GROUP_KEYS))
    if unknown_sections:
        listed = ", ".join(repr(s) for s in unknown_sections)
        if strict:
            raise ProjectConfigError(
                f"defaults file {path}: unknown section(s) {listed}")
        for key in unknown_sections:
            logger.warning("Unknown section '%s' in project config %s (ignored)", key, path)

    cleaned = {}
    for group, keys in _GROUP_KEYS.items():
        section = raw.get(group)
        if section is None:
            continue
        if not isinstance(section, dict):
            if strict:
                raise ProjectConfigError(
                    f"defaults file {path}: '{group}' section must be an object")
            logger.warning("Ignoring project config %s: '%s' section must be an object", path, group)
            continue
        cleaned_section = {}
        for key, value in section.items():
            expected = keys.get(key)
            if expected is None:
                if strict:
                    raise ProjectConfigError(
                        f"defaults file {path}: unknown key '{group}.{key}'")
                logger.warning("Unknown key '%s.%s' in project config %s (ignored)", group, key, path)
            elif not _type_matches(value, expected):
                if strict:
                    raise ProjectConfigError(
                        f"defaults file {path}: '{group}.{key}' expects "
                        f"{expected.__name__}, got {type(value).__name__}")
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
    # 机会式内存准入参数（None → runner 内置默认值）
    args.memory_margin = resolve(getattr(args, 'memory_margin', None),
                                 run_cfg.get("memory_margin"), None)
    args.memory_commit_reserve_mb = resolve(
        getattr(args, 'memory_commit_reserve_mb', None),
        run_cfg.get("memory_commit_reserve_mb"), None)
    args.memory_physical_watermark_mb = resolve(
        getattr(args, 'memory_physical_watermark_mb', None),
        run_cfg.get("memory_physical_watermark_mb"), None)
    args.memory_default_demand_mb = resolve(
        getattr(args, 'memory_default_demand_mb', None),
        run_cfg.get("memory_default_demand_mb"), None)
    args.memory_min_start_interval_s = resolve(
        getattr(args, 'memory_min_start_interval_s', None),
        run_cfg.get("memory_min_start_interval_s"), None)

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
