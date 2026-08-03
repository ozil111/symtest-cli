# 比较器插件开发指南

## 概述

CLI Test Framework 支持通过**工作区插件目录**扩展比较器能力。将 `*_comparator.py` 文件放入 workspace 的 `comparators/` 目录，框架会在首次运行时自动发现并注册。

## 快速开始

1. 在 workspace 下创建 `comparators/` 目录。
2. 新建 `your_comparator.py`，实现一个以 `*Comparator` 结尾的类，继承 `BaseComparator`。
3. 在用例配置的 `compare_files` 中使用你的类型名。

### 最简示例

**comparators/hello_comparator.py**:

```python
from symtest.file_comparator.base_comparator import BaseComparator
from symtest.file_comparator.result import ComparisonResult, Difference

class HelloComparator(BaseComparator):
    """最简自定义比较器：永远通过。"""

    def read_content(self, file_path, **kwargs):
        return None

    def compare_content(self, content1, content2):
        return True, [], False
```

**配置使用**:

```json
{
    "type": "hello",
    "actual": "output.txt",
    "baseline": "baseline.txt"
}
```

注册的 type 名 = 类名去掉 `Comparator` 再小写（此处 `HelloComparator` → `hello`）。

## 开发规范

### 基类接口

`BaseComparator` 提供三个核心方法：

| 方法 | 说明 |
|---|---|
| `read_content(file_path, ...)` | 读取文件内容，返回适合比较的数据结构 |
| `compare_content(content1, content2)` | 比较两个内容对象，返回 `(identical, differences, truncated)` |
| `compare_files(file1, file2, **kwargs)` | 高层入口，编排读取→比较→构造结果 |

对于不使用"两个文件对比"模型的比较器（如分析脚本），推荐**重写 `compare_files` 方法**，绕过文件 I/O：

```python
def compare_files(self, file1=None, file2=None, **kwargs):
    result = ComparisonResult(file1=file1 or "", file2=file2 or "")
    # 你的专用逻辑...
    result.identical = True
    result.command_output = capture_stdout  # 可选
    return result
```

### 结果构造

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

### 配置参数透传

配置 `compareSpec` 中 `actual`/`baseline`/`type`/`start_line`/`end_line`/`start_column`/`end_column` 之外的所有字段都会作为 `**kwargs` 透传给你的比较器构造函数：

```json
{
    "type": "myanalysis",
    "param1": "value1",
    "param2": 42
}
```

→

```python
class MyAnalysisComparator(BaseComparator):
    def __init__(self, param1="", param2=0, encoding="utf-8", **kwargs):
        super().__init__(encoding=encoding, **kwargs)
        self.param1 = param1
        self.param2 = param2
```

## 内置 `script` 类型

如果不想写 Python 类，可以用内置的 `script` 类型快速接入外部脚本。

配置示例：

```json
{
    "type": "script",
    "script": "analyze_xxx.py",
    "actual": "output.txt",
    "baseline": "baseline.txt",
    "pass_pattern": "RESULT: PASS",
    "timeout": 600
}
```

完整参数见 `docs/user_manual.md` 自定义文件比较器章节。

## hourglass_tangent 示例

`hourglass_tangent_comparator.py` 是一个完整的专用比较器范例，展示了：

- subprocess 调用外部分析脚本（零改动）
- 正则解析 stdout 提取结构化数值
- 构造 diffs + error_stats + command_output 的完整结果

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
