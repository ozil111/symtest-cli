"""Phase 1 unit tests for the TestCase v2 layered model.

Covers: 分层构造（metadata + Execution/Expectation/Scheduling Spec）、
平铺关键字参数归一、属性直通访问器、单命令归一为单元素 steps、
Spec 边界（execution 不携带 expected）、to_dict / to_execution_dict 形态。
"""
import copy

import pytest

from symtest.core.test_case import (
    ExecutionSpec,
    ExpectationSpec,
    SchedulingSpec,
    TestCase,
    TestCaseStep,
)


# ---------------------------------------------------------------------------
# 分层构造
# ---------------------------------------------------------------------------

class TestLayeredConstruction:
    def test_flat_kwargs_normalized_into_specs(self):
        """v1 平铺关键字参数被归一存入子 Spec。"""
        tc = TestCase(
            name="beam",
            command="solver",
            args=["model.inp"],
            expected={"return_code": 0},
            timeout=3600,
            retry_count=2,
            env={"OMP_NUM_THREADS": "4"},
            tags=["regression"],
            depends_on=["preprocess"],
            resources={"cpu_cores": 4},
            expected_failure=True,
            xfail_reason="known bug",
        )
        assert tc.execution == ExecutionSpec(
            name="beam",
            command="solver",
            args=["model.inp"],
            timeout=3600,
            retry_count=2,
            env={"OMP_NUM_THREADS": "4"},
            steps=None,
        )
        assert tc.expectation.assertions == {"return_code": 0}
        assert tc.scheduling == SchedulingSpec(
            depends_on=["preprocess"], resources={"cpu_cores": 4},
        )
        assert tc.tags == ["regression"]
        assert tc.expected_failure is True
        assert tc.xfail_reason == "known bug"

    def test_defaults_are_empty_not_none(self):
        tc = TestCase(name="t")
        assert tc.execution.args == []
        assert tc.execution.env == {}
        assert tc.execution.steps is None
        assert tc.expectation.assertions == {}
        assert tc.scheduling.depends_on == []
        assert tc.scheduling.resources is None

    def test_explicit_specs_take_precedence(self):
        """显式传入子 Spec 时平铺参数被忽略。"""
        spec = ExecutionSpec(command="explicit")
        tc = TestCase(name="t", command="ignored", execution=spec)
        assert tc.execution is spec
        assert tc.command == "explicit"

    def test_sequence_mode(self):
        steps = [
            TestCaseStep(command="a", args=[], expected={"return_code": 0}),
            TestCaseStep(command="b", args=[], expected={}),
        ]
        tc = TestCase(name="seq", steps=steps)
        assert tc.execution.steps is steps
        assert tc.is_single_command is False
        assert tc.all_steps is steps


# ---------------------------------------------------------------------------
# 属性直通访问器（case.xxx 零改动兼容面）
# ---------------------------------------------------------------------------

class TestPassthroughAccessors:
    def _tc(self):
        return TestCase(
            name="t",
            command="echo",
            args=["hi"],
            expected={"return_code": 0},
            timeout=10,
            retry_count=1,
            env={"K": "V"},
            depends_on=["a"],
            resources={"cpu_cores": 2},
        )

    def test_execution_passthrough_read(self):
        tc = self._tc()
        assert tc.command == "echo"
        assert tc.args == ["hi"]
        assert tc.timeout == 10
        assert tc.retry_count == 1
        assert tc.env == {"K": "V"}

    def test_execution_passthrough_write(self):
        tc = self._tc()
        tc.command = "ls"
        tc.args = ["-l"]
        tc.timeout = 5
        tc.retry_count = 3
        tc.env = {"A": "B"}
        tc.steps = [TestCaseStep(command="s", args=[], expected={})]
        assert tc.execution.command == "ls"
        assert tc.execution.args == ["-l"]
        assert tc.execution.timeout == 5
        assert tc.execution.retry_count == 3
        assert tc.execution.env == {"A": "B"}
        assert len(tc.execution.steps) == 1

    def test_expected_passthrough(self):
        tc = self._tc()
        assert tc.expected == {"return_code": 0}
        tc.expected = {"output_contains": ["x"]}
        assert tc.expectation.assertions == {"output_contains": ["x"]}
        tc.expected = {}
        assert tc.expectation.assertions == {}

    def test_scheduling_passthrough(self):
        tc = self._tc()
        assert tc.depends_on == ["a"]
        assert tc.resources == {"cpu_cores": 2}
        tc.depends_on = ["b"]
        tc.resources = {}
        assert tc.scheduling.depends_on == ["b"]
        assert tc.scheduling.resources == {}
        # parallel runner 依赖对 resources 的就地赋值
        tc.resources["cpu_cores"] = 1
        assert tc.scheduling.resources == {"cpu_cores": 1}
        tc.resources = None
        assert tc.scheduling.resources is None

    def test_mutation_visible_through_both_views(self):
        """直通属性与子 Spec 是同一数据（非拷贝）。"""
        tc = self._tc()
        tc.execution.command = "mutated"
        assert tc.command == "mutated"
        tc.expectation.assertions["return_code"] = 7
        assert tc.expected == {"return_code": 7}


