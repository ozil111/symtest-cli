# CLI Test Framework 设计文档

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI 入口                                 │
│     cli-test run / tui / validate / schema / compare-files       │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
       │          │          │          │          │
┌──────▼──────┐ ┌▼───────┐ ┌▼───────┐ ┌▼───────┐ ┌▼──────────────┐
│  TUI 管理   │ │ Runner │ │Config  │ │ File   │ │  Schema 输出   │
│  ┌────────┐ │ │ 体系   │ │ 验证   │ │Comparator│┌────────────┐ │
│  │CaseMgr │ │ │┌Base─┐│ │┌──────┐│ │┌Base─┐ ││JSON Schema │ │
│  │App     │ │ ││Runr ││ ││validate│ ││Comp │ ││ 输出       │ │
│  │Controller│ │ │├JSON││ ││_config│ ││├Text│ │└────────────┘ │
│  │Screens │ │ ││Runr ││ │└──────┘│ ││├Json│ │               │
│  │Widgets │ │ │├YAML││ │         │ ││├Csv │ │               │
│  └────────┘ │ ││Runr ││ │         │ ││├XML │ │               │
│             │ │└Paral││ │         │ ││├H5  │ │               │
└──────┬──────┘ │ │Runr─┼─┘         │ ││├Bin │ │               │
       │        │ │├P-JS│           │ ││├Scpt│ │               │
       │        │ ││OnRnr│          │ │└────┘ │               │
       │        │ │└P-YA│           │ │Factory│               │
       │        │ │MLRnr│           │ │+ 插件 │               │
       │        │ └─────┘           │ └───────┘               │
       │        └───────────────────┘                         │
       │                  │                                   │
┌──────▼──────────────────▼───────────────────────────────────┐
│                       Core 层                                │
│  TestCase │ Assertions │ ConfigLoader │ Execution │ Setup    │
│  ParallelRunner │ HistoryStore │ LastRunStore │ SequenceState│
│  PathResolver │ ReportGenerator │ JUnitXMLWriter            │
└─────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                    Config 管线                                │
│  raw JSON/YAML → expand_imports → resolve_inheritance        │
│  → apply_variables → substitute_placeholders → parse_test_cases│
└─────────────────────────────────────────────────────────────┘
```

框架分为四层：**CLI 入口层**（含 TUI）、**Runner / Comparator 业务层**、**Config 管线层**、**Core 基础层**。

## 2. 模块职责

### 2.1 目录结构

```
src/cli_test_framework/
├── __init__.py                  # 包入口，导出公共 API
├── cli.py                       # cli-test 命令入口（6 个子命令）
├── logging_config.py            # 统一日志配置
├── core/                        # 核心抽象与基础组件
│   ├── base_runner.py           # BaseRunner 抽象基类
│   ├── parallel_runner.py       # ParallelRunner 并行基类 + AtomicSemaphore
│   ├── config_loader.py         # 统一配置解析 + 序列执行
│   ├── execution.py             # 单测试执行 + 重试 + 文件比较断言
│   ├── process_worker.py        # 多进程 worker
│   ├── assertions.py            # 断言引擎（含 compare_files）
│   ├── setup.py                 # Setup 插件体系
│   ├── test_case.py             # TestCase / TestCaseStep 数据类
│   ├── history_store.py         # .symtest 历史记录存储
│   ├── last_run_store.py        # --last-failed 状态存储
│   ├── sequence_state.py        # --resume 步进断点续跑
│   └── types.py                 # TypedDict 类型定义
├── config/                      # 配置管线
│   ├── config_io.py             # load_config / save_config / validate_config
│   ├── config_schema.py         # JSON Schema（draft 2020-12）
│   ├── import_expander.py       # import 引用递归展开
│   └── inheritance_expander.py  # extends 继承 + 变量替换
├── runners/                     # 具体运行器
│   ├── config_runner.py         # ConfigRunner（通用顺序运行器）
│   ├── parallel_config_runner.py# ParallelConfigRunner（通用并行运行器）
│   ├── json_runner.py           # JSONRunner（薄封装）
│   ├── yaml_runner.py           # YAMLRunner（薄封装）
│   ├── parallel_json_runner.py  # ParallelJSONRunner（薄封装）
│   └── parallel_yaml_runner.py  # ParallelYAMLRunner（薄封装）
├── file_comparator/             # 文件比较子系统
│   ├── base_comparator.py       # BaseComparator 抽象基类
│   ├── result.py                # ComparisonResult / Difference
│   ├── factory.py               # ComparatorFactory 工厂 + 插件发现
│   ├── text_comparator.py       # 文本比较
│   ├── json_comparator.py       # JSON 比较
│   ├── csv_comparator.py        # CSV 比较
│   ├── xml_comparator.py        # XML 比较
│   ├── binary_comparator.py     # 二进制比较
│   ├── h5_comparator.py         # HDF5 比较
│   ├── script_comparator.py     # 外部脚本比较
│   └── comparators/             # 空目录，用于 workspace 插件
├── commands/                    # CLI 子命令
│   └── compare.py               # compare-files 入口
├── utils/                       # 工具模块
│   ├── path_resolver.py         # 路径解析
│   ├── report_generator.py      # 报告生成
│   └── junit_xml_writer.py      # JUnit XML 报告
└── tui/                         # Textual 终端 UI
    ├── app.py                   # CaseManagerApp + run_tui()
    ├── controllers/
    │   └── case_controller.py   # CaseController（CRUD + 搜索 + 运行）
    ├── screens/
    │   ├── case_list.py         # CaseListScreen（主界面）
    │   └── case_editor.py       # CaseEditorScreen（编辑表单）
    └── widgets/
        ├── case_table.py        # CaseTable（DataTable 封装）
        ├── search_bar.py        # SearchBar（多模式搜索）
        ├── expected_editor.py   # ExpectedEditor（expected 编辑）
        └── steps_editor.py      # StepsEditor（序列步骤编辑）
