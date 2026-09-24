"""Unit tests for the data-lane channel pipeline (ExtractorComparator).

Covers per-channel tolerance routing, framework-owned verdict aggregation,
extra_stats merging, channel-position prefixes, and error handling.
"""
import numpy as np
import pytest
from pathlib import Path

from symtest.file_comparator.base_comparator import CompareContext
from symtest.file_comparator.extractor_comparator import (
    ChannelData,
    ExtractorComparator,
)


class FakeExtractor(ExtractorComparator):
    """Deterministic extractor for tests."""

    def __init__(self, channels_data=None, **kwargs):
        super().__init__(**kwargs)
        self._channels_data = channels_data or {}

    def extract(self, ctx):
        return self._channels_data


def _ctx(**kw):
    return CompareContext(**kw)


class TestChannelRouting:
    def test_per_channel_tolerance_override(self):
        """A channel-specific atol overrides default_channel."""
        # diff = 0.5: fails rtol=1e-5/atol=1e-8, passes atol=1.0
        data = {"S11": ChannelData(expected=np.array([1.0]), actual=np.array([1.5]))}
        cmp = FakeExtractor(
            channels_data=data,
            channels={"S11": {"atol": 1.0}},
            default_channel={"rtol": 1e-5, "atol": 1e-8},
        )
        result = cmp.compare(_ctx())
        assert result.identical is True
        assert result.channels[0].atol == 1.0

    def test_unlisted_channel_uses_default(self):
        data = {
            "S11": ChannelData(expected=np.array([1.0]), actual=np.array([1.0])),
            "S22": ChannelData(expected=np.array([2.0]), actual=np.array([2.0])),
        }
        cmp = FakeExtractor(
            channels_data=data,
            channels={"S11": {"atol": 1.0}},
            default_channel={"rtol": 1e-5, "atol": 1e-8},
        )
        result = cmp.compare(_ctx())
        by_name = {ch.name: ch for ch in result.channels}
        assert by_name["S11"].atol == 1.0
        assert by_name["S22"].atol == 1e-8

    def test_default_rtol_atol_fallback(self):
        data = {"S11": ChannelData(expected=np.array([1.0]), actual=np.array([1.0]))}
        cmp = FakeExtractor(channels_data=data, rtol=1e-3, atol=1e-2)
        result = cmp.compare(_ctx())
        assert result.channels[0].rtol == 1e-3
        assert result.channels[0].atol == 1e-2


class TestAggregation:
    def test_all_channels_pass(self):
        data = {
            "S11": ChannelData(expected=np.array([1.0, 2.0]), actual=np.array([1.0, 2.0])),
            "S33": ChannelData(expected=np.array([3.0]), actual=np.array([3.0])),
        }
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        assert result.identical is True
        assert all(ch.passed for ch in result.channels)
        assert result.differences == []

    def test_any_channel_failure_fails_result(self):
        data = {
            "S11": ChannelData(expected=np.array([1.0]), actual=np.array([1.0])),
            "S33": ChannelData(expected=np.array([1.0]), actual=np.array([500.0])),
        }
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        assert result.identical is False
        by_name = {ch.name: ch for ch in result.channels}
        assert by_name["S11"].passed is True
        assert by_name["S33"].passed is False
        assert len(result.differences) == 1
        assert result.differences[0].position == "channel S33"
        assert result.differences[0].diff_type == "channel_mismatch"

    def test_error_stats_keyed_by_channel(self):
        data = {
            "S11": ChannelData(expected=np.array([1.0]), actual=np.array([1.0])),
            "S33": ChannelData(expected=np.array([1.0]), actual=np.array([2.0])),
        }
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        assert set(result.error_stats.keys()) == {"S11", "S33"}
        assert result.error_stats["S11"]["mismatched"] == 0
        assert result.error_stats["S33"]["mismatched"] == 1

    def test_stats_summary_fields(self):
        data = {"S11": ChannelData(expected=np.array([1.0, 2.0]), actual=np.array([1.5, 2.0]))}
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        stats = result.channels[0].stats
        for key in ("total", "mismatched", "max_abs_error", "max_rel_error",
                    "mean_abs_error", "rms_abs_error"):
            assert key in stats
        assert stats["total"] == 2


