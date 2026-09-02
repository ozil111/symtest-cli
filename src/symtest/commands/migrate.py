"""``symtest migrate`` 子命令实现（1.4 Phase 4 迁移设计第一层）。

确定性转换：加载 v1 配置 → ``config.migrate.migrate_config`` 机械映射 →
按输出扩展名写出 JSON/YAML。不做 import 展开（``expand=False``）、
不做路径解析、不校验必填 —— 校验归 ``symtest validate``，人工判断项归
迁移复查 Skill（见 examples/skill-migration）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config.config_io import load_config, save_config
from ..config.migrate import migrate_config

logger = logging.getLogger("symtest.commands.migrate")


def _resolve(path_str: str, workspace: Path) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = workspace / path
    return path.resolve()


def run_migrate(args) -> bool:
    """CLI 壳：load_config(expand=False) → migrate_config → save_config。

    Returns
    -------
    True 成功；输入不存在/加载失败/输出格式不支持返回 False。
    """
    workspace = Path(getattr(args, "workspace", None) or Path.cwd()).resolve()

    input_path = _resolve(args.config_file, workspace)
    if not input_path.exists():
        logger.error("Configuration file not found: %s", input_path)
        return False

    try:
        config = load_config(input_path, expand=False)
        migrated = migrate_config(config)
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return False

    output_arg = getattr(args, "output", None)
    if output_arg:
        output_path = _resolve(output_arg, workspace)
    else:
        # 默认输出 <stem>.v2<原扩展名>，如 old.json → old.v2.json
        output_path = input_path.parent / f"{input_path.stem}.v2{input_path.suffix}"

    try:
        save_config(migrated, output_path)
    except ValueError as exc:
        logger.error("%s", exc)
        return False

    logger.info("Migrated config written to: %s", output_path)
    print(str(output_path))
    return True