```

### 2.2 入口点

| 命令 | 映射 |
|---|---|
| `cli-test run` | `cli_test_framework.cli:run_tests` |
| `cli-test tui` | `cli_test_framework.tui.app:run_tui` |
| `cli-test validate` | `cli_test_framework.cli:run_validate` |
| `cli-test schema` | `cli_test_framework.cli:run_schema` |
| `cli-test compare` | `cli_test_framework.cli:run_compare` |

## 3. 配置管线

配置文件在加载时经过五步管线处理：

```
raw JSON/YAML 文件
    │
    ▼
expand_imports()          # 递归展开 import 引用（合并 setup、注入 tags）
    │
    ▼
resolve_inheritance()     # 解析 extends 继承链（deep-merge、去重 abstract）
    │
    ▼
apply_variables()         # 注入 --var 全局变量 + case-level variables
    │
    ▼
substitute_placeholders() # 递归替换 {placeholder} 占位符
    │
    ▼
parse_test_cases()        # 转换为 List[TestCase]（命令路径解析）
```

### 3.1 Import 展开 (`import_expander.py`)

支持主配置文件通过 `"import"` 引用子配置文件：

```json
{
  "test_cases": [
    { "import": "cases/text_tests.json", "tags": ["text", "fast"] },
    { "import": "cases/json_tests.yaml" },
    { "name": "inline_case", "command": "echo", ... }
  ]
}
```

- 递归展开所有 import，内联到主配置中
- import 级 tags 注入到子文件的每个 case
- setup 深度合并
- 循环引用检测

### 3.2 继承展开 (`inheritance_expander.py`)

支持 `extends` 字段实现用例模板继承：

```json
{
  "test_cases": [
    { "name": "_base", "abstract": true, "timeout": 3600, "expected": {"return_code": 0} },
    { "name": "my_test", "extends": "_base", "command": "solver", ... }
  ]
}
```

- 深度合并（dict）/ 整体替换（list）策略
- `abstract: true` 的模板不参与执行
- extends 链上的 `variables` 收集后统一替换
- 循环继承检测

### 3.3 配置验证 (`config_io.py`)

`cli-test validate` 子命令在不执行测试的情况下校验配置：

- Error 级（影响 valid）：JSON/YAML 语法、必填字段、import 目标存在性、循环引用、extends 目标存在性、循环继承
- Warning 级（不影响 valid）：命令可执行性（PATH 查找）、`compare_files` baseline 文件存在性

## 4. 核心类设计

### 4.1 Runner 继承体系

```
BaseRunner (ABC)
├── ConfigRunner              # 通用顺序运行器（可注入 config_loader）
│   ├── JSONRunner            # 薄封装（注入 json.load）
│   └── YAMLRunner            # 薄封装（注入 yaml.safe_load）
└── ParallelRunner
    └── ParallelConfigRunner  # 通用并行运行器（可注入 config_loader）
        ├── ParallelJSONRunner   # 薄封装
        └── ParallelYAMLRunner   # 薄封装
