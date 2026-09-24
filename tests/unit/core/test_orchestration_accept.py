"""Unit tests for the orchestration accept step (``--update-baseline``).

原则 3：Validator 永远只读；baseline 覆盖由编排层 accept 步骤执行。
行为与 1.3 ``Assertions.compare_files(update_baseline=True)`` 逐位保持。
"""
import os
import tempfile

import pytest

from symtest.core.execution.result import ExecutionResult
from symtest.core.orchestration.accept import apply_baseline_accept
from symtest.core.orchestration.single import execute_single_test_case
from symtest.core.test_case import ExecutionSpec
from symtest.core.validation.validator import validate_result
from symtest.reporting.diagnosis import (
    attach_next_action_hint,
    build_next_action_hint,
)


def _exec(output="", return_code=0, name="t"):
    return ExecutionResult(name=name, command="cmd", output=output, return_code=return_code)


def _write(tmpdir, name, content):
    p = os.path.join(tmpdir, name)
    with open(p, "w") as f:
        f.write(content)
    return p


# ---------------------------------------------------------------------------
# accept helper
# ---------------------------------------------------------------------------

class TestApplyBaselineAccept:
    def test_accepts_mismatch_and_copies_file(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "actual.txt", "new\n")
            _write(d, "baseline.txt", "old\n")
            expected = {"compare_files": [
                {"actual": "actual.txt", "baseline": "baseline.txt", "type": "text"},
            ]}
            vr = validate_result(expected, _exec(), workspace=d)
            assert vr.passed is False and vr.failure_kind == "file_compare"

            rebuilt = apply_baseline_accept(vr, workspace=d)
            assert rebuilt is not None
            entry = rebuilt[0]
            assert entry == {
                "assertion": "compare_files",
                "passed": True,
                "error_stats": None,
                "compare_failures": [],
                "baseline_updated": ["baseline.txt"],
                "message": "",
            }
            with open(os.path.join(d, "baseline.txt")) as f:
                assert f.read() == "new\n"

    def test_accept_copies_into_existing_subdir(self):
        """baseline 位于尚有父目录的相对路径 → 解析后复制成功。"""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "gold"))
            _write(d, "actual.txt", "new\n")
            _write(os.path.join(d, "gold"), "baseline.txt", "old\n")
            expected = {"compare_files": [
                {"actual": "actual.txt", "baseline": "gold/baseline.txt", "type": "text"},
            ]}
            vr = validate_result(expected, _exec(), workspace=d)
            rebuilt = apply_baseline_accept(vr, workspace=d)
            assert rebuilt is not None
            with open(os.path.join(d, "gold", "baseline.txt")) as f:
                assert f.read() == "new\n"

    def test_rejects_comparator_error(self):
        """比较器错误（如 actual 缺失）不可接受 → 返回 None（investigate）。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "baseline.txt", "old\n")
            expected = {"compare_files": [
                {"actual": "missing.txt", "baseline": "baseline.txt", "type": "text"},
            ]}
            vr = validate_result(expected, _exec(), workspace=d)
            assert vr.passed is False
            assert apply_baseline_accept(vr, workspace=d) is None

    def test_mixed_entries_partial_copy_then_reject(self):
        """多 compare_files 规格时：可接受的条目已复制，整体仍返回 None。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a1.txt", "x1\n")
            _write(d, "b1.txt", "old1\n")
            _write(d, "b2.txt", "old2\n")
            expected = {"compare_files": [
                {"actual": "a1.txt", "baseline": "b1.txt", "type": "text"},
                {"actual": "missing2.txt", "baseline": "b2.txt", "type": "text"},
            ]}
            vr = validate_result(expected, _exec(), workspace=d)
            assert apply_baseline_accept(vr, workspace=d) is None
            # 第一条已复制（与 1.3 部分复制行为一致）
            with open(os.path.join(d, "b1.txt")) as f:
                assert f.read() == "x1\n"

    def test_accept_failure_keeps_investigate_hint_semantics(self):
        """accept 失败 → update_baseline=True 的 hint 语义为 investigate。"""
        hint = build_next_action_hint("file_compare", update_baseline=True)
        assert hint["action"] == "investigate"


# ---------------------------------------------------------------------------
# 编排层端到端：execute → validate → accept
# ---------------------------------------------------------------------------

class TestExecuteSingleWithBaselineAccept:
    def _case(self, name, command, args):
        spec = ExecutionSpec(name=name, command=command, args=args)
        expectation = {
            "return_code": 0,
            "compare_files": [
                {"actual": "actual.txt", "baseline": "baseline.txt", "type": "text"},
            ],
        }
        return spec, expectation

    def test_update_baseline_flips_verdict_to_passed(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            _write(d, "baseline.txt", "old\n")
            gen = (
                "import pathlib\n"
                "pathlib.Path('actual.txt').write_text('new')\n"
            )
            case = self._case("ub", sys.executable, ["-c", gen])
            result = execute_single_test_case(
                case[0], workspace=d, expectation=case[1], update_baseline=True,
            )

            assert result["status"] == "passed"
            assert result["message"] == ""
            assert result["failure_kind"] is None
            assert result["next_action_hint"] is None
            # 1.3 行为逐位保持：result["baseline_updated"] 在成功路径保持空列表
            assert result["baseline_updated"] == []
            # 断言明细携带 baseline_updated（与 1.3 一致）
            cf = [ar for ar in result["assertion_results"]
                  if ar["assertion"] == "compare_files"][0]
            assert cf["passed"] is True
            assert cf["baseline_updated"] == ["baseline.txt"]
            with open(os.path.join(d, "baseline.txt")) as f:
                # text 比较器语义：内容比较会去掉尾部换行
                assert f.read().rstrip("\n") == "new"

    def test_without_update_baseline_fails(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            _write(d, "baseline.txt", "old\n")
            gen = (
                "import pathlib\n"
                "pathlib.Path('actual.txt').write_text('new')\n"
            )
            case = self._case("ub", sys.executable, ["-c", gen])
            result = execute_single_test_case(
                case[0], workspace=d, expectation=case[1],
            )

            assert result["status"] == "failed"
            assert result["failure_kind"] == "file_compare"
            # Orchestration 只产 failure_kind；hint 由 reporting 装配点填充
            assert result["next_action_hint"] is None
            assert attach_next_action_hint(result)["action"] == "update_baseline"
            with open(os.path.join(d, "baseline.txt")) as f:
                assert f.read() == "old\n"

    def test_comparator_error_stays_failed_even_with_update_baseline(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            _write(d, "baseline.txt", "old\n")
            # 命令成功但缺少 compare_files 的 actual 文件 → 比较器错误
            spec, expectation = self._case("ub", sys.executable, ["-c", "pass"])
            expectation["compare_files"][0]["actual"] = "missing.txt"
            result = execute_single_test_case(
                spec, workspace=d, expectation=expectation, update_baseline=True,
            )

            assert result["status"] == "failed"
            assert result["next_action_hint"] is None
            assert attach_next_action_hint(
                result, update_baseline=True,
            )["action"] == "investigate"
            with open(os.path.join(d, "baseline.txt")) as f:
                assert f.read() == "old\n"
