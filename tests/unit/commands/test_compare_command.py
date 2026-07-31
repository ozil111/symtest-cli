import json

import pytest

from symtest.commands import compare


def test_detect_file_type_uses_specific_comparators():
    assert compare.detect_file_type("data.json") == "json"
    assert compare.detect_file_type("data.xml") == "xml"
    assert compare.detect_file_type("data.csv") == "csv"
    assert compare.detect_file_type("data.h5") == "h5"
    assert compare.detect_file_type("data.txt") == "text"
    assert compare.detect_file_type("data.bin") == "binary"


def run_compare(monkeypatch, args):
    monkeypatch.setattr("sys.argv", ["compare", *args])
    with pytest.raises(SystemExit) as exc:
        compare.main()
    return exc.value.code


def test_compare_main_auto_detects_json_and_returns_success(tmp_path, monkeypatch, capsys):
    file1 = tmp_path / "a.json"
    file2 = tmp_path / "b.json"
    file1.write_text('{"a": 1, "b": [1, 2]}', encoding="utf-8")
    file2.write_text('{\n  "b": [1, 2],\n  "a": 1\n}', encoding="utf-8")

    exit_code = run_compare(monkeypatch, [str(file1), str(file2)])

    assert exit_code == 0
    assert "Files are identical" in capsys.readouterr().out


def test_compare_main_returns_nonzero_for_differences(tmp_path, monkeypatch, capsys):
    file1 = tmp_path / "a.txt"
    file2 = tmp_path / "b.txt"
    file1.write_text("same\n", encoding="utf-8")
    file2.write_text("different\n", encoding="utf-8")

    exit_code = run_compare(monkeypatch, [str(file1), str(file2), "--file-type", "text"])

    assert exit_code == 1
    assert "Files are different" in capsys.readouterr().out


def test_compare_main_json_output_is_machine_readable(tmp_path, monkeypatch, capsys):
    file1 = tmp_path / "a.csv"
    file2 = tmp_path / "b.csv"
    file1.write_text("id,name\n1,Ada\n", encoding="utf-8")
    file2.write_text("id,name\n1,Ada\n", encoding="utf-8")

    exit_code = run_compare(
        monkeypatch,
        [str(file1), str(file2), "--file-type", "csv", "--output-format", "json"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["identical"] is True
    assert payload["differences"] == []


def test_compare_main_missing_file_exits_nonzero(tmp_path, monkeypatch):
    existing = tmp_path / "exists.txt"
    existing.write_text("x", encoding="utf-8")
    missing = tmp_path / "missing.txt"

    exit_code = run_compare(monkeypatch, [str(existing), str(missing)])

    assert exit_code == 1

