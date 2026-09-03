# CLI Test Framework 使用说明书

## 目录

- [安装](#安装)
- [测试用例定义](#测试用例定义)
- [Case 级环境变量](#case-级环境变量env)
- [配置拆分机制](#配置拆分机制)
- [配置继承](#配置继承)
- [配置校验](#配置校验)
- [TUI 交互式管理器](#tui-交互式管理器)
- [运行测试](#运行测试)
- [项目入口脚本](#项目入口脚本)
- [占位符（变量替换）](#占位符变量替换)
- [标签过滤](#标签过滤)
- [Setup 模块](#setup-模块)
- [并行测试](#并行测试)
- [顺序步骤测试](#顺序步骤测试)
- [资源感知调度](#资源感知调度)
- [历史记录与回归检测](#历史记录与回归检测)
- [JUnit XML 报告](#junit-xml-报告)
- [日志配置](#日志配置)
- [文件比较](#文件比较)
- [扩展开发](#扩展开发)
- [运行框架自带测试](#运行框架自带测试)

## 安装

```bash
pip install symtest-cli
```

要求：Python >= 3.9

YAML 支持需安装可选依赖：

```bash
pip install "symtest-cli[yaml]"
```

一次安装 YAML 和 TUI 等全部可选功能：

```bash
pip install "symtest-cli[all]"
```

HDF5 文件比较依赖 `h5py`（已随框架安装）。如需在无 HDF5 环境下使用其他比较功能，可单独卸载，但 HDF5 比较将不可用。

## 测试用例定义

> **Schema v2（1.4）**：配置采用分层 DSL——执行相关字段（`command`、`args`、`timeout`、`retry_count`、`env`、`steps`）位于 `execution` 块，调度相关字段（`depends_on`、`resources`）位于 `scheduling` 块，`expected` 保持在顶层。旧的扁平布局已移除，可使用 `symtest migrate` 迁移。迁移会递归处理整棵 `import` 树：默认为每个文件生成 `<stem>.v2<ext>` 副本并自动重写父文件中的 import 路径；`--in-place` 则原地覆盖所有文件（与 `--output` 互斥）。

### JSON 格式

```json
{
    "test_cases": [
        {
            "name": "测试名称",
            "execution": {
                "command": "echo",
                "args": ["Hello"],
                "timeout": 60,
                "retry_count": 0
            },
            "scheduling": {
                "resources": {
                    "cpu_cores": 2,
                    "estimated_time": 300,
                    "min_memory_mb": 1024,
                    "priority": 5
                }
            },
            "expected": {
                "return_code": 0,
                "output_contains": ["Hello"],
                "output_matches": ".*regex.*",
                "compare_files": [
                    {
                        "actual": "output.txt",
                        "baseline": "baseline.txt",
                        "type": "text"
                    }
                ]
            }
        },
        {
            "name": "已知失败的测试",
            "execution": {
                "command": "echo",
                "args": ["should_fail"]
            },
            "expected_failure": true,
            "xfail_reason": "Bug #42 尚未修复",
            "expected": { "return_code": 1 }
        }
    ]
}
```

### YAML 格式

```yaml
test_cases:
  - name: 测试名称
    execution:
      command: echo
      args: ["Hello"]
      timeout: 60
      retry_count: 0
    scheduling:
      resources:
        cpu_cores: 2
        estimated_time: 300
        min_memory_mb: 1024
        priority: 5
    expected:
      return_code: 0
      output_contains:
        - "Hello"
      output_matches: ".*regex.*"
      compare_files:
        - actual: output.txt
          baseline: baseline.txt
          type: text

  - name: 已知失败的测试
    execution:
      command: echo
      args: ["should_fail"]
    expected_failure: true
    xfail_reason: "Bug #42 尚未修复"
    xfail_quiet: true
    expected:
      return_code: 1
```

### 预期失败（xfail）

当存在已知缺陷导致某用例无法通过时，可标记 `expected_failure: true`，框架会区分"预期中的失败"与"意外的通过"：

| 场景 | 状态 | 退出码影响 | 说明 |
|---|---|---|---|
| xfail 标记 + 确实失败 | `xfailed` | 不计数为失败 | 报告展示 `xfail_reason`，详情照常输出（可通过 `xfail_quiet` 抑制 Command Output） |
| xfail 标记 + 意外通过 | `xpassed` | **计入失败** | 报告高亮提示"移除 xfail 标记" |

这与 pytest 的 xfail 语义一致。搭配 `--last-failed` 时，xfailed 不会进入重跑集，xpassed 会进入。

```json
{
    "name": "已知Bug",
    "execution": {
        "command": "solver",
        "args": ["--input", "bug_case.dat"]
    },
    "expected_failure": true,
    "xfail_reason": "Bug #42: 边界条件处理错误，预计 v2.1 修复",
    "expected": { "return_code": 1 }
}
```

当 xfailed 用例的输出非常冗长（如数百行求解器日志）且重复出现，干扰报告阅读时，可添加 `xfail_quiet: true` 让报告 **只保留原因和命令，不输出 Command Output**。其余元信息（Description、Expected、Command、Return Code、Error Message、Compare Failures、Step Results 等）照常展示：

```json
{
    "name": "已知Bug（静默模式）",
    "execution": {
        "command": "solver",
        "args": ["--input", "bug_case.dat"]
    },
    "expected_failure": true,
    "xfail_reason": "Bug #42: 边界条件处理错误，预计 v2.1 修复",
    "xfail_quiet": true,
    "expected": { "return_code": 1 }
}
```

### 测试依赖（depends_on）

当测试用例之间存在先后依赖时（例如 D 需要 A、B、C 先生成数据），通过 `depends_on` 声明依赖关系，框架会自动按 DAG 拓扑顺序调度：

**并行模式**：A、B、C 并行执行，全部通过后 D 才被提交。依赖失败的用例会自动 skip 其下游（级联 skip）。

**顺序模式**：框架按拓扑序重排用例，保证依赖在前的先执行，依赖失败时同样跳过下游。

**JSON 示例**：

```json
{
    "test_cases": [
        { "name": "A", "execution": { "command": "python", "args": ["gen_a.py"] }, "expected": {"return_code": 0} },
        { "name": "B", "execution": { "command": "python", "args": ["gen_b.py"] }, "expected": {"return_code": 0} },
        { "name": "C", "execution": { "command": "python", "args": ["gen_c.py"] }, "expected": {"return_code": 0} },
        {
            "name": "D",
            "execution": { "command": "python", "args": ["merge.py"] },
            "scheduling": { "depends_on": ["A", "B", "C"] },
            "expected": {"return_code": 0, "compare_files": [{"file": "output.h5", "type": "hdf5"}]}
        }
    ]
}
```

**YAML 示例**：

```yaml
test_cases:
  - name: A
    execution:
      command: python
      args: ["gen_a.py"]
    expected: { return_code: 0 }

  - name: B
    execution:
      command: python
      args: ["gen_b.py"]
    expected: { return_code: 0 }

  - name: C
    execution:
      command: python
      args: ["gen_c.py"]
    expected: { return_code: 0 }

  - name: D
    execution:
      command: python
      args: ["merge.py"]
    scheduling:
      depends_on: [A, B, C]
    expected:
      return_code: 0
      compare_files:
        - file: output.h5
          type: hdf5
```

**调度语义**：

| 依赖状态 | 下游行为 |
|---|---|
| `passed` 或 `xfailed` | 依赖"满足"，下游正常执行 |
| `failed` 或 `xpassed` | 依赖"不满足"，下游标记为 `skipped`，并级联 skip |
| 存在循环依赖 | 配置校验阶段报错，禁止运行 |

`skipped` 不计入 `failed` 计数，在报告摘要中单独显示 `Skipped: N`。

**约束**：
- 依赖名称必须在同配置文件的 `test_cases` 中存在
- 不允许自依赖（`depends_on: ["self"]`）
- 不允许循环依赖（A → B → A）
- 与 `steps` 模式互不影响——`depends_on` 是用例级概念，`steps` 是用例内步骤级概念
- 无依赖时走 fast path，调度开销为零

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 测试用例名称 |
| `execution.command` | 是 | 要执行的命令（支持带参数的命令字符串，如 `python ./run.py`，框架会自动拆分并解析路径） |
| `execution.args` | 否 | 命令参数列表 |
| `description` | 否 | 测试用例描述 |
| `execution.timeout` | 否 | 超时秒数，默认 3600，设 `null` 无限制 |
| `execution.retry_count` | 否 | 失败自动重试次数，默认 0（不重试）。单命令模式作用于整个 case，步骤模式可作用于每个 step。重试后通过会在结果中标记 `flaky: true` |
| `tags` | 否 | 标签列表，用于批量过滤（如 `["smoke", "fast"]`） |
| `scheduling.resources` | 否 | 资源配置，见[资源感知调度](#资源感知调度) |
| `expected_failure` | 否 | 标记为预期失败（xfail）。设为 `true` 时，失败计为 XFailed（不影响退出码），意外通过计为 XPassed（视作失败） |
| `xfail_reason` | 否 | xfail 的原因说明，报告中将展示此文本（如 "Bug #42 尚未修复"） |
| `xfail_quiet` | 否 | 设为 `true` 时，xfailed 状态下报告中不输出 Command Output（stdout/stderr 大段输出），仅保留命令、返回码、失败原因等元信息 |
| `scheduling.depends_on` | 否 | 依赖的测试用例名称列表（如 `["A", "B"]`）。当前用例必须等待所有依赖用例通过后才执行。依赖失败时自动 skip 当前用例及下游。支持并行和顺序两种 runner |
| `execution.env` | 否 | case 级环境变量字典（如 `{"MYAPP_SCALE": "1.0"}`），定义在 `execution` 内，仅在执行该 case（序列模式为所有 step）时注入子进程，见 [Case 级环境变量](#case-级环境变量env) |
| `expected.return_code` | 否 | 期望返回码 |
| `expected.output_contains` | 否 | 输出需包含的字符串列表 |
| `expected.output_matches` | 否 | 输出需匹配的正则表达式（单个字符串） |
| `expected.compare_files` | 否 | 文件比较断言列表，见下文 |

### execution 二选一（互斥）

`execution` 有两种形态，**二选一**且互斥，同时声明两种形态属于配置错误：

- **单命令形态**：`command` + `args`（`timeout` / `retry_count` / `env` 可选）
- **序列形态**：`steps`（列表，每个 step 为 `command + args + expected`）；`command` / `args` 不得与 `steps` 并存

## Case 级环境变量（env）

通过 `execution` 内与 `command`、`steps` 同级的 `env` 字段，可为单个用例注入环境变量，仅在该用例（序列模式为所有 step）的子进程内生效，不影响其他用例。

### JSON

```json
{
    "name": "case 级环境变量示例",
    "execution": {
        "command": "solver",
        "args": ["-i", "input.dat"],
        "env": {
            "MYAPP_SCALE": "1.0",
            "OMP_NUM_THREADS": "8"
        }
    },
    "expected": { "return_code": 0 }
}
```

### YAML

```yaml
- name: case 级环境变量示例
  execution:
    command: solver
    args: ["-i", "input.dat"]
    env:
      MYAPP_SCALE: "1.0"
  expected: { return_code: 0 }
```

### 序列模式

`env` 定义在 `execution` 内（与 `steps` 同级），对该 case 的**所有 step** 生效：

```json
{
    "name": "多步骤+环境变量",
    "execution": {
        "env": { "MYAPP_SCALE": "1.0" },
        "steps": [
            { "command": "python", "args": ["./step1.py"], "expected": { "return_code": 0 } },
            { "command": "python", "args": ["./step2.py"], "expected": { "return_code": 0 } }
        ]
    }
}
```

### 语义

| 决策点 | 行为 |
|---|---|
| 生效方式 | 通过子进程 `env` 注入，不修改进程全局 `os.environ`，天然进程隔离、线程安全 |
| 优先级 | `os.environ`（含 `setup.environment_variables`）< 调度器注入（`OMP/MKL/NPROC`）< **case `env`（最高）**，即 case env 可覆盖调度器的 `OMP_NUM_THREADS` |
| 作用范围 | 仅当前 case，不污染其他 case（区别于全局 `setup.environment_variables`） |
| 占位符 | 自动支持，`"env": {"SCALE": "{scale}"}` 会被 `variables`/`--var` 替换 |
| 继承（extends） | 自动支持，`env` 为 dict，深合并、子类覆盖父类同名 key |
| 值类型 | 字符串；数字/布尔在解析时自动 `str()` 化 |

### 文件比较断言（compare_files）

在 `expected` 中通过 `compare_files` 可声明一条或多条文件比较规则，框架会在命令执行后自动用对应的比较器对比实际产出文件与基线文件。所有比较通过才算用例通过，可与 `return_code`、`output_contains` 等断言共存。

每个比较规则的字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `actual` | 是 | 测试命令产出的文件路径（相对路径按 workspace 解析） |
| `baseline` | 是 | 基线/参考文件路径（相对路径按 workspace 解析） |
| `type` | 否 | 比较器类型：`text`、`json`、`csv`、`xml`、`h5`、`binary`；省略时按扩展名自动识别 |
| `start_line` | 否 | 起始行号（1-based），仅比较该行及之后的内容 |
| `end_line` | 否 | 结束行号（1-based），比较到该行为止 |
| `start_column` | 否 | 起始列号（1-based），仅比较该列及之后的内容 |
| `end_column` | 否 | 结束列号（1-based），比较到该列为止 |
| 其他 | 否 | 透传给对应比较器的参数，如 `rtol`、`atol`、`encoding`、`tables`、`data_filter` 等 |

```json
"expected": {
    "return_code": 0,
    "compare_files": [
        {
            "actual": "result.h5",
            "baseline": "baseline/result.h5",
            "type": "h5",
            "rtol": 1e-5,
            "atol": 1e-8,
            "tables": ["/stress", "/displacement"]
        },
        {
            "actual": "summary.csv",
            "baseline": "baseline/summary.csv"
        }
    ]
}
```

## 配置拆分机制

当测试项目规模增长、用例数量达到数十甚至数百条时，单个配置文件可能变得难以维护。配置拆分机制允许将大文件按模块/功能拆分为多个子文件，通过 `import` 引用组装，运行时自动合并加载。

### 主配置文件

在主配置文件中，通过 `"import"` 字段引用子文件。`import` 是 `test_cases` 数组中的一个特殊元素，框架会在加载时将其**展开替换**为子文件的测试用例：

```json
{
    "setup": {
        "environment_variables": {
            "PYTHONPATH": "./src"
        }
    },
    "test_cases": [
        {
            "name": "内联测试用例",
            "execution": {
                "command": "echo",
                "args": ["hello"]
            },
            "expected": { "return_code": 0 }
        },
        { "import": "cases/text_tests.json", "tags": ["text"] },
        { "import": "cases/json_tests.yaml" },
        { "import": "cases/h5_tests.json", "tags": ["h5", "fast"] }
    ]
}
```

> **注意**：`import` 路径相对**主配置文件所在目录**解析，不相对当前工作目录（cwd）。这保证了配置文件的可移植性——无论从哪个目录运行测试，拆分关系都不受影响。

### 子文件格式

子文件结构与主文件一致，顶层同样是 `test_cases` 数组（可包含 `setup`）：

```json
{
    "test_cases": [
        {
            "name": "text_identical",
            "execution": {
                "command": "python",
                "args": ["./compare_text.py"]
            },
            "expected": { "return_code": 0 },
            "tags": ["text"]
        },
        {
            "name": "text_diff",
            "execution": {
                "command": "python",
                "args": ["./compare_text.py", "--mode", "diff"]
            },
            "expected": { "return_code": 1 },
            "tags": ["text"]
        }
    ]
}
```

### Import 级标签（Tags）

当一个子文件中的所有用例都标记有相同的标签（如 `"text"`）时，无需在每个 case 里重复编写 `tags`。可以直接在 `import` 条目上添加 `tags`，框架会自动将标签注入到该文件导入的每一条用例：

```json
{ "import": "cases/text_tests.json", "tags": ["text", "fast"] }
```

**合并规则**：

| 场景 | 结果 |
|---|---|
| import 有 tags，子用例无 tags | 子用例继承 import 的所有 tags |
| import 有 tags，子用例也有 tags | 合并去重，import 的 tags 在前，子用例自有的在后 |
| import 无 tags | 行为不变，向后兼容 |

> 嵌套 import（子文件内部继续 import 其他文件）也适用此规则——外层 import 的 tags 会注入到**所有**递推展开后的用例上。

### 工作原理

1. **加载时展开**：Runner 在读取配置文件后、解析 `TestCase` 对象前，自动执行 import 展开。对 Runner 和执行引擎**完全透明**，无需修改测试用例或 Runner 代码。
2. **递归展开**：子文件内可以继续 `import` 其他文件，支持多层嵌套。
3. **循环引用保护**：框架维护已加载文件路径集合，检测到循环引用时抛出明确错误。
4. **向后兼容**：不含 `import` 字段的配置文件行为与之前完全一致，零迁移成本。

### 跨格式支持

主配置为 JSON 时可以 import YAML 子文件，反之亦然。框架根据子文件扩展名（`.json` / `.yaml` / `.yml`）自动选择解析器。

### Setup 合并规则

如果主文件和子文件都定义了 `setup`，它们会深度合并（deep merge）：
- **同名变量冲突**：子文件的 `setup` 覆盖主文件的同名字段。
- **环境变量**：合并为一个字典，子文件优先。

```json
// 主文件 setup
{ "environment_variables": { "BASE": "from_main", "OVERRIDE": "from_main" } }

// 子文件 setup
{ "environment_variables": { "SUB_KEY": "from_sub", "OVERRIDE": "from_sub" } }

// 合并结果
{ "environment_variables": {
    "BASE": "from_main",
    "SUB_KEY": "from_sub",
    "OVERRIDE": "from_sub"  // 子文件覆盖
} }
```

### 渐进式迁移

无需一次性迁移所有配置：
1. 先用 `validate` 命令确认现有配置无问题（见[配置校验](#配置校验)）
2. 逐步将大文件中的部分用例移到子文件，用 `import` 引用
3. 内联用例与 import 引用可在同一个 `test_cases` 数组中混合使用

## 配置继承

当多个测试用例结构高度相似（仅路径、参数等少量不同），可以用 `extends` + `abstract` + `variables` 消除重复配置。

### 语法

用例支持三个继承相关的新字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `abstract` | `boolean` | 设为 `true` 时为模板（基类），不参与执行 |
| `extends` | `string` | 继承目标用例的 `name`，支持链式继承 |
| `variables` | `object` | 用例级占位符变量，用于 `{key}` 替换 |

### 基本用法

```json
{
  "test_cases": [
    {
      "name": "_base_echo",
      "abstract": true,
      "execution": {
        "command": "echo",
        "args": ["{msg}"]
      },
      "expected": {
        "output_contains": ["{msg}"]
      },
      "variables": {
        "msg": "hello"
      }
    },
    {
      "name": "test_hello",
      "extends": "_base_echo"
    },
    {
      "name": "test_world",
      "extends": "_base_echo",
      "variables": {
        "msg": "world"
      }
    }
  ]
}
```

展开后 `test_hello` 继承基类的全部字段（`execution.command`、`execution.args`、`expected`），占位符 `{msg}` 被 `variables.msg` 替换为 `"hello"`。`test_world` 覆盖 `variables.msg` 为 `"world"`。

### 合并规则

继承采用 **dict 深合并、list 整体替换** 策略：

- **dict 字段**（如 `expected`、`variables`）：递归合并，子类字段覆盖父类同名 key
- **list 字段**（如 `args`、`steps`、`tags`）：子类整列表替换父类，不追加

```json
{
  "name": "_base",
  "abstract": true,
  "expected": {
    "return_code": 0,
    "output_contains": ["base"]
  },
  "tags": ["a", "b"],
  "extends": "_base",
  "expected": {
    "output_contains": ["child"]
  },
  "tags": ["c"]
}
```

合并结果：`expected.return_code` = `0`（来自父类），`expected.output_contains` = `["child"]`（子类整列表替换），`tags` = `["c"]`（整列表替换）。

`abstract` 字段取子类自身值（默认 `false`），不会从父类继承，防止子类意外成为抽象模板。

### 链式继承

支持多层继承（A → B → C）：

```json
{
  "name": "_A", "abstract": true,
  "execution": { "command": "python", "args": ["-c"] }, "expected": {},
  "variables": {"a": "1"}
}
{
  "name": "_B", "abstract": true, "extends": "_A",
  "expected": {"output_contains": ["b"]},
  "variables": {"b": "2"}
}
{
  "name": "C", "extends": "_B",
  "variables": {"c": "3"},
  "execution": { "args": ["print('{a} {b} {c}')"] }
}
```

加载时自动检测循环继承并报错。

### 变量替换优先级

占位符替换分为两层：

1. **用例级 `variables`**：从继承链一路深合并（子类覆盖父类），先应用到合并后的用例内容
2. **全局 `--var`**：通过 CLI 传入（`--var KEY=VALUE`），在用例级变量之后叠加，**同名 key 全局优先级更高**

```bash
symtest run config.json --var solver=/path/to/solver
```

`setup` 区块仅使用全局 `--var` 替换（无用例级变量）。

### validate 检查

`symtest validate` 对继承配置做额外校验：

- `extends` 目标是否存在
- 是否形成循环继承链
- `abstract` 用例不计入可执行用例数
- `extends` 用例跳过必填字段检查（内容来自父类）

### TUI 编辑限制

> **注意**：TUI 目前不支持编辑继承用例。继承后的展开用例在 TUI 中可正常查看和运行，但请直接编辑 JSON/YAML 源文件来进行修改。

## 配置校验

`validate` 命令在不运行测试的情况下检查配置文件的正确性，适合在 CI 流水线中做配置合法性检查。

### 用法

```bash
# 校验单个配置文件
symtest validate test_cases.json

# 校验带 import 的主配置（自动展开并检查所有子文件）
symtest validate main_config.json

# 指定工作目录
symtest validate test_cases.json --workspace /path/to/project

# 输出 JSON 格式（适合 AI/脚本解析）
symtest validate test_cases.json --output-format json
```

### 校验内容

| 检查项 | 说明 |
|---|---|
| 语法正确性 | JSON/YAML 格式是否合法（加载时隐式检查） |
| 必填字段 | 每条用例是否包含 `name`、`execution.command`、`execution.args`、`expected`（序列模式检查每个 step） |
| import 引用 | 被引用的子文件是否存在 |
| 循环引用 | import 链中是否存在 A→B→A 的循环 |

### 输出示例

成功时：
```
  [OK] Loaded 15 test cases from 3 file(s)
  [OK] All required fields present
  [OK] No circular imports detected

  Files:
    - /project/main_config.json
    - /project/cases/text_tests.json
    - /project/cases/json_tests.yaml
```

有错误时：
```
  [OK] Loaded 3 test cases from 1 file(s)
  [FAIL] case 'bad_case': missing required field 'expected'
  [FAIL] Import target not found: /project/cases/nonexistent.json
```

## TUI 交互式管理器

当大型测试项目把用例拆分到多个 JSON/YAML 子配置后，跨文件定位用例和检查场景覆盖会逐渐困难。TUI（Terminal User Interface）在所有导入配置之上提供统一视图，用于浏览、全局搜索、辅助检查覆盖场景，并可按需编辑或运行用例。它是大型测试集的辅助工具，不是日常执行测试的必需组件。

### 安装

TUI 依赖 `textual` 库，并作为按需安装的可选依赖提供：

```bash
# 安装时附带 TUI 支持
pip install "symtest-cli[tui]"

# 或者在已有框架上单独安装 textual
pip install textual
```

如果未安装 `textual` 就直接执行 `symtest tui`，框架会给出友好的安装提示。

### 启动

```bash
# 打开 TUI 编辑测试用例
symtest tui test_cases.json

# YAML 文件同样支持
symtest tui test_cases.yaml

# 指定工作目录
symtest tui test_cases.json --workspace /path/to/project

# 打开带 import 的主配置文件（自动展开子文件中的所有用例）
symtest tui main_config.json
```

TUI 启动时会自动通过[配置拆分机制](#配置拆分机制)展开 `import` 引用，将所有用例加载到界面中统一管理。

### 界面概览

TUI 启动后显示**用例列表主界面**：

- **顶部状态栏**：当前文件名、用例总数
- **搜索栏**：`/` 键聚焦搜索框，支持子串/模糊/正则三种模式
- **用例表格**：六列（序号、名称、命令、标签、超时、模式），支持键盘导航
- **底部快捷键栏**：显示所有可用操作

### 快捷键

| 快捷键 | 功能 |
|---|---|
| `a` | 新增用例 |
| `e` | 编辑选中的用例 |
| `d` | 删除选中的用例 |
| `u` | 复制选中的用例（名称追加 `_copy` 后缀） |
| `r` | 运行选中的用例，显示执行结果 |
| `F6` / `Ctrl+S` | 保存修改到文件 |
| `/` | 聚焦搜索框 |
| `Esc` | 清除搜索，恢复完整列表 |
| `Alt+S` | 切换子串搜索模式（大小写不敏感） |
| `Alt+F` | 切换模糊搜索模式（容忍拼写差异和缩写） |
| `Alt+R` | 切换正则搜索模式 |
| `q` / `Ctrl+Q` | 退出 |
| `↑` / `↓` / `j` / `k` | 上下移动光标 |

搜索时会同时匹配 `name`、`command`、`args`、`tags`、`description` 等字段，匹配结果在表格中高亮显示。

### 编辑用例

选中用例后按 `e` 进入编辑界面。编辑界面根据用例类型有两种模式：

#### 单命令模式

编辑表单包含以下字段：

| 字段 | 说明 |
|---|---|
| `Name` | 用例名称（必填） |
| `Command` | 要执行的命令 |
| `Args` | 命令参数，每行一个 |
| `Tags` | 标签列表，每行一个 |
| `Description` | 用例描述 |
| `Timeout` | 超时秒数 |
| Expected | 期望断言的嵌套子表单（见下文） |

#### 步骤序列模式

当用例包含多个有序步骤时，切换到此模式。每个步骤有独立的 `Command`、`Args`、`Expected` 和 `Timeout`，支持添加、删除、编辑和上下移动步骤。

两种模式可通过编辑界面内的快捷键切换，切换时会提示确认以免丢失数据。

### `expected` 字段编辑

`expected` 字段是一个嵌套字典，编辑器提供结构化输入：

| 字段 | 输入方式 |
|---|---|
| `return_code` | 数字输入框 |
| `output_contains` | 多行文本输入，一行一个匹配字符串 |
| `output_matches` | 正则表达式文本输入 |
| `compare_files` | 每行一个 JSON 对象，如 `{"actual":"out.txt","baseline":"base.txt","type":"text"}` |

除上述已知字段外，还支持通过 `+ Add` 按钮添加自定义 key=value 对，value 为字符串或 JSON 文本。更多含义见[测试用例定义](#测试用例定义)。

### 运行用例

在列表中选中某条用例，按 `r` 即可实时调用框架执行引擎运行该用例。运行结束后弹出结果面板，显示：

- 通过/失败状态
- 返回码
- 耗时
- 命令输出（stdout/stderr）

结果面板仅展示、不修改配置文件。

### 保存

对用例的任何增删改操作都在**内存中**进行，不会立即写入磁盘。

- 按 `F6` 或 `Ctrl+S` **保存**：将当前全部用例写回原配置文件。
- 通过 `save_as` 可**另存为**新文件（通过界面菜单操作）。

退出 TUI 时如有未保存的修改，会弹出确认提示。

## 运行测试

### 命令行

```bash
# 运行 JSON 测试
symtest run test_cases.json

# 运行 YAML 测试
symtest run test_cases.yaml

# 运行带 import 拆分的主配置（自动展开子文件）
symtest run main_config.json

# 指定工作目录
symtest run test_cases.json --workspace /path/to/project

# 并行运行
symtest run test_cases.json --parallel --workers 4

# 指定并行模式
symtest run test_cases.json --parallel --execution-mode process

# 只运行指定用例
symtest run test_cases.json -t test_name_1 -t test_name_2

# 按标签过滤
symtest run test_cases.json --tag smoke
symtest run test_cases.json --tag smoke --tag regression

# 同时按名称和标签过滤（AND 关系）
symtest run test_cases.json -t test_name_1 --tag smoke

# 详细输出
symtest run test_cases.json --verbose

# 调试模式
symtest run test_cases.json --debug

# 输出格式
symtest run test_cases.json --output-format json|html|text

# 启用历史记录（智能调度 + 回归检测）
symtest run test_cases.json --history-dir ./hist

# 自定义回归检测阈值（默认 1.5 倍）
symtest run test_cases.json --history-dir ./hist --regression-threshold 2.0

# 输出 JUnit XML 报告（可供 Jenkins/GitLab CI 等工具解析）
symtest run test_cases.json --junit-xml report.xml

# 只运行上次失败的用例（每次运行时覆盖式更新）
symtest run test_cases.json --last-failed

# 断点续跑：跳过已通过的步骤，从失败步骤继续
symtest run test_cases.json --resume
symtest run test_cases.json --resume -t long_pipeline

# 比较失败时更新基线文件（交互运行需输入 yes）
symtest run test_cases.json --update-baseline

# 非交互环境必须显式确认
symtest run test_cases.json --update-baseline --yes

# 启用误差分析（数值比较时输出全量统计）
symtest run test_cases.json --error-analysis
```

### 只运行上次失败的用例（--last-failed）

`--last-failed` 自动过滤出上一次运行中**真正失败**的用例（`failed`、`timeout` 和 `xpassed`），适合 AI 迭代修复场景：修复一轮代码后，只需验证上次失败的用例，无需全量重跑（有限元全量可能几小时）。

**xfail 语义**：标记为 `expected_failure` 的用例如果失败（`xfailed`），是预期行为，**不会**被 `--last-failed` 选中重跑。但如果 xfail 标记的用例意外通过（`xpassed`），则被视为真正失败，**会**被选中。

**工作原理**：
- 每次运行结束后，框架在 `<workspace>/.symtest/last_run.json` 中记录每个用例的状态
- 记录采用**覆盖式更新**：本次跑到的用例用新结果覆盖旧结果，没跑到的保留原状态
- 这意味着修好的 case 在下一次显示中不再是"failed"
- 如果文件不存在（首次运行），`--last-failed` 会提示并正常运行全部用例

```bash
# 第一次：全量运行 10 个用例，3 个失败
symtest run config.json

# 修复代码后，只重跑那 3 个失败的
symtest run config.json --last-failed

# 如果 3 个全过，再跑一次全量确认
symtest run config.json
```

**与 `-t` 的交互**：`--last-failed` 与 `-t`/`--tag` 可以同时使用，效果叠加（AND 关系）。

### 断点续跑（--resume）

`--resume` 针对**顺序步骤测试（sequence）**，跳过上次运行中已通过的步骤，直接从失败步骤继续执行。适合耗时长的多步骤用例——例如有限元分析中 step 1-3 通过了（各耗时几十秒甚至分钟），只有 step 4 的断言失败，`--resume` 可以跳过 1-3、只重跑 step 4。

**工作原理**：
- 每个步骤通过后，框架在 `<workspace>/.symtest/sequence_state/<case_name>.json` 中记录步骤状态，并将输出缓存到 `cache/` 子目录
- 下次 `--resume` 时，计算配置哈希（所有步骤的 command/args/expected/timeout/retry_count 及 case 级 expected 的 SHA256）与已保存状态比对
- 哈希匹配 → 跳过已通过的步骤，从缓存重建 `combined_output`（确保 case 级 `expected` 断言能正常执行）
- 用例全部通过 → 自动删除状态文件和缓存，避免残留影响后续运行
- 哈希不匹配（配置有改动）→ 自动全量重跑，并丢弃旧状态

**信任模型**：`--resume` **不校验工作区产物**（输入文件、前置步骤生成的文件等）。使用 `--resume` 即表示用户确认输入文件未被修改。如果怀疑工作区被污染，应不带 `--resume` 全量重跑。

```bash
# 首次全量运行，long_pipeline 的 step 4 失败（总耗时 72s）
symtest run config.json

# 修复后只重跑 long_pipeline，跳过 step 1-3（仅耗时 ~0.14s）
symtest run config.json -t long_pipeline --resume

# 全部通过后，跑一次全量确认无回归
symtest run config.json
```

**与 `-t` 的交互**：`--resume` 通常与 `-t` 组合使用，先定位到单个失败用例再断点续跑。不带 `-t` 时，所有已存在状态的序列用例都会尝试续跑。

**限制**：
- 仅对序列步骤用例（`steps` 模式）生效，单命令模式忽略
- 状态文件的配置哈希会因任何 step 的 command/args/expected/timeout/retry_count 或 case 级 expected 变化而失效
- 缓存输出主要用于重建 `combined_output`，报告中的 `output` 字段仍只包含失败步骤的输出

### 自动更新基线文件（--update-baseline）

在进行算法改进或参数调整后，你可能期望输出结果发生变化（且新结果更正确）。`--update-baseline` 会自动用实际产出覆盖基线文件，免去手动复制粘贴。

```bash
# 交互运行会先要求输入 yes
symtest run config.json --update-baseline

# 自动化或 CI 中显式确认
symtest run config.json --update-baseline --yes
```

**行为**：
- 交互运行必须输入完整的 `yes` 才会开始测试
- 非交互环境不会等待输入，必须同时传入 `--yes`
- 文件比较失败时，`actual` 文件被复制到 `baseline` 路径
- 该条断言视为**通过**，用例状态为 `passed`
- 报告中显示 `Baseline Updated` 计数和更新的文件列表
- 文本报告与 JSON 报告均会列出所有被更新的 baseline 路径

> **注意**：确认发生在测试执行前，而实际被更新的文件只有比较后才能确定。请将基线纳入版本控制，并审查报告中的 `Baseline Updated` 列表。Python API 中显式传入 `update_baseline=True` 视为调用方已经确认。

### 配置校验 JSON 输出

`validate` 命令新增 `--output-format json`，输出机器可读的 JSON 报告，适合 AI/脚本自动检查配置合法性：

```bash
symtest validate config.json --output-format json
```

输出示例：
```json
{
  "valid": false,
  "errors": ["[main_config.json] case 'bad_case': missing required field 'expected'"],
  "summary": {"files": 1, "cases": 3, "files_loaded": ["/project/main_config.json"]}
}
```

### Python API

```python
from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner

# 顺序运行
runner = JSONRunner(
    config_file="test_cases.json",
    workspace="/path/to/project",    # 可选，默认项目根目录
    test_case_filter=["test_1"],     # 可选，只运行指定用例
    test_case_tag_filter=["smoke"],  # 可选，只运行包含指定标签的用例
    history_dir="./hist",            # 可选，启用历史记录与回归检测
    regression_threshold=2.0,        # 可选，回归阈值倍数，默认 1.5
    update_baseline=False,           # 可选，比较失败时自动更新基线，默认 False
    last_failed=False,               # 可选，只运行上次失败的用例，默认 False
    resume=False,                    # 可选，断点续跑序列用例，默认 False
)
success = runner.run_tests()

# YAML 格式
runner = YAMLRunner(config_file="test_cases.yaml")

# 并行运行（JSON）
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,                   # 可选，默认 CPU 核心数
    execution_mode="thread",         # "thread" 或 "process"
    test_case_filter=["test_1"],
    history_dir="./hist",            # 可选，启用历史记录与智能调度
    regression_threshold=2.0,        # 可选，回归阈值倍数，默认 1.5
    update_baseline=False,           # 可选
    last_failed=False,               # 可选
    resume=False,                    # 可选，断点续跑序列用例
)
success = runner.run_tests()

# 并行运行（YAML）
from symtest.runners import ParallelYAMLRunner
runner = ParallelYAMLRunner(
    config_file="test_cases.yaml",
    max_workers=4,
    execution_mode="thread",
)
success = runner.run_tests()
```

### 获取结果

```python
runner.run_tests()

# 汇总
runner.results["total"]
runner.results["passed"]
runner.results["failed"]
runner.results["xfailed"]      # 预期失败（不影响退出码）
runner.results["xpassed"]      # 意外通过（计入失败）
runner.results["updated"]   # 被 --update-baseline 更新的基线文件数

# 详情 — 每个结果字典包含以下字段
for detail in runner.results["details"]:
    print(detail["name"])                     # 用例名称
    print(detail["status"])                   # "passed" / "failed" / "xfailed" / "xpassed" / "timeout"
    print(detail.get("message", ""))          # 失败原因
    print(detail.get("duration"))             # 耗时（秒）
    print(detail.get("xfail_reason", ""))     # xfail 原因（仅 xfailed/xpassed 状态）
    print(detail.get("expected"))             # 期望断言（注册的验收标准）
    print(detail.get("description"))          # 用例描述
    print(detail.get("tags"))                 # 标签列表
    print(detail.get("failure_kind"))         # 失败类型：return_code/output_contains/
                                              #   output_matches/file_compare/timeout/
                                              #   execution_error
    print(detail.get("attempts", 1))          # 尝试次数（含重试）
    print(detail.get("flaky", False))         # 是否重试后才通过
    print(detail.get("attempt_history", []))  # 每次尝试的状态历史
    print(detail.get("failed_step"))          # 步骤序列中的失败步骤号
    print(detail.get("step_results", []))     # 每个步骤的详细结果
    print(detail.get("compare_failures", [])) # 文件比较失败的结构化详情
    print(detail.get("baseline_updated", [])) # 被更新的基线文件列表
```

**结果字典关键字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | str | 四态之一：`passed`（通过）、`failed`（失败）、`xfailed`（预期失败）、`xpassed`（意外通过）、`timeout`（超时） |
| `xfail_reason` | str | xfail 原因文本（来自配置中的 `xfail_reason` 字段），仅在 `xfailed`/`xpassed` 状态时有值 |
| `expected` | dict | 注册的期望断言（含 return_code、output_contains、compare_files 等），方便回查验收标准 |
| `description` | str | 测试用例的描述文本 |
| `failure_kind` | str | 失败类型枚举，AI/脚本可据此选择修复策略 |
| `attempts` | int | 总尝试次数（含重试），`1` 表示一次通过 |
| `flaky` | bool | 重试后才通过时为 `true` |
| `attempt_history` | list | 每次尝试的 `{attempt, status, message, duration}` |
| `step_results` | list | 步骤序列每个 step 的 `{step, name, status, message, duration, command}` |
| `compare_failures` | list | 每个失败的文件比较的结构化信息（含 `diff_summary`、`differences`、`error_stats`、`actual`/`baseline` 路径、容差参数） |
| `baseline_updated` | list | `--update-baseline` 覆盖的基线文件路径列表 |

## 项目入口脚本

如果你的测试项目结构复杂（需要预设环境变量、定制报告路径等），直接使用 `symtest run` 命令行可能不够灵活。此时可以创建一个项目入口脚本（如 `test.py` 或 `run_tests.py`），在 Python 代码中调用框架 API。

### 何时直接用 CLI

| 场景 | 推荐方式 |
|---|---|
| 简单项目、单个配置文件 | `symtest run config.json --workers 4` |
| 一次性运行、无特殊环境需求 | `symtest run config.yaml --tag smoke` |
| CI 流水线 | `symtest run config.json --junit-xml report.xml` |

### 何时包一层入口脚本

| 场景 | 推荐方式 |
|---|---|
| 需要预设环境变量（如注入 venv PATH） | 入口脚本 |
| 需要同时输出多种格式报告（文本 + JUnit XML） | 入口脚本 |
| 团队共享固定运行参数（workers、history-dir 等） | 入口脚本 |
| 需要根据配置文件扩展名自动选择 JSON/YAML runner | 入口脚本 |
| Windows 下 console-script 命令（如 `compare-files`）找不到的问题 | 入口脚本（注入 venv Scripts 到 PATH） |

### 入口脚本示例

框架提供了开箱即用的示例脚本 `examples/full_runner_example.py`，可复制到你的项目根目录直接使用或按需修改。它支持以下所有 CLI 参数：

| 参数 | 说明 |
|---|---|
| `config`（位置参数） | 测试配置文件路径（自动识别 .json / .yaml） |
| `--test-target` / `-t` | 按名称过滤用例 |
| `--tag` | 按标签过滤用例（OR 关系） |
| `--last-failed` | 只运行上次失败的用例 |
| `--resume` | 断点续跑序列用例 |
| `--update-baseline` | 比较失败时更新基线；交互运行需要二次确认 |
| `--yes` / `-y` | 跳过基线更新确认，供自动化或 CI 使用 |
| `--junit-xml` | JUnit XML 报告输出路径 |
| `--report` | 文本报告输出路径，默认 `test_report.txt` |
| `--workers` / `-w` | 并行工作线程数，默认 4 |
| `--execution-mode` | thread 或 process |
| `--workspace` | 工作目录，默认脚本所在目录 |
| `--var` | 模板变量替换，格式 `KEY=VALUE` |
| `--verbose` / `-v` | 详细输出（DEBUG 级别日志） |

### 快速上手

1. 复制 `examples/full_runner_example.py` 到你的项目根目录，重命名为 `run_tests.py`
2. 如果使用了虚拟环境且需要 console-script 命令，取消文件中 venv PATH 注入代码的注释
3. 按团队习惯修改默认参数（如 `--workers` 默认值、`--history-dir` 默认路径）
4. 运行测试：

```bash
# 全量运行
python run_tests.py test_cases.json --workers 4

# 只跑上次失败的用例
python run_tests.py test_cases.json --last-failed

# CI 中输出 JUnit 报告
python run_tests.py test_cases.json --junit-xml report.xml
```

### Windows 下 WinError 2 问题

如果你的测试用例 `command` 字段引用了 console-script 命令（例如 `compare-files`、`symtest` 等通过 pip 安装的入口点），在 Windows 下直接双击运行脚本或通过未激活的环境启动时，子进程可能找不到这些可执行文件，报错：

```
FileNotFoundError: [WinError 2] 系统找不到指定的文件。
```

这是因为这些命令以 `.exe` 包装器的形式存在于 `venv/Scripts/` 目录下，而子进程的 PATH 中没有该目录。

**解决方案**：在入口脚本的最顶部（`main()` 函数开头或文件级）将 venv 的 `Scripts` 目录前置到 `PATH` 环境变量：

```python
import os

venv_scripts = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", ".venv", "Scripts"))
if os.path.isdir(venv_scripts):
    os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")
```

示例脚本 `examples/full_runner_example.py` 中已包含此段代码（默认注释），按需取消注释并调整路径即可。

## 占位符（变量替换）

当同一个配置文件需要在不同环境下使用不同参数（如求解器路径、模型文件路径等）时，可以用 `{变量名}` 占位符编写配置，运行时通过 `--var` 或 `variables` 参数传入实际值。

### 编写含占位符的配置

JSON：

```json
{
    "test_cases": [
        {
            "name": "求解器测试",
            "execution": {
                "command": "{solver}",
                "args": ["--input", "{model}", "--output", "{output}"]
            },
            "expected": { "return_code": 0 }
        }
    ]
}
```

YAML：

```yaml
test_cases:
  - name: 求解器测试
    execution:
      command: "{solver}"
      args: ["--input", "{model}", "--output", "{output}"]
    expected:
      return_code: 0
```

占位符 `{变量名}` 可出现在配置文件的任意字符串值中，包括 `command`、`args`、`name`、`expected.output_contains` 等。支持同一个字符串中使用多个占位符，如 `"{solver} --input {model}"`。

> **安全设计**：只有 `variables` 字典中存在的 key 才会被替换。`{xxx}` 若无匹配不会报错，而是原样保留。因此 `expected.output_matches` 中的正则模式（如 `{2,}`、`\d{4}`）不受影响。

### 用法

#### CLI

```bash
# 单个变量
symtest run test_cases.json --var solver=/opt/solver/bin/solver.exe

# 多个变量
symtest run test_cases.json --var solver=/opt/solver/bin/solver.exe --var model=./data/model.dat

# 与并行模式、标签过滤等组合使用
symtest run test_cases.json --var solver=solver.exe --parallel --workers 4 --tag smoke
```

`--var` 格式为 `KEY=VALUE`，可多次使用。等号分隔，key 和 value 两侧的空格会被自动去除。

#### Python API

```python
from symtest.runners import JSONRunner, YAMLRunner, ParallelJSONRunner, ParallelYAMLRunner

# 顺序运行
runner = JSONRunner(
    config_file="test_cases.json",
    variables={
        "solver": "/opt/solver/bin/solver.exe",
        "model": "./data/model.dat",
        "output": "./results/output.dat",
    },
)
success = runner.run_tests()

# 并行运行
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()

# YAML 同样支持
runner = YAMLRunner(
    config_file="test_cases.yaml",
    variables={"solver": "/opt/solver/bin/solver.exe"},
)
success = runner.run_tests()
```

### 适用场景

| 场景 | 示例 |
|---|---|
| 不同求解器版本测试 | `--var solver=v1.0/solver.exe` ↔ `--var solver=v2.0/solver.exe` |
| 不同输入数据 | `--var model=case_1.dat` ↔ `--var model=case_2.dat` |
| CI/CD 环境适配 | 本地 `/opt/solver.exe`，CI `/runner/solver.exe` |
| 多平台路径 | Windows `--var solver=C:\solver.exe`，Linux `--var solver=/opt/solver.exe` |

## 标签过滤

通过标签（tags）可以对测试用例进行分类，并在运行时按标签批量过滤。标签过滤与名称过滤可同时使用，满足 AND 关系（两个条件都必须满足）。

### 在测试用例中定义标签

JSON：

```json
{
    "test_cases": [
        {
            "name": "快速测试",
            "execution": {
                "command": "echo",
                "args": ["hello"]
            },
            "tags": ["smoke", "fast"],
            "expected": { "return_code": 0 }
        },
        {
            "name": "完整回归测试",
            "execution": {
                "command": "python",
                "args": ["long_test.py"]
            },
            "tags": ["regression", "slow"],
            "expected": { "return_code": 0 }
        }
    ]
}
```

YAML：

```yaml
test_cases:
  - name: 快速测试
    execution:
      command: echo
      args: ["hello"]
    tags: ["smoke", "fast"]
    expected:
      return_code: 0
```

`tags` 是可选字段，不指定则默认为空列表。每个用例可以有多个标签。

### 运行时过滤

```bash
# 只运行带 "smoke" 标签的用例
symtest run test_cases.json --tag smoke

# 运行带 "smoke" 或 "regression" 标签的用例（OR 关系）
symtest run test_cases.json --tag smoke --tag regression

# 同时按名称和标签过滤（AND 关系）
symtest run test_cases.json -t alpha --tag fast
```

### Python API

```python
runner = JSONRunner(
    config_file="test_cases.json",
    test_case_tag_filter=["smoke"],     # 只运行含 smoke 标签的用例
)
success = runner.run_tests()

# 结合名称过滤
runner = JSONRunner(
    config_file="test_cases.json",
    test_case_filter=["alpha", "beta"],
    test_case_tag_filter=["fast"],
)
success = runner.run_tests()
```

## Setup 模块

Setup 模块在测试前执行初始化、测试后执行清理。

### 环境变量（配置文件方式）

JSON：

```json
{
    "setup": {
        "environment_variables": {
            "TEST_ENV": "development",
            "API_URL": "http://localhost:8080"
        }
    },
    "test_cases": [...]
}
```

YAML：

```yaml
setup:
  environment_variables:
    TEST_ENV: "development"
    API_URL: "http://localhost:8080"
test_cases:
  [...]
```

配置文件中的环境变量会在测试前设置、测试后恢复原值。

### 自定义 Setup 插件

```python
from symtest import BaseSetup, JSONRunner

class DatabaseSetup(BaseSetup):
    def setup(self):
        # 初始化操作
        pass

    def teardown(self):
        # 清理操作（即使测试失败也会执行）
        pass

runner = JSONRunner("test_cases.json")
runner.setup_manager.add_setup(DatabaseSetup({"connection": "test_db"}))
success = runner.run_tests()
```

多个插件按添加顺序执行 setup，按逆序执行 teardown。

### 执行顺序

1. 加载配置文件中的 setup 配置（环境变量等）
2. 执行所有 setup 插件的 `setup()`（按添加顺序）
3. 运行测试
4. 执行所有 setup 插件的 `teardown()`（逆序，保证执行）

## 并行测试

```python
from symtest.runners import ParallelJSONRunner

runner = ParallelJSONRunner(
    config_file="test_cases.json",
    max_workers=4,                # 最大并发数，默认 CPU 核心数
    execution_mode="thread"       # "thread" 或 "process"
)
success = runner.run_tests()

# 回退到顺序执行
runner.run_tests_sequential()
```

**线程模式**：共享内存，支持资源感知调度（见下节）。  
**进程模式**：进程隔离，不支持资源调度。

## 顺序步骤测试

一个测试用例可包含多个有序步骤，某步失败则跳过后续步骤（fail-fast）。

### JSON

```json
{
    "test_cases": [
        {
            "name": "多步骤测试",
            "execution": {
                "steps": [
                    {
                        "command": "echo",
                        "args": ["step1"],
                        "expected": { "return_code": 0 }
                    },
                    {
                        "command": "echo",
                        "args": ["step2"],
                        "expected": { "return_code": 0 },
                        "retry_count": 2
                    }
                ]
            }
        }
    ]
}
```

### YAML

```yaml
test_cases:
  - name: 多步骤测试
    execution:
      steps:
        - command: echo
          args: ["step1"]
          expected:
            return_code: 0
        - command: echo
          args: ["step2"]
          expected:
            return_code: 0
```

每个 step 支持 `command`、`args`、`expected`、`timeout`、`retry_count` 字段。

**失败输出瘦身**：当序列中某一步失败时，结果字典的 `output` 字段**仅包含失败步骤的输出**——不会拼接前面成功步骤的大量输出。这大幅减少了失败报告的体积，适合 AI 快速诊断失败的步骤。

**步骤详情**：通过 `detail["step_results"]` 可查看每个步骤的独立状态（即使全部通过），方便了解整个序列的执行流程。

**失败标记**：失败时结果中 `failed_step` 字段标注失败步骤编号，如 "Failed at step 2/3"。

**断点续跑**：序列用例失败后，可通过 `--resume` 跳过已通过的步骤，直接从失败步骤继续执行，大幅节省长耗时用例的迭代成本。详见[断点续跑](#断点续跑resume)。

### Case 级别 expected（顺序步骤）

当所有步骤都执行通过后，可以在 case 级别定义额外的 `expected` 断言，对所有步骤产生的文件做统一的验证（如文件比较）。Case 级别的 `expected` 字段格式与单命令模式完全一致，支持 `return_code`、`output_contains`、`output_matches`、`compare_files`。

```json
{
    "name": "多步骤+文件对比",
    "execution": {
        "steps": [
            {
                "command": "python",
                "args": ["./generate.py", "output.csv"],
                "expected": { "return_code": 0 }
            },
            {
                "command": "python",
                "args": ["./process.py", "output.csv"],
                "expected": { "return_code": 0, "output_contains": ["Done"] }
            }
        ]
    },
    "expected": {
        "compare_files": [
            {
                "actual": "output.csv",
                "baseline": "baseline/output.csv",
                "type": "csv",
                "rtol": 0.02,
                "start_line": 93,
                "end_line": 99
            }
        ]
    }
}
```

> **注意**：case 级别的 `expected` 只在所有 step 通过后才执行。如果某个 step 失败，case 级断言不会运行。case 级断言失败时，错误消息包含 "Case-level assertion failed" 前缀以便区分。

## 资源感知调度

仅线程模式生效。通过 `scheduling.resources` 字段配置，框架自动管理 CPU 核心分配。

```json
{
    "name": "Heavy_Simulation",
    "execution": {
        "command": "solver",
        "args": ["-i", "input.dat"],
        "timeout": 36000
    },
    "scheduling": {
        "resources": {
            "cpu_cores": 4,
            "estimated_time": 18000,
            "min_memory_mb": 16000,
            "priority": 10
        }
    },
    "expected": { "return_code": 0 }
}
```

| 字段 | 说明 |
|---|---|
| `cpu_cores` | 所需 CPU 核心数，默认 1。框架用信号量控制分配，超限任务排队等待 |
| `estimated_time` | 预估耗时（秒），用于 LPT 调度（长任务优先启动） |
| `min_memory_mb` | 预估内存（MB），目前仅用于日志警告 |
| `priority` | 优先级 0-10，目前仅用于信息标注 |

框架行为：
- 自动检测 CPU 核心数，预留 2 核给系统
- 任务启动时自动注入 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`NPROC` 环境变量，防止求解器线程失控
- 按 `estimated_time` 降序调度（LPT 策略）；若启用 `--history-dir`，优先使用历史 `avg_duration` 排序

## 历史记录与回归检测

通过 `--history-dir` 指定一个目录，框架会在该目录下维护一个 `.symtest` 文件，记录每个 case 的历史运行时间。

### 工作原理

1. **首次运行**：目录下没有 `.symtest`，自动创建空文件，排序仍使用配置中的 `estimated_time`
2. **后续运行**：读取 `.symtest` 中的历史数据，优先使用 `avg_duration` 做调度排序
3. **回归检测**：每次运行结束后，如果某 case 耗时超过历史均值的阈值倍数（默认 1.5），打印警告

### CLI 用法

```bash
# 启用历史记录
symtest run test_cases.json --history-dir ./hist

# 自定义回归阈值（超过 2 倍均值才警告）
symtest run test_cases.json --history-dir ./hist --regression-threshold 2.0
```

### Python API

```python
from symtest.runners import JSONRunner, ParallelJSONRunner

# 顺序运行 + 历史记录
runner = JSONRunner(
    config_file="test_cases.json",
    history_dir="./hist",
    regression_threshold=2.0,  # 可选，默认 1.5
)
success = runner.run_tests()

# 并行运行 + 历史记录（调度排序也会使用历史数据）
runner = ParallelJSONRunner(
    config_file="test_cases.json",
    history_dir="./hist",
)
success = runner.run_tests()
```

### .symtest 文件格式

```json
{
  "version": 1,
  "cases": {
    "case_name_1": {
      "avg_duration": 3.5,
      "last_duration": 3.2,
      "run_count": 5
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| `avg_duration` | 累计平均耗时（秒），用于调度排序和回归基线 |
| `last_duration` | 最近一次运行耗时 |
| `run_count` | 历史运行次数 |

### 回归警告示例

当某 case 运行时间超过历史均值的阈值倍数时：

```
⚠ WARNING: Case 'heavy_simulation' regressed: 18.2s vs avg 10.5s (1.73x slower)
```

### 不启用历史记录

不传 `--history-dir` 时行为与之前完全一致，不创建任何额外文件。

### 清零历史记录（--update-history）

当算法重构或环境变化导致历史耗时数据不再有代表性时，`--update-history`
会清除本次运行涉及的 case 在 `.symtest` 中的历史记录，让本次运行成为
新的回归检测基线。

```bash
# 清除历史后本次运行成为新基线（需搭配 --history-dir）
symtest run config.json --history-dir ./hist --update-history
```

**行为**：
- 清除 `.symtest` 中**本次运行涉及的 case** 的历史条目
- 未参与本次运行的 case 的历史数据保留不动
- 本次运行的回归检测不会产生误报（无历史基线可比）
- 本次通过 case 的耗时会被记录为全新起点
- 报告中显示 `History Reset` 计数

> **注意**：需搭配 `--history-dir` 使用。清零范围仅限本次运行的 case，不影响其他 case 的历史数据。

## JUnit XML 报告

通过 `--junit-xml` 可在运行测试的同时输出 JUnit 格式的 XML 报告，兼容 Jenkins、GitLab CI、CircleCI 等 CI 工具。

### CLI 用法

```bash
symtest run test_cases.json --junit-xml report.xml
```

`--junit-xml` 是补充输出，与 `--output-format`（text/json/html）并存，不影响控制台报告。

### Python API

```python
from symtest import write_junit_xml

runner.run_tests()
write_junit_xml(runner.results, "report.xml", suite_name="my_suite")
```

状态映射：`passed` 记为通过；`failed` 记为 failure（断言失败）或 error（执行错误）；`timeout` 记为 error；`xfailed` 记为 **skipped**（预期失败，不影响构建）；`xpassed` 记为 **failure**（意外通过，视为构建失败）。每个 testcase 元素附带命令输出与失败原因。

## 日志配置

框架所有诊断与状态信息都通过 Python 标准 `logging` 模块输出，统一挂在 `symtest` 命名空间下。日志默认写入 **stderr**，因此 `stdout` 始终保持干净，可安全配合 `--output-format json` 做机器可读输出。

### 命令行控制日志级别

`run` 与 `compare` 子命令均支持：

| 选项 | 说明 |
|---|---|
| `--verbose` / `-v` | 详细输出，日志级别提升至 DEBUG |
| `--debug` | 调试模式，同样提升至 DEBUG，并在出错时打印完整堆栈 |

默认级别为 INFO，仅显示关键进度与错误；加 `--verbose` 或 `--debug` 后会输出命令输出、调度细节等 DEBUG 级信息。

```bash
# 详细模式（含命令输出等 DEBUG 信息）
symtest run test_cases.json --verbose

# 调试模式（出错时打印堆栈）
symtest run test_cases.json --debug
```

### 库使用方式

作为库被 import 时，框架默认只挂载 `NullHandler`，不产生任何输出（符合库的礼貌日志规范）。需要看到日志时，调用 `setup_console_logging()` 启用控制台输出：

```python
import logging
from symtest.logging_config import setup_console_logging, get_logger

# 启用控制台日志（stderr），可指定级别
setup_console_logging(level=logging.DEBUG)

logger = get_logger(__name__)   # 自动归入 symtest 命名空间
logger.info("自定义日志信息")
```

### 输出到日志文件

框架未内置 `--log-file` 选项，但可借助 Python 标准 `logging` 自行为 `symtest` logger 添加文件处理器：

```python
import logging
from symtest.logging_config import get_logger

file_handler = logging.FileHandler("run.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
)

# 给框架根 logger 加文件处理器，所有子 logger 都会继承
logging.getLogger("symtest").addHandler(file_handler)
```

上述代码既适用于库调用，也可放在脚本中配合 `symtest` 一起使用。控制台与文件处理器可并存。

## 文件比较

框架提供独立的文件比较能力，支持文本、JSON、CSV、XML、HDF5、二进制等多种格式。既可通过命令行工具使用，也可在测试用例的 `expected.compare_files` 中自动调用（见[文件比较断言](#文件比较断言compare_files)）。

### 命令行工具

有两种等价的调用方式，参数完全一致：

```bash
# 独立命令
compare-files <file1> <file2> [选项]

# symtest 子命令
symtest compare <file1> <file2> [选项]
```

### 通用选项

| 选项 | 说明 |
|---|---|
| `--file-type` | 文件类型：`auto`（默认）、`text`、`json`、`csv`、`xml`、`h5`、`binary` |
| `--start-line` | 起始行号（1-based），默认 1 |
| `--end-line` | 结束行号（1-based） |
| `--start-column` | 起始列号（1-based），默认 1 |
| `--end-column` | 结束列号（1-based） |
| `--encoding` | 文本编码，默认 `utf-8` |
| `--output-format` | 输出格式：`text`、`json`、`html` |
| `--verbose` / `-v` | 详细输出 |
| `--debug` | 调试模式 |
| `--num-threads` | 并行线程数，默认 4 |

### 文本文件比较

```bash
compare-files file1.txt file2.txt --start-line 10 --end-line 20
```

### JSON 文件比较

```bash
# 精确比较（默认）
compare-files data1.json data2.json

# 按 key 字段比较
compare-files data1.json data2.json --json-compare-mode key-based --json-key-field id
```

| 选项 | 说明 |
|---|---|
| `--json-compare-mode` | `exact`（默认）或 `key-based` |
| `--json-key-field` | key-based 模式的匹配字段，支持逗号分隔多字段 |

### CSV 文件比较

```bash
# 基本比较
compare-files data1.csv data2.csv

# 自定义分隔符与数值容差
compare-files data1.csv data2.csv --csv-delimiter ';' --csv-rtol 1e-4 --csv-atol 1e-6

# TSV 文件（自动识别为 csv 类型）
compare-files data1.tsv data2.tsv

# 数据过滤（只比较满足条件的数值单元格）
compare-files data1.csv data2.csv --csv-data-filter '>1e-6'
compare-files data1.csv data2.csv --csv-data-filter 'abs>1e-9'
compare-files data1.csv data2.csv --csv-data-filter '<=0.01'
```

| 选项 | 说明 |
|---|---|
| `--csv-rtol` | 数值相对容差，默认 1e-5 |
| `--csv-atol` | 数值绝对容差，默认 1e-8 |
| `--csv-delimiter` | 字段分隔符，默认 `,` |
| `--csv-quotechar` | 引用字符，默认 `"` |
| `--csv-data-filter` | 数据过滤表达式：`>`, `>=`, `<`, `<=`, `==`，支持 `abs` 前缀。只比较两个文件中**都满足**条件的数值单元格 |

CSV 比较按行列结构逐单元格比对；数值单元格在容差范围内视为相等。`--csv-data-filter` 过滤后，不满足条件的数值单元格对不会报差异。差异报告包含行数、列数不匹配与单元格不一致，最多列出 10 条。

#### 误差分析（--error-analysis）

默认情况下，CSV 和 HDF5 比较器在发现 10 条差异后停止报告。当需要了解**全体数值单元格**的统计特征时，可通过 `--error-analysis` 启用流式全量统计。

启用后，每个失败的文件比较会在报告的 Compare Failures 区块中附加 `error_stats` 信息：

| 统计量 | 说明 |
|---|---|
| `total_numeric_cells` | 参与数值比较的单元格总数 |
| `mismatched_cells` | 超出容差的单元格数 |
| `max_abs_error` | 全体数值单元格中的最大绝对误差及其位置 |
| `max_rel_error` | 全体数值单元格中的最大相对误差及其位置 |
| `mean_abs_error` | 全体数值单元格的平均绝对误差（分母为 `total_numeric_cells`） |
| `rms_abs_error` | 全体数值单元格的均方根绝对误差（RMSE，分母为 `total_numeric_cells`） |

统计是**流式**计算的，不依赖差异截断，幅值统计（max/mean/rms）覆盖**全体**参与比较的数值单元格（含在容差内通过的单元格），可用于观察通过格离容差的余量；非有限值（NaN/inf）单元格不参与幅值统计。两个参数的统计口径完全一致，区别仅在于：默认仅失败的比较输出统计，通过的比较不输出。

如需让**通过**的用例也输出统计信息（例如用于监控容差余量），可改用 `--error-analysis-all`（它会隐含启用 `--error-analysis`）：

```bash
# 对所有用例（含通过的）输出误差统计
symtest run config.json --error-analysis-all
```

启用后，每个**通过**的用例会在 Detailed Results 区块中以 `error_stats (baseline vs actual):` 的形式列出上述统计量（与失败用例的 `error_stats` 字段一致）。通过用例的统计也同时写入 `--output json` 的 `assertion_results[].error_stats`，便于程序化消费。仅当 `--error-analysis-all` 启用时才会对通过用例产生额外输出，未启用时行为不变。

**CLI 用法**：

```bash
# 启用误差分析
symtest run config.json --error-analysis

# 启用误差分析并对通过的用例也输出统计
symtest run config.json --error-analysis-all

# 与比较参数组合使用
symtest run config.json --error-analysis --csv-rtol 1e-4 --csv-data-filter '>0'
```

**Python API**：

```python
# 在比较器中启用
comparator = ComparatorFactory.create_comparator(
    "csv", rtol=1e-5, atol=1e-8, error_analysis=True
)
result = comparator.compare_files("data1.csv", "data2.csv")
print(result.error_stats)  # dict 或 None

# 通过 Assertions.compare_files 启用
from symtest.core.assertions import Assertions
cf_result = Assertions.compare_files(
    "actual.csv", "baseline.csv",
    file_type="csv", rtol=1e-5, atol=1e-8,
    error_analysis=True,
)
print(cf_result["error_stats"])
```

> **注意**：`--error-analysis` 仅对数值型比较器（CSV、HDF5）生效，文本/JSON/XML/二进制比较器忽略此参数。未启用时行为不变，无额外开销。

### XML 文件比较

```bash
# 结构化比较（标签、属性、文本、子元素）
compare-files config1.xml config2.xml

# HTML 文件（自动识别为 xml 类型）
compare-files page1.html page2.html
```

XML 比较按 DOM 结构递归比对标签、属性、文本内容与子元素数量。差异报告定位到具体路径（如 `/root/item[0]/@id`），最多列出 10 条。

### HDF5 文件比较

```bash
# 比较指定表
compare-files data1.h5 data2.h5 --h5-table table1,table2

# 用正则匹配表名
compare-files data1.h5 data2.h5 --h5-table-regex "result_.*"

# 逗号分隔多个正则
compare-files data1.h5 data2.h5 --h5-table-regex "table1,table2,table3"

# 数值容差
compare-files data1.h5 data2.h5 --h5-rtol 1e-5 --h5-atol 1e-8

# 数据过滤（只比较满足条件的数据）
compare-files data1.h5 data2.h5 --h5-data-filter '>1e-6'
compare-files data1.h5 data2.h5 --h5-data-filter 'abs>1e-9'
compare-files data1.h5 data2.h5 --h5-data-filter '<=0.01'

# 禁止自动展开 group 路径
compare-files data1.h5 data2.h5 --h5-table group1 --h5-no-expand-path
```

| 选项 | 说明 |
|---|---|
| `--h5-table` | 指定表名，逗号分隔 |
| `--h5-table-regex` | 正则匹配表名，逗号分隔多个模式 |
| `--h5-structure-only` | 只比较结构，不比较内容 |
| `--h5-show-content-diff` | 显示内容差异详情 |
| `--h5-rtol` | 相对容差，默认 1e-5 |
| `--h5-atol` | 绝对容差，默认 1e-8 |
| `--h5-data-filter` | 数据过滤表达式：`>`, `>=`, `<`, `<=`, `==`，支持 `abs` 前缀 |
| `--h5-no-expand-path` | 禁止自动展开 group 路径下的子项 |

### 二进制文件比较

```bash
compare-files binary1.bin binary2.bin --similarity --chunk-size 16384
```

| 选项 | 说明 |
|---|---|
| `--similarity` | 计算相似度指数 |
| `--chunk-size` | 读取块大小，默认 8192 |

### Python API

```python
from symtest.file_comparator import ComparatorFactory

# 文本比较
comparator = ComparatorFactory.create_comparator("text", encoding="utf-8", verbose=True)
result = comparator.compare_files("file1.txt", "file2.txt")

# JSON 比较
comparator = ComparatorFactory.create_comparator("json", compare_mode="key-based", key_field="id")
result = comparator.compare_files("data1.json", "data2.json")

# CSV 比较
comparator = ComparatorFactory.create_comparator("csv", rtol=1e-5, atol=1e-8, delimiter=",")
result = comparator.compare_files("data1.csv", "data2.csv")

# CSV 比较（启用误差分析）
comparator = ComparatorFactory.create_comparator("csv", rtol=1e-5, atol=1e-8, delimiter=",", error_analysis=True)
result = comparator.compare_files("data1.csv", "data2.csv")
print(result.error_stats)  # 全量数值统计

# XML 比较
comparator = ComparatorFactory.create_comparator("xml", encoding="utf-8")
result = comparator.compare_files("config1.xml", "config2.xml")

# HDF5 比较
comparator = ComparatorFactory.create_comparator("h5", tables=["table1"], rtol=1e-5)
result = comparator.compare_files("data1.h5", "data2.h5")

# 结果
result.identical   # bool
result.differences # list
```

## 扩展开发

### 自定义 Runner

```python
from symtest.core.base_runner import BaseRunner

class CustomRunner(BaseRunner):
    def load_test_cases(self):
        # 加载测试用例到 self.test_cases
        pass

    def run_single_test(self, test_case):
        # 执行单个测试，返回结果字典
        pass
```

### 自定义 Setup 插件

```python
from symtest import BaseSetup

class MySetup(BaseSetup):
    def setup(self):
        # self.config 可获取传入的配置字典
        pass

    def teardown(self):
        pass
```

### 自定义文件比较器

框架支持三种方式扩展比较能力：

#### 方式一：工作区插件目录（推荐）

在 workspace 下创建 `comparators/` 目录，放入 `*_comparator.py` 文件（命名与内置比较器一致），框架会在首次使用时自动发现并注册其中的 `*Comparator` 类。

```
your-workspace/
├── comparators/
│   └── my_analysis_comparator.py   # 由框架自动发现
└── test_config.json
```

可通过 CLI `--plugin-dir` 参数指定额外插件目录（支持多次使用）：

```bash
symtest run test_config.json --plugin-dir ./extra_plugins
```

插件也会通过环境变量 `CLITEST_PLUGIN_DIRS` 自动继承到 process 模式子进程。

**插件开发注意事项**：
- 继承 `symtest.file_comparator.BaseComparator`
- 类名必须以 `Comparator` 结尾（如 `MyAnalysisComparator`）
- 注册的 type 名 = 类名去掉 `Comparator` 再小写（如 `myanalysis`）
- 推荐重写 `compare_files(file1, file2, **kwargs)` 方法而非 `read_content`/`compare_content`（若比较器不使用两文件模型）
- 通过 `from symtest.file_comparator import ComparisonResult, Difference` 构造结构化结果
- `extra_kwargs` 自动从 config `compareSpec` 透传

在配置中直接使用注册的类型名：

```json
{
  "type": "myanalysis",
  "actual": "optional_for_plugins",
  "baseline": "optional_for_plugins",
  "param1": "value1"
}
```

#### 方式二：内置 `script` 类型比较器

适用于独立分析脚本快速接入，无需编写比较器类：

```json
{
  "type": "script",
  "script": "analyze_xxx.py",
  "actual": "output.txt",
  "baseline": "baseline.txt",
  "cwd": ".",
  "pass_pattern": "RESULT: PASS",
  "fail_pattern": "RESULT: (MISMATCH|FAILED)",
  "pass_exit_code": 0,
  "timeout": 600
}
```

**参数说明**：

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `script` | 是 | — | 脚本路径（相对 workspace 或绝对） |
| `actual` | 否 | — | 传给脚本的第一个文件参数 |
| `baseline` | 否 | — | 传给脚本的第二个文件参数 |
| `cwd` | 否 | — | 脚本工作目录 |
| `interpreter` | 否 | `sys.executable` | Python 解释器 |
| `pass_exit_code` | 否 | `0` | 判定为通过的退出码 |
| `pass_pattern` | 否 | — | stdout 必须匹配此正则才判定为通过 |
| `fail_pattern` | 否 | — | stdout 匹配此正则则强制判定为失败（优先级最高） |
| `timeout` | 否 | `3600` | 超时秒数 |

**判定逻辑**：
1. `fail_pattern` 匹配 → 失败（优先级最高）
2. `pass_pattern` 设置但不匹配 → 失败
3. `pass_pattern` 匹配 → 使用退出码判定
4. 无 pattern → 直接使用退出码判定

脚本的 stdout 和 stderr 会完整捕获到 `Comparator Output` 区块中，在报告渲染时限 20 行展示。

#### 方式三：手动注册（编程方式）

```python
from symtest.file_comparator import ComparatorFactory
from symtest.file_comparator.base_comparator import BaseComparator

class FooComparator(BaseComparator):
    # 实现 read_content / compare_content 等方法
    pass

ComparatorFactory.register_comparator("foo", FooComparator)

# 之后即可在 compare_files 断言或命令行 --file-type foo 中使用
comparator = ComparatorFactory.create_comparator("foo")
```

#### 专用插件示例：hourglass 切线刚度分析

`examples/plugins/hourglass_tangent_comparator.py` 是一个完整的工作区插件示例，展示了如何将专用的 `analyze_*_tangent.py` 分析脚本接入框架：

```json
{
  "type": "hourglass_tangent",
  "script": "case/.../analyze_case01_tangent.py",
  "case_dir": "case/.../case01",
  "pass_threshold": 1e-6,
  "timeout": 600
}
```

**特点**：
- 通过 subprocess 调分析脚本（**零改动** analyze 代码），捕获 stdout 后用正则解析 `RESULT:` 行和 `full_rel`/`aa_rel`/`hh_rel`/`asymmetry` 等数值指标
- 构造结构化 `ComparisonResult`：`identical` 基于 `full_rel < pass_threshold` 判定；`differences` 列出超限指标；`error_stats` 包含全部数值
- 脚本 stdout 进入 `Comparator Output` 区块

使用方法：将插件文件复制到 workspace 的 `comparators/` 目录下即可自动发现，无需改框架代码。

> **更多插件开发指导**：参见 `examples/plugins/README.md`。entry points (`pip install` 即生效) 将在后续迭代中支持。

### 断言与文件比较

`Assertions` 类提供静态断言方法，`expected` 中的校验均由其完成：

```python
from symtest.core.assertions import Assertions

Assertions.return_code_equals(actual_code, 0)
Assertions.contains(output, "expected text")
Assertions.matches(output, r".*regex.*")
Assertions.compare_files("actual.txt", "baseline.txt", file_type="text", workspace="/ws")

# 启用误差分析（仅 CSV/H5 生效）
Assertions.compare_files("actual.h5", "baseline.h5", file_type="h5", workspace="/ws", rtol=1e-5, error_analysis=True)
```

`compare_files` 会自动按扩展名识别类型（`.h5/.hdf5/.hdf`→h5、`.json`→json、`.csv/.tsv`→csv、`.xml/.html/.htm`→xml、`.txt/.log/.out/.py`→text、其余→binary），相对路径按 `workspace` 解析，额外参数（含 `error_analysis`）透传给比较器。

成功时返回结构化字典（含 `identical`、`actual`、`baseline`、`diff_summary`、`differences` 等字段），失败时抛出 `ValidationError(AssertionError)`，携带 `failure_kind` 和 `compare_failures` 列表。

## 运行框架自带测试

项目自带统一测试入口 `tests/run_all.py`，通过 `--scope` 选择测试范围（test target），并可用 `--extra` 透传任意 pytest 参数。

### 测试范围

| scope | 说明 | 对应目录 |
|---|---|---|
| `unit` | 单元测试（core、runners 等） | `tests/unit` |
| `integration` | 集成测试（文件比较、并行、路径处理等） | `tests/integration` |
| `e2e` | 端到端测试（用户流程） | `tests/e2e` |
| `all` | 运行上述全部范围（默认） | 三者合集 |

> 注：`tests/demos/` 下的脚本为手动/交互演示，不纳入 scope 运行，需单独执行。

### 用法

```bash
# 运行全部测试（默认）
python tests/run_all.py

# 开发者也可一次安装全部可选与测试依赖
pip install -e ".[dev]"

# 只运行单元测试
python tests/run_all.py --scope unit

# 只运行集成测试
python tests/run_all.py --scope integration

# 只运行端到端测试
python tests/run_all.py --scope e2e

# 透传 pytest 参数，例如按关键字过滤
python tests/run_all.py --scope integration --extra "-k h5"

# 透传多个 pytest 参数
python tests/run_all.py --scope unit --extra "-v -k assertions"
```

`--extra` 接收的字符串会经 `shlex` 拆分后追加到 pytest 命令行。脚本通过当前解释器（`sys.executable -m pytest`）调用 pytest，确保使用激活的环境而非 PATH 中首个 `pytest`。

测试环境需先激活你的 Python 环境（如 conda）：

```bash
conda activate <你的环境名>
python tests/run_all.py
```
