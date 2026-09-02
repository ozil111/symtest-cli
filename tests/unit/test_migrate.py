"""Tests for ``symtest migrate``（1.4 Phase 4 迁移设计）。

覆盖两层验收：
1. migrate 单测：机械字段映射、幂等性、顶层保留、CLI 壳；
2. 迁移等价性不变量（design_1_4.md §六）：

    legacy config ──legacy 语义（TestCase 平铺 kwargs）──▶ Normalized A
    legacy config ──migrate──▶ new config ──new parser──▶ Normalized B
                                       断言 A == B

语料：tests/fixtures/migration/v1/（tests/ 与 examples/ 存量 v1 配置的原件拷贝）。
"""

import argparse
import json
from pathlib import Path

import pytest

from symtest.commands.migrate import run_migrate
from symtest.config.migrate import migrate_case, migrate_config
from symtest.core.config_loader import parse_test_cases
from symtest.core.test_case import TestCase, TestCaseStep

V1_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "migration" / "v1"


# ---------------------------------------------------------------------------
# migrate_case 单测
# ---------------------------------------------------------------------------

class TestMigrateCase:
    def test_single_command_fields_move_into_execution(self):
        v1 = {
            "name": "t",
            "command": "solver",
            "args": ["model.inp"],
            "timeout": 3600,
            "retry_count": 2,
            "env": {"OMP_NUM_THREADS": "4"},
            "expected": {"return_code": 0},
        }
        assert migrate_case(v1) == {
            "name": "t",
            "execution": {
                "command": "solver",
                "args": ["model.inp"],
                "timeout": 3600,
                "retry_count": 2,
                "env": {"OMP_NUM_THREADS": "4"},
            },
            "expected": {"return_code": 0},
        }

    def test_sequence_steps_move_into_execution(self):
        v1 = {
            "name": "seq",
            "retry_count": 1,
            "steps": [
                {"command": "a", "args": [], "expected": {"return_code": 0}},
            ],
            "expected": {"output_contains": ["done"]},
        }
        assert migrate_case(v1) == {
            "name": "seq",
            "execution": {
                "retry_count": 1,
                "steps": [
                    {"command": "a", "args": [], "expected": {"return_code": 0}},
                ],
            },
            "expected": {"output_contains": ["done"]},
        }

    def test_depends_on_and_resources_move_into_scheduling(self):
        v1 = {
            "name": "d",
            "command": "echo",
            "args": [],
            "expected": {},
            "depends_on": ["A", "B"],
            "resources": {"cpu_cores": 4},
        }
        assert migrate_case(v1) == {
            "name": "d",
            "execution": {"command": "echo", "args": []},
            "expected": {},
            "scheduling": {"depends_on": ["A", "B"], "resources": {"cpu_cores": 4}},
        }

    def test_metadata_and_unknown_fields_preserved(self):
        v1 = {
            "name": "x",
            "expected_failure": True,
            "xfail_reason": "bug",
            "xfail_quiet": True,
            "abstract": False,
            "extends": "base",
            "variables": {"a": 1},
            "description": "d",
            "tags": ["t"],
            "command": "echo",
            "args": [],
            "expected": {},
            "custom_field": {"keep": "me"},
        }
        out = migrate_case(v1)
        for key in ("name", "expected_failure", "xfail_reason", "xfail_quiet",
                    "abstract", "extends", "variables", "description", "tags"):
            assert out[key] == v1[key]
        assert out["custom_field"] == {"keep": "me"}

    def test_scheduling_omitted_when_empty(self):
        v1 = {"name": "t", "command": "echo", "args": [], "expected": {}}
        out = migrate_case(v1)
        assert "scheduling" not in out

    def test_idempotent_on_v2_input(self):
        v2 = {
            "name": "t",
            "execution": {"command": "echo", "args": []},
            "expected": {"return_code": 0},
            "scheduling": {"depends_on": ["a"]},
        }
        assert migrate_case(v2) == v2

    def test_input_not_mutated(self):
        v1 = {"name": "t", "command": "echo", "args": [], "expected": {}}
        snapshot = json.dumps(v1)
        migrate_case(v1)
        assert json.dumps(v1) == snapshot


# ---------------------------------------------------------------------------
# migrate_config 单测
# ---------------------------------------------------------------------------

class TestMigrateConfig:
    def test_top_level_keys_preserved(self):
        config = {
            "setup": {"environment_variables": {"K": "V"}},
            "test_cases": [
                {"name": "t", "command": "echo", "args": [], "expected": {}},
            ],
        }
        out = migrate_config(config)
        assert out["setup"] == config["setup"]
        assert out["test_cases"][0]["execution"]["command"] == "echo"
        assert "command" not in out["test_cases"][0]

    def test_import_refs_pass_through(self):
        config = {"test_cases": [{"import": "sub.json"}]}
        assert migrate_config(config) == {"test_cases": [{"import": "sub.json"}]}

    def test_missing_test_cases_raises(self):
        with pytest.raises(ValueError):
            migrate_config({"setup": {}})