```

JSON/YAML Runner 的区别仅在于配置加载器，通用逻辑统一在 ConfigRunner / ParallelConfigRunner 中。

#### BaseRunner

所有 Runner 的抽象基类，定义测试执行的模板流程。

```python
class BaseRunner(ABC):
    def __init__(self, config_file: str, workspace: Optional[str] = None,
                 test_case_filter: Optional[List[str]] = None,
                 test_case_tag_filter: Optional[List[str]] = None,
                 history_dir: Optional[str] = None,
                 regression_threshold: float = 1.5,
                 update_baseline: bool = False,
                 update_history: bool = False,
                 error_analysis: bool = False,
                 last_failed: bool = False,
                 resume: bool = False,
                 plugin_dirs: Optional[List[str]] = None)
```

**模板方法 `run_tests()`**：

```
load_test_cases() → _apply_test_case_filter() → setup_manager.setup_all()
    → [run_single_test(case) for case in test_cases]  # 顺序执行
    → _update_history()  → _save_last_run()
    → setup_manager.teardown_all()
```

**关键属性**：

| 属性 | 类型 | 说明 |
|---|---|---|
| `workspace` | `Path` | 工作目录 |
| `test_cases` | `List[TestCase]` | 加载后的测试用例 |
| `results` | `Dict` | 运行结果 `{total, passed, failed, xfailed, xpassed, updated, details}` |
| `assertions` | `Assertions` | 断言引擎实例 |
| `setup_manager` | `SetupManager` | Setup 管理器 |
| `history_dir` | `Optional[str]` | `.symtest` 历史记录目录 |
| `regression_threshold` | `float` | 回归检测阈值倍数，默认 1.5 |
| `update_baseline` | `bool` | 比较失败时自动更新 baseline |
| `update_history` | `bool` | 清除历史后重新记录 |
| `error_analysis` | `bool` | CSV/H5 数值误差统计 |
| `last_failed` | `bool` | 仅运行上次失败的用例 |
| `resume` | `bool` | 序列用例从断点恢复 |

**抽象方法**：

| 方法 | 职责 |
|---|---|
| `load_test_cases()` | 解析配置文件，填充 `self.test_cases` |
| `run_single_test(case)` | 执行单个测试，返回结果字典 |

**过滤机制 `_apply_test_case_filter()`**：

支持三种过滤方式（可组合）：
- `test_case_filter`：按名称精确匹配
- `test_case_tag_filter`：按 tags 匹配（交集逻辑）
- `last_failed`：从 `.cli-test/last_run.json` 读取上次失败的用例名

**xfail 机制 `_apply_xfail_status()`**：

当 `case.expected_failure=True` 时：
- `passed` → `xpassed`（意外通过，计入失败）
- 任意非 passed 状态 → `xfailed`（预期失败，不计入失败）

#### ParallelRunner

继承 BaseRunner，覆写 `run_tests()` 为并行版本。

```python
class ParallelRunner(BaseRunner):
    def __init__(self, config_file, workspace=None,
                 max_workers=None, execution_mode="thread", ...)
