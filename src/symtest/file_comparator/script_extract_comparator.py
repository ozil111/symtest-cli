#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file script_extract_comparator.py
@brief Built-in ``script_extract`` comparator: zero-modification script to channel pipeline
@author Xiaotong Wang
@date 2026

Lets an existing analysis script feed the data lane without writing a Python
plugin.  The script is executed as a subprocess and must print a JSON document
on stdout::

    {
      "channels": {
        "S11":  {"expected": [...], "actual": [...], "extra_stats": {"k": v}},
        "S33":  {"expected": [...], "actual": [...]}
      }
    }

Each channel then goes through the standard per-channel tolerance pipeline
(``channels`` / ``default_channel`` compareSpec keys).  Exit code 0 is
required; any non-zero exit, timeout, or malformed JSON becomes a comparison
error (never a silent pass).

Config example::

    {
      "type": "script_extract",
      "script": "extract_channels.py",
      "args": ["--frame", "10"],
      "cwd": "case/subdir",
      "timeout": 600,
      "channels": {"S33": {"atol": 600.0}},
      "default_channel": {"rtol": 1e-5, "atol": 1e-8}
    }
"""

import json
import subprocess
import sys
from typing import Dict

from .base_comparator import CompareContext
from .extractor_comparator import ChannelData, ExtractorComparator


class ScriptExtractComparator(ExtractorComparator):
    """
    @brief Run an external script and route its JSON channel output through
           the framework-owned numeric pipeline.
    @details Inherits per-channel verdict logic from
             :class:`ExtractorComparator`; this class only handles the
             subprocess invocation and JSON protocol parsing.
    """

    comparator_type = "script_extract"  # factory type name (convention would yield "scriptextract")
    path_params = ("script", "cwd")

    def __init__(self, script: str = "", args=None, cwd: str = None,
                 interpreter: str = None, timeout: int = 3600,
                 channels=None, default_channel=None):
        """
        @param script str: Path to the extraction script (required).
        @param args list: Extra CLI arguments passed to the script.
        @param cwd str: Working directory for the subprocess (workspace-
               resolved by the framework BEFORE construction via
               ``path_params``).
        @param interpreter str: Python interpreter (default ``sys.executable``).
        @param timeout int: Subprocess timeout in seconds (default 3600).
        @note Parameters are strict: unknown/misspelled config keys fail loudly.
        """
        super().__init__(channels=channels, default_channel=default_channel)
        self.script = script      # workspace-resolved by the framework
        self.args = list(args) if args else []
        self.cwd = cwd            # workspace-resolved by the framework
        self.interpreter = interpreter or sys.executable
        self.timeout = timeout

    def extract(self, ctx: CompareContext) -> Dict[str, ChannelData]:
        """
        @brief Execute the script and parse its JSON channel payload.
        @raises ValueError: On non-zero exit, timeout, or malformed payload.
        """
        if not self.script:
            raise ValueError("script_extract: 'script' parameter is required")

        cmd = [self.interpreter, self.script, *self.args]
        # Trailing positional slots carry the framework-resolved file paths,
        # baseline first (same convention as the script comparator); scripts
        # that take no file inputs simply ignore them.
        if ctx.baseline:
            cmd.append(str(ctx.baseline))
        if ctx.actual:
            cmd.append(str(ctx.actual))

        self.logger.info("Executing extraction script: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"script_extract: script timed out after {self.timeout}s: {self.script}"
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        self._last_command_output = stdout + ("\n" + stderr if stderr else "")

        if proc.returncode != 0:
            tail = (stderr.strip() or stdout.strip())[-500:]
            raise ValueError(
                f"script_extract: script exited with code {proc.returncode}: {self.script}"
                + (f" — {tail}" if tail else "")
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"script_extract: script stdout is not valid JSON ({exc}). "
                f"Expected {{\"channels\": {{name: {{expected: [...], actual: [...]}}}}}}. "
                f"stdout head: {stdout[:200]!r}"
            )

        return self._parse_payload(payload)

    def _parse_payload(self, payload) -> Dict[str, ChannelData]:
        """Validate the JSON document shape and build ChannelData entries."""
        if not isinstance(payload, dict) or not isinstance(
                payload.get("channels"), dict) or not payload["channels"]:
            raise ValueError(
                "script_extract: JSON payload must contain a non-empty "
                "'channels' object mapping channel names to "
                "{'expected': [...], 'actual': [...], 'extra_stats': {...}}"
            )

        channels: Dict[str, ChannelData] = {}
        for name, spec in payload["channels"].items():
            if not isinstance(spec, dict) or "expected" not in spec or "actual" not in spec:
                raise ValueError(
                    f"script_extract: channel '{name}' must provide "
                    f"'expected' and 'actual' arrays"
                )
            extra = spec.get("extra_stats")
            if extra is not None and not isinstance(extra, dict):
                raise ValueError(
                    f"script_extract: channel '{name}' extra_stats must be an object"
                )
            channels[str(name)] = ChannelData(
                expected=spec["expected"],
                actual=spec["actual"],
                extra_stats=extra,
            )
        return channels
