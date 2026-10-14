"""JSONRunner – thin backward-compatible wrapper around ConfigRunner."""
import json
import logging
from typing import Optional

from .config_runner import ConfigRunner

logger = logging.getLogger("symtest.runners.json_runner")


def _jsonc_load(f):
    """Lazy-load the JSONC parser so ``json`` stays the default path."""
    from ..config import jsonc

    return jsonc.load(f)


class JSONRunner(ConfigRunner):
    """Sequential JSON test runner (backward-compatible thin wrapper)."""

    def __init__(self, config_file="test_cases.json",
                 workspace: Optional[str] = None, **kwargs):
        # .jsonc files carry comments/trailing commas; plain .json keeps
        # the standard library loader.
        if str(config_file).lower().endswith(".jsonc"):
            config_loader = _jsonc_load
        else:
            config_loader = json.load
        super().__init__(
            config_file=config_file,
            workspace=workspace,
            config_loader=config_loader,
            **kwargs,
        )
