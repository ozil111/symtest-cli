"""Tests for ``symtest migrate``（1.4 Phase 4 迁移设计）。

覆盖两层验收：
1. migrate 单测：机械字段映射、幂等性、顶层保留、CLI 壳；
2. 迁移等价性不变量（design_1_4.md §六）：

    legacy config ──legacy 语义（TestCase 平铺 kwargs）──▶ Normalized A
    legacy config ──migrate──▶ new config ──new parser──▶ Normalized B
                                       断言 A == B

3. 递归 import 树迁移：默认 .v2 副本 + 路径重写，--in-place 原地覆盖。

语料：tests/fixtures/migration/v1/（tests/ 与 examples/ 存量 v1 配置的原件拷贝）。
"""

import argparse
import json
from pathlib import Path

import pytest

from symtest.commands.migrate import run_migrate
from symtest.config.migrate import migrate_case, migrate_config
from symtest.config.normalize import normalize_draft_config
from symtest.core.config_loader import parse_test_cases
from symtest.core.test_case import TestCase, TestStep

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
            TestStep.from_flat(
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

    # B 侧：migrate(legacy) → draft normalize（迁移不补必填，宽松形态由
    # DSL 层 normalize 承担）→ 生产 parse_test_cases → to_dict()
    migrated = migrate_config({"test_cases": v1_cases})
    side_b = [
        tc.to_dict()
        for tc in parse_test_cases(normalize_draft_config(migrated))
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


# ---------------------------------------------------------------------------
# 递归 import 树迁移（默认 .v2 副本 + 路径重写 / --in-place 原地覆盖）
# ---------------------------------------------------------------------------

def _v1_case(name):
    return {
        "name": name,
        "command": "echo",
        "args": [name],
        "expected": {"return_code": 0},
    }


class TestRunMigrateTree:
    def _args(self, config, output=None, workspace=None, in_place=False):
        return argparse.Namespace(
            config_file=str(config),
            output=str(output) if output else None,
            workspace=workspace,
            in_place=in_place,
        )

    @staticmethod
    def _read(path):
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        return json.loads(path.read_text(encoding="utf-8"))

    def _three_level_tree(self, tmp_path):
        """main.json -> sub.json -> subsub.json 三层 v1 import 树。"""
        (tmp_path / "subsub.json").write_text(
            json.dumps({"test_cases": [_v1_case("leaf")]}), encoding="utf-8")
        (tmp_path / "sub.json").write_text(json.dumps({
            "test_cases": [{"import": "subsub.json"}, _v1_case("mid")],
        }), encoding="utf-8")
        (tmp_path / "main.json").write_text(json.dumps({
            "test_cases": [
                {"import": "sub.json", "tags": ["api"]},
                _v1_case("root"),
            ],
        }), encoding="utf-8")

    def test_default_mode_migrates_whole_tree(self, tmp_path):
        self._three_level_tree(tmp_path)
        assert run_migrate(
            self._args(tmp_path / "main.json", workspace=str(tmp_path))
        ) is True

        main_v2 = tmp_path / "main.v2.json"
        sub_v2 = tmp_path / "sub.v2.json"
        subsub_v2 = tmp_path / "subsub.v2.json"
        for p in (main_v2, sub_v2, subsub_v2):
            assert p.exists()

        # 父文件 import 路径已重写为 .v2 名，tags 等其他字段保留
        migrated_main = self._read(main_v2)
        assert migrated_main["test_cases"][0]["import"] == "sub.v2.json"
        assert migrated_main["test_cases"][0]["tags"] == ["api"]
        assert migrated_main["test_cases"][1]["execution"]["command"] == "echo"
        migrated_sub = self._read(sub_v2)
        assert migrated_sub["test_cases"][0]["import"] == "subsub.v2.json"
        assert self._read(subsub_v2)["test_cases"][0]["execution"]["args"] == ["leaf"]

        # 原文件保持 v1 未动
        for name in ("main.json", "sub.json", "subsub.json"):
            for tc in self._read(tmp_path / name)["test_cases"]:
                if "import" not in tc:
                    assert "execution" not in tc

    def test_in_place_overwrites_tree(self, tmp_path):
        self._three_level_tree(tmp_path)
        assert run_migrate(
            self._args(tmp_path / "main.json",
                       workspace=str(tmp_path), in_place=True)
        ) is True

        # 原文件原地变为 v2，import 路径不变，不产生 .v2 副本
        migrated_main = self._read(tmp_path / "main.json")
        assert migrated_main["test_cases"][0]["import"] == "sub.json"
        assert migrated_main["test_cases"][1]["execution"]["command"] == "echo"
        assert self._read(tmp_path / "sub.json")["test_cases"][0]["import"] \
            == "subsub.json"
        assert self._read(tmp_path / "subsub.json")["test_cases"][0] \
            ["execution"]["args"] == ["leaf"]
        assert not (tmp_path / "main.v2.json").exists()

    def test_diamond_import_migrated_once(self, tmp_path):
        (tmp_path / "d.json").write_text(
            json.dumps({"test_cases": [_v1_case("shared")]}), encoding="utf-8")
        for name in ("b.json", "c.json"):
            (tmp_path / name).write_text(json.dumps(
                {"test_cases": [{"import": "d.json"}]}), encoding="utf-8")
        (tmp_path / "main.json").write_text(json.dumps({
            "test_cases": [{"import": "b.json"}, {"import": "c.json"}],
        }), encoding="utf-8")

        assert run_migrate(
            self._args(tmp_path / "main.json",
                       workspace=str(tmp_path), in_place=True)
        ) is True
        # 菱形引用不误报循环，d.json 已迁移
        assert self._read(tmp_path / "d.json")["test_cases"][0] \
            ["execution"]["command"] == "echo"

    def test_circular_import_writes_nothing(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps({"test_cases": [{"import": "b.json"}]}), encoding="utf-8")
        (tmp_path / "b.json").write_text(
            json.dumps({"test_cases": [{"import": "a.json"}]}), encoding="utf-8")
        snapshot = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()}

        assert run_migrate(
            self._args(tmp_path / "a.json", workspace=str(tmp_path))
        ) is False
        # 两阶段保证：任一失败不写任何文件
        assert {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()} \
            == snapshot

    def test_missing_import_writes_nothing(self, tmp_path):
        (tmp_path / "main.json").write_text(
            json.dumps({"test_cases": [{"import": "ghost.json"}]}),
            encoding="utf-8")
        before = (tmp_path / "main.json").read_text(encoding="utf-8")

        assert run_migrate(
            self._args(tmp_path / "main.json", workspace=str(tmp_path))
        ) is False
        assert (tmp_path / "main.json").read_text(encoding="utf-8") == before
        assert not (tmp_path / "main.v2.json").exists()

    def test_sub_without_test_cases_writes_nothing(self, tmp_path):
        (tmp_path / "sub.json").write_text(
            json.dumps({"setup": {}}), encoding="utf-8")
        (tmp_path / "main.json").write_text(
            json.dumps({"test_cases": [{"import": "sub.json"}]}),
            encoding="utf-8")

        assert run_migrate(
            self._args(tmp_path / "main.json", workspace=str(tmp_path))
        ) is False
        assert not (tmp_path / "main.v2.json").exists()
        assert not (tmp_path / "sub.v2.json").exists()

    def test_output_and_in_place_conflict(self, tmp_path):
        src = tmp_path / "old.json"
        src.write_text(json.dumps({"test_cases": []}), encoding="utf-8")
        assert run_migrate(self._args(
            src, output=tmp_path / "new.json",
            workspace=str(tmp_path), in_place=True,
        )) is False
        assert not (tmp_path / "new.json").exists()
        assert json.loads(src.read_text(encoding="utf-8")) == {"test_cases": []}

    def test_in_place_idempotent_on_v2_tree(self, tmp_path):
        self._three_level_tree(tmp_path)
        assert run_migrate(
            self._args(tmp_path / "main.json",
                       workspace=str(tmp_path), in_place=True)
        ) is True
        first_pass = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()}
        assert run_migrate(
            self._args(tmp_path / "main.json",
                       workspace=str(tmp_path), in_place=True)
        ) is True
        assert {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()} \
            == first_pass

    def test_mixed_json_yaml_tree(self, tmp_path):
        (tmp_path / "sub.yaml").write_text(
            "test_cases:\n"
            "  - name: y\n"
            "    command: echo\n"
            "    args: []\n"
            "    expected: {}\n",
            encoding="utf-8",
        )
        (tmp_path / "main.json").write_text(
            json.dumps({"test_cases": [{"import": "sub.yaml"}]}),
            encoding="utf-8")

        assert run_migrate(
            self._args(tmp_path / "main.json", workspace=str(tmp_path))
        ) is True
        assert (tmp_path / "sub.v2.yaml").exists()
        assert self._read(tmp_path / "sub.v2.yaml")["test_cases"][0] \
            ["execution"]["command"] == "echo"
        assert self._read(tmp_path / "main.v2.json")["test_cases"][0]["import"] \
            == "sub.v2.yaml"
