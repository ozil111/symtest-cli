"""Unit tests for the built-in script_extract comparator (JSON protocol).

Covers: valid channel payloads, pass/fail verdicts (framework-owned),
extra_stats passthrough, error handling (non-zero exit, malformed JSON,
empty channels, timeout), and the baseline-first trailing file-arg convention.
"""
import json
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from symtest.file_comparator.base_comparator import CompareContext
from symtest.file_comparator.script_extract_comparator import ScriptExtractComparator


class TestValidPayloads:
    def test_pass(self, tmp_path):
        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json, sys
            print(json.dumps({"channels": {
                "S11": {"expected": [1.0, 2.0], "actual": [1.0, 2.0]}
            }}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.error is None
        assert result.identical is True
        assert [ch.name for ch in result.channels] == ["S11"]
        assert result.channels[0].passed is True

    def test_fail_with_channel_prefix(self, tmp_path):
        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json
            print(json.dumps({"channels": {
                "S33": {"expected": [1.0], "actual": [900.0]}
            }}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert result.differences[0].position == "channel S33"
        assert result.error_stats["S33"]["mismatched"] == 1

    def test_extra_stats_passthrough(self, tmp_path):
        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json
            print(json.dumps({"channels": {
                "K": {"expected": [1.0], "actual": [1.0],
                      "extra_stats": {"asymmetry": 2e-13}}
            }}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        ch = result.channels[0]
        # Plugin metrics live in the separate extra_stats namespace
        assert ch.extra_stats["asymmetry"] == 2e-13
        assert "asymmetry" not in ch.stats

    def test_per_channel_tolerance_routing(self, tmp_path):
        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json
            print(json.dumps({"channels": {
                "S33": {"expected": [1.0], "actual": [1.5]}
            }}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(
            script=str(script), channels={"S33": {"atol": 1.0}},
        )
        result = cmp.compare(CompareContext())
        assert result.identical is True

    def test_command_output_captured(self, tmp_path):
        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json
            print("loading data...")
            print(json.dumps({"channels": {"A": {"expected": [1], "actual": [1]}}}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert "loading data..." in result.command_output

    def test_trailing_file_args_baseline_first(self, tmp_path):
        """baseline then actual are appended as trailing argv slots."""
        captured = {}

        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json, sys
            captured = {"argv": sys.argv[1:]}
            print(json.dumps({"channels": {"A": {"expected": [1], "actual": [1]}}}))
            import pathlib
            pathlib.Path(__file__).with_suffix(".argv").write_text(json.dumps(captured))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext(actual="out.dat", baseline="ref.dat"))

        assert result.identical is True
        captured = json.loads(script.with_suffix(".argv").read_text())
        assert captured["argv"] == ["ref.dat", "out.dat"]

    def test_script_reads_input_file_content(self, tmp_path):
        """End-to-end: script reads files and emits per-channel arrays."""
        ref = tmp_path / "ref.csv"
        out = tmp_path / "out.csv"
        ref.write_text("1.0\n2.0\n", encoding="utf-8")
        out.write_text("1.0\n2.5\n", encoding="utf-8")

        script = tmp_path / "extract.py"
        script.write_text(textwrap.dedent("""
            import json, sys
            baseline, actual = sys.argv[-2], sys.argv[-1]
            def load(p):
                return [float(x) for x in open(p).read().split()]
            print(json.dumps({"channels": {
                "col1": {"expected": load(baseline), "actual": load(actual)}
            }}))
        """), encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext(actual=str(out), baseline=str(ref)))
        assert result.identical is False  # 2.0 vs 2.5 beyond default tolerance


class TestErrorHandling:
    def test_nonzero_exit_is_error(self, tmp_path):
        script = tmp_path / "fail.py"
        script.write_text("import sys; sys.exit(3)", encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "exited with code 3" in result.error

    def test_malformed_json_is_error(self, tmp_path):
        script = tmp_path / "badjson.py"
        script.write_text("print('not json')", encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "not valid JSON" in result.error

    def test_missing_channels_key_is_error(self, tmp_path):
        script = tmp_path / "nochan.py"
        script.write_text('import json; print(json.dumps({"data": []}))', encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "'channels'" in result.error

    def test_empty_channels_is_error(self, tmp_path):
        script = tmp_path / "emptychan.py"
        script.write_text('import json; print(json.dumps({"channels": {}}))', encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "non-empty" in result.error

    def test_channel_missing_arrays_is_error(self, tmp_path):
        script = tmp_path / "badchan.py"
        script.write_text(
            'import json; print(json.dumps({"channels": {"A": {"expected": [1]}}}))',
            encoding="utf-8",
        )
        cmp = ScriptExtractComparator(script=str(script))
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "channel 'A'" in result.error

    def test_timeout_is_error(self, tmp_path):
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(30)", encoding="utf-8")
        cmp = ScriptExtractComparator(script=str(script), timeout=1)
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "timed out" in result.error

    def test_missing_script_param_is_error(self):
        cmp = ScriptExtractComparator()
        result = cmp.compare(CompareContext())
        assert result.identical is False
        assert "'script' parameter is required" in result.error
