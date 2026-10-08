"""Tests for the ``execution.outputs`` declared-artifact cleanup feature.

Covers:
- parsing (case-level + step-level ``outputs`` into TestCase/TestStep);
- wire-dict round-trip (``to_dict`` + ``_spec_from_v2``);
- pre-execution deletion (file / directory / missing file) on every attempt;
- loud failure on workspace escape and locked files;
- sequence semantics: case-level cleanup once on full runs, skipped on resume;
- resume config hash sensitivity to step ``outputs``;
- ``validate_config`` outputs checks (escape error, conflict warning).
"""
import os
import sys

import pytest

from symtest.config.config_io import validate_config
from symtest.core.config_loader import parse_test_cases
from symtest.core.execution.executor import clean_outputs
from symtest.core.orchestration.sequence import execute_sequence
from symtest.core.orchestration.single import execute_single_test_case
from symtest.core.process_worker import _spec_from_v2
from symtest.core.sequence_state import (
    compute_config_hash,
    save_sequence_state,
    save_step_output,
)
from symtest.core.test_case import ExecutionSpec, TestCase, TestStep


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestParseOutputs:
    def test_single_command_case_outputs(self):
        config = {
            "test_cases": [
                {
                    "name": "t",
                    "execution": {
                        "command": "solver",
                        "args": ["-i", "in.dat"],
                        "outputs": ["result.h5", "logs/solver.log"],
                    },
                    "expected": {"return_code": 0},
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].outputs == ["result.h5", "logs/solver.log"]

    def test_sequence_case_level_and_step_outputs(self):
        config = {
            "test_cases": [
                {
                    "name": "seq",
                    "execution": {
                        "outputs": ["final.h5"],
                        "steps": [
                            {
                                "command": "python",
                                "args": ["pre.py"],
                                "outputs": ["mesh.dat"],
                                "expected": {"return_code": 0},
                            },
                            {
                                "command": "python",
                                "args": ["solve.py"],
                                "expected": {"return_code": 0},
                            },
                        ],
                    },
                }
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].outputs == ["final.h5"]
        assert cases[0].steps[0].outputs == ["mesh.dat"]
        assert cases[0].steps[1].outputs == []

    def test_outputs_absent_defaults_to_empty(self):
        config = {
            "test_cases": [
                {
                    "name": "t",
                    "execution": {"command": "solver", "args": []},
                    "expected": {"return_code": 0},
                },
            ]
        }
        cases = parse_test_cases(config)
        assert cases[0].outputs == []


class TestWireRoundTrip:
    def test_to_dict_includes_outputs(self):
        case = TestCase(
            name="t", command="solver", args=["-i", "in.dat"],
            outputs=["result.h5"],
        )
        d = case.to_dict()
        assert d["execution"]["outputs"] == ["result.h5"]

    def test_to_dict_omits_empty_outputs(self):
        case = TestCase(name="t", command="solver", args=[])
        assert "outputs" not in case.to_dict()["execution"]

    def test_spec_from_v2_preserves_outputs(self):
        case = TestCase(
            name="seq",
            outputs=["final.h5"],
            steps=[
                TestStep.from_flat(
                    "python", ["pre.py"], {"return_code": 0}, outputs=["mesh.dat"],
                ),
                TestStep.from_flat("python", ["solve.py"], {"return_code": 0}),
            ],
        )
        spec = _spec_from_v2(case.to_dict())
        assert spec.outputs == ["final.h5"]
        assert spec.steps[0].outputs == ["mesh.dat"]
        assert spec.steps[1].outputs == []


# ---------------------------------------------------------------------------
# Execution-time cleanup
# ---------------------------------------------------------------------------

def _run(spec, workspace):
    return execute_single_test_case(
        spec, workspace, expectation={"return_code": 0},
    )


class TestCleanOutputsExecution:
    def test_stale_file_deleted_before_run(self, tmp_path):
        stale = tmp_path / "result.h5"
        stale.write_text("stale from previous run")
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=["result.h5"],
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "passed"
        assert not stale.exists()

    def test_stale_directory_deleted_before_run(self, tmp_path):
        outdir = tmp_path / "results"
        outdir.mkdir()
        (outdir / "old.txt").write_text("stale")
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=["results"],
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "passed"
        assert not outdir.exists()

    def test_missing_outputs_skipped_silently(self, tmp_path):
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=["never_existed.h5"],
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "passed"

    def test_no_outputs_is_zero_overhead(self, tmp_path):
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
        )
        assert _run(spec, str(tmp_path))["status"] == "passed"

    def test_relative_escape_is_loud_failure(self, tmp_path):
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=["../outside.txt"],
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "failed"
        assert result["failure_kind"] == "execution_error"
        assert "escapes workspace" in result["message"]

    def test_absolute_path_outside_workspace_is_loud_failure(self, tmp_path):
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=[str(tmp_path.parent / "elsewhere.txt")],
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "failed"
        assert "escapes workspace" in result["message"]

    def test_outputs_without_workspace_is_loud_failure(self, tmp_path):
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", "pass"],
            outputs=["result.h5"],
        )
        result = _run(spec, None)
        assert result["status"] == "failed"
        assert "no workspace" in result["message"]

    @pytest.mark.skipif(os.name != "nt",
                        reason="Windows-only: open handle blocks deletion")
    def test_locked_file_fails_loudly(self, tmp_path):
        locked = tmp_path / "locked.h5"
        locked.write_text("busy")
        with open(locked, "w"):
            spec = ExecutionSpec(
                name="t", command=sys.executable, args=["-c", "pass"],
                outputs=["locked.h5"],
            )
            result = _run(spec, str(tmp_path))
        assert result["status"] == "failed"
        assert result["failure_kind"] == "execution_error"
        assert "failed to delete" in result["message"]

    def test_retry_re_cleans_before_every_attempt(self, tmp_path):
        # Command appends one 'x' to out.txt then always fails; with
        # per-attempt cleanup the final file contains exactly one 'x'.
        script = (
            "open('out.txt','a').write('x'); "
            "import sys; sys.exit(1)"
        )
        spec = ExecutionSpec(
            name="t", command=sys.executable, args=["-c", script],
            outputs=["out.txt"], retry_count=1,
        )
        result = _run(spec, str(tmp_path))
        assert result["status"] == "failed"
        assert result["attempts"] == 2
        assert (tmp_path / "out.txt").read_text() == "x"


# ---------------------------------------------------------------------------
# Sequence semantics
# ---------------------------------------------------------------------------

class TestSequenceOutputs:
    def _steps(self, tmp_path, scripts):
        return [
            TestStep.from_flat(
                sys.executable, ["-c", script], {"return_code": 0},
                outputs=outputs,
            )
            for script, outputs in scripts
        ]

    def test_step_outputs_cleaned_before_step(self, tmp_path):
        stale = tmp_path / "mesh.dat"
        stale.write_text("stale")
        steps = self._steps(tmp_path, [
            ("pass", ["mesh.dat"]),
            ("pass", []),
        ])
        result = execute_sequence("seq", steps, str(tmp_path))
        assert result["status"] == "passed"
        assert not stale.exists()

    def test_case_level_outputs_cleaned_once_on_full_run(self, tmp_path):
        case_file = tmp_path / "final.h5"
        case_file.write_text("stale")
        steps = self._steps(tmp_path, [("pass", []), ("pass", [])])
        result = execute_sequence(
            "seq", steps, str(tmp_path), case_outputs=["final.h5"],
        )
        assert result["status"] == "passed"
        assert not case_file.exists()

    def test_case_level_cleanup_failure_fails_case(self, tmp_path):
        steps = self._steps(tmp_path, [("pass", [])])
        result = execute_sequence(
            "seq", steps, str(tmp_path), case_outputs=["../escape.txt"],
        )
        assert result["status"] == "failed"
        assert result["failure_kind"] == "execution_error"
        assert result["step_results"] == []

    def test_resume_skips_case_level_cleanup(self, tmp_path):
        case_file = tmp_path / "final.h5"
        case_file.write_text("produced by skipped step")
        steps = self._steps(tmp_path, [("pass", []), ("pass", [])])
        config_hash = compute_config_hash(steps, None, None)
        state = {"case": "seq", "config_hash": config_hash, "steps": {}}
        state["steps"]["1"] = {"status": "passed", "duration": 0.1}
        save_sequence_state(str(tmp_path), "seq", state)
        save_step_output(str(tmp_path), "seq", 1, "step1 output\n")

        result = execute_sequence(
            "seq", steps, str(tmp_path),
            case_outputs=["final.h5"], resume=True,
        )
        assert result["status"] == "passed"
        assert case_file.exists(), (
            "case-level outputs must not be cleaned on a resumed run"
        )

    def test_resume_does_not_clean_skipped_step_outputs(self, tmp_path):
        mesh = tmp_path / "mesh.dat"
        mesh.write_text("produced by step 1")
        steps = self._steps(tmp_path, [("pass", ["mesh.dat"]), ("pass", [])])
        config_hash = compute_config_hash(steps, None, None)
        state = {"case": "seq", "config_hash": config_hash, "steps": {}}
        state["steps"]["1"] = {"status": "passed", "duration": 0.1}
        save_sequence_state(str(tmp_path), "seq", state)
        save_step_output(str(tmp_path), "seq", 1, "step1 output\n")

        result = execute_sequence("seq", steps, str(tmp_path), resume=True)
        assert result["status"] == "passed"
        assert mesh.exists()


# ---------------------------------------------------------------------------
# Resume hash sensitivity
# ---------------------------------------------------------------------------

def test_config_hash_changes_with_step_outputs():
    steps_a = [TestStep.from_flat("python", ["a.py"], {"return_code": 0})]
    steps_b = [TestStep.from_flat(
        "python", ["a.py"], {"return_code": 0}, outputs=["out.dat"],
    )]
    assert compute_config_hash(steps_a) != compute_config_hash(steps_b)


# ---------------------------------------------------------------------------
# validate_config checks
# ---------------------------------------------------------------------------

class TestValidateOutputs:
    def _write_config(self, tmp_path, cases):
        import json
        cfg = tmp_path / "cases.json"
        cfg.write_text(json.dumps({"test_cases": cases}), encoding="utf-8")
        return cfg

    def test_workspace_escape_is_error(self, tmp_path):
        cfg = self._write_config(tmp_path, [{
            "name": "t",
            "execution": {"command": "solver", "args": [], "outputs": ["../x.txt"]},
            "expected": {"return_code": 0},
        }])
        report = validate_config(cfg, workspace=str(tmp_path))
        assert not report["valid"]
        assert any("escapes workspace" in e for e in report["errors"])

    def test_bad_outputs_type_is_error(self, tmp_path):
        cfg = self._write_config(tmp_path, [{
            "name": "t",
            "execution": {"command": "solver", "args": [], "outputs": "result.h5"},
            "expected": {"return_code": 0},
        }])
        report = validate_config(cfg, workspace=str(tmp_path))
        assert not report["valid"]
        assert any("array of strings" in e for e in report["errors"])

    def test_duplicate_outputs_without_depends_on_warns(self, tmp_path):
        cfg = self._write_config(tmp_path, [
            {
                "name": "A",
                "execution": {"command": "solver", "args": [], "outputs": ["out.h5"]},
                "expected": {"return_code": 0},
            },
            {
                "name": "B",
                "execution": {"command": "solver", "args": [], "outputs": ["out.h5"]},
                "expected": {"return_code": 0},
            },
        ])
        report = validate_config(cfg, workspace=str(tmp_path))
        assert report["valid"]
        assert any("out.h5" in w and "A" in w and "B" in w
                   for w in report["warnings"])

    def test_duplicate_outputs_with_depends_on_no_warning(self, tmp_path):
        # B depends on A: shared artifact ownership is legitimate.
        cfg = self._write_config(tmp_path, [
            {
                "name": "A",
                "execution": {"command": "solver", "args": [], "outputs": ["out.h5"]},
                "expected": {"return_code": 0},
            },
            {
                "name": "B",
                "execution": {"command": "solver", "args": [], "outputs": ["out.h5"]},
                "scheduling": {"depends_on": ["A"]},
                "expected": {"return_code": 0},
            },
        ])
        report = validate_config(cfg, workspace=str(tmp_path))
        assert report["valid"]
        assert not any("out.h5" in w for w in report["warnings"])

    def test_placeholder_outputs_skipped(self, tmp_path):
        cfg = self._write_config(tmp_path, [{
            "name": "t",
            "execution": {"command": "solver", "args": [],
                          "outputs": ["{output_dir}/result.h5"]},
            "expected": {"return_code": 0},
        }])
        report = validate_config(cfg, workspace=str(tmp_path))
        assert report["valid"]


# ---------------------------------------------------------------------------
# clean_outputs unit-level contract
# ---------------------------------------------------------------------------

class TestCleanOutputsHelper:
    def test_empty_outputs_returns_none(self, tmp_path):
        assert clean_outputs([], str(tmp_path)) is None
        assert clean_outputs(None, str(tmp_path)) is None

    def test_no_workspace_with_outputs_returns_error(self, tmp_path):
        err = clean_outputs(["a.txt"], None)
        assert err is not None and "no workspace" in err

    def test_nested_relative_path_within_workspace(self, tmp_path):
        target = tmp_path / "sub" / "out.txt"
        target.parent.mkdir()
        target.write_text("stale")
        err = clean_outputs(["sub/out.txt"], str(tmp_path))
        assert err is None
        assert not target.exists()
