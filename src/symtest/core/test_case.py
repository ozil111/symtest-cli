from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

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
class TestCase:
    __test__ = False

    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    expected: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    timeout: Optional[float] = None
    resources: Optional[Dict[str, Any]] = None
    steps: Optional[List[TestCaseStep]] = None
    tags: List[str] = field(default_factory=list)
    retry_count: int = 0
    expected_failure: bool = False
    xfail_reason: str = ""
    xfail_quiet: bool = False
    depends_on: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize the internal single-command representation.

        A single-command case (``steps`` is None) keeps its flat
        command/args/expected/timeout/retry_count fields but also mirrors them
        into a single-element ``_single_step`` list.  This gives the two modes
        one unified step-level data model (see ``all_steps``) while the public
        ``steps`` attribute stays ``None`` so existing ``if case.steps``
        dispatch keeps working unchanged.
        """
        if self.steps is None:
            self._single_step: Optional[TestCaseStep] = TestCaseStep(
                command=self.command,
                args=self.args,
                expected=self.expected,
                timeout=self.timeout,
                retry_count=self.retry_count,
            )
        else:
            self._single_step: Optional[TestCaseStep] = None

    # -- 统一步骤访问（单命令模式返回单元素列表） -----------------------------

    @property
    def all_steps(self) -> List[TestCaseStep]:
        """Return the unified list of steps regardless of mode.

        Single-command cases yield a single-element list; sequence cases yield
        ``steps`` itself.  This is the merge point that lets callers treat a
        single command as a special case of a sequence.
        """
        return self.steps if self.steps is not None else [self._single_step]

    @property
    def is_single_command(self) -> bool:
        """True when this case uses the flat single-command representation."""
        return self.steps is None

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

    def to_execution_dict(self) -> Dict[str, Any]:
        """Convert to the dict format expected by ``execute_single_test_case``.

        Only for single-command mode; sequence cases should use
        ``execute_sequence()`` instead.
        """
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "expected": self.expected,
            "description": self.description or None,
            "timeout": self.timeout,
            "resources": self.resources,
            "retry_count": self.retry_count,
            "env": self.env,
        }
