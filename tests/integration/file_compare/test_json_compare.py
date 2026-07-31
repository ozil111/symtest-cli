from symtest.file_comparator.factory import ComparatorFactory


def compare_json(file1, file2, **kwargs):
    comparator = ComparatorFactory.create_comparator("json", **kwargs)
    return comparator.compare_files(file1, file2)


def test_json_exact_match(tmp_path):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text('{"a": 1, "b": [1,2]}', encoding="utf-8")
    f2.write_text('{"a": 1, "b": [1,2]}', encoding="utf-8")

    result = compare_json(f1, f2)
    assert result.identical


def test_json_value_difference(tmp_path):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text('{"a": 1, "b": [1,2]}', encoding="utf-8")
    f2.write_text('{"a": 2, "b": [1,2]}', encoding="utf-8")

    result = compare_json(f1, f2)
    assert not result.identical
    assert result.differences


def test_json_key_based_ignores_order(tmp_path):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text('[{"id":1,"v":"a"},{"id":2,"v":"b"}]', encoding="utf-8")
    f2.write_text('[{"id":2,"v":"b"},{"id":1,"v":"a"}]', encoding="utf-8")

    result = compare_json(f1, f2, compare_mode="key-based", key_field="id")
    assert result.identical


def test_json_key_missing_detected(tmp_path):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text('[{"id":1,"v":"a"}]', encoding="utf-8")
    f2.write_text('[{"id":1,"v":"b"},{"id":2,"v":"c"}]', encoding="utf-8")

    result = compare_json(f1, f2, compare_mode="key-based", key_field="id")
    assert not result.identical

