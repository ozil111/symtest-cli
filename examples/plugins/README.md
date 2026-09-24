# 比较器插件开发指南

## 概述

CLI Test Framework 支持通过**工作区插件目录**扩展比较器能力。将 `*_comparator.py` 文件放入 workspace 的 `comparators/` 目录，框架会在首次运行时自动发现并注册。

比较器插件体系（v2）围绕根契约 `ComparatorBase.compare(ctx) -> ComparisonResult` 组织，
按判定权归属分为**三条泳道**：

| 泳道 | 基类 | 适用场景 | verdict 归属 |
|---|---|---|---|
| 文件泳道 | `FileComparator` | 比较两个同类文件（text/json/csv/xml/h5/binary 内置即此类） | 插件 |
| 数据泳道 | `ExtractorComparator` | 提取数值数据（可多通道），框架按 per-channel 容差判定 | **框架** |
| 自主泳道 | 直接继承 `ComparatorBase` | 独特判定逻辑（阈值组合、标签解析、渐近分析等） | 插件 |

## 快速开始

1. 在 workspace 下创建 `comparators/` 目录。
2. 新建 `your_comparator.py`，按泳道选择基类，实现一个以 `*Comparator` 结尾的类。
3. 在用例配置的 `compare_files` 中使用你的类型名。

### 最简示例（自主泳道）

**comparators/hello_comparator.py**:

```python
from symtest.file_comparator.base_comparator import BaseComparator, CompareContext
from symtest.file_comparator.result import ComparisonResult

class HelloComparator(BaseComparator):
    """最简自定义比较器：永远通过。"""

    def compare(self, ctx: CompareContext) -> ComparisonResult:
        result = ComparisonResult(
            file1=str(ctx.baseline or ""), file2=str(ctx.actual or "")
        )
        result.identical = True
        return result
```

**配置使用**:

```json
{
    "type": "hello",
    "actual": "output.txt",
    "baseline": "baseline.txt"
}
```

注册的 type 名 = 类名去掉 `Comparator` 再小写（此处 `HelloComparator` → `hello`）；
也可用类属性 `comparator_type` 显式指定。

> v2 breaking 说明：根基类不再有 `read_content`/`compare_content` 抽象方法，
> 也不要再覆写 `compare_files`——唯一契约是 `compare(ctx)`。

## 开发规范

### 根契约与上下文

`ComparatorBase` 的唯一抽象方法是 `compare(ctx)`。`CompareContext` 字段：

| 字段 | 说明 |
|---|---|
| `workspace` | workspace 根目录 |
| `actual` / `baseline` | 命令输出 / 基准文件路径（无文件输入时为 `None`，构造前已按 workspace 解析） |
| `params` | 调用级参数（文件泳道窗口范围）；**不携带比较器配置副本** |
| `error_analysis` | 是否启用误差统计（`--error-analysis`） |

**路径解析**：`actual`/`baseline` 以及插件 `path_params` 类属性声明的路径参数
由框架在**构造之前**按 workspace 解析——构造器捕获的状态已是绝对路径。
插件内部**禁止**对 CWD 做 `Path.resolve()`。

**严格配置**：构造器参数显式声明；未声明/拼错的配置键在构造时大声失败
（错误含比较器类型名与支持参数清单）。自由参数仅限插件显式 `**params` opt-in。
插件自有配置建议放 `options` compareSpec 键（并入构造参数，顶层键优先）。

### 数据泳道：通道提取器

只需实现 `extract(ctx)`，返回 `{channel_name: ChannelData}`，判定全部由框架完成：

```python
import numpy as np
from symtest.file_comparator import ExtractorComparator, ChannelData, CompareContext

class MyExtractor(ExtractorComparator):
    path_params = ("ref_csv", "actual_csv")

    def __init__(self, ref_csv="", actual_csv=""):
        super().__init__()
        self.ref_csv, self.actual_csv = ref_csv, actual_csv

    def extract(self, ctx):
        ref = np.loadtxt(self.ref_csv, delimiter=",")
        act = np.loadtxt(self.actual_csv, delimiter=",")
        return {
            "S11": ChannelData(expected=ref[:, 0], actual=act[:, 0]),
            "S33": ChannelData(
                expected=ref[:, 2], actual=act[:, 2],
                extra_stats={"note": "自定义误差指标并入 stats"},
            ),
        }
```

