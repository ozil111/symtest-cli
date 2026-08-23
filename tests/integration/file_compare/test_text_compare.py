from symtest.file_comparator.factory import ComparatorFactory


def compare_text(file1, file2, **kwargs):
    comparator = ComparatorFactory.create_comparator("text", **kwargs)
    return comparator.compare_files(file1, file2, **kwargs)


def test_text_identical(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("line1\nline2\n", encoding="utf-8")
    f2.write_text("line1\nline2\n", encoding="utf-8")

    result = compare_text(f1, f2)
    assert result.identical
    assert result.differences == []


def test_text_difference_detected(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("line1\nline2\n", encoding="utf-8")
    f2.write_text("line1\nLINE2\n", encoding="utf-8")

    result = compare_text(f1, f2)
    assert not result.identical
    assert result.differences


def test_text_range_limits_scope(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("keep\nsame\nDIFF\n", encoding="utf-8")
    f2.write_text("keep\nsame\ndiff\n", encoding="utf-8")

    # Only compare first two lines; third-line diff ignored
    result = compare_text(f1, f2, start_line=0, end_line=1)
    assert result.identical


def test_start_line_offset_in_difference_positions(tmp_path):
    """Line numbers in differences should reflect original file positions,
    not positions within the sliced content."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    # 3 header lines, then 3 data lines — only compare from line 3 (0-based)
    f1.write_text("# header 1\n# header 2\n# header 3\n"
                  "data_a\nsame_data\ndata_c\n", encoding="utf-8")
    f2.write_text("# header 1\n# header 2\n# header 3\n"
                  "data_x\nsame_data\ndata_z\n", encoding="utf-8")

    result = compare_text(f1, f2, start_line=3)

    assert not result.identical
    assert len(result.differences) == 2

    # Differences should report original file line numbers (1-based in position string)
    positions = {d.position for d in result.differences}
    assert positions == {"line 4", "line 6"}, (
        f"Expected positions {{'line 4', 'line 6'}} (original file lines), "
        f"got {positions}"
    )


def test_start_line_offset_no_offset_same_as_default(tmp_path):
    """With start_line=0, line numbers should match the actual file lines."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("line1\nDIFFERENT\n", encoding="utf-8")
    f2.write_text("line1\ndifferent\n", encoding="utf-8")

    result = compare_text(f1, f2, start_line=0)

    assert not result.identical
    assert len(result.differences) == 1
    assert result.differences[0].position == "line 2"


def test_expected_actual_not_swapped(tmp_path):
    """expected should contain baseline (file2) content,
    actual should contain actual (file1) content."""
    f1 = tmp_path / "actual.txt"
    f2 = tmp_path / "baseline.txt"
    f1.write_text("actual_value\n", encoding="utf-8")
    f2.write_text("baseline_value\n", encoding="utf-8")

    result = compare_text(f1, f2)

    assert not result.identical
    assert len(result.differences) == 1
    diff = result.differences[0]
    assert diff.expected == "baseline_value\n", (
        f"expected should be baseline content, got {diff.expected!r}"
    )
    assert diff.actual == "actual_value\n", (
        f"actual should be actual content, got {diff.actual!r}"
    )
    assert diff.diff_type == "content"


def test_large_batch_diff_no_false_missing(tmp_path):
    """When many consecutive lines differ, every difference should be
    'content' type — not 'missing' due to lookahead window limitation."""
    f1 = tmp_path / "actual.txt"
    f2 = tmp_path / "baseline.txt"
    lines1 = [f"0.0  {i:15.7e}  0.0  0.0\n" for i in range(100)]
    lines2 = [f"0.0  {i+0.5:15.7e}  0.0  0.0\n" for i in range(100)]
    f1.write_text("".join(lines1), encoding="utf-8")
    f2.write_text("".join(lines2), encoding="utf-8")

    result = compare_text(f1, f2)

    assert not result.identical
    # All differences should be "content" type, never "missing"
    for d in result.differences:
        assert d.diff_type == "content", (
            f"Unexpected diff_type '{d.diff_type}' at {d.position}: "
            f"expected={d.expected!r}, actual={d.actual!r}"
        )
        assert d.actual is not None, (
            f"actual should not be None for content diff at {d.position}"
        )

