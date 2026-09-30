#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file my_channel_extractor.py
@brief Data-lane (channel) workspace plugin template for symtest-cli (v2 contract)
@details Copy this file into <workspace>/comparators/ and adapt the extraction
         logic.  Auto-discovered and registered as type "mychannelextractor".

Data lane = the plugin only EXTRACTS per-channel numeric data; the FRAMEWORK
owns the verdict via per-channel tolerances (config `channels` /
`default_channel`) using the shared numeric core.  Benefits: uniform error
stats, per-channel pass/fail in reports, predictable semantics for AI
consumers.  If you need a custom verdict, use the autonomous lane instead
(see my_analysis_comparator.py).

Companion config example::

    {
      "type": "mychannelextractor",
      "ref_csv": "out/reference.csv",
      "actual_csv": "out/actual.csv",
      "channels": {
        "S33": {"atol": 600.0, "data_filter": "abs>1e-12"}
      },
      "default_channel": {"rtol": 1e-5, "atol": 1e-8}
    }

No-plugin alternative: if your data comes from an existing script, the
built-in "script_extract" type runs it as a subprocess and parses a JSON
channel payload from stdout — see extract_channels_script.py.
"""

from symtest.file_comparator.base_comparator import CompareContext
from symtest.file_comparator.extractor_comparator import ChannelData, ExtractorComparator


class MyChannelExtractorComparator(ExtractorComparator):
    """
    @brief Extracts named channels of (expected, actual) numeric arrays.
    @details Implement `extract(ctx)` only.  Constructor parameters are
             strict: `channels` / `default_channel` / `rtol` / `atol` are
             consumed by the base class; plugin params (ref_csv, actual_csv)
             are declared here.  Unknown compareSpec keys fail loudly.
    """

    # Constructor params holding filesystem paths (framework-resolved).
    path_params = ("ref_csv", "actual_csv")

    def __init__(self, ref_csv="", actual_csv="", **params):
        # NOTE: `**params` here is an explicit opt-in for free-form user
        # configuration; drop it if your extractor declares all its options.
        super().__init__(**params)
        self.ref_csv = ref_csv      # already workspace-resolved
        self.actual_csv = actual_csv

    def extract(self, ctx: CompareContext):
        """
        @return dict: {channel_name: ChannelData(expected, actual, extra_stats)}
        @raises Exception: failures become ComparisonResult.error (never a
                silent pass).
        """
        ref = self._load(self.ref_csv)
        act = self._load(self.actual_csv)

        return {
            "S11": ChannelData(expected=ref[:, 0], actual=act[:, 0]),
            "S22": ChannelData(expected=ref[:, 1], actual=act[:, 1]),
            "S33": ChannelData(
                expected=ref[:, 2],
                actual=act[:, 2],
                # Optional plugin-defined error metrics, merged into this
                # channel's stats and rendered by the report.
                extra_stats={"hydrostatic_shift": float(act[:, 2].mean())},
            ),
        }

    @staticmethod
    def _load(path):
        import numpy as np
        data = np.loadtxt(path, delimiter=",")
        # Guarantee 2-D (rows x columns) so per-channel column indexing works
        # even for single-column files, where loadtxt returns a 1-D array.
        return data.reshape(-1, 1) if data.ndim == 1 else data