配置（per-channel 容差按名路由，未声明通道用 `default_channel`）：

```json
{
    "type": "myextractor",
    "ref_csv": "out/ref.csv",
    "actual_csv": "out/act.csv",
    "channels": {"S33": {"atol": 600.0, "data_filter": "abs>1e-12"}},
    "default_channel": {"rtol": 1e-5, "atol": 1e-8}
}
```

结果语义：`identical = 所有通道全过`；差异 position 带通道前缀；
`error_stats` 按通道名嵌套；报告逐通道展示 pass/fail。

### 结果构造（自主泳道）

使用 `ComparisonResult` 和 `Difference` 构造结构化结果：

```python
from symtest.file_comparator.result import ComparisonResult, Difference

result = ComparisonResult()
result.identical = False
result.differences = [
    Difference(position="metric_name", expected="< 1e-6", actual="5.0e-03", diff_type="threshold_exceeded"),
]
result.error_stats = {
    "full_rel": 5.0e-03,
    "aa_rel": 1.23e-02,
    "hh_rel": 3.45e-03,
}
result.command_output = "stdout from subprocess"  # 在报告中渲染
return result
```

### 配置参数（严格校验）

配置 `compareSpec` 中 `actual`/`baseline`/`type` 之外的键会作为
`**kwargs` 传给你的比较器构造函数，但**参数是严格的**：构造器未声明的键
（如拼写错误 `pass_threhsold`）会抛出带类型名与支持参数清单的
`TypeError`，绝不静默回退到默认值。插件自有配置推荐放 `options`
命名空间（并入构造参数，显式顶层键优先）：

```json
{
    "type": "myanalysis",
    "options": {"param1": "value1", "param2": 42}
}
```

→

```python
class MyAnalysisComparator(BaseComparator):
    def __init__(self, param1="", param2=0):
        super().__init__()   # 根类不再接收/忽略任意 kwargs
        self.param1 = param1
        self.param2 = param2
```

## 零改动脚本接入

不想写 Python 类时的两种内置方式：

| 类型 | 判定归属 | 协议 |
|---|---|---|
| `script` | 脚本（exit code + pass/fail pattern） | 子进程执行，exit 0 → 通过 |
| `script_extract` | 框架（per-channel 容差） | 子进程执行，stdout 打印 JSON：`{"channels": {name: {"expected": [...], "actual": [...]}}}` |

`script_extract` 的错误语义：非零退出码、超时、畸形 JSON 一律判为比较 error
（绝不静默通过）。完整协议见 `docs/user_manual.md` 自定义文件比较器章节。

## hourglass_tangent 示例

`hourglass_tangent_comparator.py` 是一个完整的自主泳道范例，展示了：

- subprocess 调用外部分析脚本（零改动）
- 正则解析 stdout 提取结构化数值
- 构造 diffs + error_stats + command_output 的完整结果
- `path_params` 声明路径参数由框架解析

使用方法：

```json
{
    "type": "hourglass_tangent",
    "script": "case/.../analyze_HG-M1_D1_A1e-4_tangent.py",
    "case_dir": "case/.../HG-M1_D1_A1e-4",
    "pass_threshold": 1e-6,
    "timeout": 600
}
```

## CLI 参数

```bash
# 指定额外插件目录（可多次使用）
symtest run test_config.json --plugin-dir ./extra_plugins

# workspace/comparators/ 始终自动探测，无需手动指定
```

## entry points（后续迭代）

`pip install` 即生效的 entry point 插件体系将在后续迭代中支持，届时自定义比较器可作为独立 Python 包分发。