```

- 线程模式：`ThreadPoolExecutor`，共享内存，支持资源调度
- 进程模式：`ProcessPoolExecutor` + `process_worker.run_test_in_process()`，进程隔离
- 线程安全：`_results_lock` / `_print_lock` 保护共享状态
- 回退方法：`run_tests_sequential()`

#### ParallelConfigRunner

在 ParallelRunner 基础上增加**资源感知调度**：

1. 加载用例后按 `estimated_time` 降序排序（LPT 策略）；若启用 `history_dir`，优先使用 `.symtest` 中的历史 `avg_duration` 排序
2. 创建 `AtomicSemaphore(safe_capacity)` 资源池，`safe_capacity = max(1, cpu_count - 2)`
3. 每个 case 执行前 acquire `cpu_cores` 个信号量，执行后 release
4. 自动注入 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`NPROC` 环境变量
5. `_assign_relative_cpu_cores()`：按 `estimated_time` 和 `min_memory_mb` 权重比例分配 CPU 核心数

### 4.2 TestCase 数据模型

```python
@dataclass
class TestCaseStep:
    command: str
    args: List[str]
    expected: Dict[str, Any]
    timeout: Optional[float] = None
    retry_count: int = 0

@dataclass
class TestCase:
    name: str
    command: str = ""
    args: List[str] = field(default_factory=list)
    expected: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    timeout: Optional[float] = None
    resources: Optional[Dict[str, Any]] = None
    steps: Optional[List[TestCaseStep]] = None
    tags: List[str] = field(default_factory=list)
    retry_count: int = 0
    expected_failure: bool = False
    xfail_reason: str = ""
    xfail_quiet: bool = False
```

两种模式：
- **单命令模式**：`command` + `args` + `expected`
- **步骤序列模式**：`steps` 列表，每个 step 含 `command` + `args` + `expected`

新增字段：
- `tags`：标签过滤
- `retry_count`：失败重试次数
- `expected_failure` / `xfail_reason` / `xfail_quiet`：预期失败标记

### 4.3 Assertions

```python
class Assertions:
    def return_code_equals(self, actual, expected) -> None    # 精确匹配
    def contains(self, output, expected_text) -> None         # 子串匹配
    def matches(self, output, expected_patterns) -> None      # 正则匹配
    def compare_files(self, actual_path, baseline_path, ...)  # 文件比较断言
```

断言逻辑：返回码精确匹配，`contains` 做子串匹配，`matches` 做正则匹配。所有断言均为可选，未指定的字段不做校验。

`compare_files` 在断言层面调用 ComparatorFactory，使文件比较成为一等断言。

### 4.4 Setup 插件体系

```python
class BaseSetup(ABC):
    def __init__(self, config: Dict)
    @abstractmethod
    def setup(self) -> None
    @abstractmethod
    def teardown(self) -> None

class EnvironmentSetup(BaseSetup):
    # setup(): 设置环境变量（保存旧值）
    # teardown(): 恢复环境变量

class SetupManager:
    def add_setup(self, setup: BaseSetup) -> None
    def setup_all(self) -> None      # 按添加顺序执行
    def teardown_all(self) -> None   # 逆序执行，保证即使出错也继续清理
```

**配置文件集成**：`load_setup_from_config()` 从 JSON/YAML 的 `setup.environment_variables` 字段自动创建 EnvironmentSetup 并注册。

### 4.5 PathResolver

```python
class PathResolver:
    SYSTEM_COMMANDS = {'echo', 'python', 'node', 'java', ...}

    def resolve_command(self, command: str) -> str
    def resolve_path(self, path: str) -> str
    def split_command(self, cmd_str: str) -> Tuple[str, List[str]]
