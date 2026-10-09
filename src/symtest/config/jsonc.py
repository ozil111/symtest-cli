"""Minimal JSONC (JSON with Comments) parser – zero dependencies.

Implements the VS Code JSONC dialect:

- ``//`` line comments and ``/* ... */`` block comments;
- trailing commas in objects and arrays.

String literals are string-aware: ``//`` and ``/*`` inside strings,
including URLs and escaped quotes (``\\"``), are never stripped.

Stripped characters are replaced with spaces **in place**, newline
characters preserved, so :func:`json.loads` reports syntax errors with
line/column numbers that match the original file.

The public API mirrors the :mod:`json` module: ``loads`` accepts a
``str`` (or ``bytes``), ``load`` accepts an open file object.  This makes
``load`` directly injectable as a ``config_loader`` into ``ConfigRunner``
/ ``ParallelConfigRunner``.
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO, TextIO, Union


def strip_jsonc(text: str) -> str:
    """Return *text* with JSONC comments and trailing commas blanked out.

    The result has the same length as *text* (stripped characters become
    spaces) and keeps every newline, so error positions from
    ``json.loads`` match the original source.
    """
    out = list(text)
    n = len(text)
    i = 0

    # ── Pass 1: strip comments (string-aware) ─────────────────────────
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2  # skip escaped character (e.g. \" stays intact)
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                # Line comment: blank until (not including) the newline.
                while i < n and text[i] not in "\r\n":
                    out[i] = " "
                    i += 1
                continue
            if nxt == "*":
                # Block comment: blank everything, keep newlines.
                j = i + 2
                while j < n and not (text[j] == "*" and j + 1 < n
                                     and text[j + 1] == "/"):
                    if text[j] not in "\r\n":
                        out[j] = " "
                    j += 1
                end = j + 2 if j + 1 < n else n
                for k in range(i, end):
                    if text[k] not in "\r\n":
                        out[k] = " "
                i = end
                continue
        i += 1

    # ── Pass 2: strip trailing commas (string-aware) ──────────────────
    i = 0
    in_string = False
    while i < n:
        ch = out[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and out[j] in " \t\r\n":
                j += 1
            if j < n and out[j] in "}]":
                out[i] = " "
        i += 1

    return "".join(out)


def loads(s: Union[str, bytes, bytearray]) -> Any:
    """Parse a JSONC string (comments + trailing commas) like ``json.loads``."""
    if isinstance(s, (bytes, bytearray)):
        s = s.decode("utf-8")
    return json.loads(strip_jsonc(s))


def load(fp: Union[BinaryIO, TextIO]) -> Any:
    """Parse a JSONC file object like ``json.load``."""
    data = fp.read()
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return loads(data)
