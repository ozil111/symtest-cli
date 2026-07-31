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

