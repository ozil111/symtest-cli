"""
CLI Test Framework - A powerful command-line testing framework

This package provides tools for testing command-line applications and scripts
with support for parallel execution and advanced file comparison capabilities.

Logging
-------
All diagnostic and status messages go through Python's standard ``logging``
module under the ``symtest`` namespace.  By default only a
``NullHandler`` is attached — no output is produced on import.  The CLI
entry point calls ``setup_console_logging()`` to enable stderr output at
runtime.  Library users can enable console logging explicitly::

    from symtest.logging_config import setup_console_logging
    setup_console_logging(level=logging.DEBUG)
"""

__version__ = "1.3.1"
__author__ = "Xiaotong Wang"
__email__ = "xiaotongwang98@gmail.com"

# Import main classes for convenient access
from .runners.json_runner import JSONRunner
from .runners.parallel_json_runner import ParallelJSONRunner
from .runners.yaml_runner import YAMLRunner
from .core.test_case import TestCase
from .core.assertions import Assertions
from .core.setup import BaseSetup, EnvironmentSetup, SetupManager
from .logging_config import get_logger, setup_console_logging
from .utils.junit_xml_writer import write_junit_xml

__all__ = [
    'JSONRunner',
    'ParallelJSONRunner',
    'YAMLRunner',
    'TestCase',
    'Assertions',
    'BaseSetup',
    'EnvironmentSetup',
    'SetupManager',
    'get_logger',
    'setup_console_logging',
    'write_junit_xml',
]