```

职责：
- 系统命令原样返回，非系统命令拼接到 workspace 路径
- Shell builtin（echo/cd/export 等）自动包装为平台 shell 执行
- 复合命令（如 `"python ./script.py"`）拆分后分别解析

### 4.6 Execution

`execute_single_test_case(case, workspace)` — 单测试的执行函数：

1. PathResolver 解析命令和参数
2. `subprocess.run()` 执行，捕获 stdout/stderr/returncode
3. `validate_result()` 逐项校验（return_code / contains / matches / compare_files）
4. 支持失败自动重试（`retry_count` 次）
5. 超时时 kill 整个进程组
6. 返回结构化结果（含 `next_action_hint` 建议下一步操作）

### 4.7 HistoryStore

`.symtest` 历史记录存储模块，用于持久化每个 case 的运行时间，支持智能调度和回归检测。

```python
# .symtest 文件格式 (JSON):
# {
#   "version": 1,
#   "cases": {
#     "case_name": {
#       "avg_duration": 3.5,    # 累计平均耗时
#       "last_duration": 3.2,   # 最近一次耗时
#       "run_count": 5           # 运行次数
#     }
#   }
# }
```

核心接口：

| 函数 | 说明 |
|---|---|
| `ensure_symtest(history_dir)` | 如果目录下没有 `.symtest` 就创建 |
| `load_history(history_dir)` | 读取 `.symtest` |
| `save_history(history_dir, history)` | 写回 `.symtest` |
| `update_case(history, name, duration)` | 累计平均更新 |
| `reset_cases(history, case_names)` | 清除指定 case 的历史记录 |
| `check_regression(history, name, duration, threshold)` | 回归检测 |

### 4.8 LastRunStore

`--last-failed` 状态存储模块（`core/last_run_store.py`）：

```python
# 存储位置: <workspace>/.cli-test/last_run.json
# {
#   "case_name": {"status": "passed"},
#   ...
# }
```

核心接口：

| 函数 | 说明 |
|---|---|
| `update_last_run(workspace, results)` | 用当前运行结果覆写上次状态 |
| `get_last_failed_names(workspace)` | 返回上次失败/超时/xpassed 的用例名列表 |
| `get_last_run_summary(workspace)` | 返回上次运行的统计摘要 |

每次运行**覆写**参与执行的用例状态，未执行的保留旧状态。

### 4.9 SequenceState

`--resume` 断点续跑模块（`core/sequence_state.py`）：

```python
# 状态文件: <workspace>/.cli-test/sequence_state/<case_name>.json
# 输出缓存: <workspace>/.cli-test/sequence_state/cache/<case_name>.step<N>.log
```

核心接口：

| 函数 | 说明 |
|---|---|
| `compute_config_hash(steps, case_expected)` | 计算步骤配置的 SHA-256（检测配置变更） |
| `save_sequence_state(workspace, case_name, state)` | 保存步骤状态 |
| `load_sequence_state(workspace, case_name)` | 加载步骤状态 |
| `save_step_output(workspace, case_name, step_idx, output)` | 缓存步骤输出 |
| `load_step_output(workspace, case_name, step_idx)` | 读取缓存输出 |
| `delete_sequence_state(workspace, case_name)` | 全部通过后清理 |

**信任模型**：`--resume` 信任 workspace 产物未被修改，不进行 artifact 验证。

### 4.10 ReportGenerator

```python
class ReportGenerator:
    def print_report(self) -> None                   # 终端输出
    def generate_report(self) -> str                 # 返回文本字符串
    def generate_json_report(self) -> str            # JSON 格式
    def generate_html_report(self) -> str            # HTML 格式
```

### 4.11 JUnitXMLWriter

```python
def write_junit_xml(results: Dict, filepath: str,
                    suite_name: Optional[str] = None,
                    classname: Optional[str] = None) -> None
