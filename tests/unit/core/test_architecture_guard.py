"""Architecture guard tests —— 架构宪法可执行化（docs/design.md §10）。

通过 import 图静态断言依赖方向，由 CI 强制执行，使宪法可回归验证：
- 原则 2：execution 包不得 import validation / assertions（executor 不知道
  expected 的存在 —— Phase 2 唯一验收标准）；
- 原则 3：validation 只允许 import execution 的 result 类型（读取执行事实），
  不得 import 编排层；
- 原则 6：core 不得 import cli / tui / commands / runners（表现层）。
  注：``symtest.reporting.diagnosis`` 是唯一例外 —— 它是 result consumer
  工具，被 orchestration 调用以填充 wire format 的 next_action_hint 字段。
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "symtest"

# import / from 语句捕获（含相对导入的前导点）
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([.\w]+)", re.MULTILINE)


def _py_files(root: Path):
    assert root.is_dir(), f"missing package dir: {root}"
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py" or True)


def _imports(path: Path):
    return set(_IMPORT_RE.findall(path.read_text(encoding="utf-8")))


class TestExecutorPurity:
    """原则 2（Phase 2 唯一验收标准）：executor 不知道 expected 的存在。"""

    def test_execution_import_graph_has_no_validation_or_assertions(self):
        offenders = []
        for f in _py_files(SRC / "core" / "execution"):
            for mod in _imports(f):
                norm = mod.lstrip(".")
                if "validation" in norm or "assertions" in norm:
                    offenders.append(f"{f.relative_to(SRC)}: {mod}")
        assert not offenders, (
            "execution 包禁止 import validation/assertions: "
            f"{offenders}"
        )

    def test_execution_does_not_reference_expectation_or_status_semantics(self):
        """executor 源码不出现判定语义词汇（expected/baseline/hint/status）。"""
        forbidden = re.compile(r"\b(expected|baseline|next_action_hint|assertion)\b")
        # 剥离三引号字符串（docstring）与行注释后扫描
        string_or_comment = re.compile(
            r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|[^\n]*#.*)'
        )
        offenders = []
        for f in _py_files(SRC / "core" / "execution"):
            code = string_or_comment.sub("", f.read_text(encoding="utf-8"))
            for i, line in enumerate(code.splitlines(), 1):
                if forbidden.search(line):
                    offenders.append(f"{f.relative_to(SRC)}:{i}: {line.strip()}")
        assert not offenders, f"executor 源码中出现判定语义: {offenders}"


class TestExecutionValidationIndependence:
    """原则 3：validation 只读，仅依赖 execution 的 result 类型。"""

    def test_validation_imports_only_execution_result(self):
        allowed = {"execution", "execution.result"}
        offenders = []
        for f in _py_files(SRC / "core" / "validation"):
            for mod in _imports(f):
                norm = mod.lstrip(".")
                if norm.startswith("execution") and norm not in allowed:
                    offenders.append(f"{f.relative_to(SRC)}: {mod}")
                if "orchestration" in norm:
                    offenders.append(f"{f.relative_to(SRC)}: {mod}")
        assert not offenders, f"validation 依赖越界: {offenders}"


class TestCoreDoesNotImportPresentation:
    """原则 6：核心模型不依赖表现层。"""

    def test_core_has_no_presentation_imports(self):
        forbidden_abs = ("symtest.cli", "symtest.tui", "symtest.commands", "symtest.runners")
        forbidden_rel = ("cli", "tui", "commands", "runners")
        offenders = []
        for f in _py_files(SRC / "core"):
            for mod in _imports(f):
                if mod.startswith("."):
                    tail = mod.lstrip(".")
                    if tail.startswith(forbidden_rel):
                        offenders.append(f"{f.relative_to(SRC)}: {mod}")
                elif mod.startswith(forbidden_abs):
                    offenders.append(f"{f.relative_to(SRC)}: {mod}")
        assert not offenders, f"core import 了表现层: {offenders}"


class TestReportingConsumesResultsOnly:
    """原则 5：reporting 只能消费 Result，不得反向依赖 core 内部实现。"""

    def test_reporting_import_graph_is_leaf(self):
        offenders = []
        for f in _py_files(SRC / "reporting"):
            for mod in _imports(f):
                norm = mod.lstrip(".")
                if norm.startswith(("core", "execution", "validation",
                                    "orchestration", "runners", "tui", "cli")):
                    offenders.append(f"{f.relative_to(SRC)}: {mod}")
        assert not offenders, f"reporting 依赖越界: {offenders}"
