"""TestCase v2 分层数据模型（1.4 Core Model Refactoring, Phase 1）。

架构宪法（docs/design.md §10）：
- TestCase 是声明，不执行任何事情 —— 只有数据与访问器，没有 run/validate。
- 语义分三层：``execution``（执行什么）、``expectation``（如何判定）、
  ``scheduling``（何时/以何资源执行）；``name/description/tags/xfail_*``
  等保留为顶层 metadata，避免 DSL 啰嗦。

兼容性说明（Phase 3 Schema v2 落地前的过渡形态）：
- 构造函数保留 v1 平铺关键字参数（``command/args/expected/timeout/steps/
  retry_count/env/depends_on/resources``），内部归一存入子 Spec；
- ``case.command`` / ``case.expected`` / ``case.env`` ... 等属性直通访问器
  映射到子 Spec，使现有 ``case.xxx`` 访问点零改动；
- ``to_execution_dict()`` 是 runner→executor 的旧桥接，将在 Phase 2
  调用点改净后删除。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TestCaseStep:
    """A single step within a sequence test case."""
    __test__ = False
    command: str
    args: List[str]
    expected: Dict[str, Any]
    timeout: Optional[float] = None
    retry_count: int = 0


@dataclass
class ExecutionSpec:
    """执行语义：一个执行单元（case 或 step）要执行什么。

    纯数据，不包含任何判定语义（expected 属于 ExpectationSpec）。
    ``steps`` 非 None 表示 sequence 模式（steps 为原子"执行+判定"对列表）；
    为 None 表示单命令模式，由 ``command/args/timeout/retry_count`` 描述。
    """
    __test__ = False
    name: str = ""
    command: str = ""
    args: List[str] = field(default_factory=list)
    timeout: Optional[float] = None
    retry_count: int = 0
    env: Dict[str, str] = field(default_factory=dict)
    steps: Optional[List[TestCaseStep]] = None


@dataclass
class ExpectationSpec:
    """验证语义：如何判断结果（原则 3：Validator 消费的本规格）。

    Phase 1 保留原始断言字典（``return_code`` / ``output_contains`` /
    ``output_matches`` / ``compare_files``）；Phase 3 Schema v2 将把
    字典结构化为具名字段。
    """
    __test__ = False
    assertions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SchedulingSpec:
    """调度语义：什么时候、以什么资源执行（原则 4：编排层消费）。"""
    __test__ = False
    depends_on: List[str] = field(default_factory=list)
    resources: Optional[Dict[str, Any]] = None


@dataclass(init=False)
class TestCase:
    __test__ = False

    # ── 顶层 metadata ──
    name: str
    description: str
    tags: List[str]
    expected_failure: bool
    xfail_reason: str
    xfail_quiet: bool
    # ── 分层语义 ──
    execution: ExecutionSpec
    expectation: ExpectationSpec
    scheduling: SchedulingSpec

    def __init__(
        self,
        name: str,
        command: str = "",
        args: Optional[List[str]] = None,
        expected: Optional[Dict[str, Any]] = None,
        description: str = "",
        timeout: Optional[float] = None,
        resources: Optional[Dict[str, Any]] = None,
        steps: Optional[List[TestCaseStep]] = None,
        tags: Optional[List[str]] = None,
        retry_count: int = 0,
        expected_failure: bool = False,
        xfail_reason: str = "",
        xfail_quiet: bool = False,
        depends_on: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        execution: Optional[ExecutionSpec] = None,
        expectation: Optional[ExpectationSpec] = None,
        scheduling: Optional[SchedulingSpec] = None,
    ) -> None:
        """构造 TestCase。

        平铺关键字参数（v1 形态）在 ``execution/expectation/scheduling``
        未显式给出时归一存入对应子 Spec；显式传入子 Spec 时平铺参数被忽略。
        """
        self.name = name
        self.description = description
        self.tags = tags if tags else []
        self.expected_failure = expected_failure
        self.xfail_reason = xfail_reason
        self.xfail_quiet = xfail_quiet

        self.execution = execution if execution is not None else ExecutionSpec(
            name=name,
            command=command,
            args=args if args is not None else [],
            timeout=timeout,
            retry_count=retry_count,
            env=env if env else {},
            steps=steps,
        )
        self.expectation = expectation if expectation is not None else ExpectationSpec(
            assertions=expected if expected else {},
        )
        self.scheduling = scheduling if scheduling is not None else SchedulingSpec(
            depends_on=depends_on if depends_on else [],
            resources=resources,
        )

    # ── execution 直通访问器 ─────────────────────────────────────────────

    @property
    def command(self) -> str:
        return self.execution.command

    @command.setter
    def command(self, value: str) -> None:
        self.execution.command = value

    @property
    def args(self) -> List[str]:
        return self.execution.args

    @args.setter
    def args(self, value: List[str]) -> None:
        self.execution.args = value

    @property
    def timeout(self) -> Optional[float]:
        return self.execution.timeout

    @timeout.setter
    def timeout(self, value: Optional[float]) -> None:
        self.execution.timeout = value

    @property
    def retry_count(self) -> int:
        return self.execution.retry_count

    @retry_count.setter
    def retry_count(self, value: int) -> None:
        self.execution.retry_count = value

    @property
    def env(self) -> Dict[str, str]:
        return self.execution.env

    @env.setter
    def env(self, value: Dict[str, str]) -> None:
        self.execution.env = value

    @property
    def steps(self) -> Optional[List[TestCaseStep]]:
        return self.execution.steps

    @steps.setter
    def steps(self, value: Optional[List[TestCaseStep]]) -> None:
        self.execution.steps = value

    # ── expectation / scheduling 直通访问器 ─────────────────────────────

    @property
    def expected(self) -> Dict[str, Any]:
        """原始断言字典（兼容 v1 访问形态）。"""
        return self.expectation.assertions

    @expected.setter
    def expected(self, value: Dict[str, Any]) -> None:
        self.expectation.assertions = value if value else {}

    @property
    def depends_on(self) -> List[str]:
        return self.scheduling.depends_on

    @depends_on.setter
    def depends_on(self, value: List[str]) -> None:
        self.scheduling.depends_on = value

    @property
    def resources(self) -> Optional[Dict[str, Any]]:
        return self.scheduling.resources

    @resources.setter
    def resources(self, value: Optional[Dict[str, Any]]) -> None:
        self.scheduling.resources = value

    # ── 统一步骤访问（单命令模式返回单元素列表） ─────────────────────────

    @property
    def all_steps(self) -> List[TestCaseStep]:
        """Return the unified list of steps regardless of mode.

        Single-command cases yield a single-element list; sequence cases yield
        ``execution.steps`` itself.  This is the merge point that lets callers
        treat a single command as a special case of a sequence.
        """
        if self.execution.steps is not None:
            return self.execution.steps
        return [TestCaseStep(
            command=self.execution.command,
            args=self.execution.args,
            expected=self.expectation.assertions,
            timeout=self.execution.timeout,
            retry_count=self.execution.retry_count,
        )]

    @property
    def is_single_command(self) -> bool:
        """True when this case uses the flat single-command representation."""
        return self.execution.steps is None

    # ── 序列化 ───────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Convert test case to dictionary format."""
        result = {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "expected": self.expected,
            "timeout": self.timeout,
            "resources": self.resources,
            "tags": self.tags,
            "retry_count": self.retry_count,
        }
        if self.env:
            result["env"] = self.env
        if self.expected_failure:
            result["expected_failure"] = self.expected_failure
            result["xfail_reason"] = self.xfail_reason
            if self.xfail_quiet:
                result["xfail_quiet"] = self.xfail_quiet
        if self.steps is not None:
            result["steps"] = [
                {
                    "command": s.command,
                    "args": s.args,
                    "expected": s.expected,
                    "timeout": s.timeout,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ]
        return result
