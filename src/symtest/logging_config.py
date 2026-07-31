"""
Central logging configuration for the CLI test framework.

Provides a unified ``get_logger(name)`` helper that returns a logger
under the ``symtest`` namespace.  By default only a
``NullHandler`` is attached — no output is produced when the package
is imported as a library.  Applications that want console logging
should call ``setup_console_logging()`` (the CLI entry point does
this automatically).

Replaces the previous ad-hoc ``print()`` / ``_print_lock`` pattern.
The ``logging`` module is already thread-safe, so the manual locking
is no longer needed.
"""

from __future__ import annotations

import logging
import sys

DEFAULT_FORMAT = "%(levelname)-7s %(name)-35s %(message)s"

# ── package-level logger (used as parent for all child loggers) ──────────────
_logger = logging.getLogger("symtest")
_logger.setLevel(logging.DEBUG)          # let handlers decide; do not block

# ── default: NullHandler (polite library behaviour) ──────────────────────────
_logger.addHandler(logging.NullHandler())


def setup_console_logging(level: int = logging.INFO) -> None:
    """Attach a console handler (stderr) for CLI usage.

    Replaces any existing NullHandler with a StreamHandler writing
    to ``sys.stderr`` so that logs never pollute the ``stdout``
    stream (which is reserved for machine-readable output such as
    ``--output-format json``).
    """
    # Remove any NullHandler so we don't have duplicate handlers.
    _logger.handlers = [
        h for h in _logger.handlers
        if not isinstance(h, logging.NullHandler)
    ]

    # Only add if no real handler is already attached (idempotent).
    if not _logger.handlers:
        _handler = logging.StreamHandler(sys.stderr)
        _handler.setLevel(level)
        _handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        _logger.addHandler(_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``symtest`` namespace.

    Usage::

        from symtest.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Hello")
    """
    # Ensure the logger is a child of symtest so it inherits
    # the handler (unless the user removes / replaces it).
    if not name.startswith("symtest"):
        name = "symtest." + name
    return logging.getLogger(name)
