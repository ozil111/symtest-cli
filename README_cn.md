# CLI 测试框架

轻量级命令行自动化测试框架，用 JSON/YAML 定义测试用例，一行命令跑完所有验证。

特别适合科学计算场景——对 HDF5 结果文件有深度支持：正则匹配表格、数据过滤、容差对比，轻松搞定仿真结果校验。

## 为什么开发这个框架

这个项目最初是为有限元求解器做回归测试而生的。在这个领域，检查退出码远远不够——每个测试可能需要运行多条命令、生成数值结果文件、在容差范围内对比 HDF5/CSV 输出、还要防止性能退化。

过程中我们发现，这个框架天然适配 **TDD + AI 协作** 的工作流：

1. **建模测试** — 用干净的 JSON/YAML 定义测试的输入、命令和预期行为
2. **声明验收标准** — `return_code`、`output_contains`、`compare_files` 带容差——这就是你的"契约"
3. **跑起来** — 框架执行命令、对比输出和基线、产出结构化结果
4. **喂给 AI** — 测试失败时，结构化的 diff（哪里失败了、怎么失败的、容差信息）为 LLM 提供了修复所需的全部上下文
5. **迭代** — `--last-failed` 只重跑失败用例；`--resume` 跳过已通过的步骤继续执行；循环压缩到秒级

这让测试套件变成了一份**机器可读的目标规格书**——"正确"只需定义一次，之后交给 AI 对着定义迭代。框架架起了人类意图和自动验证之间的桥梁。

本质上，CLI 测试框架始终聚焦于它的原点：**科学计算回归测试**。但 TDD + AI 这一循环适用于任何命令行工具——脚本、编译器、仿真器、数据管线，一切从终端运行的程序都行。

## 功能亮点

- **Golden File 断言** — `compare_files` 嵌入测试 `expected`，运行后自动对比产物文件与基准文件，支持容差
- **并行执行** — 多线程/多进程，3–5 倍加速
- **资源感知调度** — 自动管理 CPU 核心分配，防止求解器线程失控
- **顺序步骤测试** — 单个用例内多步执行，失败即停
- **配置拆分与继承** — `import` 引入子文件，`extends` 继承模板基类——大型测试套件告别重复
- **TUI 交互式管理器** — 在终端里浏览、搜索、编辑、运行测试用例，无需切出编辑器
- **AI 友好迭代** — `--last-failed` 只跑失败用例；`--resume` 跳过已通过步骤继续；`--update-baseline` 刷新基线；`xfail` 标记已知缺陷
- **文件比较** — 文本 / JSON / CSV / XML / HDF5 / 二进制，支持 CLI 独立使用和内嵌断言两种方式
- **筛选运行** — 按名称、标签或两者组合（AND 逻辑）筛选运行
- **JUnit XML 输出** — 开箱即用的 CI 报告，兼容 GitLab CI / Jenkins / CircleCI
- **自定义比较器插件** — 将 `*_comparator.py` 放入工作区即可自动发现；通过 `type: script` 调用任意外部分析脚本

## 快速开始

```bash
pip install cli-test-framework
```

### 30 秒上手

1. 写测试用例 `test_cases.json`：

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

2. 运行：

```bash
cli-test run test_cases.json
```

### 测试中对比 Golden File

运行仿真命令，自动对比输出文件与基准：

```json
{
    "test_cases": [
        {
            "name": "FEA 位移检查",
            "command": "my_solver",
            "args": ["--input", "case1.dat", "--output", "out.h5"],
            "expected": {
                "return_code": 0,
                "compare_files": [
                    {
                        "actual": "out.h5",
                        "baseline": "ref/golden.h5",
                        "rtol": 1e-5,
                        "atol": 1e-8,
                        "tables": ["NASTRAN/RESULT/NODAL/DISPLACEMENT"]
                    }
                ]
            }
        }
    ]
}
```

- `actual` — 命令产出的文件
- `baseline` — 用于对比的基准文件
- `type` — 比较器类型（省略时从后缀自动检测：`.h5`→h5，`.json`→json，`.csv`→csv，`.xml`→xml，`.txt`→text）
- 其余字段透传到对应比较器（`rtol`、`atol`、`tables`、`table_regex`、`data_filter`、`encoding`、`structure_only`、`delimiter`、`compare_mode`、`key_field` 等）

支持同时对比多个文件，以及与已有断言混用：

```json
{
    "expected": {
        "return_code": 0,
        "output_contains": ["仿真完成"],
        "compare_files": [
            {"actual": "out.h5",   "baseline": "ref/disp.h5",      "rtol": 1e-5},
            {"actual": "report.csv", "baseline": "ref/expected.csv", "rtol": 1e-6}
        ]
    }
}
```

