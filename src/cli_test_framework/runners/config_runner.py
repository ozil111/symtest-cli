"""Generic config-driven test runner with injectable config loader.

The only difference between JSON and YAML runners was the ``load`` call.
This module extracts the common logic into ``ConfigRunner``, accepting a
``config_loader`` callable.  ``JSONRunner`` and ``YAMLRunner`` are now thin
wrappers that inject ``json.load`` / ``yaml.safe_load`` respectively.
"""
import sys
import logging
from typing import Optional, Dict, Any, Callable, BinaryIO

from ..core.base_runner import BaseRunner
from ..core.config_loader import parse_test_cases, substitute_placeholders
from ..core.test_case import TestCase
from ..core.execution import execute_single_test_case
from ..core.types import TestCaseData
from ..utils.path_resolver import PathResolver
from ..config.import_expander import expand_imports

logger = logging.getLogger("cli_test_framework.runners.config_runner")


class ConfigRunner(BaseRunner):
    """Generic sequential test runner.

    Instead of hardcoding ``json.load`` / ``yaml.safe_load``, subclasses (or
    direct callers) inject a ``config_loader`` – any callable that accepts an
    open file-like object and returns a ``dict``.
    """

    def __init__(self, config_file: str = "test_cases.json",
                 workspace: Optional[str] = None,
                 config_loader: Optional[Callable[[BinaryIO], Dict[str, Any]]] = None,
                 variables: Optional[Dict[str, Any]] = None,
                 **kwargs):
        super().__init__(config_file, workspace, **kwargs)
        self._config_loader = config_loader
        self._variables = variables or {}
        # Backward-compatible attribute for tests that patch path_resolver
        self.path_resolver = PathResolver(self.workspace)

    def load_test_cases(self) -> None:
        """Load test cases from config file using the injected loader."""
        if self._config_loader is None:
            raise RuntimeError(
                "config_loader must be set before loading test cases"
            )
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = self._config_loader(f)

            # Expand import references (no-op if none present)
            config = expand_imports(config, self.config_path)
            config = substitute_placeholders(config, self._variables)

            self.load_setup_from_config(config)
            self.test_cases = parse_test_cases(
                config, self.workspace, self.path_resolver,
            )

            logger.info("Successfully loaded %d test cases",
                        len(self.test_cases))
        except Exception as e:
            sys.exit(f"Failed to load configuration file: {str(e)}")

    def run_single_test(self, case: TestCase) -> Dict[str, Any]:
        if case.steps:
            return self._run_sequence(case)

        case_data = case.to_execution_dict()

        command_preview = (
            f"{case_data['command']} {' '.join(case_data['args'])}".strip()
        )
        logger.info("  Executing command: %s", command_preview)

        result = execute_single_test_case(
            case_data,
            str(self.workspace) if self.workspace else None,
            update_baseline=self.update_baseline,
        )

        if result["output"].strip():
            logger.debug("  Command output:")
            for line in result["output"].splitlines():
                logger.debug("    %s", line)

        if result["status"] != "passed" and result.get("message"):
            logger.error("  Error: %s", result["message"])

        return result
