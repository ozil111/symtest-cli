from symtest.file_comparator.factory import ComparatorFactory
from symtest.file_comparator.binary_comparator import BinaryComparator


def compare_binary(file1, file2, **kwargs):
    comparator = ComparatorFactory.create_comparator("binary", **kwargs)
    return comparator.compare_files(file1, file2)


def test_binary_identical(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    data = b"\x00\x01\x02demo"
    f1.write_bytes(data)
    f2.write_bytes(data)

    result = compare_binary(f1, f2)
    assert result.identical
    assert result.differences == []


def test_binary_difference_and_similarity(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"\x00\x01\x02demo")
    f2.write_bytes(b"\x00\x01\x03demo")

    result = compare_binary(f1, f2, similarity=True)
    assert not result.identical
    assert result.similarity is not None
    assert result.differences


# ---------------------------------------------------------------------------
# _compute_similarity 回归测试（小文件 ≤1MB，走 SequenceMatcher 路径）
# ---------------------------------------------------------------------------

def test_compute_similarity_both_empty():
    comp = BinaryComparator()
    assert comp._compute_similarity(b"", b"") == 1.0


def test_compute_similarity_one_empty():
    comp = BinaryComparator()
    assert comp._compute_similarity(b"", b"hello") == 0.0
    assert comp._compute_similarity(b"hello", b"") == 0.0


def test_compute_similarity_identical():
    comp = BinaryComparator()
    data = b"\x00\x01\x02\x03hello world\xff\xfe"
    assert comp._compute_similarity(data, data) == 1.0


def test_compute_similarity_completely_different():
    comp = BinaryComparator()
    assert comp._compute_similarity(b"\x00\x01\x02", b"\xff\xfe\xfd") == 0.0


def test_compute_similarity_one_byte_diff():
    """单字节不同——验证 SequenceMatcher.ratio() 精确值"""
    comp = BinaryComparator()
    a = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
    b_diff = b"\x00\x01\x02\x03\xff\x05\x06\x07\x08\x09"
    # 10 字节中 9 字节匹配，ratio = 2 * 9 / 20 = 0.9
    assert comp._compute_similarity(a, b_diff) == 0.9


def test_compute_similarity_partial_match():
    """等长字符串，前后缀匹配——验证部分相似场景的 ratio"""
    comp = BinaryComparator()
    # 26 bytes, prefix + suffix match, middle differs
    a = b"abcdefghijklmnopqrstuvwxyz"
    b_diff = b"abcdefghijXXXXXXXXXXuvwxyz"  # exactly 26 bytes
    # 前缀 "abcdefghij" (10 bytes) + 后缀 "uvwxyz" (6 bytes) = 16 matching
    # total bytes = 26 + 26 = 52 → ratio = 2 * 16 / 52 = 32/52
    expected = 32.0 / 52.0
    assert abs(comp._compute_similarity(a, b_diff) - expected) < 1e-9


def test_compute_similarity_same_size_different():
    """等长但无任何公共字节 → 0.0"""
    comp = BinaryComparator()
    # 两段完全不重叠的字节集
    a = b"\x00" * 100
    b_diff = b"\xff" * 100
    assert comp._compute_similarity(a, b_diff) == 0.0


# ---------------------------------------------------------------------------
# _hash_chunk_similarity 回归测试（大文件分块哈希路径）
# ---------------------------------------------------------------------------

def test_hash_chunk_similarity_empty():
    comp = BinaryComparator()
    assert comp._hash_chunk_similarity(b"", b"") == 1.0


def test_hash_chunk_similarity_identical():
    """两个 8KB 完全相同的内容 → 所有分块哈希相同 → 1.0"""
    comp = BinaryComparator()
    data = b"\x00" * 4096 + b"\x01" * 4096
    assert comp._hash_chunk_similarity(data, data) == 1.0


def test_hash_chunk_similarity_completely_different():
    """4KB 分块完全不同 → 交集为空 → 0.0"""
    comp = BinaryComparator()
    a = b"\x00" * 4096
    b = b"\xff" * 4096
    assert comp._hash_chunk_similarity(a, b) == 0.0


def test_hash_chunk_similarity_half_overlap():
    """两个文件各 2 个分块，共享 1 个 → Jaccard = 1/3"""
    comp = BinaryComparator()
    chunk_a = b"\x00" * 4096
    chunk_b = b"\x01" * 4096
    chunk_c = b"\x02" * 4096
    a = chunk_a + chunk_b  # 分块: {hash(chunk_a), hash(chunk_b)}
    b = chunk_b + chunk_c  # 分块: {hash(chunk_b), hash(chunk_c)}
    # 交集 1, 并集 3
    assert comp._hash_chunk_similarity(a, b) == 1.0 / 3.0


def test_hash_chunk_similarity_all_same():
    """全部分块相同 → 1.0"""
    comp = BinaryComparator()
    chunk = b"\xAB" * 4096
    data = chunk * 5  # 5 个相同分块
    assert comp._hash_chunk_similarity(data, data) == 1.0


# ---------------------------------------------------------------------------
# 集成回归：通过 compare_files 验证相似度具体数值
# ---------------------------------------------------------------------------

def test_binary_similarity_exact_value(tmp_path):
    """验证旧 LCS 算法曾会高估的场景——新实现给出正确的 ratio"""
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    # 26 字节，前后缀匹配，中间不同
    f1.write_bytes(b"abcdefghijklmnopqrstuvwxyz")
    f2.write_bytes(b"abcdefghijXXXXXXXXXXuvwxyz")  # 等长 26 bytes

    result = compare_binary(f1, f2, similarity=True)
    assert not result.identical
    # 前缀 10 + 后缀 6 = 16 匹配 / 总数 52 → 32/52
    expected = 32.0 / 52.0
    assert abs(result.similarity - expected) < 1e-9
    assert result.differences

