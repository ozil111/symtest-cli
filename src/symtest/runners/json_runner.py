"""JSONRunner – thin backward-compatible wrapper around ConfigRunner."""
import json
import logging
from typing import Optional

from .config_runner import ConfigRunner

logger = logging.getLogger("symtest.runners.json_runner")


class JSONRunner(ConfigRunner):
    """Sequential JSON test runner (backward-compatible thin wrapper)."""

    def __init__(self, config_file="test_cases.json",
                 workspace: Optional[str] = None, **kwargs):
        super().__init__(
            config_file=config_file,
            workspace=workspace,
            config_loader=json.load,
            **kwargs,
        )
