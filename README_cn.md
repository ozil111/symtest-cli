# CLI Test Framework

中文 | [English](README.md)

一个面向命令行程序的功能型自动化测试框架。它服务于不能只检查退出码的回归测试：
多步骤命令、数值结果对比、大型配置集、并行执行，以及可直接接入 CI 的报告。

项目最初来自有限元求解器开发。在这类场景中，一个测试可能需要依次运行多个程序，
生成 HDF5 或 CSV 结果，按照数值容差与基线比较，并持续跟踪不同版本的运行耗时。

## 解决什么问题

CLI Test Framework 使用一份 JSON 或 YAML 配置，同时描述执行流程和验收标准：

- **执行工作流**：支持单命令或失败即停止的步骤序列，以及超时、重试、变量、标签和
  预期失败。
- **验证结果**：支持返回码、输出文本、正则表达式，以及 text、JSON、CSV、XML、
  HDF5、二进制和自定义脚本文件比较。
- **管理大型测试集**：通过 `import` 拆分配置、通过 `extends` 复用模板、按名称或
  标签筛选，并可在可选 TUI 中跨文件查看用例。
- **迭代与集成**：支持并行执行、`--last-failed`、步骤级 `--resume`、耗时历史、
  结构化报告和 JUnit XML。

项目强调务实：功能来自真实 CLI 和科学计算项目中出现的测试需求。

## 安装

要求 Python 3.9 或更高版本。

```bash
pip install cli-test-framework
```

YAML 和 TUI 均为可选能力：

```bash
pip install "cli-test-framework[yaml]"
pip install "cli-test-framework[tui]"
pip install "cli-test-framework[all]"
```

默认安装包含 HDF5 和数值比较支持。

## 快速开始

创建 `test_cases.json`：

```json
{
  "test_cases": [
    {
      "name": "hello",
      "command": "echo",
      "args": ["Hello World"],
      "tags": ["smoke"],
      "expected": {
        "return_code": 0,
        "output_contains": ["Hello World"]
      }
    }
  ]
}
```

运行测试：

```bash
cli-test run test_cases.json
```

只校验配置而不执行：

```bash
cli-test validate test_cases.json
```

## 数值 Golden File 测试

文件比较可以直接作为测试的验收条件。数值容差、表选择、数据过滤和编码等参数与命令
一起声明：

```json
{
  "test_cases": [
    {
      "name": "有限元位移检查",
      "command": "my_solver",
      "args": ["--input", "case1.dat", "--output", "out.h5"],
      "expected": {
        "return_code": 0,
        "output_contains": ["simulation finished"],
        "compare_files": [
          {
            "actual": "out.h5",
            "baseline": "ref/golden.h5",
            "rtol": 1e-5,
            "atol": 1e-8,
            "tables": ["NASTRAN/RESULT/NODAL/DISPLACEMENT"]
          },
          {
            "actual": "summary.csv",
            "baseline": "ref/summary.csv",
            "rtol": 1e-6
          }
        ]
      }
    }
  ]
}
```

省略 `type` 时，框架会根据扩展名自动选择比较器。内置类型包括 `text`、`json`、
`csv`、`xml`、`h5`、`binary` 和 `script`，也可以在工作区中增加自定义比较器。

当结果变化合理、需要接受新基线时，可使用 `--update-baseline`。该操作可能覆盖参考
文件，因此交互运行时必须输入 `yes`，非交互环境必须显式增加 `--yes`：

```bash
cli-test run test_cases.json --update-baseline
cli-test run test_cases.json --update-baseline --yes   # 自动化或 CI
```

请将基线纳入版本控制，并审查每一次更新。

## 多步骤与迭代工作流

一个用例可以包含有序的 `steps` 列表，任一步骤失败后立即停止。对于长耗时流程，
`--resume` 会复用保存的状态，跳过已经通过的步骤：

```bash
cli-test run solver_tests.json
cli-test run solver_tests.json --last-failed
cli-test run solver_tests.json -t long_case --resume
```

`--resume` 明确信任两次运行之间的工作区产物未被修改。

## 大型测试集与可选 TUI

大型测试集可以拆分为多个子配置：

```json
{
  "test_cases": [
    {"import": "cases/text_tests.json", "tags": ["text"]},
    {"import": "cases/h5_tests.json", "tags": ["h5", "regression"]}
  ]
}
```

可选 TUI 能在所有导入文件之上提供统一的可搜索视图，主要用于大型项目中定位用例和
辅助检查场景覆盖情况，并不是日常执行测试的必要组件。

```bash
cli-test tui main_config.json
```

## 并行执行与资源

```bash
cli-test run test_cases.json --parallel --workers 4
cli-test run test_cases.json --parallel --execution-mode process
```

线程模式目前支持 CPU 令牌分配、求解器线程环境变量注入，以及基于预估时间或历史
耗时的 LPT 调度。进程模式提供执行隔离，但尚未接入资源调度器。真实内存约束、
priority 语义和更完整的资源管理仍是后续演进方向。

## CI 与报告

```bash
cli-test run test_cases.json \
  --parallel --workers 4 \
  --junit-xml report.xml
```

当前测试集包含 750 个单元、集成和端到端测试，行覆盖率为 83%。CI 在 Windows 和
Linux 上覆盖 Python 3.9 至 3.13。

## Python API

```python
from cli_test_framework.runners import JSONRunner, ParallelJSONRunner

runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,
    execution_mode="thread",
    history_dir="./hist",
    variables={"solver": "/opt/solver/bin/solver"},
)

success = runner.run_tests()
for detail in runner.results["details"]:
    print(detail["name"], detail["status"], detail.get("duration"))
```

## 独立文件比较

```bash
compare-files result1.h5 result2.h5 --h5-table-regex "output_.*" --h5-rtol 1e-5
compare-files data1.csv data2.csv --csv-rtol 1e-4 --csv-data-filter ">1e-6"
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

## AI 辅助 TDD：一个额外收益

同一份配置也可以作为机器可读的验收契约。结构化校验失败、文件差异详情和定向重跑
很适合组成 AI 辅助的 TDD 循环：

```text
定义验收条件
    → 运行相关用例
    → 阅读结构化失败信息
    → 修改实现
    → 使用 --last-failed 定向验证
    → 执行完整回归测试
```

这是明确测试与结构化结果带来的额外收益，并不是使用框架的前提。

## 文档

- [中文使用说明](docs/user_manual.md)
- [中文设计文档](docs/design.md)
- [插件示例](examples/plugins/README.md)

## 开发

一次安装全部可选功能和测试依赖：

```bash
pip install -e ".[dev]"
python -m pytest tests/unit tests/integration tests/e2e
```

欢迎提交缺陷修复、比较器插件和文档改进，也欢迎分享真实项目中的测试需求与使用经验。

## 许可证

MIT
