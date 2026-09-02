# CLI Test Framework 设计文档

> **维护原则（单一事实来源）**：本文档不镜像代码结构——不再维护目录树、类签名、
> 函数清单、dataclass 字段定义等会随代码漂移的内容。目录结构与 API 以
> `src/symtest/` 源码及其 docstring 为准，用法示例见 `examples/`。
> 本文档只承载代码里读不出来的设计信息：架构分层、职责边界、关键流程语义、
> 扩展契约、设计决策与核心架构宪法。

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  CLI 入口层    symtest run / tui / validate / schema /       │
│                compare-files（+ TUI 交互界面）                │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  业务层        Runners（顺序 / 并行 / DAG / 资源感知）        │
│                File Comparators（多类型 + 插件）             │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  配置管线      raw JSON/YAML → expand_imports                │
│                → resolve_inheritance → apply_variables       │
│                → substitute_placeholders → parse_test_cases  │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Core 层       TestCase 模型 · 断言引擎 · 单测试执行          │
│                Runner 基类 · Setup 插件 · .symtest 状态存储   │
│                路径解析 · 报告生成 · JUnit XML                │
└─────────────────────────────────────────────────────────────┘
```

框架分为四层：**CLI 入口层**（含 TUI）、**Runner / Comparator 业务层**、**Config 管线层**、**Core 基础层**。

层与层不是自由组合：跨层数据流与依赖方向受 §10「核心架构宪法」约束，
新增 feature 请先对照宪法确定归属。

## 2. 模块地图

以包为单位的职责划分（文件级明细与公开 API 以源码为准）：

| 包 | 职责 |
|---|---|
| `cli.py` / `commands/` | 子命令入口、参数装配与日志激活 |
| `core/` | TestCase 数据模型、断言引擎、单测试执行、Runner 基类（顺序 / 并行 / DAG）、`.symtest` 状态存储、Setup 插件体系 |
| `config/` | 配置 IO、JSON Schema 校验（draft 2020-12）、import 展开、extends 继承、变量与占位符替换 |
| `runners/` | Config/JSON/YAML × 顺序/并行 的薄封装运行器 |
| `file_comparator/` | 比较器家族 + 工厂 + workspace 插件发现（详见 §6） |
| `utils/` | 路径解析、报告生成、JUnit XML 输出 |
| `tui/` | Textual 交互式用例管理（详见 §7） |

### 2.1 入口点

| 命令 | 映射 |
|---|---|
| `symtest run` | `symtest.cli:run_tests` |
| `symtest tui` | `symtest.tui.app:run_tui` |
| `symtest validate` | `symtest.cli:run_validate` |
| `symtest schema` | `symtest.cli:run_schema` |
| `symtest compare` | `symtest.cli:run_compare` |

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

主配置文件通过 `"import"` 引用子配置文件：

- 递归展开所有 import，内联到主配置中
- import 级 tags 注入到被引文件的每个 case
- setup 深度合并
- 循环引用检测

配置形态与用法示例见 `examples/`。

### 3.2 继承展开 (`inheritance_expander.py`)

`extends` 字段实现用例模板继承：

- 深度合并（dict）/ 整体替换（list）策略
- `abstract: true` 的模板不参与执行
- extends 链上的 `variables` 收集后统一替换
- 循环继承检测

### 3.3 配置验证 (`config_io.py`)

`symtest validate` 子命令在不执行测试的情况下校验配置：

- Error 级（影响 valid）：JSON/YAML 语法、必填字段、import 目标存在性、循环引用、extends 目标存在性、循环继承
- Warning 级（不影响 valid）：命令可执行性（PATH 查找）、`compare_files` baseline 文件存在性

## 4. 执行语义

> 本章只记载跨模块的行为语义约定；类属性、方法签名与默认值以源码为准。

### 4.1 Runner 模板与状态映射

- 模板流程固定：`load_test_cases()` → 过滤（名称精确 / tags 交集 / `--last-failed`）→ `setup_all()` → 逐 case 执行 → xfail 状态映射 → 历史与 last-run 更新 → `teardown_all()`（逆序，保证出错也继续清理）
- JSON/YAML Runner 仅注入不同的 config_loader，通用逻辑统一在顺序 / 并行通用运行器中
- xfail：`expected_failure=True` 时 `passed → xpassed`（意外通过，计入失败）；任意非 passed → `xfailed`（预期失败，不计入失败）
- JUnit XML 状态映射：`xfailed → <skipped>`、`xpassed → <failure>`、`timeout → <error>`、`failed` 按消息类型分 `<failure>` / `<error>`
- 历史：累计平均更新；写入前先按 `regression_threshold` 与旧均值做回归检测；`--update-history` 清除后重记
- `--last-failed`：每次运行只覆写本次参与执行的用例状态，子集运行不丢失其余用例状态

### 4.2 测试双模式

单命令模式（`command + args + expected`）与 steps 序列模式二选一；每个 step 是
"执行 + 判定"的原子对（command / args / timeout / retry_count / expected）。
字段全集见 `core/test_case.py` 与 JSON Schema，本文不复述。

### 4.3 并行与资源调度

- LPT 策略：长任务先行；启用 history 时优先用 `.symtest` 历史 `avg_duration` 排序，其次才看声明的 `estimated_time`
- `AtomicSemaphore` 资源池：`safe_capacity = max(1, cpu_count − 2)`；每个 case 按 `cpu_cores` acquire/release
- 按权重比例分配相对 CPU 核数，并自动注入 `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `NPROC`
- 环境变量优先级：`os.environ` < 调度器注入 < case 级 env（经 subprocess 注入，不改进程全局环境）
- 线程模式共享内存 + 结果/打印锁；进程模式经 process worker 隔离；可回退顺序执行

