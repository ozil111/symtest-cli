from cli_test_framework.core.sequence_state import (
    compute_config_hash,
    delete_sequence_state,
    load_sequence_state,
    load_step_output,
    save_sequence_state,
    save_step_output,
)
from cli_test_framework.core.test_case import TestCaseStep


def test_config_hash_is_stable_for_mapping_key_order():
    steps_a = [
        {
            "command": "solver",
            "args": ["--input", "model.dat"],
            "expected": {"return_code": 0, "output_contains": ["done"]},
        }
    ]
    steps_b = [
        {
            "expected": {"output_contains": ["done"], "return_code": 0},
            "args": ["--input", "model.dat"],
            "command": "solver",
        }
    ]

    assert compute_config_hash(steps_a) == compute_config_hash(steps_b)


def test_config_hash_preserves_argument_order():
    first = [{"command": "tool", "args": ["input.dat", "--verbose"]}]
    second = [{"command": "tool", "args": ["--verbose", "input.dat"]}]

    assert compute_config_hash(first) != compute_config_hash(second)


def test_config_hash_covers_step_controls_and_case_expected():
    step = TestCaseStep(
        command="solver",
        args=["model.dat"],
        expected={"return_code": 0},
        timeout=10,
        retry_count=1,
    )
    changed_timeout = TestCaseStep(
        command="solver",
        args=["model.dat"],
        expected={"return_code": 0},
        timeout=20,
        retry_count=1,
    )

    base = compute_config_hash([step], {"compare_files": []})
    assert base != compute_config_hash([changed_timeout], {"compare_files": []})
    assert base != compute_config_hash([step], {"return_code": 0})


def test_sequence_state_round_trip_and_corruption(tmp_path, caplog):
    state = {"config_hash": "abc", "passed_steps": [1], "label": "已通过"}
    save_sequence_state(str(tmp_path), "case_a", state)

    assert load_sequence_state(str(tmp_path), "case_a") == state
    state_path = tmp_path / ".cli-test" / "sequence_state" / "case_a.json"
    state_path.write_text("{broken", encoding="utf-8")

    assert load_sequence_state(str(tmp_path), "case_a") is None
    assert "Corrupted sequence state" in caplog.text


def test_step_output_round_trip_and_delete(tmp_path):
    workspace = str(tmp_path)
    save_sequence_state(workspace, "case_a", {"passed_steps": [1, 2]})
    save_step_output(workspace, "case_a", 1, "first\n")
    save_step_output(workspace, "case_a", 2, "第二步\n")

    assert load_step_output(workspace, "case_a", 1) == "first\n"
    assert load_step_output(workspace, "case_a", 2) == "第二步\n"
    assert load_step_output(workspace, "case_a", 3) is None

    delete_sequence_state(workspace, "case_a")

    assert load_sequence_state(workspace, "case_a") is None
    assert load_step_output(workspace, "case_a", 1) is None
    assert load_step_output(workspace, "case_a", 2) is None
