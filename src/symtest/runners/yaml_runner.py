"""YAMLRunner – thin backward-compatible wrapper around ConfigRunner."""
import logging
from typing import Optional

from .config_runner import ConfigRunner

logger = logging.getLogger("symtest.runners.yaml_runner")


def _yaml_load(f):
    """Lazy-load yaml.safe_load so the package is importable without PyYAML."""
    import yaml
    return yaml.safe_load(f)


class YAMLRunner(ConfigRunner):
    """Sequential YAML test runner (backward-compatible thin wrapper)."""

    def __init__(self, config_file="test_cases.yaml",
                 workspace: Optional[str] = None, **kwargs):
        super().__init__(
            config_file=config_file,
            workspace=workspace,
            config_loader=_yaml_load,
            **kwargs,
        )