```

生成兼容 GitLab CI / Jenkins / CircleCI 的 JUnit XML 报告。

状态映射：
- `passed` → 无子元素（JUnit passed 约定）
- `xfailed` → `<skipped>`（预期失败）
- `xpassed` → `<failure>`（意外通过，标记为断言失败）
- `timeout` → `<error>`（超时）
- `failed` → 按消息类型分 `<failure>` 或 `<error>`

## 5. 文件比较子系统

### 5.1 类继承

```
BaseComparator (ABC)
├── TextComparator       # 基于 difflib 行级比较
│   ├── JsonComparator   # 按 key 字段对齐后比较
│   ├── CsvComparator    # CSV 结构化比较
│   └── XmlComparator    # XML 结构化比较
├── H5Comparator         # HDF5 科学数据比较
├── BinaryComparator     # 二进制流式分块 + LCS 相似度
└── ScriptComparator     # 委托外部脚本执行比较
```

### 5.2 BaseComparator

```python
class BaseComparator(ABC):
    def __init__(self, encoding="utf-8", chunk_size=8192, verbose=False)

    @abstractmethod
    def read_content(self, file_path, start_line, end_line, start_column, end_column)

    @abstractmethod
    def compare_content(self, content1, content2) -> Tuple[bool, List[Difference]]

    def compare_files(self, file1, file2, start_line, end_line,
                      start_column, end_column) -> ComparisonResult
```

### 5.3 ComparatorFactory

```python
class ComparatorFactory:
    @staticmethod
    def create_comparator(file_type: str, **kwargs) -> BaseComparator
    @staticmethod
    def register_comparator(file_type, comparator_class)
    @staticmethod
    def set_plugin_dirs(dirs)              # 设置 workspace 插件目录
    @staticmethod
    def get_available_comparators()        # 获取已注册比较器列表
    @staticmethod
    def reset()                            # 重置所有状态（测试用）
```

**插件发现机制**：

1. 自动发现内置 `*_comparator.py` 模块
2. 扫描 `workspace/comparators/` 目录（自动）
3. `--plugin-dir` CLI 参数指定额外目录
4. `CLITEST_PLUGIN_DIRS` 环境变量（进程模式 worker 使用）
5. 插件命名约定：`*_comparator.py` + `*Comparator` 类名

`file_type` 取值：`"text"` / `"json"` / `"csv"` / `"xml"` / `"h5"` / `"binary"` / `"script"`

### 5.4 ScriptComparator

委托外部脚本执行比较的新比较器类型：

```json
{
  "type": "script",
  "script": "analyze.py",
  "actual": "output.dat",
  "baseline": "baseline.dat",
  "pass_pattern": "PASS",
  "fail_pattern": "(MISMATCH|FAILED)"
}
```

- 执行 `python script.py <actual> <baseline>` 子进程
- 默认 exit code 0 → pass
- 可选 `pass_pattern` / `fail_pattern` 正则匹配 stdout 细化判定
- 支持 `timeout` 超时控制

### 5.5 ComparisonResult

```python
class ComparisonResult:
    file1: str
    file2: str
    identical: bool
    differences: List[Difference]
    error: Optional[str]
    command_output: Optional[str]    # ScriptComparator 的输出
    # 支持输出: str() / to_json() / to_html()
