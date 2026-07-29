#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for BinaryComparator — covering read_content, compare_content,
compare_files, streaming, similarity, and get_file_hash."""

import pytest
from pathlib import Path
from unittest.mock import patch

from cli_test_framework.file_comparator.binary_comparator import BinaryComparator
from cli_test_framework.file_comparator.result import Difference


# =============================================================================
# read_content
# =============================================================================


class TestReadContent:
    """Test BinaryComparator.read_content()."""

    def test_read_full_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world")
        comp = BinaryComparator()
        content = comp.read_content(f)
        assert content == b"hello world"

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"0123456789")
        comp = BinaryComparator()
        content = comp.read_content(f, start_line=3)
        assert content == b"3456789"

    def test_read_with_range(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"0123456789")
        comp = BinaryComparator()
        content = comp.read_content(f, start_line=2, end_line=7)
        assert content == b"23456"

    def test_read_empty_range(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"0123456789")
        comp = BinaryComparator()
        with pytest.raises(ValueError, match="End offset must be greater"):
            comp.read_content(f, start_line=5, end_line=3)

    def test_file_not_found(self, tmp_path):
        comp = BinaryComparator()
        with pytest.raises(ValueError, match="File not found"):
            comp.read_content(tmp_path / "nonexistent.bin")

    def test_read_with_end_none(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"abcdef")
        comp = BinaryComparator()
        content = comp.read_content(f, start_line=0, end_line=None)
        assert content == b"abcdef"


# =============================================================================
# compare_content
# =============================================================================


class TestCompareContent:
    """Test BinaryComparator.compare_content()."""

    def test_identical_content(self):
        comp = BinaryComparator()
        data = b"hello world"
        identical, diffs, _ = comp.compare_content(data, data)
        assert identical is True
        assert diffs == []

    def test_size_difference(self):
        comp = BinaryComparator()
        identical, diffs, _ = comp.compare_content(b"abc", b"abcdef")
        assert identical is False
        assert len(diffs) >= 1
        assert diffs[0].diff_type == "size"

    def test_single_byte_diff(self):
        comp = BinaryComparator()
        identical, diffs, _ = comp.compare_content(b"hello xorld", b"hello world")
        assert identical is False
        assert len(diffs) >= 1
        assert diffs[0].diff_type == "content"
        assert "byte" in diffs[0].position

    def test_diff_at_beginning(self):
        comp = BinaryComparator()
        identical, diffs, _ = comp.compare_content(b"Xello world", b"hello world")
        assert identical is False
        assert len(diffs) >= 1
        assert "byte 0" in diffs[0].position

    def test_diff_at_end(self):
        comp = BinaryComparator()
        data1 = b"aaaaaaaaaaX"
        data2 = b"aaaaaaaaaaY"
        identical, diffs, _ = comp.compare_content(data1, data2)
        assert identical is False
        assert len(diffs) >= 1

    def test_max_differences_limit(self):
        """When many chunks differ, max_differences=10 should cap output."""
        comp = BinaryComparator(chunk_size=2, verbose=True)
        # Create two 40-byte sequences that differ in every chunk
        data1 = bytes([i % 256 for i in range(40)])
        data2 = bytes([(i + 1) % 256 for i in range(40)])
        identical, diffs, truncated = comp.compare_content(data1, data2)
        assert identical is False
        # Should have at most 10 real differences
        assert len(diffs) <= 10
        # Should be truncated (no fake placeholder diff)
        assert truncated is True
        assert not any(d.position is None for d in diffs)

    def test_empty_content(self):
        comp = BinaryComparator()
        identical, diffs, _ = comp.compare_content(b"", b"")
        assert identical is True
        assert diffs == []

    def test_hex_context_in_differences(self):
        comp = BinaryComparator()
        identical, diffs, _ = comp.compare_content(b"\x00\x01\x02\x03\x04", b"\x00\x01\xff\x03\x04")
        assert identical is False
        # expected/actual should contain hex representations
        assert any(" " in d.expected for d in diffs if d.diff_type == "content")


# =============================================================================
# compare_files
# =============================================================================


class TestCompareFilesBasic:
    """Test BinaryComparator.compare_files() basic paths."""

    def test_identical_files(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        data = b"hello world binary data"
        f1.write_bytes(data)
        f2.write_bytes(data)

        comp = BinaryComparator()
        result = comp.compare_files(f1, f2)

        assert result.identical is True
        assert result.differences == []
        assert result.error is None
        assert result.file1_size == len(data)

    def test_different_files_streaming(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"hello")
        f2.write_bytes(b"hallo")

        comp = BinaryComparator()
        result = comp.compare_files(f1, f2)

        assert result.identical is False
        assert len(result.differences) >= 1

    def test_different_files_with_similarity(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"hello world test data here")
        f2.write_bytes(b"hello world test data ther")

        comp = BinaryComparator(similarity=True)
        result = comp.compare_files(f1, f2)

        assert result.identical is False
        assert result.similarity is not None
        # Files only differ by one byte, similarity should be high
        assert result.similarity > 0.8

    def test_size_mismatch_early_return(self, tmp_path):
        """When file sizes differ and similarity=False, should return early."""
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"short")
        f2.write_bytes(b"much longer data")

        comp = BinaryComparator(similarity=False)
        result = comp.compare_files(f1, f2)

        assert result.identical is False
        assert len(result.differences) >= 1
        assert result.differences[0].diff_type == "size"

    def test_file_not_found_error(self, tmp_path):
        comp = BinaryComparator()
        result = comp.compare_files(
            tmp_path / "nonexistent.bin",
            tmp_path / "also_missing.bin",
        )
        assert result.error is not None
        assert result.identical is False

    def test_with_offsets(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"xxxxxHELLOyyyyy")
        f2.write_bytes(b"xxxxxHELLOyyyyy")

        comp = BinaryComparator()
        result = comp.compare_files(f1, f2, start_line=5, end_line=10)

        assert result.identical is True


# =============================================================================
# _compare_files_streaming
# =============================================================================


class TestCompareFilesStreaming:
    """Test BinaryComparator._compare_files_streaming()."""

    def test_streaming_identical(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"streaming data test")
        f2.write_bytes(b"streaming data test")

        comp = BinaryComparator(chunk_size=4)
        identical, diffs, _ = comp._compare_files_streaming(f1, f2)
        assert identical is True
        assert diffs == []

    def test_streaming_with_offset(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"abcHELLOxyz")
        f2.write_bytes(b"abcHELLOxyz")

        comp = BinaryComparator(chunk_size=2)
        identical, diffs, _ = comp._compare_files_streaming(f1, f2, start_offset=3, end_offset=8)
        assert identical is True

    def test_streaming_different_sizes(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"short")
        f2.write_bytes(b"much longer")

        comp = BinaryComparator()
        identical, diffs, _ = comp._compare_files_streaming(f1, f2)
        assert identical is False
        assert any("byte" in d.position for d in diffs)

    def test_streaming_single_diff(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"AABBCCDD")
        f2.write_bytes(b"AABBXXDD")

        comp = BinaryComparator(chunk_size=4)
        identical, diffs, _ = comp._compare_files_streaming(f1, f2)
        assert identical is False

    def test_streaming_max_differences(self, tmp_path):
        """When two files differ in every chunk, max_differences caps output."""
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(bytes(100))
        f2.write_bytes(bytes([255] * 100))

        comp = BinaryComparator(chunk_size=4)
        identical, diffs, truncated = comp._compare_files_streaming(f1, f2)
        assert identical is False
        assert truncated is True
        assert not any(d.position is None for d in diffs)

    def test_streaming_file_not_found(self, tmp_path):
        comp = BinaryComparator()
        with pytest.raises(ValueError, match="File not found"):
            comp._compare_files_streaming(
                tmp_path / "nope.bin",
                tmp_path / "alsono.bin",
            )

    def test_streaming_invalid_offset(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"data")
        f2.write_bytes(b"data")

        comp = BinaryComparator()
        with pytest.raises(ValueError):
            comp._compare_files_streaming(f1, f2, start_offset=10, end_offset=5)


# =============================================================================
# _compute_similarity
# =============================================================================


class TestComputeSimilarity:
    """Test BinaryComparator._compute_similarity()."""

    def test_identical(self):
        comp = BinaryComparator()
        sim = comp._compute_similarity(b"hello", b"hello")
        assert sim == 1.0

    def test_completely_different(self):
        comp = BinaryComparator()
        sim = comp._compute_similarity(b"abcde", b"vwxyz")
        assert sim < 1.0  # difflib may find some partial matches

    def test_empty_both(self):
        comp = BinaryComparator()
        sim = comp._compute_similarity(b"", b"")
        assert sim == 1.0

    def test_one_empty(self):
        comp = BinaryComparator()
        sim = comp._compute_similarity(b"hello", b"")
        assert sim == 0.0

    def test_diff_mid_range(self):
        comp = BinaryComparator()
        # ~70% similar
        sim = comp._compute_similarity(b"abcdefghij", b"abcXYZfghij")
        # difflib.SequenceMatcher: a, b, c, d, e, f, g, h, i, j vs a, b, c, X, Y, Z, f, g, h, i, j
        # matching blocks: 'abc' (3), 'fghij' (5) = 8 matching out of (10+11)/2 ≈ 0.76
        assert 0.5 < sim < 1.0

    def test_large_file_hash_path(self, tmp_path):
        """When total_bytes > 1MB, _hash_chunk_similarity is used."""
        comp = BinaryComparator()
        data_a = bytes([i % 256 for i in range(1_200_000)])
        data_b = bytes([i % 256 for i in range(1_200_000)])
        # total_bytes = 2_400_000 > 1_048_576 → hash chunk path
        sim = comp._compute_similarity(data_a, data_b)
        assert sim == 1.0

    def test_large_file_different(self):
        comp = BinaryComparator()
        # Two 600KB files (total > 1MB)
        data_a = bytes([i % 256 for i in range(600_000)])
        data_b = bytes([(i + 1) % 256 for i in range(600_000)])
        sim = comp._compute_similarity(data_a, data_b)
        # With hash chunk approach, similarity should be < 1.0
        assert sim < 1.0


# =============================================================================
# _hash_chunk_similarity
# =============================================================================


class TestHashChunkSimilarity:
    """Test BinaryComparator._hash_chunk_similarity()."""

    def test_identical(self):
        comp = BinaryComparator()
        data = b"hello world"
        sim = comp._hash_chunk_similarity(data, data)
        assert sim == 1.0

    def test_different(self):
        comp = BinaryComparator()
        sim = comp._hash_chunk_similarity(b"aaaaaaaa", b"bbbbbbbb")
        # With chunk_size=4096 and small data, each is one chunk
        assert sim < 1.0

    def test_both_empty(self):
        comp = BinaryComparator()
        sim = comp._hash_chunk_similarity(b"", b"")
        assert sim == 1.0


# =============================================================================
# get_file_hash
# =============================================================================


class TestGetFileHash:
    """Test BinaryComparator.get_file_hash()."""

    def test_hash_basic(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello")
        comp = BinaryComparator()
        h = comp.get_file_hash(f)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        comp = BinaryComparator()
        h = comp.get_file_hash(f)
        assert len(h) == 64

    def test_hash_deterministic(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        data = b"same content"
        f1.write_bytes(data)
        f2.write_bytes(data)
        comp = BinaryComparator()
        assert comp.get_file_hash(f1) == comp.get_file_hash(f2)

    def test_hash_different_content(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"hello")
        f2.write_bytes(b"world")
        comp = BinaryComparator()
        assert comp.get_file_hash(f1) != comp.get_file_hash(f2)

    def test_hash_custom_chunk_size(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"x" * 100)
        comp = BinaryComparator()
        h = comp.get_file_hash(f, chunk_size=16)
        assert len(h) == 64