# ---------------------------------------------------------------------------
# 迁移等价性不变量：A == B
# ---------------------------------------------------------------------------

def _legacy_case_to_testcase(case):
    """A 侧构造：legacy 语义载体（v1 平铺 dict → TestCase，宽松缺省）。"""
    steps = None
    if "steps" in case:
        steps = [
            TestCaseStep(
                command=s.get("command", ""),
                args=s.get("args", []),
                expected=s.get("expected", {}),
                timeout=s.get("timeout"),
                retry_count=s.get("retry_count", 0),
            )
            for s in case.get("steps", [])
        ]
    env = case.get("env")
    return TestCase(
        name=case.get("name", ""),
        command=case.get("command", ""),
        args=case.get("args", []),
        expected=case.get("expected", {}),
        description=case.get("description", ""),
        timeout=case.get("timeout"),
        resources=case.get("resources"),
        steps=steps,
        tags=case.get("tags", []),
        retry_count=case.get("retry_count", 0),
        expected_failure=case.get("expected_failure", False),
        xfail_reason=case.get("xfail_reason", ""),
        xfail_quiet=case.get("xfail_quiet", False),
        depends_on=case.get("depends_on", []),
        env={str(k): str(v) for k, v in env.items()} if env else {},
    )


def _load_v1_cases(path: Path):
    """读取 v1 配置文件，返回可参与等价性断言的 case dict 列表。"""
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        config = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for tc in config.get("test_cases", []):
        if not isinstance(tc, dict) or "import" in tc:
            continue  # import 引用不参与 case 级等价性
        cases.append(tc)
    return cases


def _v1_fixture_paths():
    return sorted(
        p for p in V1_FIXTURES.iterdir()
        if p.suffix.lower() in (".json", ".yaml", ".yml")
    )


@pytest.mark.parametrize("path", _v1_fixture_paths(), ids=lambda p: p.name)
def test_migration_equivalence_invariant(path):
    """A == B：legacy 语义归一 == migrate → new parser 归一。"""
    v1_cases = _load_v1_cases(path)
    if not v1_cases:
        pytest.skip("no concrete cases in fixture")

    # A 侧：legacy dict 经 TestCase 平铺 kwargs 构造（legacy 语义）→ to_dict()
    side_a = [_legacy_case_to_testcase(tc).to_dict() for tc in v1_cases]

    # B 侧：migrate(legacy) 经生产 parse_test_cases → to_dict()
    migrated = migrate_config({"test_cases": v1_cases})
    side_b = [
        tc.to_dict()
        for tc in parse_test_cases(migrated, strict=False)
    ]

    assert side_a == side_b


# ---------------------------------------------------------------------------
# CLI 壳
# ---------------------------------------------------------------------------

class TestRunMigrate:
    def _args(self, config, output=None, workspace=None):
        return argparse.Namespace(
            config_file=str(config),
            output=str(output) if output else None,
            workspace=workspace,
        )

    def test_migrate_writes_v2_json(self, tmp_path, capsys):
        src = tmp_path / "old.json"
        src.write_text(json.dumps({
            "test_cases": [
                {"name": "t", "command": "echo", "args": ["hi"],
                 "expected": {"return_code": 0}},
            ]
        }), encoding="utf-8")

        assert run_migrate(self._args(src, workspace=str(tmp_path))) is True

        out = tmp_path / "old.v2.json"
        assert out.exists()
        migrated = json.loads(out.read_text(encoding="utf-8"))
        assert migrated["test_cases"][0]["execution"]["command"] == "echo"
        assert "command" not in migrated["test_cases"][0]
        # stdout 打印输出路径（便于脚本串联）
        assert capsys.readouterr().out.strip() == str(out)

    def test_migrate_respects_output_path(self, tmp_path):
        src = tmp_path / "old.yaml"
        src.write_text(
            "test_cases:\n"
            "  - name: t\n"
            "    command: echo\n"
            "    args: []\n"
            "    expected: {}\n",
            encoding="utf-8",
        )
        dst = tmp_path / "new.json"
        assert run_migrate(self._args(src, output=dst, workspace=str(tmp_path))) is True
        assert dst.exists()

    def test_migrate_missing_input_fails(self, tmp_path):
        assert run_migrate(
            self._args(tmp_path / "nope.json", workspace=str(tmp_path))
        ) is False

    def test_migrate_unsupported_output_format_fails(self, tmp_path):
        src = tmp_path / "old.json"
        src.write_text(json.dumps({"test_cases": []}), encoding="utf-8")
        assert run_migrate(
            self._args(src, output=tmp_path / "out.txt", workspace=str(tmp_path))
        ) is False
