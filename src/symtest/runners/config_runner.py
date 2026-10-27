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
from ..core.config_loader import parse_test_cases
from ..config.prepared import prepare_config
from ..core.test_case import TestCase
from ..core.orchestration.single import execute_single_test_case
from ..core.types import TestCaseData
from ..utils.path_resolver import PathResolver

logger = logging.getLogger("symtest.runners.config_runner")


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
        """Load test cases through the shared config preparation pipeline."""
        if self._config_loader is None:
            raise RuntimeError(
                "config_loader must be set before loading test cases"
            )
        try:
            # Shared pipeline: raw-form schema validation, import expansion,
            # extends resolution, variable application, expanded-form
            # completeness validation and semantic checks (same rules as
            # ``symtest validate``).
            prepared = prepare_config(
                self.config_path,
                workspace=str(self.workspace) if self.workspace else None,
                variables=self._variables,
                file_loader=self._config_loader,
            )
            if not prepared.valid:
                details = "\n  ".join(prepared.errors)
                sys.exit(
                    f"Failed to load configuration file "
                    f"(invalid configuration, {len(prepared.errors)} error(s)):\n"
                    f"  {details}"
                )
            config = prepared.config

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

        spec = case.execution

        command_preview = (
            f"{spec.command} {' '.join(spec.args)}".strip()
        )
        logger.info("  Executing command: %s", command_preview)

        result = execute_single_test_case(
            spec,
            str(self.workspace) if self.workspace else None,
            expectation=case.expected,
            update_baseline=self.update_baseline,
            error_analysis=self.error_analysis,
        )

        if result["output"].strip():
            logger.debug("  Command output:")
            for line in result["output"].splitlines():
                logger.debug("    %s", line)

        if result["status"] != "passed" and result.get("message"):
            logger.error("  Error: %s", result["message"])

        return result