### 项目入口脚本

如果你的项目需要自定义环境配置、预设运行参数或多格式报告输出，可以将 `examples/full_runner_example.py` 复制到项目根目录并重命名（如 `run_tests.py`）。它提供了一个功能完备的 Python 入口，自动识别 JSON/YAML 配置文件，支持所有 CLI 参数（`--last-failed`、`--resume`、`--update-baseline`、`--junit-xml`、`--workers`、`--var` 等）——非常适合团队共享的工作流。

```bash
python run_tests.py test_cases.json --workers 4 --junit-xml report.xml
```

## 核心使用场景

### 科学计算回归测试

用多格式 Golden File 对比定义求解器测试。当算法改动导致数值结果变化时，`--update-baseline` 刷新基线，git 帮你兜底。`--history-dir` 追踪耗时趋势，性能退化自动告警。

```bash
cli-test run fea_cases.json --history-dir ./hist --regression-threshold 2.0
```

### TDD + AI 协作循环

先写测试，定义好"什么叫正确"，跑一遍。框架的结构化输出——失败类型、详细 diff、容差违规——把测试失败变成了 LLM 的精确提示词。AI 修复代码后，用 `--last-failed` 只验证刚才失败的那几个用例。

```bash
cli-test run solver_tests.json                        # 3 个失败
# ... AI 根据结构化失败输出修复代码 ...
cli-test run solver_tests.json --last-failed           # 只验证那 3 个
cli-test run solver_tests.json                         # 全量回归确认
```

### CI/CD 集成

在 CI 环境中先校验配置（`cli-test validate config.json --output-format json`），再执行测试并输出 JUnit XML。`--workers` 并行执行，保持流水线速度。

```yaml
# .gitlab-ci.yml
test:
  script:
    - cli-test validate test_cases.json
    - cli-test run test_cases.json --parallel --workers 4 --junit-xml report.xml
  artifacts:
    reports:
      junit: report.xml
```

### 长耗时测试的迭代调试

对于每步要跑几分钟的多步仿真工作流：`--resume` 跳过已通过的步骤，直接从失败处继续。`--last-failed` 缩小范围。`--update-baseline` 按预期变更后刷新基线。

```bash
# BS-U_01 第 4/8 步失败后：
cli-test run config.json -t BS-U_01 --resume            # ~0.14s 而不是 72s
```

### 管理大型测试套件

测试用例上百后，用 `import` 拆分到多个文件，用 `extends` + `abstract` 共享公共结构，用 `--tag` 批量筛选，用 TUI 交互式浏览编辑。

```json
{
    "test_cases": [
        { "import": "cases/text_tests.json", "tags": ["text"] },
        { "import": "cases/h5_tests.json",   "tags": ["h5", "fast"] }
    ]
}
```

```bash
cli-test tui main_config.json
```

## Python API

```python
from cli_test_framework.runners import JSONRunner, ParallelJSONRunner

# 顺序运行
runner = JSONRunner(config_file="test_cases.json")
success = runner.run_tests()

# 并行运行
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,
    execution_mode="thread",
    history_dir="./hist",
    last_failed=False,
    resume=False,
    update_baseline=False,
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()

# 获取结果
runner.results["total"]
runner.results["passed"]
runner.results["failed"]
for detail in runner.results["details"]:
    print(detail["name"], detail["status"], detail.get("duration"))
```

## 文件比较（独立 CLI）

```bash
compare-files result1.h5 result2.h5 --h5-table-regex "output_.*" --h5-rtol 1e-5
compare-files data1.csv data2.csv --csv-rtol 1e-4 --csv-data-filter '>1e-6'
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

📖 **完整使用说明**：[docs/user_manual.md](docs/user_manual.md)

## 参与协作

欢迎各种形式的参与：

- **代码** — bug 修复、新功能、文档完善。Fork 本仓库，修改后提交 PR。请先确保测试通过：

  ```bash
  python tests/run_all.py
  ```

- **自定义比较器与插件** — 为你的领域专属数据格式写了比较器？欢迎提交到官方插件库。直接开 PR 或提 issue 讨论。

- **使用场景与经验分享** — 用框架解决了什么有意思的问题？在某个求解器或仿真管线上有什么经验？在 issue 里分享你的工作流——真实的用户故事能帮我们在正确的方向上改进框架。

- **Issues** — bug 报告、功能需求，或者只是提个问题，都欢迎。

## 许可证

MIT