class TestExtraStats:
    def test_extra_stats_in_separate_namespace(self):
        """Plugin-defined metrics live in ChannelResult.extra_stats, never
        merged into framework-owned canonical stats."""
        data = {
            "S33": ChannelData(
                expected=np.array([1.0]),
                actual=np.array([1.0]),
                extra_stats={"asymmetry": 1.5e-13, "verdict": "PASS"},
            ),
        }
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        ch = result.channels[0]
        # Canonical stats untouched by plugin metrics
        assert "asymmetry" not in ch.stats
        assert "verdict" not in ch.stats
        assert ch.stats["max_abs_error"] is not None or ch.stats["total"] == 1
        # Plugin metrics ride along in their own namespace
        assert ch.extra_stats["asymmetry"] == 1.5e-13
        assert ch.extra_stats["verdict"] == "PASS"
        # Serialized shape keeps the namespaces distinct
        d = ch.to_dict()
        assert d["extra_stats"]["asymmetry"] == 1.5e-13
        assert "asymmetry" not in d["stats"]

    def test_extra_stats_cannot_overwrite_canonical_stats(self):
        """A plugin providing canonical-looking keys must NOT overwrite
        framework-owned metrics."""
        data = {
            "S33": ChannelData(
                expected=np.array([1.0]),
                actual=np.array([900.0]),  # canonical max_abs_error = 899.0
                extra_stats={"max_abs_error": 123.0, "total": 999},
            ),
        }
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        ch = result.channels[0]
        assert ch.stats["max_abs_error"] == pytest.approx(899.0)
        assert ch.stats["total"] == 1
        assert ch.extra_stats["max_abs_error"] == 123.0
        assert ch.extra_stats["total"] == 999


class TestErrorHandling:
    def test_size_mismatch_is_channel_error(self):
        data = {"S11": ChannelData(expected=np.array([1.0, 2.0]), actual=np.array([1.0]))}
        cmp = FakeExtractor(channels_data=data)
        result = cmp.compare(_ctx())
        assert result.identical is False
        ch = result.channels[0]
        assert ch.passed is False
        assert ch.differences[0].diff_type == "channel_error"

    def test_extract_failure_becomes_result_error(self):
        class BoomExtractor(FakeExtractor):
            def extract(self, ctx):
                raise RuntimeError("solver output missing")

        cmp = BoomExtractor()
        result = cmp.compare(_ctx())
        assert result.identical is False
        assert "solver output missing" in result.error
        assert result.channels == []

    def test_empty_channels_is_error(self):
        cmp = FakeExtractor(channels_data={})
        result = cmp.compare(_ctx())
        assert result.identical is False
        assert "no channels" in result.error


class TestDataFilter:
    def test_channel_data_filter_excludes_cells(self):
        """data_filter routes small-magnitude cells out of the comparison."""
        data = {"U": ChannelData(
            expected=np.array([1.0, 1e-12]),
            actual=np.array([1.0, 5e-12]),  # second cell differs but is filtered out
        )}
        cmp = FakeExtractor(
            channels_data=data,
            default_channel={"data_filter": "abs>1e-6"},
        )
        result = cmp.compare(_ctx())
        assert result.identical is True
        assert result.channels[0].stats["total"] == 1


class TestAssertionsIntegration:
    def test_compare_files_resolves_path_params(self, tmp_path, monkeypatch):
        """Assertions.compare_files resolves path_params against workspace
        BEFORE construction: constructor-captured state already holds the
        absolute path (single source of truth — ctx.params carries no copy)."""
        from symtest.file_comparator.factory import ComparatorFactory
        from symtest.core.validation.assertions import Assertions

        captured = {}

        class PathParamExtractor(FakeExtractor):
            path_params = ("data_file",)

            def __init__(self, data_file="", **kwargs):
                super().__init__(**kwargs)
                # Constructor-captured state must already be workspace-resolved.
                self.data_file = data_file

            def extract(self, ctx):
                captured["ctor_data_file"] = self.data_file
                captured["ctx_params"] = dict(ctx.params)
                values = [float(x) for x in Path(self.data_file).read_text().split()]
                return {"v": ChannelData(expected=values, actual=values)}

        monkeypatch.setattr(
            ComparatorFactory, "_comparators",
            {**ComparatorFactory._comparators, "pathparam": PathParamExtractor},
        )

        data_file = tmp_path / "values.txt"
        data_file.write_text("1.0 2.0 3.0\n", encoding="utf-8")

        response = Assertions.compare_files(
            actual_path=None,
            baseline_path=None,
            file_type="pathparam",
            workspace=str(tmp_path),
            data_file="values.txt",  # workspace-relative
        )
        assert response["identical"] is True
        resolved = captured["ctor_data_file"]
        assert Path(resolved).is_absolute()
        assert Path(resolved) == data_file
        # ctx.params is invocation-level only — no configuration copy.
        assert "data_file" not in captured["ctx_params"]
        assert response["channels"][0]["name"] == "v"
        assert response["channels"][0]["passed"] is True
