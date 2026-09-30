#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file extract_channels_script.py
@brief Zero-modification script template for the built-in "script_extract" type
@details The framework runs this script as a subprocess and parses the JSON
         channel payload printed on stdout.  No Python plugin class needed.

Companion config example::

    {
      "type": "script_extract",
      "script": "extract_channels_script.py",
      "args": [],
      "channels": {"S33": {"atol": 600.0}},
      "default_channel": {"rtol": 1e-5, "atol": 1e-8},
      "timeout": 600
    }

Protocol contract:
- Print EXACTLY ONE JSON document on stdout:
    {"channels": {"<name>": {"expected": [...], "actual": [...],
                             "extra_stats": {...}  # optional
                             }}}
- Exit code MUST be 0.  Non-zero exit, timeout, malformed JSON, missing
  "channels" key, or a channel missing expected/actual arrays all become
  comparison ERRORS (never a silent pass).
- Extra stdout lines (progress logs) are fine; only stdout is parsed, so
  print the JSON last and keep it on a single line (json.dumps default).
- If the compareSpec declares "actual"/"baseline", they arrive as trailing
  argv slots with baseline FIRST: sys.argv[-2] = baseline, sys.argv[-1] = actual.
- Tolerances come from the config (per-channel overrides in "channels",
  fallback in "default_channel") — the script never judges pass/fail itself.
"""

import json
import sys


def load_numeric_column(path, column):
    """Example loader: one numeric column from a whitespace-delimited file."""
    values = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if parts:
                values.append(float(parts[column]))
    return values


def main():
    # Trailing file slots (optional in the config): baseline first, then actual.
    baseline_path = sys.argv[-2] if len(sys.argv) >= 2 else None
    actual_path = sys.argv[-1] if len(sys.argv) >= 2 else None

    # TODO: replace with real extraction — read solver output, ODB, HDF5,
    # or whatever upstream data the test produces.
    expected = load_numeric_column(baseline_path, column=0)  # reference data
    actual = load_numeric_column(actual_path, column=0)      # command output

    payload = {
        "channels": {
            "col1": {
                "expected": expected,
                "actual": actual,
                # Optional plugin-defined metrics (free-form dict), merged
                # into this channel's stats in the report:
                # "extra_stats": {"max_gradient": 0.12},
            },
        }
    }
    # Print the JSON document LAST on stdout — the framework parses it.
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
