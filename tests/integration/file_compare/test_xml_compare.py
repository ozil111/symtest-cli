from symtest.file_comparator.factory import ComparatorFactory


def compare_xml(file1, file2):
    comparator = ComparatorFactory.create_comparator("xml")
    return comparator.compare_files(file1, file2)


def test_xml_identical_structure(tmp_path):
    file1 = tmp_path / "a.xml"
    file2 = tmp_path / "b.xml"
    content = "<root><item id='1'>Ada</item></root>"
    file1.write_text(content, encoding="utf-8")
    file2.write_text(content, encoding="utf-8")

    result = compare_xml(file1, file2)

    assert result.identical
    assert result.differences == []


def test_xml_text_difference(tmp_path):
    file1 = tmp_path / "a.xml"
    file2 = tmp_path / "b.xml"
    file1.write_text("<root><item>Ada</item></root>", encoding="utf-8")
    file2.write_text("<root><item>Grace</item></root>", encoding="utf-8")

    result = compare_xml(file1, file2)

    assert not result.identical
    diff = result.differences[0]
    assert diff.diff_type == "text_mismatch"
    assert diff.position == "/item[0]"


def test_xml_attribute_difference(tmp_path):
    file1 = tmp_path / "a.xml"
    file2 = tmp_path / "b.xml"
    file1.write_text("<root><item id='1'/></root>", encoding="utf-8")
    file2.write_text("<root><item id='2'/></root>", encoding="utf-8")

    result = compare_xml(file1, file2)

    assert not result.identical
    diff_types = {diff.diff_type for diff in result.differences}
    assert "missing_attribute" in diff_types
    assert "extra_attribute" in diff_types


def test_xml_child_count_difference(tmp_path):
    file1 = tmp_path / "a.xml"
    file2 = tmp_path / "b.xml"
    file1.write_text("<root><item/><item/></root>", encoding="utf-8")
    file2.write_text("<root><item/></root>", encoding="utf-8")

    result = compare_xml(file1, file2)

    assert not result.identical
    assert result.differences[0].diff_type == "children_count_mismatch"


def test_xml_invalid_file_sets_error(tmp_path):
    file1 = tmp_path / "a.xml"
    file2 = tmp_path / "b.xml"
    file1.write_text("<root>", encoding="utf-8")
    file2.write_text("<root/>", encoding="utf-8")

    result = compare_xml(file1, file2)

    assert not result.identical
    assert "Invalid XML" in result.error