### 4.4 DAG 依赖调度语义

- `depends_on` 非空自动切换拓扑模式；无依赖时走零开销 fast path
- Kahn 入度表 + 就绪队列，依赖满足后立即提交后继
- 依赖"满足" = `passed` 或 `xfailed`；`failed` / `xpassed` 触发 BFS 级联 skip 全部下游
- `skipped` 不计入 `failed` 计数，报告中单独列出
- 顺序 runner 同样按拓扑序执行，依赖失效时跳过下游

### 4.5 单测试执行

PathResolver 解析（系统命令直通、shell builtin 平台包装、复合命令拆分解析）
→ subprocess 隔离执行（捕获 stdout / stderr / returncode / duration）
→ 断言校验（return_code / contains / matches / compare_files）
→ 失败按 `retry_count` 重试
→ 超时 kill 整个进程组
→ 返回附带 `next_action_hint` 的结构化结果。

### 4.6 断言与文件比较集成

- `compare_files` 是一等断言，经 ComparatorFactory 按类型分发（详见 §6）
- 所有断言可选；未声明的字段不做校验
- `--error-analysis` 为 CSV/H5 数值比较提供流式误差统计：`total_numeric_cells` / `mismatched_cells` / `max_abs_error` / `max_rel_error` / `mean_abs_error` / `rms_abs_error`

## 5. 运行时状态持久化（`.symtest/`）

| 状态 | 内容 | 更新时机 / 语义 |
|---|---|---|
| 历史记录 | per-case `avg_duration` / `last_duration` / `run_count` | 运行后累计平均更新；先回归检测后写入 |
| `last_run.json` | case → 上次状态 | 覆写参与执行的用例；未执行的保留旧状态 |
| `sequence_state/<case>.json` | steps + case expected 的 SHA-256 配置哈希、已通过的 step 集 | 每步 pass 后保存；全部通过后清理 |
| `sequence_state/cache/*.log` | 步骤输出缓存 | 与上同步；供 resume 拼接复现 |

**resume 语义**：`--resume` 比对配置哈希——匹配则跳过已过步骤并拼接缓存输出，
失配即全量重跑。纯信任模型：不验证 workspace 产物，由用户保证未被修改。

## 6. 文件比较子系统

### 6.1 比较器分层

- 文本系比较器共享 difflib 行级基底，json / csv / xml 为其结构化特化（键对齐 / 列结构 / DOM 对齐）
- h5 面向科学数据集；binary 流式分块 + LCS 相似度；script 委托外部脚本
- 统一返回 ComparisonResult（identical / differences / error / script command_output），支持 text / json / html 渲染；支持行列窗口范围参数截取后比较

### 6.2 工厂与插件发现

