"""Unit tests for HourglassTangentComparator (plugin example).

Tests the stdout-parsing and verdict logic without running a real case.
The comparator is loaded via ``importlib.util`` from examples/plugins/ so the
test also validates that workspace plugin loading works.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


# Locate the plugin file under examples/plugins/
_PLUGIN_FILE = (
    Path(__file__)
    .resolve()
    .parent.parent.parent.parent  # tests/
    / "examples" / "plugins" / "hourglass_tangent_comparator.py"
)

_FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _load_hg_module():
    """Load HourglassTangentComparator from the plugin file."""
    spec = importlib.util.spec_from_file_location(
        "hourglass_tangent_comparator", str(_PLUGIN_FILE)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hg_module():
    return _load_hg_module()


@pytest.fixture
def pass_stdout():
    return (_FIXTURES / "hourglass_stdout_sample.txt").read_text(encoding="utf-8")


@pytest.fixture
def mismatch_stdout():
    return (_FIXTURES / "hourglass_stdout_mismatch.txt").read_text(encoding="utf-8")


class TestStdoutParsing:
    def test_parse_pass_stdout(self, hg_module, pass_stdout):
        data = hg_module._parse_stdout(pass_stdout)
        assert data["verdict"] == "PASS"
        assert data["full_rel"] == pytest.approx(8.000000e-08)
        assert data["observed_rel"] == pytest.approx(5.000000e-08)
        assert data["asymmetry"] == pytest.approx(2.000e-13)
        assert data["aa_rel"] is not None
        assert data["hh_rel"] is not None
        assert data["native_norm"] == pytest.approx(1.234567e06)
        assert data["uel_norm"] == pytest.approx(1.234567e06)

    def test_parse_mismatch_stdout(self, hg_module, mismatch_stdout):
        data = hg_module._parse_stdout(mismatch_stdout)
        assert data["verdict"] == "MISMATCH"
        assert data["full_rel"] == pytest.approx(5.000000e-02)
        assert data["observed_rel"] == pytest.approx(5.000000e-02)
        assert data["asymmetry"] == pytest.approx(1.500e-05)


class TestHourglassComparatorLogic:
    def test_pass_case(self, hg_module, pass_stdout):
        """With pass stdout, the comparator should report identical=True."""
        # Instead of executing a real script, we can instantiate the comparator
        # and test the parsing logic by reading a fixture file.
        cls = getattr(hg_module, "HourglassTangentComparator", None)
        assert cls is not None, "HourglassTangentComparator not found in plugin module"

        # Create instance with dummy script (won't be called in this test)
        cmp = cls(script="dummy.py")
        # Manually verify parsing logic using the fixture
        data = hg_module._parse_stdout(pass_stdout)

        # Simulate the verdict logic from compare_files
        verdict = data["verdict"]
        full_rel = data["full_rel"]
        threshold = cmp.pass_threshold

        # PASS verdict and full_rel < 1e-6 should be pass
        assert verdict == "PASS"
        assert full_rel is not None and full_rel < threshold

    def test_mismatch_case_differences(self, hg_module, mismatch_stdout):
        """MISMATCH stdout produces error_stats and non-identical result."""
        cls = getattr(hg_module, "HourglassTangentComparator", None)
        assert cls is not None

        cmp = cls(script="dummy.py")
        data = hg_module._parse_stdout(mismatch_stdout)

        verdict = data["verdict"]
        assert verdict == "MISMATCH"

        full_rel = data["full_rel"]
        assert full_rel is not None and full_rel >= cmp.pass_threshold

        # error_stats should contain all parsed metrics
        stats_keys = [
            k for k in ("full_rel", "observed_rel", "aa_rel", "hh_rel",
                        "asymmetry", "native_norm", "uel_norm", "verdict")
            if data.get(k) is not None
        ]
        assert len(stats_keys) >= 5  # should have most keys


class TestHourglassComparatorEdge:
    def test_empty_stdout(self, hg_module):
        data = hg_module._parse_stdout("")
        assert data["verdict"] is None
        assert all(
            data[k] is None
            for k in ("full_rel", "observed_rel", "aa_rel",
                      "hh_rel", "asymmetry", "native_norm", "uel_norm")
        )