```

### 5.6 Error Analysis

`--error-analysis` 为 CSV/H5 数值比较提供流式误差统计：
- `total_numeric_cells`：比较的数值单元格总数
- `mismatched_cells`：不匹配单元格数
- `max_abs_error` / `max_rel_error`：最大绝对/相对误差
- `mean_abs_error` / `rms_abs_error`：平均绝对误差 / 均方根误差

## 6. TUI 子系统

基于 [Textual](https://textual.textualize.io/) 的终端交互界面。

```
cli-test tui test_cases.json --workspace /path/to/project
```

### 6.1 架构

```
CaseManagerApp (Textual App)
├── CaseController              # 业务逻辑层
│   ├── load()                  # 加载配置文件
│   ├── create_case()           # 创建用例
│   ├── update_case()           # 更新用例
│   ├── delete_case()           # 删除用例
│   ├── run_single()            # 运行单个用例
│   └── save()                  # 保存配置
├── Screens
│   ├── CaseListScreen          # 主界面：用例列表 + 搜索 + 操作
│   └── CaseEditorScreen        # 编辑表单：单命令 / 序列步骤
└── Widgets
    ├── CaseTable               # DataTable 封装（名称/命令/状态列）
    ├── SearchBar               # 名称/命令/标签多模式搜索
    ├── ExpectedEditor          # expected 断言配置编辑
    └── StepsEditor             # 多步骤序列编辑
```

### 6.2 快捷键

| 按键 | 功能 |
|---|---|
| `q` / `Ctrl+Q` | 退出 |
| `r` | 刷新列表 |
| `e` | 编辑选中用例 |
| `f` | 执行选中用例 |
| `/` | 搜索 |
| `a` | 添加新用例 |
| `d` | 删除选中用例 |
| `s` | 保存配置 |

## 7. 数据流

### 7.1 测试执行流

```
配置文件 (JSON/YAML)
       │
       ▼
  expand_imports()           # import 引用展开
       │
       ▼
  resolve_inheritance()      # extends 继承解析
       │
       ▼
  apply_variables()          # 全局变量 + 用例变量注入
       │
       ▼
  substitute_placeholders()  # {placeholder} 替换
       │
       ▼
  parse_test_cases()         # 解析为 List[TestCase]
       │
       ▼
  _apply_test_case_filter()  # 按名称/tags/--last-failed 过滤
       │
       ▼
  setup_manager.setup_all()  # 环境变量 + 自定义插件
       │
       ▼
  [如果 history_dir] load .symtest → 读取历史 avg_duration（用于调度排序）
       │
       ▼
  ┌──────────────────────────────────────┐
  │  for each TestCase:                  │
  │    PathResolver 解析命令              │
  │    subprocess.run() 执行             │
  │    validate_result() 逐项校验         │
  │      ├── return_code_equals          │
  │      ├── contains (输出子串)          │
  │      ├── matches (正则匹配)           │
  │      └── compare_files (文件比较)     │
  │    [如果失败且 retry_count > 0] 重试  │
  │    收集到 results["details"]          │
  └──────────────────────────────────────┘
       │
       ▼
  _apply_xfail_status()      # xfail 状态映射
       │
       ▼
  _update_history()          # 回归检测 + 更新 .symtest
       │
       ▼
  _save_last_run()           # 写入 .cli-test/last_run.json
       │
       ▼
  setup_manager.teardown_all() # 逆序清理
       │
       ▼
  ReportGenerator / write_junit_xml()   # text / json / html / JUnit XML
```

### 7.2 并行执行流

```
ParallelConfigRunner.run_tests()
       │
       ▼
  LPT 排序 (历史 avg_duration 优先，fallback 到 estimated_time 降序)
       │
       ▼
  _assign_relative_cpu_cores()  # 按权重比例分配 CPU 核心
       │
       ▼
  ┌──────────────────────────────────────┐
  │  ThreadPoolExecutor.map():           │
  │    AtomicSemaphore.acquire(cores)    │
  │    注入 OMP/MKL/NPROC 环境变量       │
  │    execute_single_test_case()        │
  │    AtomicSemaphore.release(cores)    │
  │    _update_results() (线程安全)      │
  └──────────────────────────────────────┘
```

### 7.3 文件比较流

```
cli-test compare file1 file2 [options]
       │
       ▼
  自动检测 / 指定 --file-type
       │
       ▼
  ComparatorFactory.create_comparator(file_type, **kwargs)
       │
       ▼
  comparator.compare_files(file1, file2, ...)
       │
       ├── read_content() × 2
       ├── compare_content()
       └── ComparisonResult
       │
       ▼
  format_result(result, --output-format)  # text / json / html