- `file_type` 取值：`text` / `json` / `csv` / `xml` / `h5` / `binary` / `script`；工厂按类型分发，支持动态注册与全局 reset（测试用）
- 插件发现四处来源：内置 `*_comparator.py` 自动发现、`workspace/comparators/` 自动扫描、`--plugin-dir` CLI 参数、`CLITEST_PLUGIN_DIRS` 环境变量（供进程模式 worker 使用）
- 命名约定：`*_comparator.py` + `*Comparator` 类名

### 6.3 script 比较协议（对外契约）

- 子进程方式执行 `<interpreter> <script> <actual> <baseline>`
- 默认 exit code 0 → 通过；可选 `pass_pattern` / `fail_pattern` 正则匹配 stdout 细化判定
- 超时可配

## 7. TUI 子系统

基于 Textual 的终端交互界面：App + Controller（load / create / update /
delete / run_single / save 业务动作）+ 列表 / 编辑两屏 + 表格封装、多模式搜索条
（名称 / 命令 / 标签）、expected 编辑器、steps 编辑器。

快捷键：`q` / Ctrl+Q 退出、`r` 刷新、`e` 编辑、`f` 单跑、`/` 搜索、`a` 新增、`d` 删除、`s` 保存。

TUI 与 runner 共用同一解析器；宽松的展示形态在 TUI 侧自行处理（§10 原则 6）。

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
| `.symtest/` 目录 | 不干扰用户目录视图，JSON 格式便于调试；状态文件统一管理 |
| 环境变量注入 | 科学计算求解器常忽略 Python 级线程控制 |
| case 级 env 通过 subprocess 注入 | 不改进程全局 `os.environ`，进程隔离、并行线程安全；优先级 `os.environ` < 调度器 < case env |
| Comparator 工厂 + 插件发现 | 按文件类型创建比较器，workspace `comparators/` 目录自动发现插件 |
| subprocess 隔离执行 | 每个 test case 独立子进程，保证测试间互不影响 |
| xfail 机制 | 支持预期失败的测试（CI 中不阻塞流水线），意外通过时告警 |
| --last-failed 覆写策略 | 只覆写本次执行的用例状态，避免子集运行时丢失未执行用例的状态 |
| --resume 纯信任模型 | 不验证 artifact，由用户保证 workspace 未被修改，简化实现 |
| retry_count 重试机制 | 应对偶发性网络抖动或竞态条件，首次失败后自动重试 |
| DAG 依赖调度 | 基于 Kahn 拓扑 + 就绪队列，依赖满足后立即提交；依赖失败级联 skip 下游；无依赖时走 fast path 零开销 |
| --update-baseline | 比较失败时自动将实际输出覆盖 baseline，适合批量更新基准 |
| next_action_hint 结构化建议 | 失败结果附带下一步操作建议（update_baseline / update_expected / increase_timeout / investigate），便于 AI 消费 |
| TUI 基于 Textual | 利用成熟的终端 UI 框架，提供交互式用例管理 |
| JUnit XML 输出 | 兼容 GitLab CI / Jenkins / CircleCI 等主流 CI 系统的测试报告格式 |
| Logging 统一化 | 通过 `logging` 模块集中管理，CLI 入口激活控制台输出，库用户按需启用 |

---

## 10. 核心架构宪法

> **地位与效力**：本节自 Symtest 1.4 Phase 0 评审定稿，是本项目的核心架构契约，
> 对所有后续 feature 具有最高约束力——任何功能需求先对照本宪法确定归属，再写代码。
> 修订宪法必须在变更说明中显式指出所放宽/违反的条款及理由。

### 10.1 数据流主线

```
TestCase（specification，永不执行）
    ├── ExecutionSpec  ──▶ Executor.execute()                        ──▶ ExecutionResult
    ├── ExpectationSpec ─┐
    └── SchedulingSpec ──▶ Orchestration（何时跑、跑哪个、组合与重试）
                             │
           Validator.validate(ExpectationSpec, ExecutionResult)
                             ▼
                    ValidationResult ──▶ TestResult ──▶ Reporter
                                          console / JSON / JUnit / AI diagnosis
```

一次 attempt = `Executor.execute → Validator.validate`；verdict 由编排层聚合为 TestResult。

### 10.2 六条原则

