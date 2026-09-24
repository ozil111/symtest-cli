"""``symtest migrate`` 子命令实现（1.4 Phase 4 迁移设计第一层）。

确定性转换：加载 v1 配置 → ``config.migrate.migrate_config`` 机械映射 →
按输出扩展名写出 JSON/YAML。

支持递归迁移整棵 ``import`` 树（两阶段：先把全部文件加载并迁移到内存，
任一失败则不写任何文件，全部成功后才统一写盘）：

- 默认模式：每个文件写出 ``<stem>.v2<ext>`` 兄弟副本（原文件不动），
  并把已迁移配置中的 import 路径重写为对应的 ``.v2`` 文件名，
  迁移产物整棵树自洽、可直接 ``symtest validate``；
- ``--in-place``：整树原地覆盖（文件名/格式/import 路径全不变），
  默认关闭，开启即接受覆盖风险；与 ``--output`` 互斥。

不做路径解析、不校验必填 —— 校验归 ``symtest validate``，人工判断项归
迁移复查 Skill（见 examples/skill-migration）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config.config_io import save_config
from ..config.import_expander import _load_raw_config
from ..config.migrate import migrate_config

logger = logging.getLogger("symtest.commands.migrate")


def _resolve(path_str: str, workspace: Path) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def _collect_import_tree(entry_path: Path) -> List[Path]:
    """DFS 后序收集入口文件及全部 import 子文件。

    - processed 集合保证菱形 import（同一文件被多个父文件引用）只收集一次；
    - 递归栈检测真循环 import 并抛 RuntimeError；
    - 子文件缺失抛 FileNotFoundError；
    - 返回顺序保证子文件先于引用它的父文件。
    """
    ordered: List[Path] = []
    processed: set = set()

    def _walk(path: Path, stack: Tuple[str, ...]) -> None:
        canonical = str(path.resolve())
        if canonical in processed:
            return
        if canonical in stack:
            raise RuntimeError(
                f"Circular import detected: {canonical} "
                f"(chain: {' -> '.join(stack + (canonical,))})"
            )
        config = _load_raw_config(path)
        for item in config.get("test_cases", []) or []:
            if isinstance(item, dict) and "import" in item:
                sub_path = (path.parent / str(item["import"])).resolve()
                if not sub_path.exists():
                    raise FileNotFoundError(
                        f"Imported config file not found: {sub_path} "
                        f"(referenced from {path})"
                    )
                _walk(sub_path, stack + (canonical,))
        processed.add(canonical)
        ordered.append(path)

    _walk(entry_path, ())
    return ordered


def _v2_sibling(import_path: str) -> str:
    """'cases/sub.json' -> 'cases/sub.v2.json'（纯字符串变换，保留原分隔符）。"""
    sep_idx = max(import_path.rfind("/"), import_path.rfind("\\"))
    if sep_idx >= 0:
        directory, filename = import_path[: sep_idx + 1], import_path[sep_idx + 1:]
    else:
        directory, filename = "", import_path
    stem, dot, ext = filename.rpartition(".")
    if not dot or not stem:
        # 无扩展名（或 .gitignore 类隐藏名）：直接追加后缀
        return f"{directory}{filename}.v2"
    return f"{directory}{stem}.v2.{ext}"


def _rewrite_import_paths(config: Dict[str, Any]) -> Dict[str, Any]:
    """把 config 中 import 条目的路径改写为 .v2 兄弟名（就地修改并返回）。

    import 条目中的其他字段（如 tags）原样保留。
    """
    for item in config.get("test_cases", []) or []:
        if isinstance(item, dict) and "import" in item:
            item["import"] = _v2_sibling(str(item["import"]))
    return config


def run_migrate(args) -> bool:
    """CLI 壳：收集 import 树 → 整树 migrate_config → 按模式统一写盘。

    Returns
    -------
    True 成功；输入不存在/加载失败/循环 import/输出格式不支持返回 False。
    """
    workspace = Path(getattr(args, "workspace", None) or Path.cwd()).resolve()

    input_path = _resolve(args.config_file, workspace)
    if not input_path.exists():
        logger.error("Configuration file not found: %s", input_path)
        return False

    in_place = getattr(args, "in_place", False)
    output_arg = getattr(args, "output", None)
    if in_place and output_arg:
        logger.error("--output cannot be combined with --in-place")
        return False

    try:
        files = _collect_import_tree(input_path)
        # 第一阶段：整树加载并迁移到内存，任一失败则不写任何文件
        pending: List[Tuple[Path, Dict[str, Any]]] = [
            (f, migrate_config(_load_raw_config(f))) for f in files
        ]
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return False

    if output_arg and not in_place:
        entry_output = _resolve(output_arg, workspace)
    else:
        # 默认输出 <stem>.v2<原扩展名>，如 old.json → old.v2.json
        entry_output = input_path.parent / f"{input_path.stem}.v2{input_path.suffix}"

    written: List[Path] = []
    try:
        # 第二阶段：统一写盘
        for src, migrated in pending:
            if in_place:
                target = src
            else:
                # import 路径指向 .v2 子副本（--output 仅移动入口文件位置，
                # 隐含假设输出与入口同目录，否则需手工核对相对路径）
                _rewrite_import_paths(migrated)
                if src == input_path:
                    target = entry_output
                else:
                    target = src.parent / f"{src.stem}.v2{src.suffix}"
            save_config(migrated, target)
            written.append(target)
    except ValueError as exc:
        logger.error("%s", exc)
        return False

    for target in written:
        logger.info("Migrated config written to: %s", target)
        print(str(target))
    return True
