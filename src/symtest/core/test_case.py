"""TestCase v2 分层数据模型（1.4 Core Model Refactoring）。

架构宪法（docs/design.md §10）：
- TestCase 是声明，不执行任何事情 —— 只有数据与访问器，没有 run/validate。
- 语义分三层：``execution``（执行什么）、``expectation``（如何判定）、
  ``scheduling``（何时/以何资源执行）；``name/description/tags/xfail_*``
  等保留为顶层 metadata，避免 DSL 啰嗦。

形态说明：
- ``to_dict()`` 输出 v2 分层配置形态（execution/expected/scheduling），
  可直接写入配置文件（TUI 保存路径即消费方）；
- 构造函数保留平铺关键字参数作为 legacy 语义归一入口（TUI 编辑路径、
  迁移等价性测试的 legacy 侧复用它）；
- ``case.command`` / ``case.expected`` / ``case.env`` ... 等属性直通访问器
  映射到子 Spec，使现有 ``case.xxx`` 访问点零改动；
- 序列步骤为 :class:`TestStep`（execution + expectation 分层）；
  ``TestStep.from_flat`` 是 DSL 平铺字段的归一入口。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExecutionSpec:
    """执行语义：一个执行单元（case 或 step）要执行什么。

    纯数据，不包含任何判定语义（expected 属于 ExpectationSpec）。
    ``steps`` 非 None 表示 sequence 模式（steps 为 ``TestStep`` 列表，
    每项是原子"执行+判定"对）；为 None 表示单命令模式，由
    ``command/args/timeout/retry_count`` 描述。
    """
    __test__ = False
    name: str = ""
    command: str = ""
    args: List[str] = field(default_factory=list)
    timeout: Optional[float] = None
    retry_count: int = 0
    env: Dict[str, str] = field(default_factory=dict)
    steps: Optional[List["TestStep"]] = None


@dataclass
class ExpectationSpec:
    """验证语义：如何判断结果（原则 3：Validator 消费的本规格）。

    断言保持原始字典形态（``return_code`` / ``output_contains`` /
    ``output_matches`` / ``compare_files`` ...），与 v2 DSL 的
    ``expected`` 块一一对应；结构化字段化留待后续版本。
    """
    __test__ = False
    assertions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestStep:
    """序列中的一个原子步骤：execution + expectation 分层（1.4 v2 模型）。

    DSL 形态不变（step dict：``command/args/expected/timeout/retry_count``），
    由 parser / ``from_flat`` 负责归一；本类型提供平铺直通访问器，使
    duck-typing 消费点（``_step_attr``、``compute_config_hash``、TUI steps
    编辑器）零改动。
    """
    __test__ = False
    execution: ExecutionSpec
    expectation: ExpectationSpec

    @classmethod
    def from_flat(
        cls,
        command: str,
        args: List[str],
        expected: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        retry_count: int = 0,
    ) -> "TestStep":
        """DSL 平铺字段 → 分层 TestStep（parser / wire dict 重建入口）。"""
        return cls(
            execution=ExecutionSpec(
                command=command, args=args,
                timeout=timeout, retry_count=retry_count,
            ),
            expectation=ExpectationSpec(assertions=expected if expected else {}),
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

    # ── expectation 直通访问器 ───────────────────────────────────────────

    @property
    def expected(self) -> Dict[str, Any]:
        return self.expectation.assertions

    @expected.setter
    def expected(self, value: Dict[str, Any]) -> None:
        self.expectation.assertions = value if value else {}


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
        steps: Optional[List["TestStep"]] = None,
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
    def steps(self) -> Optional[List["TestStep"]]:
        return self.execution.steps

    @steps.setter
    def steps(self, value: Optional[List["TestStep"]]) -> None:
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
    def all_steps(self) -> List["TestStep"]:
        """Return the unified list of steps regardless of mode.

        Single-command cases yield a single-element list; sequence cases yield
        ``execution.steps`` itself.  This is the merge point that lets callers
        treat a single command as a special case of a sequence.
        """
        if self.execution.steps is not None:
            return self.execution.steps
        return [TestStep.from_flat(
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
        """Serialize to the v2 layered config form.

        顶层为 metadata（name/tags/description/xfail_*），执行语义进入
        ``execution``、验证语义进入 ``expected``、调度语义进入
        ``scheduling``（为空时整体省略）。steps 模式下 execution 只含
        ``steps``（+ case 级 retry_count/timeout/env），省略 command/args。
        """
        execution: Dict[str, Any] = {
            "timeout": self.timeout,
            "retry_count": self.retry_count,
        }
        if self.env:
            execution["env"] = dict(self.env)
        if self.steps is not None:
            execution["steps"] = [
                {
                    "command": s.command,
                    "args": s.args,
                    "expected": s.expected,
                    "timeout": s.timeout,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ]
        else:
            execution["command"] = self.command
            execution["args"] = self.args

        result: Dict[str, Any] = {
            "name": self.name,
            "tags": self.tags,
            "expected": self.expected,
            "execution": execution,
        }
        if self.description:
            result["description"] = self.description
        if self.expected_failure:
            result["expected_failure"] = self.expected_failure
            result["xfail_reason"] = self.xfail_reason
            if self.xfail_quiet:
                result["xfail_quiet"] = self.xfail_quiet

        scheduling: Dict[str, Any] = {}
        if self.depends_on:
            scheduling["depends_on"] = list(self.depends_on)
        if self.resources is not None:
            scheduling["resources"] = self.resources
        if scheduling:
            result["scheduling"] = scheduling
        return result