#### 原则 1 — TestCase 是声明，不执行任何事情

`TestCase = specification`。禁止出现 `test_case.run()` / `test_case.validate()` /
`test_case.update_baseline()` 这类方法；TestCase 只描述**执行什么**
（ExecutionSpec）、**如何判定**（ExpectationSpec）、**调度约束**
（SchedulingSpec）与元数据。

概念模型分层 ≠ 配置 DSL 必须机械映射类层次：`name/tags/description` 允许保留
顶层以避免啰嗦；真正必须拆出去的是执行语义、验证语义、调度语义。

#### 原则 2 — Execution 不知道"通过/失败"

```
Executor: ExecutionSpec ──execute──▶ ExecutionResult
```

ExecutionResult 只承载执行事实：`return_code / stdout / stderr / duration /
timed_out / error / artifacts`。

Executor 禁止感知：`expected_return_code / output_contains / baseline / rtol /
file comparison / xfail / next_action_hint`。超时只报告 `timed_out=True`，
"timeout 是否算失败"由 Validator 判定。

#### 原则 3 — Validation 不执行被测程序，且永远只读

```
Validator: ExpectationSpec + ExecutionResult ──validate──▶ ValidationResult
```

Validator 禁止 `subprocess.Popen` 被测进程、kill 进程、retry。

**例外条款（受控豁免）**：comparator 是验证的内部工具，`script` comparator
执行的是"比较工具"而非"被测程序"，属本条明确豁免范围。

**baseline 语义**：Validator 永远只读文件。`--update-baseline` 由 runner 在拿到
ValidationResult 后执行独立的 accept 步骤（复制 actual → baseline）再判定。

#### 原则 4 — Orchestration 组合，而不实现底层语义

Runner / Scheduler / DAG / ParallelRunner 负责：什么时候执行、执行哪个 case、
顺序、依赖、并发、**retry policy**（一次 attempt =
`Executor.execute → Validator.validate`，runner 拿 verdict 决定是否重跑，
flaky 判定也在编排层）；但不自己实现 subprocess 管理、float 比较、stdout 判断。

#### 原则 5 — Reporting 只能消费 Result

```
TestResult ──▶ Reporter ──┬── console
                          ├── JSON
                          ├── JUnit
                          └── AI diagnosis
```

Reporter 的合法输入只能是 Result 类型；`next_action_hint` 属于 result consumer
（diagnosis），不得存在于 execution 层。

#### 原则 6 — 核心模型不依赖表现层

`core` 绝对不能 import：`cli` / `tui` / `reporter` / AI-specific adapter。

解析器全系统唯一：TUI 与 runner 使用同一 parser，不允许存在 "TUI mode 后门"
（如 workspace=None 时放宽校验）；宽松形态由 TUI 侧自行处理。

### 10.3 模块依赖方向

允许：

- `orchestration` import `execution` / `validation`（它是唯一组合者）；
- `reporting` 仅 import result 类型
  （ExecutionResult / ValidationResult / TestResult）。

禁止：

- `execution` 与 `validation` 互不 import；
- `executor` 不得 import `assertions` / validation 侧模块；
- `validator` 不得启动被测进程（见原则 3）；
- `core` 不得 import `cli` / `tui` / `reporter`。

### 10.4 违宪归属速查

任何新需求先问归属：

| 提问 | 归属 |
|---|---|
| 增加 GPU resource requirement？ | SchedulingSpec |
| 增加 stderr regex assertion？ | ExpectationSpec / Validator |
| 支持 Docker command execution？ | Executor |
| AI 告诉我下一步该干嘛？ | Result consumer / diagnosis |

判据：若仍经常出现"这个功能到底放 execution、runner 还是 testcase？"的争论，
说明宪法没有被正确适用，应回到 10.2 逐条对照。

### 10.5 宪法可执行化

宪法不是纯文档约定，配套 architecture guard 测试并由 CI 强制：

- 断言 import 图：如 `execution/executor.py` 的 import 不得出现
  `assertions` / `validation`；`core/**` 不得 import `cli` / `tui` /
  `reporter`；
- guard 测试纳入常规回归套件（`python tests\run_all.py`），违规即失败；
- 冲突裁决次序：guard 测试 > 本节文字 > 个人偏好。
