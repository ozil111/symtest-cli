import numpy as np
import h5py
import pytest

from symtest.file_comparator.factory import ComparatorFactory


def create_h5(tmp_path, name, datasets):
    """Create an H5 file with given dataset mapping."""
    path = tmp_path / name
    with h5py.File(path, "w") as f:
        for ds_path, payload in datasets.items():
            data = np.array(payload["data"])
            attrs = payload.get("attrs", {})
            parts = ds_path.split("/")
            group = f
            for part in parts[:-1]:
                group = group.require_group(part)
            ds = group.create_dataset(parts[-1], data=data)
            for key, value in attrs.items():
                ds.attrs[key] = value
    return path


def compare_h5(file1, file2, **kwargs):
    comparator = ComparatorFactory.create_comparator("h5", **kwargs)
    return comparator.compare_files(file1, file2)


def test_identical_files(tmp_path):
    file1 = create_h5(tmp_path, "a.h5", {"data": {"data": [1.0, 2.0, 3.0]}})
    file2 = create_h5(tmp_path, "b.h5", {"data": {"data": [1.0, 2.0, 3.0]}})

    result = compare_h5(file1, file2)
    assert result.identical
    assert result.differences == []


def test_tolerance_controls_difference(tmp_path):
    file1 = create_h5(tmp_path, "a.h5", {"data": {"data": [1.0]}})
    file2 = create_h5(tmp_path, "b.h5", {"data": {"data": [1.0 + 2e-5]}})

    tight = compare_h5(file1, file2, rtol=1e-5, atol=1e-8)
    assert not tight.identical

    loose = compare_h5(file1, file2, rtol=1e-4, atol=1e-6)
    assert loose.identical


def test_table_selection_and_regex(tmp_path):
    datasets = {
        "group1/data": {"data": [1, 2, 3]},
        "group2/data": {"data": [10, 20, 30]},
    }
    file1 = create_h5(tmp_path, "a.h5", datasets)
    # group2 differs
    file2 = create_h5(
        tmp_path,
        "b.h5",
        {"group1/data": {"data": [1, 2, 3]}, "group2/data": {"data": [10, 20, 31]}},
    )

    only_group1 = compare_h5(file1, file2, tables=["group1/data"])
    assert only_group1.identical  # diff in group2 ignored

    regex_group2 = compare_h5(file1, file2, table_regex="group2/data")
    assert not regex_group2.identical
    assert any("group2/data" in diff.position for diff in regex_group2.differences)


def test_expand_path_toggle(tmp_path):
    file1 = create_h5(tmp_path, "a.h5", {"parent/data": {"data": [1, 2, 3]}})
    file2 = create_h5(tmp_path, "b.h5", {"parent/data": {"data": [1, 2, 4]}})

    # Without expand_path, only the group metadata is compared
    no_expand = compare_h5(file1, file2, tables=["parent"], expand_path=False)
    assert no_expand.identical

    # With expand_path (default), dataset diff is detected
    with_expand = compare_h5(file1, file2, tables=["parent"])
    assert not with_expand.identical


@pytest.mark.parametrize(
    "data_filter,expected_identical",
    [
        (">100.0", True),   # filters out the differing 100.0 vs 100.1
        (">=100.0", False), # keeps the differing value
        ("abs>0.001", False),
    ],
)
def test_data_filter_behavior(tmp_path, data_filter, expected_identical):
    file1 = create_h5(tmp_path, "a.h5", {"demo": {"data": [0.0, 100.0, -0.002]}})
    file2 = create_h5(tmp_path, "b.h5", {"demo": {"data": [0.0, 100.1, 0.002]}})

    result = compare_h5(file1, file2, data_filter=data_filter)
    assert result.identical is expected_identical


def test_missing_table_reports_difference(tmp_path):
    file1 = create_h5(tmp_path, "a.h5", {"exists": {"data": [1, 2, 3]}})
    file2 = create_h5(tmp_path, "b.h5", {})  # table missing

    result = compare_h5(file1, file2, tables=["exists"])
    assert not result.identical
    assert any(diff.diff_type == "structure" for diff in result.differences)

