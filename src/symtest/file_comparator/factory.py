#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file factory.py
@brief Factory class for creating comparators based on type
@author Xiaotong Wang
@date 2025

Comparator construction lifecycle (single, shared by every discovery path)::

    resolve type name → comparator class
        → resolve plugin path params against workspace   (BEFORE construction)
        → instantiate with strict, validated parameters
        → configure framework-owned logging (verbose)
        → comparator.compare(ctx)

Path resolution happens *before* the constructor runs so that constructor-
captured state (``self.script``, ``self.cwd``, ``self.case_dir``, ...) already
holds workspace-resolved absolute paths.  Plugins must never resolve paths
against the process CWD.
"""

import importlib
import importlib.util
import inspect
import os
import pkgutil
import logging
from pathlib import Path

logger = logging.getLogger("symtest.file_comparator.factory")

_ENV_VAR = "CLITEST_PLUGIN_DIRS"
_COMPARATOR_SUFFIX = "Comparator"


def _type_name_from_class(class_name: str) -> str:
    """Convention-based fallback: strip ONLY a trailing ``Comparator`` suffix.

    ``FooComparator -> foo``; ``ScriptExtractComparator -> scriptextract``
    (use an explicit ``comparator_type`` class attribute for names containing
    underscores, e.g. ``"script_extract"``).
    """
    if class_name.endswith(_COMPARATOR_SUFFIX):
        return class_name[:-len(_COMPARATOR_SUFFIX)].lower()
    return class_name.lower()


class ComparatorFactory:
    """
    @brief Factory class for creating comparators
    @details Manages creation and registration of comparator classes, with
             automatic plugin discovery.  All discovery paths (built-in module
             scan and workspace plugin directories) share the same
             registration rules via :meth:`_register_comparator_class`.
    """
    _comparators = {}
    _initialized = False
    _plugin_dirs = []

    # ------------------------------------------------------------------
    # Registration (single entry point for every discovery path)
    # ------------------------------------------------------------------
    @staticmethod
    def register_comparator(file_type, comparator_class):
        """
        @brief Register a comparator class for a specific type name
        @param file_type str: Type name the comparator handles
        @param comparator_class class: Comparator class to register
        """
        ComparatorFactory._comparators[file_type.lower()] = comparator_class

    @staticmethod
    def _register_comparator_class(attr, module_name):
        """Shared registration rules for ALL discovery paths.

        A class is registered only when it:
        - is a concrete (non-abstract) class defined in ``module_name``;
        - its name ends with ``Comparator``.

        Type-name priority: explicit ``comparator_type`` class attribute
        (validated, lowercased) > suffix-stripped class-name convention.

        :returns: the registered type name, or ``None`` when skipped.
        """
        if not (isinstance(attr, type)
                and attr.__module__ == module_name
                and attr.__name__.endswith(_COMPARATOR_SUFFIX)):
            return None
        if inspect.isabstract(attr):
            # Abstract bases (ComparatorBase / FileComparator /
            # ExtractorComparator) are contracts, not instantiable types.
            return None

        explicit = getattr(attr, "comparator_type", None)
        if explicit is not None:
            if not isinstance(explicit, str) or not explicit.strip():
                logger.warning(
                    "Ignoring invalid comparator_type %r on %s (must be a "
                    "non-empty string); falling back to class-name convention",
                    explicit, attr.__name__,
                )
                type_name = _type_name_from_class(attr.__name__)
            else:
                type_name = explicit.strip().lower()
        else:
            type_name = _type_name_from_class(attr.__name__)

        ComparatorFactory.register_comparator(type_name, attr)
        return type_name

    # ------------------------------------------------------------------
    # Construction lifecycle
    # ------------------------------------------------------------------
    @staticmethod
    def get_comparator_class(file_type):
        """
        @brief Return the comparator class for a type name (no instantiation).
        @details 'auto'/'text' resolve to TextComparator ('auto' is normally
                 resolved from the file extension by the assertion/CLI layer
                 before reaching the factory).  Unknown types fail LOUDLY with
                 the list of available types — a typo in the compareSpec
                 ``type`` field must never silently degrade to another
                 comparator (that would produce wrong "passing" results).
        """
        if not ComparatorFactory._initialized:
            ComparatorFactory._load_comparators()

        comparator_class = ComparatorFactory._comparators.get(file_type.lower())
        if comparator_class is None:
            if file_type.lower() in ("auto", "text"):
                from .text_comparator import TextComparator
                return TextComparator
            raise ValueError(
                f"Unknown comparator type '{file_type}'. "
                f"Available types: {ComparatorFactory.get_available_comparators()}. "
                f"Unknown types fail loudly — check the compareSpec 'type' for typos."
            )
        return comparator_class

    @staticmethod
    def resolve_plugin_params(comparator_class, params, workspace=None):
        """Resolve plugin-declared path parameters against the workspace.

        Must run BEFORE ``comparator_class(**params)`` so constructor-captured
        state already holds absolute paths.  Only parameters listed in the
        class's ``path_params`` attribute are touched; ``actual``/``baseline``
        are resolved separately by the assertion layer.
        """
        resolved = dict(params or {})
        if workspace:
            for name in getattr(comparator_class, "path_params", ()) or ():
                value = resolved.get(name)
                if isinstance(value, str) and value and not os.path.isabs(value):
                    # normpath keeps separators consistent with the platform
                    resolved[name] = os.path.normpath(os.path.join(workspace, value))
        return resolved

    @staticmethod
    def _accepts_param(cls, name):
        """Whether ``cls.__init__`` accepts ``name`` (or **kwargs)."""
        try:
            sig = inspect.signature(cls.__init__)
        except (TypeError, ValueError):
            return False
        for param in sig.parameters.values():
            if param.name == "self":
                continue
            if param.name == name or param.kind is inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    @staticmethod
    def create_comparator(file_type, workspace=None, verbose=False,
                          error_analysis=False, **kwargs):
        """
        @brief Create a comparator instance (resolve → instantiate lifecycle).
        @param file_type str: Comparator type name ('auto' detects by extension
               at the assertion layer; here it falls back like legacy code).
        @param workspace str|None: Workspace root; ``path_params``-declared
               parameters are resolved against it BEFORE construction.
        @param verbose bool: Framework-owned logging knob; configures the
               comparator's logger level, never stored as comparator config.
        @param error_analysis bool: Forwarded to the constructor only when the
               comparator declares the parameter (numeric comparators).
        @param **kwargs: Comparator configuration.  Unknown parameters fail
               loudly with a TypeError identifying the comparator type —
               configuration typos must never fall back to defaults.
        """
        comparator_class = ComparatorFactory.get_comparator_class(file_type)

        params = ComparatorFactory.resolve_plugin_params(
            comparator_class, kwargs, workspace,
        )
        # Framework-injected knobs are not comparator configuration.
        params.pop("verbose", None)
        params.pop("error_analysis", None)
        if error_analysis and ComparatorFactory._accepts_param(
                comparator_class, "error_analysis"):
            params["error_analysis"] = True

        try:
            comparator = comparator_class(**params)
        except TypeError as exc:
            supported = sorted(
                p for p in inspect.signature(comparator_class.__init__).parameters
                if p != "self"
            )
            raise TypeError(
                f"Invalid configuration for comparator type '{file_type}' "
                f"({comparator_class.__name__}): {exc}. "
                f"Supported parameters: {supported}. "
                f"Unknown parameters fail loudly — check the compareSpec for typos."
            ) from exc

        if verbose:
            comparator.logger.setLevel(logging.DEBUG)
        return comparator

    # ------------------------------------------------------------------
    # Plugin discovery
    # ------------------------------------------------------------------
    @staticmethod
    def set_plugin_dirs(dirs):
        """Register workspace-level plugin directories.

        Thread-pool runners share ``_plugin_dirs`` in-process.  Process-pool
        runners (``spawn``) receive the same list explicitly via the pool
        ``initializer`` (see ``parallel_runner``) — the framework NEVER
        mutates ``os.environ``.

        ``CLITEST_PLUGIN_DIRS`` remains a user-facing *input*: when set by
        the user in the environment, ``_load_comparators()`` reads it as an
        extra discovery source.  The framework only reads it, never writes
        or deletes it.

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
        if ComparatorFactory._initialized:
            ComparatorFactory._load_from_dirs(deduped)

    @staticmethod
    def _load_comparators():
        """
        @brief Load and register all available comparators
        @details Automatically discovers comparator classes from the package
                 and from workspace plugin directories.  Both paths share the
                 registration rules in :meth:`_register_comparator_class`.
        """
        package_dir = Path(__file__).parent
        for module_info in pkgutil.iter_modules([str(package_dir)]):
            if module_info.name.endswith('_comparator') and module_info.name != 'base_comparator':
                try:
                    module = importlib.import_module(f".{module_info.name}", package=__package__)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        type_name = ComparatorFactory._register_comparator_class(
                            attr, module.__name__,
                        )
                        if type_name:
                            logger.debug(
                                "Registered built-in comparator '%s' -> %s",
                                type_name, attr_name,
                            )
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
                        f"symtest.plugins.{mod_name}",
                        str(py_file),
                    )
                    if spec is None or spec.loader is None:
                        logger.warning("Cannot load plugin spec for %s", py_file)
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        type_name = ComparatorFactory._register_comparator_class(
                            attr, module.__name__,
                        )
                        if type_name:
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
        """Reset all internal state (for testing).

        Never touches ``os.environ`` — ``CLITEST_PLUGIN_DIRS`` belongs to
        the user's environment, not to framework state.
        """
        ComparatorFactory._comparators = {}
        ComparatorFactory._initialized = False
        ComparatorFactory._plugin_dirs = []
