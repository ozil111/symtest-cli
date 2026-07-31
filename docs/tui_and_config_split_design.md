# 测试用例管理增强设计文档（配置拆分 + TUI 管理器）

> 本文档描述为解决「测试案例增多导致配置文件过大、不易维护」问题而设计的两项增强能力：
> **方案 B — 配置拆分机制**（治本，缓解文件膨胀）与 **方案 A — TUI 管理器**（治标，提供可视化 CRUD）。

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 现状分析](#2-现状分析)
- [3. 总体架构](#3-总体架构)
- [4. 方案 B：配置拆分机制](#4-方案-b配置拆分机制)
- [5. 方案 A：TUI 管理器](#5-方案-atui-管理器)
- [6. 模块结构](#6-模块结构)
- [7. 数据流](#7-数据流)
- [8. CLI 集成](#8-cli-集成)
- [9. 依赖管理](#9-依赖管理)
- [10. 技术难点与风险](#10-技术难点与风险)
- [11. 实施阶段与工作量](#11-实施阶段与工作量)
- [12. 兼容性与回退策略](#12-兼容性与回退策略)

---

## 1. 背景与目标

### 1.1 问题

随着被测项目的规模增长，单个测试配置文件（`test_cases.json` / `test_cases.yaml`）中的用例数量可能达到数十甚至数百条。每条用例又包含 `command`、`args`、`expected`（嵌套 dict）、`steps`、`resources`、`tags` 等字段，导致：

- **文件过长**：动辄上千行，人工浏览、定位、修改成本高。
- **易冲突**：多人协作时合并冲突频繁。
- **复用困难**：不同测试套件之间无法共享用例片段。
- **编辑易错**：手工编辑大段 JSON/YAML 容易出现缩进、逗号、字段缺失等语法错误。

### 1.2 目标

| 目标 | 对应方案 |
|---|---|
| 从结构上拆分大配置文件，按模块/标签组织用例 | 方案 B（配置拆分） |
| 提供可视化界面浏览、编辑、运行用例 | 方案 A（TUI） |
| 不破坏现有 CLI 用法，向后兼容 | 两者皆需 |
| 最小化对核心代码的侵入 | 两者皆需 |
| 保持核心包轻量，TUI 依赖可选安装 | 方案 A |

---

## 2. 现状分析

### 2.1 现有读写闭环

框架已具备完整的配置读写能力，这是两项增强方案的共同基础：

```
配置文件 (JSON/YAML)
    │  JSONRunner/YAMLRunner.load_test_cases()
    │  → json.load / yaml.safe_load
    ▼
config dict  (含 "test_cases" 列表)
    │  core.config_loader.parse_test_cases()
    ▼
List[TestCase]  (dataclass)
    │  run_single_test() / _run_sequence()
    ▼
results dict
```

### 2.2 关键复用点

| 能力 | 现状 | 对增强方案的意义 |
|---|---|---|
| `TestCase` / `TestCaseStep` 数据模型 | dataclass，字段清晰 | 可直接映射为 TUI 表格列 / 表单字段 |
| `TestCase.to_dict()` | 已实现，对象 → dict | TUI 保存写回配置文件几乎零成本 |
| `parse_test_cases()` | 已实现，dict → `List[TestCase]` | TUI 读取配置已有完整逻辑 |
| 配置格式 | 纯 JSON/YAML，顶层 `test_cases` 数组 | 结构简单，拆分与 TUI 展示均不复杂 |
| CLI 入口 | `cli.py` 用 argparse subparsers | 可无缝新增 `tui` 子命令 |

### 2.3 `TestCase` 数据模型回顾

```python
@dataclass
class TestCaseStep:
    command: str
    args: List[str]
    expected: Dict[str, Any]
    timeout: Optional[float] = None

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

    def to_dict(self) -> Dict[str, Any]: ...
```

两种模式：
- **单命令模式**：`command` + `args` + `expected`
- **步骤序列模式**：`steps` 列表，每步含 `command` + `args` + `expected` + `timeout`

---

## 3. 总体架构

两项方案在架构上互补，且都遵循「只做展示/组织层，复用核心读写逻辑」的原则：

```
┌──────────────────────────────────────────────────────────┐
│                      用户交互层                           │
│   symtest run      symtest tui      symtest validate  │
│      (现有)          (新增 A)           (新增 B 辅助)      │
└─────────┬───────────────┬───────────────────┬────────────┘
          │               │                   │
┌─────────▼───────────────▼───────────────────▼────────────┐
│                   管理增强层 (新增)                        │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │ config_io.py (B)    │   │ tui/ (A)                 │  │
│  │  配置读写封装        │   │  app / screens / widgets │  │
│  │  导入展开            │   │  依赖 config_io          │  │
│  └──────────┬──────────┘   └────────────┬─────────────┘  │
└─────────────┼───────────────────────────┼────────────────┘
              │                           │
┌─────────────▼───────────────────────────▼────────────────┐
│                      核心层 (复用，不改动)                 │
│  parse_test_cases()  │  TestCase.to_dict()               │
│  BaseRunner / Runners│  Assertions / Execution           │
└──────────────────────────────────────────────────────────┘
```

**设计原则**：
1. 管理增强层**只做读写封装与展示**，不重新实现解析/断言/执行逻辑。
2. 核心层 `parse_test_cases()` 与 `TestCase.to_dict()` 不需要修改。
3. 配置拆分在「加载时展开」为标准 config dict，对 Runner 完全透明。

---

## 4. 方案 B：配置拆分机制

### 4.1 设计目标

让用户可以把一个大配置文件拆成多个小文件，按模块/功能/标签组织，运行时自动合并加载。**不改 Runner，不改 `parse_test_cases`**，仅在「文件 → config dict」这一步做展开。

### 4.2 拆分方式：显式导入（import 引用）

主配置文件通过 `import` 字段引用子文件：

```json
// main_config.json
{
  "setup": {
    "environment_variables": { "PYTHONPATH": "./src" }
  },
  "test_cases": [
    { "import": "cases/text_tests.json" },
    { "import": "cases/json_tests.json" },
    { "import": "cases/h5_tests.yaml" }
  ]
}
```

子文件结构与主文件中的 `test_cases` 元素一致，即子文件顶层就是 `test_cases` 数组：

```json
// cases/text_tests.json
{
  "test_cases": [
    {
      "name": "text_identical",
      "command": "python",
      "args": ["./compare_text.py"],
      "expected": { "return_code": 0 }
    }
  ]
}
```

**展开规则**：加载主配置时，遇到 `test_cases` 中带 `import` 键的元素，递归读取子文件，把子文件的 `test_cases` 内联展开替换 `import` 元素。

### 4.3 展开算法

```
function load_and_expand(config_path, workspace):
    raw = json.load / yaml.safe_load(config_path)
    
    # 1. 合并 setup（如果有）
    setup = raw.get("setup", {})
    
    # 2. 展开 test_cases
    expanded_cases = []
    for item in raw.get("test_cases", []):
        if "import" in item:
            sub_path = resolve_relative_to(config_path, item["import"])
            sub_raw = load_and_expand(sub_path, workspace)  # 递归
            sub_setup = sub_raw.get("setup", {})
            merge_setup(setup, sub_setup)
            expanded_cases.extend(sub_raw["test_cases"])
        else:
            expanded_cases.append(item)
    
    return { "setup": setup, "test_cases": expanded_cases }
```

**循环引用保护**：维护一个已加载文件路径集合，遇到重复路径时抛出明确错误。

**路径解析**：`import` 路径相对于**主配置文件所在目录**解析，不相对于 cwd。

### 4.4 配置校验辅助命令

新增 `validate` 子命令，在不运行测试的情况下检查配置：

```bash
symtest validate test_cases.json
symtest validate ./test_suite/
```

校验内容：
- JSON/YAML 语法正确性
- 必填字段完整性（`name`、`command`、`args`、`expected`）
- `import` 引用的文件是否存在
- 循环引用检测

### 4.5 与 Runner 的集成方式

**关键决策：在 Runner 加载配置时做展开，而非修改 `parse_test_cases`。**

两种集成路径（择一）：

| 路径 | 做法 | 侵入性 |
|---|---|---|
| **路径 1（推荐）**：在 `BaseRunner.load_test_cases()` 调用 `load_and_expand()` 替代直接 `json.load` | 改动集中在各 Runner 的 `load_test_cases`，一行替换 | 低 |
| 路径 2：在 `cli.py` 展开后写临时文件传给 Runner | 不改 Runner，但产生临时文件 | 中 |

推荐**路径 1**，因为 `JSONRunner.load_test_cases()` 和 `YAMLRunner.load_test_cases()` 当前实现就是「读文件 → 调 `parse_test_cases`」，只需在「读文件」后插入展开步骤。

---

## 5. 方案 A：TUI 管理器

### 5.1 技术选型

| 候选 | 评估 |
|---|---|
| **Textual**（推荐） | 基于 rich，现代 TUI 框架，支持 CSS 样式、组件化、虚拟滚动表格；SSH 友好；与 CLI 框架定位一致 |
| prompt_toolkit | 更底层，稳定但开发量大 |
| curses | 太底层，跨平台性差（Windows 支持弱） |
| tkinter / PyQt | GUI 方案，不支持 SSH，依赖重，与 CLI 定位不符 |
| Streamlit / Gradio | Web UI，需起服务，不适合纯终端场景 |

**选型结论：Textual**。理由：
1. 与 CLI 框架定位高度一致。
2. SSH/远程开发友好（用户多为开发者）。
3. 组件丰富（DataTable、Input、TabbedContent 等），开发效率高。
4. 依赖可控，可作为可选依赖安装。

### 5.2 界面设计

#### 主界面 — 用例列表

```
┌─ CLI Test Framework - Case Manager ──────────────────────┐
│ File: test_cases.json          [15 cases]  [tag: All   ]  │
├──────────────────────────────────────────────────────────┤
│ Search: [json_exact                    ]  [3 matches    ]  │
├──────────────────────────────────────────────────────────┤
│ #  │ Name           │ Command      │ Tags      │ Timeout │
│────┼────────────────┼──────────────┼───────────┼─────────│
│▶2  │ json_exact     │ python ./co..│ json      │ -       │
│ 3  │ h5_comparison  │ python ./co..│ h5        │ 30.0    │
│ 5  │ json_partial   │ python ./co..│ json,fuzz │ 5.0     │
├──────────────────────────────────────────────────────────┤
│ [/]fuzzy  [a]dd  [e]dit  [d]elete  [u]plicate  [r]un  [F6]save  [^Q]quit│
└──────────────────────────────────────────────────────────┘
```

功能：
- 表格展示所有 case，列：序号、名称、命令、标签、超时、模式（单命令/序列）
- 顶部状态栏：当前文件、用例数、tag 过滤下拉
- **搜索栏**：实时模糊搜索，搜索所有字段（name / command / args / tags / description）
- 底部快捷键栏，`/` 键快速聚焦搜索框

#### 编辑界面 — 表单

单命令模式：
```
┌─ Edit Test Case ─────────────────────────────────────────┐
│ Name:     [json_exact                          ]          │
│ Command:  [python                              ]          │
│ Args:     [./compare_json.py, --strict         ]          │
│ Timeout:  [                                     ]          │
│ Tags:     [json, exact                          ]          │
│ Description:                                              │
│ [Compare two JSON files with exact matching             ] │
│                                                          │
│ ── Expected ─────────────────────────────────────────── │
│ return_code:      [0      ]                              │
│ output_contains:  [+ Add string]                         │
│   • "success"  [x]                                       │
│   • "done"     [x]                                       │
│ output_matches:   [.*regex.*]  (optional)                │
│ compare_files:   [+ Add file pair]                       │
│                                                          │
│ [Save]  [Cancel]  [Switch to Sequence Mode]              │
└──────────────────────────────────────────────────────────┘
```

步骤序列模式：
```
┌─ Edit Test Case (Sequence) ──────────────────────────────┐
│ Name: [multi_step_pipeline              ]                 │
│ Tags: [pipeline                         ]                 │
│                                                          │
│ ── Steps ─────────────────────────────────────────────  │
│ Step 1/3  [Edit] [Delete] [↑] [↓]                        │
│   command: python ./step1.py                             │
│ Step 2/3  [Edit] [Delete] [↑] [↓]                        │
│   command: python ./step2.py                             │
│ Step 3/3  [Edit] [Delete] [↑] [↓]                        │
│   command: python ./step3.py                             │
│ [+ Add Step]                                             │
│                                                          │
│ [Save]  [Cancel]  [Switch to Single Command Mode]        │
└──────────────────────────────────────────────────────────┘
```

#### 运行结果面板

选中单条 case 按 `r` 运行后，底部弹出结果面板：
```
┌─ Run Result: json_exact ─────────────────────────────────┐
│ Status: PASSED   Return code: 0   Duration: 1.23s        │
├──────────────────────────────────────────────────────────┤
│ Output:                                                  │
│ Comparing files...                                       │
│ Files are identical.                                     │
│                                                          │
│ [Close]                                                  │
└──────────────────────────────────────────────────────────┘
```

### 5.3 功能清单

| 功能 | 说明 |
|---|---|
| 列表浏览 | DataTable 虚拟滚动，支持数百条 case |
| **模糊搜索** | `/` 键聚焦搜索框，实时模糊搜索所有字段（name / command / args / tags / description）；搜索结果高亮、显示匹配数、上下导航跳转 |
| tag 过滤 | 按 tag 下拉选择过滤，与搜索条件叠加 |
| 列排序 | 点击列表头按该列排序（升序/降序切换） |
| 新增 | 弹出空表单，填完后追加到列表 |
| 编辑 | 弹出预填表单，保存后更新 |
| 删除 | 选中后确认删除 |
| 复制 | 选中后复制为新 case（名称加 `_copy` 后缀） |
| 上下移动 | 调整 case 在列表中的顺序 |
| 单条运行 | 调用 `execute_single_test_case` 执行，显示结果 |
| 批量运行 | 可选：选中多条后运行，复用现有 Runner |
| 保存 | 写回原配置文件（利用 `to_dict()` + `json.dump` / `yaml.dump`） |
| 另存为 | 保存到新文件 |
| 切换模式 | 单命令 ↔ 步骤序列（切换时清空对应字段并提示） |
| 未保存提示 | 有改动未保存时退出/切换文件时提示确认 |

### 5.3.1 搜索功能深入设计

搜索的设计目标是**不低于 VS Code Ctrl+F 的使用体验**。具体实现如下：

#### 搜索模式

支持三种模式，通过 `Tab` 切换：

| 模式 | 快捷键 | 说明 | 示例 |
|---|---|---|---|
| 子串匹配（默认） | - | 大小写不敏感，任意位置匹配 | `json` 匹配 `json_exact`、`compare_json`、`MyJsonTest` |
| 模糊匹配 | `Alt+F` | 字符级模糊，容忍拼写差异和缩写 | `jexc` 匹配 `json_exact`、`jsont` 匹配 `json_test` |
| 正则匹配 | `Alt+R` | 完整正则，大小写敏感可选 | `json.*h5`、`^(text\|json)_` |

#### 模糊匹配算法

使用 **双阶段匹配**，在搜索性能和结果质量间取得平衡：

1. **初筛（filtering）**：对每个 case 展开所有可搜索字段为一个文本 blob，对所有 blob 做字符级模糊匹配。使用基于 N-gram（1-gram + 2-gram）的评分，快速粗筛。
2. **精排（scoring）**：对候选结果按匹配质量排序：
   - **连续子串匹配** > 分隔字符匹配 > 非连续匹配
   - name 字段匹配权重 > command 字段 > 其他字段
   - 匹配位置越靠前得分越高

```python
# 模糊匹配评分伪代码
def fuzzy_score(query: str, candidate_fields: dict) -> float:
    score = 0.0
    field_weights = {"name": 2.0, "command": 1.5, "description": 1.0,
                     "tags": 1.0, "args": 0.5}
    
    for field_name, text in candidate_fields.items():
        weight = field_weights.get(field_name, 0.5)
        # N-gram overlap score
        score += weight * ngram_similarity(query, text.lower())
    
    return score
```

#### 搜索字段

默认搜索所有以下字段（可配置开关单个字段）：

| 字段 | 权重 | 可禁用 |
|---|---|---|
| `name` | 2.0 | ✓ |
| `command` | 1.5 | ✓ |
| `args` | 0.5 | ✓ |
| `tags` | 1.0 | ✓ |
| `description` | 1.0 | ✓ |

#### 搜索结果导航

- 搜索结果自动过滤表格，仅显示匹配的行。
- 匹配的文本在表格中**高亮显示**。
- 搜索栏右侧显示「第 N/M 个匹配」。
- `Enter` / `Shift+Enter` 在匹配结果间上下跳转。
- `Esc` 清空搜索，恢复完整列表。
- 搜索历史：`↑` / `↓` 在搜索框中浏览最近 10 条搜索词。

#### 交互布局

```
┌─ CLI Test Framework - Case Manager ──────────────────────┐
│ File: test_cases.json          [15→3]  [tag: All       ]  │
├──────────────────────────────────────────────────────────┤
│ Search: [json_▌                          ] [模糊]  [3/3]  │
│  模式: [子串] [模糊(F)] [正则(R)]  大小写: [Aa]           │
├──────────────────────────────────────────────────────────┤
│ #  │ Name           │ Command      │ Tags      │ Timeout │
│────┼────────────────┼──────────────┼───────────┼─────────│
│▶2  │ json_exact     │ python ./co..│ json      │ -       │
│ 3  │ h5_comparison  │ python ./co..│ h5,**json**│ 30.0  │
│ 5  │ json_partial   │ python ./co..│ json,fuzz │ 5.0     │
├──────────────────────────────────────────────────────────┤
│ [/]fuzzy  [a]dd  [e]dit  [d]elete  [u]plicate  [r]un  [F6]save  [^Q]quit│
└──────────────────────────────────────────────────────────┘
```

搜索栏展开时显示第二行（模式切换），平时收起只显示一行以节省空间。

### 5.4 `expected` 字段编辑策略

`expected` 是嵌套 dict，key 不固定。采用「已知 key 固定表单 + 未知 key 自定义扩展」策略：

| 已知 key | 编辑方式 |
|---|---|
| `return_code` | 数字输入框 |
| `output_contains` | 字符串列表（动态增删） |
| `output_matches` | 文本输入框（正则） |
| `compare_files` | 文件对列表（actual / baseline / type 三元组） |

未知 key 通过「自定义键值对」区域添加，值为字符串或 JSON 文本。

---

## 6. 模块结构

### 6.1 新增目录结构

```
src/symtest/
├── config/                    ← 新增（方案 B）
│   ├── __init__.py
│   ├── config_io.py           # 配置读写封装
│   └── import_expander.py     # import 引用展开
├── tui/                       ← 新增（方案 A）
│   ├── __init__.py
│   ├── app.py                 # Textual App 主入口
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── case_list.py       # 列表主界面
│   │   └── case_editor.py     # 编辑表单界面
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── case_table.py      # 测试用例表格组件
│   │   ├── expected_editor.py # expected dict 编辑组件
│   │   ├── steps_editor.py    # steps 序列编辑组件
│   │   └── search_bar.py      # 模糊搜索栏组件
│   └── controllers/
│       ├── __init__.py
│       └── case_controller.py # 协调 config_io 与 TUI 状态
├── cli.py                     # 修改：新增 tui / validate 子命令
└── ...（现有模块不变）
```

### 6.2 模块职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `config/config_io.py` | 统一的配置读写入口：读文件 → 展开 → 返回 config dict；写 config dict → 文件 | `import_expander` |
| `config/import_expander.py` | 递归展开 `import` 引用，处理循环引用 | 无（纯逻辑） |
| `tui/app.py` | Textual App 实例，管理 Screen 切换、全局状态 | textual |
| `tui/screens/case_list.py` | 列表主界面 Screen | `case_table`、`search_bar`、`case_controller` |
| `tui/screens/case_editor.py` | 编辑表单 Screen（单命令 + 序列两种模式） | `expected_editor`、`steps_editor` |
| `tui/widgets/case_table.py` | DataTable 封装，支持过滤排序 | textual |
| `tui/widgets/search_bar.py` | 模糊搜索栏，支持多字段实时搜索 | textual |
| `tui/widgets/expected_editor.py` | `expected` 嵌套 dict 编辑组件 | textual |
| `tui/widgets/steps_editor.py` | `steps` 列表编辑组件 | textual |
| `tui/controllers/case_controller.py` | 协调 config_io 与 TUI：持有 `List[TestCase]`、处理 CRUD、保存 | `config.config_io`、`core.test_case` |

### 6.3 与现有模块的复用关系

```
tui/controllers/case_controller.py
    ├── 读: config.config_io.load_config() → config dict
    │         → core.config_loader.parse_test_cases() → List[TestCase]
    └── 写: List[TestCase] → [tc.to_dict() for tc in ...]
              → config dict → config.config_io.save_config()
```

**关键：TUI 层不直接调用 `parse_test_cases`，而是通过 `config_io` 拿到 config dict 后复用 `parse_test_cases`。保存时通过 `to_dict()` 重建 config dict 再写回。**

---

## 7. 数据流

### 7.1 配置拆分加载流（方案 B）

```
用户传入 config_file
       │
       ▼
config_io.load_config(config_file, workspace)
       │
       └── json.load / yaml.safe_load → raw config dict
             │
             └── import_expander.expand(raw, config_path)
                   ├── 遍历 test_cases
                   ├── 遇到 {"import": "..."} → 递归 load_config
                   └── 内联展开
       │
       ▼
展开后的 config dict  (标准结构，与原格式一致)
       │
       ▼
Runner.load_test_cases() → parse_test_cases() → List[TestCase]
       (Runner 对拆分过程完全无感知)
```

### 7.2 TUI 编辑流（方案 A）

```
启动 TUI
       │
       ▼
config_io.load_config(file) → config dict
       │
       ▼
parse_test_cases(config, workspace, path_resolver) → List[TestCase]
       │
       ▼
CaseController 持有 List[TestCase]
       │
       ├── 展示 → case_table widget
       │
       ├── 用户编辑 → 更新内存中的 TestCase 对象
       │
       ├── 单条运行 → execute_single_test_case(tc, workspace) → 结果面板
       │
       └── 保存:
             List[TestCase]
               │ [tc.to_dict() for tc in cases]
               ▼
             config dict {"test_cases": [...], "setup": ...}
               │
               ▼
             config_io.save_config(config_dict, file_path)
               │
               ▼
             json.dump / yaml.dump → 文件
```

### 7.3 配置校验流（validate 命令）

```
symtest validate <path>
       │
       ▼
config_io.load_config(path) → config dict  (含展开)
       │
       ├── 检查 JSON/YAML 语法 ✓
       ├── 检查必填字段 ✓
       ├── 检查 import 引用存在性 ✓
       └── 循环引用检测 ✓
       │
       ▼
输出校验报告:
  ✓ Loaded 15 test cases from 3 files
  ✓ All required fields present
  ✓ No circular imports detected
  
  Files:
    - main_config.json (5 cases)
    - cases/text_tests.json (6 cases)
    - cases/json_tests.json (4 cases)
```

---

## 8. CLI 集成

### 8.1 新增子命令

在 `cli.py` 的 `create_parser()` 中新增：

```python
# ---- TUI command (方案 A) ----
tui_parser = subparsers.add_parser('tui', help='Launch interactive TUI for managing test cases')
tui_parser.add_argument('config_file', help='Path to the test configuration file (JSON or YAML)')
tui_parser.add_argument('--workspace', '-w', help='Working directory')

# ---- Validate command (方案 B 辅助) ----
validate_parser = subparsers.add_parser('validate', help='Validate test configuration without running')
validate_parser.add_argument('config_file', help='Path to config file or directory')
validate_parser.add_argument('--workspace', '-w', help='Working directory')
```

### 8.2 `run` 命令增强

`run` 命令的 `config_file` 参数支持带 `import` 引用的主配置文件：

```bash
# 现有用法（不变）
symtest run test_cases.json
symtest run test_cases.yaml

# 新增：带 import 的主配置
symtest run main_config.json
```

### 8.3 `main()` 分发

```python
if args.command == 'run':
    success = run_tests(args)
    sys.exit(0 if success else 1)
elif args.command == 'compare':
    success = run_compare(args)
    sys.exit(0 if success else 1)
elif args.command == 'tui':
    from .tui.app import run_tui  # 延迟导入，避免未安装 textual 时报错
    run_tui(args.config_file, args.workspace)
elif args.command == 'validate':
    from .config.config_io import validate_config
    validate_config(args.config_file, args.workspace)
else:
    parser.print_help()
    sys.exit(1)
```

**注意 `tui` 子命令的延迟导入**：`from .tui.app import run_tui` 放在 `elif` 分支内部，确保未安装 textual 时其他命令不受影响。

### 8.4 使用示例

```bash
# 方案 B：配置拆分
symtest run main_config.json          # 自动展开 import
symtest validate main_config.json     # 校验配置

# 方案 A：TUI 管理
symtest tui test_cases.json           # 打开 TUI 编辑
symtest tui test_cases.yaml -w ./proj # 指定工作目录

# 组合使用：拆分配置 + TUI
symtest tui main_config.json          # TUI 中编辑主配置（含 import 引用）
```

---

## 9. 依赖管理

### 9.1 可选依赖

在 `pyproject.toml` / `setup.py` 中新增 extras：

```toml
[project.optional-dependencies]
tui = ["textual>=0.40.0"]
```

```bash
pip install symtest-cli[tui]   # 安装 TUI 依赖
pip install symtest-cli        # 核心包，不含 TUI
```

### 9.2 优雅降级

当用户执行 `symtest tui` 但未安装 textual 时，给出友好提示：

```python
def run_tui(config_file, workspace):
    try:
        import textual
    except ImportError:
        print(
            "TUI 功能需要安装 textual。请运行：\n"
            "  pip install symtest-cli[tui]\n"
            "或：\n"
            "  pip install textual"
        )
        sys.exit(1)
    # 正常启动 TUI ...
```

### 9.3 方案 B 无额外依赖

配置拆分机制仅使用标准库（`json`、`pathlib`、`os`）和已有的 `yaml`，不引入新依赖。

---

## 10. 技术难点与风险

| 难点 | 说明 | 应对 |
|---|---|---|
| `expected` 嵌套 dict 编辑 | key 不固定，含 `return_code`、`output_contains`、`output_matches`、`compare_files` 等 | 已知 key 固定表单 + 未知 key 动态键值对；`compare_files` 做专门的三元组编辑组件 |
| `steps` 序列模式编辑 | 一个 case 内多步，每步又有完整 command/args/expected | 分步编辑：先选步骤再进步骤编辑表单；支持上下移动、增删 |
| 单命令 ↔ 序列模式切换 | 字段结构不同，切换会丢失数据 | 切换前提示确认，保留可保留字段（name/tags/description） |
| Textual 版本兼容 | Textual 仍在 0.x，API 可能变化 | 锁定最低版本 `>=0.40.0`，CI 中固定测试版本 |
| 配置拆分循环引用 | A import B，B import A | 维护已加载路径集合，检测到循环抛出明确错误 |
| `import` 路径解析基准 | 相对 cwd 还是相对配置文件 | **相对配置文件所在目录**，更符合直觉 |
| setup 合并冲突 | 多文件各有 setup.environment_variables | 后加载覆盖先加载（文档明确说明）；同名变量冲突时 warning |
| 大量 case 性能 | 数百条 case 的 TUI 渲染 | Textual DataTable 支持虚拟滚动，性能可接受 |
| 保存格式一致性 | 读 YAML 存 JSON 或反之 | 保持原文件扩展名，按扩展名选择 dumper；另存为时按目标扩展名 |

---

## 11. 实施阶段与工作量

### 11.1 推荐实施顺序

**方案 B 优先**（投入产出比高，且为方案 A 提供基础）：

```
阶段 1: 方案 B — 配置拆分
  ├── import_expander.py
  ├── config_io.py
  ├── validate 子命令
  ├── run 命令集成（支持 import 展开）
  └── 测试

阶段 2: 方案 A — TUI 管理器
  ├── config_io 复用（已在阶段 1 完成）
  ├── case_controller.py
  ├── case_table + search_bar widgets
  ├── case_list screen
  ├── case_editor screen
  ├── expected_editor / steps_editor widgets
  ├── tui 子命令 + 优雅降级
  └── 测试
```

### 11.2 工作量估算

| 模块 | 估算 |
|---|---|
| **方案 B** | |
| `import_expander.py` | 1 天 |
| `config_io.py`（读写封装 + 展开集成） | 0.5 天 |
| `validate` 子命令 + `run` 集成 | 0.5 天 |
| 测试（含循环引用、展开、合并） | 1 天 |
| **方案 B 小计** | **3 天** |
| **方案 A** | |
| `case_controller.py` + TUI 脚手架 | 0.5 天 |
| 列表主界面（case_table + 搜索栏 + 过滤排序） | 1.5 天 |
| 搜索栏（子串/模糊/正则三种模式 + 高亮导航） | 1 天 |
| 编辑表单（单命令模式 + expected 编辑器） | 1.5 天 |
| 序列模式编辑（steps_editor） | 1 天 |
| 单条运行 + 结果面板 | 0.5 天 |
| `tui` 子命令 + 可选依赖 + 优雅降级 | 0.5 天 |
| 测试 | 1 天 |
| **方案 A 小计** | **7.5 天** |
| **合计** | **约 10.5 天** |

---

## 12. 兼容性与回退策略

### 12.1 向后兼容

| 方面 | 兼容性 |
|---|---|
| 现有 `run` 命令用法 | ✅ 完全兼容，单文件配置行为不变 |
| 现有配置文件格式 | ✅ 完全兼容，无 `import` 字段时按原逻辑加载 |
| `parse_test_cases()` | ✅ 不修改，接收的仍是展开后的标准 config dict |
| `TestCase.to_dict()` | ✅ 不修改 |
| Python API（`JSONRunner` / `YAMLRunner` 直接使用） | ✅ 兼容，`load_test_cases` 内部改用 `config_io` 但返回结构不变 |
| 现有测试 | ✅ 不受影响 |

### 12.2 回退策略

- **方案 B**：如果配置拆分出现问题，用户只需把所有用例放回单文件即可，`config_io` 对无 `import` 的配置与原逻辑等价。
- **方案 A**：TUI 完全可选，不安装 textual 不影响任何现有功能。用户可随时回退到手工编辑配置文件。

### 12.3 渐进式采用

用户无需一次性迁移所有配置：
1. 先用 `validate` 命令校验现有配置无问题。
2. 逐步把大文件中的用例拆到子文件，用 `import` 引用。
3. 需要可视化编辑时安装 `[tui]` extra 并使用 `symtest tui`。

---

## 附录：设计决策汇总

| 决策 | 原因 |
|---|---|
| 配置拆分在加载时展开，不改 `parse_test_cases` | 保持核心层纯净，Runner 对拆分无感知 |
| `import` 路径相对配置文件目录解析 | 比相对 cwd 更符合直觉，配置可移植 |
| TUI 选 Textual 而非 GUI | 与 CLI 框架定位一致，SSH 友好 |
| TUI 依赖设为可选 extras | 保持核心包轻量 |
| `tui` 子命令延迟导入 textual | 未安装时不影响其他命令 |
| `expected` 用已知 key 固定表单 + 未知 key 动态扩展 | 平衡易用性与灵活性 |
| 单命令/序列模式可切换 | 适应不同用例复杂度 |
| 方案 B 优先实施 | 投入产出比高，且为 TUI 提供配置读写基础 |