# ---------------------------------------------------------------------------
# 单命令归一为单元素 steps
# ---------------------------------------------------------------------------

class TestUnifiedSteps:
    def test_single_command_all_steps_single_element(self):
        tc = TestCase(
            name="t",
            command="echo",
            args=["ok"],
            expected={"return_code": 0},
            timeout=30,
            retry_count=2,
        )
        steps = tc.all_steps
        assert len(steps) == 1
        assert steps[0].command == "echo"
        assert steps[0].args == ["ok"]
        assert steps[0].expected == {"return_code": 0}
        assert steps[0].timeout == 30
        assert steps[0].retry_count == 2

    def test_is_single_command_true_for_flat_case(self):
        assert TestCase(name="t", command="echo").is_single_command is True

    def test_sequence_all_steps_returns_steps_list(self):
        steps = [TestCaseStep(command="s", args=[], expected={})]
        tc = TestCase(name="t", steps=steps)
        assert tc.all_steps == steps


# ---------------------------------------------------------------------------
# Spec 边界：ExecutionSpec 不携带判定语义
# ---------------------------------------------------------------------------

class TestSpecBoundaries:
    def test_execution_spec_has_no_expected_field(self):
        spec = ExecutionSpec()
        assert not hasattr(spec, "expected")
        assert not hasattr(spec, "assertions")

    def test_step_carries_its_own_expected(self):
        """steps 是"执行+判定"原子对，step 级 expected 属于 step。"""
        step = TestCaseStep(command="a", args=[], expected={"return_code": 0})
        spec = ExecutionSpec(steps=[step])
        assert spec.steps[0].expected == {"return_code": 0}


# ---------------------------------------------------------------------------
# 序列化形态
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_single_mode(self):
        tc = TestCase(
            name="t",
            command="echo",
            args=["ok"],
            expected={"return_code": 0},
            env={"A": "1"},
            tags=["x"],
        )
        assert tc.to_dict() == {
            "name": "t",
            "command": "echo",
            "args": ["ok"],
            "expected": {"return_code": 0},
            "timeout": None,
            "resources": None,
            "tags": ["x"],
            "retry_count": 0,
            "env": {"A": "1"},
        }

    def test_to_dict_sequence_mode_keeps_steps(self):
        tc = TestCase(
            name="seq",
            steps=[
                TestCaseStep(command="a", args=["1"], expected={}, timeout=5.0),
            ],
        )
        assert tc.to_dict()["steps"] == [
            {"command": "a", "args": ["1"], "expected": {},
             "timeout": 5.0, "retry_count": 0},
        ]

    def test_to_execution_dict_bridge_removed(self):
        """1.4 已删除 to_execution_dict 桥接：由 ExecutionSpec 直供编排层。"""
        tc = TestCase(name="t", command="echo")
        assert not hasattr(tc, "to_execution_dict")

    def test_deepcopy_works(self):
        """TUI duplicate_case 依赖 deepcopy。"""
        tc = TestCase(
            name="t",
            steps=[TestCaseStep(command="a", args=[], expected={})],
        )
        clone = copy.deepcopy(tc)
        clone.name = "clone"
        clone.steps[0].command = "b"
        assert tc.name == "t"
        assert tc.steps[0].command == "a"


# ---------------------------------------------------------------------------
# TestCase 是声明：不提供任何执行入口（原则 1）
# ---------------------------------------------------------------------------

class TestDeclarationOnly:
    @pytest.mark.parametrize(
        "method",
        ["run", "validate", "update_baseline", "execute"],
    )
    def test_no_execution_methods(self, method):
        assert not hasattr(TestCase, method)