```

### 7.4 --resume 断点续跑流

```
序列测试用例执行
       │
       ▼
  [--resume 启用] compute_config_hash(steps)
       │
       ▼
  load_sequence_state()  → 检查配置哈希是否匹配
       │
       ├── 匹配 → 跳过已过步骤，拼接缓存输出
       └── 不匹配 → 全量执行
       │
       ▼
  每步 pass → save_sequence_state() + save_step_output()
       │
       ▼
  全部 pass → delete_sequence_state() (清理)
```

## 8. 扩展点

| 扩展点 | 基类 | 用途 |
|---|---|---|
| 新配置格式 | `BaseRunner` | 支持新的测试定义格式（如 XML、TOML） |
| 自定义 Setup | `BaseSetup` | 数据库初始化、服务启停等 |
| 自定义断言 | 扩展 `Assertions` | 特定业务校验逻辑 |
| 新比较器 | `BaseComparator` | 支持新的文件格式比较，放入 `comparators/` 目录自动发现 |
| 新 Runner | `ParallelRunner` / `BaseRunner` | 自定义并行调度策略 |
| TUI 扩展 | `CaseController` / Widgets | 扩展终端管理界面 |

## 9. 设计决策

| 决策 | 原因 |
|---|---|
| Runner 用模板方法模式 | 统一执行流程（load → filter → setup → run → history → last-run → teardown），子类只需实现配置解析和单测试执行 |
| Config 管线化处理 | import/extends/variables 正交分解，每步职责单一，可独立测试和组合 |
| JSON/YAML Runner 统一为 ConfigRunner | 消除代码重复，通过注入 config_loader 适配不同格式 |
| Setup 逆序 teardown | 类似栈语义，后初始化的依赖先清理 |
| 信号量管理 CPU 核心 | 比线程池 worker 数更精细，允许不同 case 声明不同核心需求 |
| LPT 调度策略 | 长任务先启动，减少尾延迟；优先使用 `.symtest` 历史数据 |
| 累计平均更新历史 | 直觉简单，随运行次数增多单次异常自然稀释 |
| 回归检测在更新前执行 | 先与旧均值比较再更新，确保对比的是"历史基线" |
| `.symtest` 隐藏文件 + `.cli-test/` 目录 | 不干扰用户目录视图，JSON 格式便于调试；状态文件统一管理 |
| 环境变量注入 | 科学计算求解器常忽略 Python 级线程控制 |
| Comparator 工厂 + 插件发现 | 按文件类型创建比较器，workspace `comparators/` 目录自动发现插件 |
| subprocess 隔离执行 | 每个 test case 独立子进程，保证测试间互不影响 |
| xfail 机制 | 支持预期失败的测试（CI 中不阻塞流水线），意外通过时告警 |
| --last-failed 覆写策略 | 只覆写本次执行的用例状态，避免子集运行时丢失未执行用例的状态 |
| --resume 纯信任模型 | 不验证 artifact，由用户保证 workspace 未被修改，简化实现 |
| retry_count 重试机制 | 应对偶发性网络抖动或竞态条件，首次失败后自动重试 |
| --update-baseline | 比较失败时自动将实际输出覆盖 baseline，适合批量更新基准 |
| next_action_hint 结构化建议 | 失败结果附带下一步操作建议（update_baseline / update_expected / increase_timeout / investigate），便于 AI 消费 |
| TUI 基于 Textual | 利用成熟的终端 UI 框架，提供交互式用例管理 |
| JUnit XML 输出 | 兼容 GitLab CI / Jenkins / CircleCI 等主流 CI 系统的测试报告格式 |
| Logging 统一化 | 通过 `logging` 模块集中管理，CLI 入口激活控制台输出，库用户按需启用 |
