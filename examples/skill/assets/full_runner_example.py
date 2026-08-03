#!/usr/bin/env python
"""
完整 runner 示例脚本。

可直接复制到你的项目中，按需修改配置后使用。建议将其重命名为项目入口脚本
（例如 test.py 或 run_tests.py），放在项目根目录。

核心能力：
  - 支持 JSON 和 YAML 配置文件（自动按扩展名识别）
  - 全参数 CLI 透传：--test-target / --tag / --last-failed / --resume /
    --update-baseline / --yes / --update-history / --junit-xml / --workers
  - 可选 venv 环境 PATH 注入（解决 Windows 下 compare-files 子进程
    WinError 2 问题，详见下方注释）
  - --error-analysis 启用 CSV/HDF5 数值比较的流式误差统计
  - 文本报告落盘 + JUnit XML 报告（CI 集成）+ 退出码处理

用法示例：
  # 全量运行
  python run_tests.py test_cases.json --workers 4

  # 只运行指定用例
  python run_tests.py test_cases.json --test-target alpha gamma

  # 按标签过滤
  python run_tests.py test_cases.json --tag smoke

  # 只跑上次失败的用例（AI 迭代修复场景）
  python run_tests.py test_cases.json --last-failed

  # 断点续跑序列用例（跳过已通过的步骤）
  python run_tests.py test_cases.json --resume -t BS-U_01

  # 比较失败时自动更新基线文件
  python run_tests.py test_cases.json --update-baseline

  # 清零历史耗时记录，重新建立回归基线
  python run_tests.py test_cases.json --update-history

  # 启用误差分析（CSV/HDF5 数值比较的统计信息）
  python run_tests.py test_cases.json --error-analysis

  # 输出 JUnit XML 供 Jenkins/GitLab CI 解析
  python run_tests.py test_cases.json --junit-xml report.xml
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from symtest.runners import (
    ParallelJSONRunner,
    ParallelYAMLRunner,
)
from symtest.utils.report_generator import ReportGenerator
from symtest import write_junit_xml, setup_console_logging


# ---------------------------------------------------------------------------
# 可选：确保 venv 中的 console-script 命令可见
# ---------------------------------------------------------------------------
# 如果你的项目使用虚拟环境且测试配置文件中的 command 引用了 console-script
# 命令（例如 compare-files、symtest），在 Windows 下直接双击运行或通过
# 未激活的环境启动脚本时，子进程可能找不到这些命令，报错 WinError 2
# （系统找不到指定的文件）。
#
# 解决方案：将 venv/Scripts 目录前置到 PATH，让子进程继承后能正确定位。
# 如果你的剧本始终在已激活的环境中运行，可以安全删除此段代码。
#
# 具体示例（按你的项目结构调整路径）：
#
# venv_scripts = os.path.abspath(os.path.join(
#     os.path.dirname(__file__), "..", ".venv", "Scripts"))
# if os.path.isdir(venv_scripts):
#     os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")
# ---------------------------------------------------------------------------


def _auto_create_runner(config_file, workspace, max_workers, execution_mode,
                        test_case_filter, test_case_tag_filter,
                        update_baseline, update_history, last_failed, resume, history_dir,
                        regression_threshold, variables, **extra_kwargs):
    """根据配置文件扩展名自动选择 JSON 或 YAML runner。"""
    ext = Path(config_file).suffix.lower()
    common_kwargs = dict(
        config_file=config_file,
        workspace=workspace,
        max_workers=max_workers,
        execution_mode=execution_mode,
        test_case_filter=test_case_filter,
        test_case_tag_filter=test_case_tag_filter,
        update_baseline=update_baseline,
        update_history=update_history,
        last_failed=last_failed,
        resume=resume,
        history_dir=history_dir,
        regression_threshold=regression_threshold,
        variables=variables,
    )
    common_kwargs.update(extra_kwargs)

    if ext == ".json":
        return ParallelJSONRunner(**common_kwargs)
    elif ext in (".yaml", ".yml"):
        return ParallelYAMLRunner(**common_kwargs)
    else:
        raise ValueError(
            f"Unsupported config file format '{ext}'. "
            f"Expected .json, .yaml, or .yml."
        )


def main():
    # ---- 可选：venv PATH 注入（取消注释以启用） ----
    # 说明见文件头部注释。如果你的环境已激活，无需此段代码。
    # venv_scripts = os.path.abspath(os.path.join(
    #     os.path.dirname(__file__), "..", ".venv", "Scripts"))
    # if os.path.isdir(venv_scripts):
    #     os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")

    parser = argparse.ArgumentParser(
        description="CLI test runner — 项目入口脚本示例",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_tests.py test_cases.json
  python run_tests.py test_cases.json --test-target alpha gamma
  python run_tests.py test_cases.json --tag smoke
  python run_tests.py test_cases.json --last-failed
  python run_tests.py test_cases.json --resume -t BS-U_01
  python run_tests.py test_cases.json --update-baseline
  python run_tests.py test_cases.json --update-history
  python run_tests.py test_cases.json --junit-xml report.xml --workers 4
        """,
    )

    # ---- 位置参数 ----
    parser.add_argument(
        "config",
        help="测试配置文件路径（.json 或 .yaml）",
    )

    # ---- 用例过滤 ----
    parser.add_argument(
        "--test-target", "-t",
        nargs="+",
        default=None,
        help="指定要运行的测试案例名称，支持多个，例如: --test-target alpha gamma",
    )
    parser.add_argument(
        "--tag",
        nargs="+",
        default=None,
        dest="test_tag",
        help="按标签过滤测试案例，支持多个（OR 关系），例如: --tag smoke --tag regression",
    )

    # ---- 运行模式 ----
    parser.add_argument(
        "--last-failed",
        action="store_true",
        default=False,
        help="只运行上次失败的用例（覆盖式更新，适合 AI 迭代修复）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="断点续跑序列用例，跳过已通过的步骤",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        default=False,
        help="比较失败时自动更新基线文件（建议搭配版本控制使用）",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        help="不询问并确认更新基线（非交互环境中与 --update-baseline 一起使用）",
    )
    parser.add_argument(
        "--update-history",
        action="store_true",
        default=False,
        help="清零本次运行涉及的 case 的历史耗时记录，重新建立回归基线",
    )
    parser.add_argument(
        "--error-analysis",
        action="store_true",
        default=False,
        help="启用数值比较的流式误差统计（CSV/HDF5）："
             "total_numeric_cells、mismatched_cells、"
             "max_abs/rel_error、mean/rms_abs_error",
    )

    # ---- 输出 ----
    parser.add_argument(
        "--junit-xml",
        default=None,
        metavar="PATH",
        help="JUnit XML 报告输出路径（供 Jenkins/GitLab CI 解析）",
    )
    parser.add_argument(
        "--report",
        default="test_report.txt",
        metavar="PATH",
        help="文本报告输出路径，默认 test_report.txt",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="详细输出（DEBUG 级别日志）",
    )

    # ---- 并行配置 ----
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="并行工作线程数，默认 4",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["thread", "process"],
        default="thread",
        help="并行执行模式：thread（默认，支持资源感知调度）或 process（进程隔离）",
    )

    # ---- 工作区与高级选项 ----
    parser.add_argument(
        "--workspace",
        default=None,
        help="测试工作目录，默认脚本所在目录",
    )
    parser.add_argument(
        "--history-dir",
        default=".symtest",
        help="历史记录目录，默认 .symtest（用于智能调度排序与回归检测）",
    )
    parser.add_argument(
        "--regression-threshold",
        type=float,
        default=1.5,
        help="回归检测阈值（耗时倍数），默认 1.5 倍",
    )

    # ---- 模板变量（占位符替换） ----
    parser.add_argument(
        "--var",
        nargs="+",
        default=None,
        dest="variables_raw",
        help="模板变量替换，格式 KEY=VALUE，例如：--var solver=/path/to/solver.exe",
    )

    # ---- 自定义比较器插件 ----
    parser.add_argument(
        "--plugin-dir",
        nargs="+",
        default=None,
        help="额外比较器插件目录（可包含 *_comparator.py）。"
             "工作区 comparators/ 目录始终自动探测。",
    )

    args = parser.parse_args()

    if args.update_baseline and not args.yes:
        if not sys.stdin.isatty():
            parser.error("非交互环境使用 --update-baseline 时必须同时传入 --yes")
        try:
            confirmed = input(
                "警告：--update-baseline 可能覆盖参考文件。\n"
                "输入 'yes' 继续："
            )
        except (EOFError, KeyboardInterrupt):
            confirmed = ""
        if confirmed.strip().lower() != "yes":
            print("已取消基线更新。", file=sys.stderr)
            return 1

    # ---- 日志配置 ----
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_console_logging(level=log_level)

    # ---- 解析模板变量 ----
    variables = {}
    if args.variables_raw:
        for item in args.variables_raw:
            if "=" not in item:
                parser.error(f"Invalid --var format: '{item}' (expected KEY=VALUE)")
            key, value = item.split("=", 1)
            variables[key.strip()] = value.strip()

    # ---- 工作区默认值 ----
    workspace = args.workspace
    if workspace is None:
        workspace = os.path.dirname(os.path.abspath(__file__))

    # ---- 创建 runner ----
    runner = _auto_create_runner(
        config_file=args.config,
        workspace=workspace,
        max_workers=args.workers,
        execution_mode=args.execution_mode,
        test_case_filter=args.test_target,
        test_case_tag_filter=args.test_tag,
        update_baseline=args.update_baseline,
        update_history=args.update_history,
        last_failed=args.last_failed,
        resume=args.resume,
        history_dir=args.history_dir,
        regression_threshold=args.regression_threshold,
        variables=variables,
        plugin_dirs=args.plugin_dir,
        error_analysis=args.error_analysis,
    )

    # ---- 运行测试 ----
    success = runner.run_tests()

    # ---- 文本报告落盘 ----
    report_path = os.path.join(workspace, args.report) if not os.path.isabs(args.report) else args.report
    report = ReportGenerator(runner.results, report_path)
    report.save_report()

    # ---- JUnit XML 报告（CI 集成） ----
    if args.junit_xml:
        junit_path = (
            os.path.join(workspace, args.junit_xml)
            if not os.path.isabs(args.junit_xml)
            else args.junit_xml
        )
        write_junit_xml(
            runner.results,
            junit_path,
            suite_name=os.path.splitext(os.path.basename(args.config))[0],
        )

    # ---- 退出码 ----
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
