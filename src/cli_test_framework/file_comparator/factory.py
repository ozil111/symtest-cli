#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file factory.py
@brief Factory class for creating file comparators based on file type
@author Xiaotong Wang
@date 2025
"""

import importlib
import importlib.util
import os
import pkgutil
import logging
from pathlib import Path

logger = logging.getLogger("cli_test_framework.file_comparator.factory")

_ENV_VAR = "CLITEST_PLUGIN_DIRS"

class ComparatorFactory:
    """
    @brief Factory class for creating file comparators
    @details This class manages the creation and registration of different types of file comparators.
             It provides a centralized way to create appropriate comparators based on file type
             and automatically discovers and registers comparator classes via plugin scanning.
    """
    _comparators = {}
    _initialized = False
    _plugin_dirs = []

    @staticmethod
    def register_comparator(file_type, comparator_class):
        """
        @brief Register a new comparator class for a specific file type
        @param file_type str: Type of file the comparator handles
        @param comparator_class class: Comparator class to register
        """
        ComparatorFactory._comparators[file_type.lower()] = comparator_class

    @staticmethod
    def create_comparator(file_type, **kwargs):
        """
        @brief Create a comparator instance for the specified file type
        @param file_type str: Type of file to compare
        @param **kwargs: Additional arguments to pass to the comparator
        @return BaseComparator: An instance of the appropriate comparator class
        @details Creates and returns a comparator instance based on the file type.
                 If no specific comparator is found, falls back to TextComparator
                 for text files or BinaryComparator for other types.
        """
        if not ComparatorFactory._initialized:
            ComparatorFactory._load_comparators()

        comparator_class = ComparatorFactory._comparators.get(file_type.lower())
        if not comparator_class:
            if file_type.lower() in ['auto', 'text']:
                from .text_comparator import TextComparator
                return TextComparator(**kwargs)
            else:
                from .binary_comparator import BinaryComparator
                return BinaryComparator(**kwargs)

        return comparator_class(**kwargs)

    @staticmethod
    def set_plugin_dirs(dirs):
        """Persist workspace-level plugin directories and expose them via env var.

        Thread-pool runners share ``_plugin_dirs`` in-process.  Process-pool
        runners (``spawn``) pick up the plugin paths from ``CLITEST_PLUGIN_DIRS``
        so that the lazy ``_load_comparators()`` in each worker discovers the
        same workspace plugins.

        :param dirs: Iterable of absolute or relative directory paths.
        """
        dirs = list(dirs) if dirs else []
        deduped = []
        seen = set()
        for d in dirs:
            resolved = str(Path(d).resolve())
            if resolved not in seen:
                deduped.append(resolved)
                seen.add(resolved)
        ComparatorFactory._plugin_dirs = deduped
        os.environ[_ENV_VAR] = os.pathsep.join(deduped)
        if ComparatorFactory._initialized:
            ComparatorFactory._load_from_dirs(deduped)

    @staticmethod
    def _load_comparators():
        """
        @brief Load and register all available comparators
        @details Automatically discovers and registers comparator classes from the package.
                 This includes both built-in comparators and any additional comparators
                 that follow the naming convention '*_comparator.py'.
        """
        package_dir = Path(__file__).parent
        for module_info in pkgutil.iter_modules([str(package_dir)]):
            if module_info.name.endswith('_comparator') and module_info.name != 'base_comparator':
                try:
                    module = importlib.import_module(f".{module_info.name}", package=__package__)

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            attr.__module__ == module.__name__ and
                            attr_name.endswith('Comparator')):
                            type_name = attr_name.lower().replace('comparator', '')
                            ComparatorFactory.register_comparator(type_name, attr)
                except ImportError as e:
                    logger.warning("Failed to import comparator module %s: %s", module_info.name, e)

        # --- workspace & env-var plugin dirs ---
        extra_dirs = list(ComparatorFactory._plugin_dirs)
        env_val = os.environ.get(_ENV_VAR, "")
        if env_val:
            for p in env_val.split(os.pathsep):
                p = p.strip()
                if p and p not in extra_dirs:
                    extra_dirs.append(p)
        if extra_dirs:
            ComparatorFactory._load_from_dirs(extra_dirs)

        ComparatorFactory._initialized = True

    @staticmethod
    def _load_from_dirs(dirs):
        """Scan *directory* paths for ``*_comparator.py`` modules and auto-register them.

        Uses ``importlib.util.spec_from_file_location`` so that files outside the
        framework package tree can be loaded.
        """
        for dir_path in dirs:
            d = Path(dir_path)
            if not d.is_dir():
                if os.path.isabs(dir_path):
                    logger.debug("Plugin dir not found, skipped: %s", dir_path)
                continue
            for py_file in sorted(d.glob("*_comparator.py")):
                mod_name = py_file.stem
                # Skip base_comparator
                if mod_name == "base_comparator":
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"cli_test_framework.plugins.{mod_name}",
                        str(py_file),
                    )
                    if spec is None or spec.loader is None:
                        logger.warning("Cannot load plugin spec for %s", py_file)
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type)
                                and attr.__module__ == module.__name__
                                and attr_name.endswith("Comparator")):
                            type_name = attr_name.lower().replace("comparator", "")
                            ComparatorFactory.register_comparator(type_name, attr)
                            logger.info(
                                "Registered workspace plugin '%s' -> %s from %s",
                                type_name, attr_name, py_file,
                            )
                except Exception as e:
                    logger.warning(
                        "Failed to load workspace plugin %s: %s", py_file, e,
                    )

    @staticmethod
    def get_available_comparators():
        """
        @brief Get a list of all registered comparator types
        @return list: List of available comparator type names
        """
        if not ComparatorFactory._initialized:
            ComparatorFactory._load_comparators()
        return sorted(ComparatorFactory._comparators.keys())

    @staticmethod
    def reset():
        """Reset all internal state (for testing)."""
        ComparatorFactory._comparators = {}
        ComparatorFactory._initialized = False
        ComparatorFactory._plugin_dirs = []
        if _ENV_VAR in os.environ:
            del os.environ[_ENV_VAR]

