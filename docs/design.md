# SymTest 设计文档

> **维护原则（单一事实来源）**：本文档不镜像代码结构——不再维护目录树、类签名、
> 函数清单、dataclass 字段定义等会随代码漂移的内容。目录结构与 API 以
> `src/symtest/` 源码及其 docstring 为准，用法示例见 `examples/`。
> 本文档只承载代码里读不出来的设计信息：架构分层、职责边界、关键流程语义、
> 扩展契约、设计决策与核心架构不变量。

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  CLI 入口层    symtest run / find / validate / schema /      │
│                compare-files                                  │
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

框架分为四层：**CLI 入口层**、**Runner / Comparator 业务层**、**Config 管线层**、**Core 基础层**。

层与层不是自由组合：跨层数据流与依赖方向受 §10「架构不变量」约束，
新增 feature 请先对照不变量确定归属。

## 2. 模块地图

以包为单位的职责划分（文件级明细与公开 API 以源码为准）：

| 包 | 职责 |
|---|---|
| `cli.py` / `commands/` | 子命令入口、参数装配与日志激活 |
| `core/` | TestCase 数据模型、断言引擎、单测试执行、Runner 基类（顺序 / 并行 / DAG）、`.symtest` 状态存储、Setup 插件体系 |
| `config/` | 配置 IO、公共准备流程（`prepared.py`）、双形态 JSON Schema 契约与校验（draft 2020-12，`config_schema.py`）、import 展开、extends 继承、变量与占位符替换 |
| `runners/` | Config/JSON/YAML × 顺序/并行 的薄封装运行器 |
| `file_comparator/` | 比较器家族 + 工厂 + workspace 插件发现（详见 §6） |
| `utils/` | 路径解析、报告生成（文本 / 结构化 HTML）、JUnit XML 输出、项目级默认配置（`.symtest/symtest.json`） |

### 2.1 入口点

| 命令 | 映射 |
|---|---|
| `symtest run` | `symtest.cli:run_tests` |
| `symtest find` | `symtest.commands.find:run_find` |
| `symtest validate` | `symtest.cli:run_validate` |
| `symtest schema` | `symtest.cli:run_schema` |
| `symtest compare` | `symtest.cli:run_compare` |
| `compare-files` | `symtest.commands.compare:main`（独立入口，与 `symtest compare` 共享参数装配与执行逻辑，为旧版用户与 Windows console-script 用法保留） |

## 3. 配置管线

配置契约的唯一定义是 `config/config_schema.py`（JSON Schema draft 2020-12，双形态）：

- **raw 形态**（`CONFIG_SCHEMA`）：用户/AI 编写的原始配置文件；`abstract` 模板与 `extends` 继承用例允许缺少必填执行字段，完整性在展开后检查；`symtest schema` 导出该形态
- **展开形态**（`EXPANDED_CONFIG_SCHEMA`）：import / extends / variables 全部解析后的有效配置；每个可执行用例必须完整

`validate` / `run` / `find` 三个入口共用公共流程 `config/prepared.py:prepare_config()`，结构检查失败即停止处理对应输入（后续代码不会见到畸形 dict）：

```
raw JSON/JSONC/YAML 文件（.jsonc 由 config/jsonc.py 剥离注释与尾逗号）
    │
    ▼
raw 形态 schema 校验        # 每个加载的文件（含 import 子文件）：
                           # 字段名/类型/取值范围/执行形态互斥/未知字段
    │
    ▼
expand_imports()           # 递归展开 import 引用（合并 setup、注入 tags）
    │
    ▼
重名用例检查                 # extends 引用必须无歧义
    │
    ▼
resolve_inheritance()      # 解析 extends 继承链（deep-merge、去重 abstract）
    │
    ▼
apply_variables()          # 注入 --var 全局变量 + case-level variables，
                           # 递归替换 {placeholder} 占位符
    │
    ▼
展开形态 schema 校验         # 展开后每个可执行用例必须完整
    │
    ▼
语义检查                    # error 级：depends_on 图（存在性/自引用/环）、
                           # outputs 路径边界；warning 级：命令可执行性、
                           # baseline 存在性、outputs 冲突
    │
    ▼
parse_test_cases()         # 转换为 List[TestCase]（命令路径解析）
```

以后新增普通配置字段只需：在 schema 中定义其合法性、在解析器中实现其转换，`validate` 即自动获得相应检查——不再维护独立的字段规则清单。

raw 形态的模板和继承用例允许局部 `execution` 字典，复用完整执行定义的字段约束，
仅延迟检查 `command/args` 必填项；`steps` 按整体替换语义仍要求所提供的 step 完整。
`load_config(..., workspace=...)` 将工作区传入公共流程，`find` 显式转交 CLI 工作区。
导入文件的读取异常在文件边界统一为带文件和引用来源的诊断，包含 YAML 解析异常。

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

### 3.3 配置校验与公共准备流程 (`prepared.py` / `config_io.py`)

`validate_config()` 内部委托 `prepare_config()`；`run` 的配置加载阶段与
`find`（经 `load_config()`）走同一流程。同一份非法配置在 `validate` 与
`run` 中产生一致的错误，且 `run` 在执行任何命令之前退出。诊断信息带
文件路径与字段路径（jsonschema `json_path`），import 子文件中的错误能
定位到具体文件和字段。

- Error 级（影响 valid）：JSON/YAML 语法、raw/展开双形态 schema 检查
  （必填字段、类型、取值范围、执行形态互斥、未知字段）、import 目标存在性、
  循环 import、用例重名、extends 目标存在性、循环继承、展开后用例完整性、
  `outputs` 路径边界、depends_on 目标存在性/自引用/环
- Warning 级（不影响 valid）：`command` 可执行性（PATH 查找）、
  `compare_files` baseline 文件存在性、多用例声明相同 outputs 且无
  depends_on

## 4. 执行语义

> 本章只记载跨模块的行为语义约定；类属性、方法签名与默认值以源码为准。

### 4.1 Runner 模板与状态映射

- 模板流程固定：`load_test_cases()` → 过滤（名称精确 / tags 交集 / `--last-failed`）→ `setup_all()` → 逐 case 执行 → xfail 状态映射 → 历史与 last-run 更新 → `teardown_all()`（逆序，保证出错也继续清理）
- JSON/YAML Runner 仅注入不同的 config_loader，通用逻辑统一在顺序 / 并行通用运行器中
- xfail：`expected_failure=True` 时 `passed → xpassed`（意外通过，计入失败）；任意非 passed → `xfailed`（预期失败，不计入失败）
- JUnit XML 状态映射：`xfailed → <skipped>`、`xpassed → <failure>`、`timeout → <error>`、`failed` 按消息类型分 `<failure>` / `<error>`
- 历史：耗时累计平均更新，写入前先按 `regression_threshold` 与旧均值做回归检测；内存峰值独立记录（`last_peak_memory_bytes` / `max_peak_memory_bytes` / `peak_memory_count` / `peak_memory_source`，字节），有效测量即可记录（含 failed / timeout），调度估算用历史最大值；`--update-history` 清除整条记录（耗时 + 内存）
- `--last-failed`：每次运行只覆写本次参与执行的用例状态，子集运行不丢失其余用例状态

### 4.2 测试双模式

单命令模式（`command + args + expected`）与 steps 序列模式二选一；每个 step 是
"执行 + 判定"的原子对（command / args / timeout / retry_count / expected）。
字段全集见 `core/test_case.py` 与 JSON Schema，本文不复述。

### 4.3 并行与资源调度

- LPT 策略：长任务先行；启用 history 时优先用 `.symtest` 历史 `avg_duration` 排序，其次才看声明的 `estimated_time`（兼容"只有内存记录、没有耗时字段"的历史条目，按 0 处理）
- `AtomicSemaphore` 资源池：`safe_capacity = max(1, cpu_count − 2)`；每个 case 按 `cpu_cores` acquire/release
- 按权重比例分配相对 CPU 核数，并自动注入 `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `NPROC`
- 环境变量优先级：`os.environ` < 调度器注入 < case 级 env（经 subprocess 注入，不改进程全局环境）
- 线程模式共享内存 + 结果/打印锁；进程模式经 process worker 隔离；可回退顺序执行

**Windows 内存感知调度——机会式准入**（线程模式 + Windows + 启用 `--history-dir` 或声明 `min_memory_mb` 时启用；其余情况走原 CPU-only 路径，行为不变）：

- 内存需求估算优先级：显式 `min_memory_mb` > history 历史最大峰值 × 安全系数（默认 1.2，`memory_margin` 可配） > 可配置默认需求（`memory_default_demand_mb`，默认 4096 MB）；不再整池独占
- `JointResourceManager` 联合资源池：CPU 令牌 + 系统快照（`GlobalMemoryStatusEx` 可用物理内存、`GetPerformanceInfo` 提交余量）在同一把锁下原子评估——消除"持 CPU 等内存、持内存等 CPU"的部分占有死锁
- **机会式准入判据**（全部满足才启动）：CPU 令牌充足；峰值可能拥挤时距上次授予 ≥ 最小启动间隔（`memory_min_start_interval_s`，默认 1s，错开启动防扎堆）；提交余量 ≥ 新任务估算需求 + 提交保留量（`memory_commit_reserve_mb`，默认 2048 MB）；可用物理内存 ≥ 物理低水位（`memory_physical_watermark_mb`，默认 2048 MB，独立检查不与需求量挂钩）。提交与物理两种口径分开建模、互不混用
- **不重复计账**：不再为运行中任务保留完整未来峰值——已占用内存自然体现在系统余量中；未来再次增长导致超额的风险明确接受（允许偶发 OOM，不保证零失败）。实测证明旧的"完整预留 + 快照兜底"策略在 31.8 GiB 机器上把 2/4 worker 并发压到 1
- 内存压力大时只暂停启动新任务，已运行任务继续执行；等待者在锁内复用已授予的 ticket，防止轮询超时与 release 交错导致重复扣额；被启动间隔阻塞的等待者按剩余间隔唤醒
- 拒绝原因（含关键数值：需求/保留量/余量/水位）来自实际判断路径，记入 `waiter.deny_reason` 与调度日志，供验收归因
- 物理低水位校验：已知总物理内存时，非零水位必须严格小于总量，否则初始化抛出 `ValueError`，避免永久排队。请降低 `memory_physical_watermark_mb`，或设为 0 禁用该检查。
- 内存不足排队等待而非降级（CPU 的 10s 降级逻辑不适用内存）；需求未知（`None`）或需求加提交保留量超过系统提交上限（结构性不可满足，如 pagefile 过小）时跳过提交检查放行（物理水位与启动间隔仍生效），交由用例自身失败暴露问题，不永久排队
- Job 内全部后代与启动器共享命令超时期限；管道 EOF 后继续等待组内进程结束，期限耗尽则终止整组并报告超时
- 上述参数为 `symtest.json` run 段配置键（CLI 第一版不提供旗标）；进程模式不接入资源调度（保持既有行为）

仅在存在活动任务且“活动任务估算峰值之和 + 新任务需求 + 提交保留量”大于当前提交余量时，才要求距上次授予达到启动间隔；余量充足或活动任务全部结束时立即放行。该估算可能重复计入已占用内存，只用于保守地触发间隔，不作为硬预留。快照或需求未知且存在活动任务时保守保留间隔。

### 4.4 DAG 依赖调度语义

- `depends_on` 非空自动切换拓扑模式；无依赖时走零开销 fast path
- Kahn 入度表 + 就绪队列，依赖满足后立即提交后继
- 依赖"满足" = `passed` 或 `xfailed`；`failed` / `xpassed` 触发 BFS 级联 skip 全部下游
- `skipped` 不计入 `failed` 计数，报告中单独列出
- 顺序 runner 同样按拓扑序执行，依赖失效时跳过下游
- 名称过滤默认不展开依赖闭包：依赖未选中时依赖边失效并打 WARNING；`--with-deps` 在过滤前对 `test_case_filter` 展开 `depends_on` 传递闭包（标签过滤不展开；`--last-failed` 不隐式展开）

### 4.5 单测试执行

PathResolver 解析（系统命令直通、shell builtin 平台包装、复合命令拆分解析）
→ 声明产物清理（`execution.outputs` 声明的文件在 subprocess 启动前删除；只允许声明文件，声明目录或 workspace 根一律拒绝；路径 resolve 后必须在 workspace 内，删除失败大声失败记为执行错误；每次 attempt 都执行，`--resume` 跳过的 step 天然不清理）
→ subprocess 隔离执行（捕获 stdout / stderr / returncode / duration；Windows 测量启用时经 Job Object 以挂起创建→绑定→恢复执行整组进程，捕获进程组提交内存峰值 `PeakJobMemoryUsed`，超时经 `TerminateJobObject` 终止整组，测量失败回退普通 subprocess 路径、峰值保持未知）
→ 断言校验（return_code / contains / matches / compare_files）
→ 失败按 `retry_count` 重试
→ 超时 kill 整个进程组
→ 返回附带 `next_action_hint` 的结构化结果。

进程组内存峰值是**执行事实**（原则 2），随结果可选携带 `peak_memory_bytes` /
`peak_memory_source`（Windows 提交内存口径，非物理内存峰值；无可测量时字段缺席，
不用 0 表示未知）。聚合规则：retry 取各 attempt 最大值；sequence 取实际执行步骤的
最大值（步骤串行，不求和；`--resume` 跳过的步骤不补造数据）。

### 4.6 断言与文件比较集成

- `compare_files` 是一等断言，经 ComparatorFactory 按类型分发（详见 §6）
- 所有断言可选；未声明的字段不做校验
- `--error-analysis` 为 CSV/H5 数值比较提供流式误差统计：`total_numeric_cells` / `mismatched_cells` / `max_abs_error` / `max_rel_error` / `mean_abs_error` / `rms_abs_error`；幅值统计（max/mean/rms）覆盖全体参与比较的数值单元格（含通过格），mean/rms 以 `total_numeric_cells` 为分母。`--error-analysis-all` 额外对通过用例输出统计，除此之外两者行为一致

## 5. 运行时状态持久化（`.symtest/`）

| 状态 | 内容 | 更新时机 / 语义 |
|---|---|---|
| 项目默认配置 `symtest.json` | `run` 组运行选项 + `report` 组报告路径 | 运行启动时读取（CLI > 选中的参数文件 > 内置默认）；默认入口 `.symtest/symtest.json`（宽容校验，问题只警告），`--defaults FILE` 显式替代入口（严格校验，问题报错退出，不与默认文件叠加）；只读，运行中不更新 |
| 历史记录 | per-case `avg_duration` / `last_duration` / `run_count` | 运行后累计平均更新；先回归检测后写入 |
| `last_run.json` | case → 上次状态 | 覆写参与执行的用例；未执行的保留旧状态 |
| `sequence_state/<case>.json` | steps + case expected 的 SHA-256 配置哈希、已通过的 step 集 | 每步 pass 后保存；全部通过后清理 |
| `sequence_state/cache/*.log` | 步骤输出缓存 | 与上同步；供 resume 拼接复现 |

**resume 语义**：`--resume` 比对配置哈希——匹配则跳过已过步骤并拼接缓存输出，
失配即全量重跑。纯信任模型：不验证 workspace 产物，由用户保证未被修改。

## 6. 文件比较子系统

### 6.1 三泳道比较器架构

所有比较器共享根契约 `ComparatorBase.compare(ctx) -> ComparisonResult`：
框架构建 `CompareContext`（workspace / actual / baseline / params / error_analysis）；
`actual`/`baseline` 以及插件 `path_params` 声明的构造参数在**比较器构造之前**
按 workspace 统一解析，插件不得自行对 CWD resolve。配置单一事实源：
比较器配置只存在于构造器捕获的实例状态，`ctx` 仅承载调用级上下文。
三条泳道职责互斥：

| 泳道 | 基类 | 契约 | verdict 归属 | 内置实例 |
|---|---|---|---|---|
| 文件泳道 | `FileComparator` | `read_content` + `compare_content`（两文件模型，行列窗口、line N 偏移、chunk_size、similarity 均属本泳道） | 插件 | text / json / csv / xml / h5 / binary |
| 数据泳道 | `ExtractorComparator` | `extract(ctx) -> {channel: ChannelData}`；框架逐通道跑 `compare_numeric`，per-channel 容差（`channels` / `default_channel`），聚合 `ChannelResult` | **框架**（容差语义对 AI 消费端可预期） | script_extract、extractor 插件 |
| 自主泳道 | 直接继承根 | `compare(ctx)` 全权判定 | 插件 | script、hourglass 式分析插件 |

- 文本系共享 difflib 行级基底，json / csv / xml 为其结构化特化；h5 面向科学数据集；binary 流式分块 + LCS 相似度
- 统一返回 `ComparisonResult`（identical / differences / error / error_stats / command_output / channels），支持 text / json / html 渲染
- 数据泳道插件可通过 `ChannelData.extra_stats` 附带自定义误差指标，存放在独立命名空间（`ChannelResult.extra_stats`），不可覆盖框架规范指标；但 verdict 仍由框架容差持有——需要自定 verdict 的走自主泳道

#### 6.1.1 窗口与数值比较语义（文件泳道）

- 行列窗口统一 **0-based 闭区间**（`start_line`/`end_line`/`start_column`/`end_column`，end 含端点），断言层负责把用户 1-based 输入转换；CSV 的列窗口按 **CSV 字段**裁剪（不是字符列），H5 的大数据集分块分支同样应用窗口，与内存分支语义一致。差异 position（`line N` / `row N, column M` / `row N`）由泳道基类统一偏移回原始文件坐标
- H5 标量（0 维）数据集参与数值比较；数据集读取失败记为 `diff_type="error"` 差异并判失败，绝不静默通过
- `allow_nonfinite` 的布尔类型约束在原始/展开配置 schema 中复用同一定义，比较器构造及共享数值核心也检查 Python API 输入，禁止依赖真值转换。CSV 文本快速路径对所有含指数、NaN/Inf 提示或长度不少于 309 的单元格实际解析，以覆盖长尾数和带下划线的溢出写法；是否启用误差统计不影响判定。数据泳道（含 `script_extract`）的覆盖顺序为逐通道 → `default_channel` → 比较器参数 → `false`。
- 共享数值核心 `compare_numeric` 逐元素保留整数类型，覆盖完整 int64 / uint64 范围及整数、浮点混合序列；整数差值使用 Python 整数避免溢出，整数与浮点数配对时按该浮点数实际表示的值计算差值。判定前不把整数转成 float64，也不因其他单元格的类型或幅值回退浮点通路。纯浮点数组仍走 NumPy 向量化比较。容差与报告中的误差幅值统计使用浮点数；调用者已转成浮点数组而丢失的精度无法恢复。CSV 数值单元格整数优先解析，H5 / 数据泳道可直接传整数数组
- **非有限值默认拒绝**：任意一侧为 NaN 或 ±Inf 的单元格判为不匹配（差异 `diff_type="non_finite_value"`）——求解器输出出现 NaN/Inf 通常意味着求解失败，"结果与基准一致"不能推出"结果有效"。需要接受非有限值时显式设置 `allow_nonfinite=true`（CSV/H5 比较器参数、数据泳道比较器参数及 per-channel 覆盖），仅恢复 `NaN==NaN`、同号 `±Inf` 相等的旧语义；反号 Inf 仍然是不匹配。该规则在共享数值核心实施，CSV（含流式/内存文本快速路径与 `1e999` 溢出文本）、H5（含大数据集分块分支）、数据泳道三路一致；`data_filter` 不能提前排除非有限单元格，被过滤条件排除的 NaN 仍会被强制纳入比较并判失败
- CSV 误差统计累计用于 verdict 的逐行数值比较结果，不汇总原始数值后重新比较；比较走流式逐行路径（覆写 `compare_files`），行窗口按记录索引施加，行数不匹配在两侧流读取耗尽后按窗口内记录数判定和报告，窗口外的增删行不影响结果；起始记录索引大于等于任一文件的总记录数时返回越界错误（包括空文件）。内存与文件大小无关（O(单行)）；直接调用 `read_content`/`compare_content` 的 Python API 保留全量内存路径，两者共享逐行判定逻辑
- `--error-analysis` 误差统计覆盖参与比较的全部数值单元格，含 H5 分块大数据集（启用统计时不因首个差异提前返回）

### 6.2 通道协议（数据泳道）

- 通道判定：`identical = all(channels.passed)`；差异 position 带通道前缀（`channel S33`）；`error_stats` 按通道名嵌套
- 内置 `script_extract` 类型：子进程执行用户脚本（零改动接入），脚本 stdout 输出约定 JSON：

```json
{"channels": {"S11": {"expected": [...], "actual": [...], "extra_stats": {...}}}}
```

  非零退出、超时、畸形 JSON 一律判为比较 error（绝不静默通过）；`actual`/`baseline` 按惯例以 baseline 在前的顺序追加为尾部 argv 槽位（可缺省）
- 结果粒度：一条 compareSpec = 一条断言；`ComparisonResult.channels` 携带通道级子结果，报告逐通道展示 pass/fail + stats；JSON 输出中通道 differences 按 per-channel 配额截断

### 6.3 工厂与插件发现

- `file_type` 取值：`text` / `json` / `csv` / `xml` / `h5` / `binary` / `script` / `script_extract`；工厂按类型分发，支持动态注册与全局 reset（测试用）
- 插件发现四处来源：内置 `*_comparator.py` 自动发现、`workspace/comparators/` 自动扫描、`--plugin-dir` CLI 参数、`CLITEST_PLUGIN_DIRS` 环境变量（用户声明的输入；框架只读，进程模式 worker 经进程池 initializer 显式接收插件目录，框架从不修改 `os.environ`）
- 命名约定：`*_comparator.py` + `*Comparator` 类名；可用类属性 `comparator_type` 显式指定类型名（如 `script_extract`）；抽象基类自动跳过注册
- 配置传递与严格校验：`actual`/`baseline`/`type`/`options` 之外的键转发给比较器构造函数（kwargs）；构造器参数是**严格**的——未声明的键（拼写错误）在构造时大声失败并给出支持参数清单。`options` 是框架持有的插件配置命名空间（并入构造参数，显式顶层键优先），核心 schema 不为单个插件增加专属字段；`channels`/`default_channel` 属数据泳道框架结构

### 6.4 script 比较协议（自主泳道对外契约）

- 子进程方式执行 `<interpreter> <script> <baseline> <actual>`（文件槽位可缺省）
- 默认 exit code 0 → 通过；可选 `pass_pattern` / `fail_pattern` 正则匹配 stdout 细化判定
- 超时可配

### 6.5 插件公共 API

`symtest.file_comparator` 包导出：`ComparatorBase` / `CompareContext` /
`FileComparator` / `ExtractorComparator` / `ChannelData` / `ChannelResult` /
`compare_numeric` / `NumericComparisonStats` / `parse_data_filter`。
数据泳道插件只需依赖 `ExtractorComparator` + `ChannelData`，数值判定全部复用框架核心。

## 7. 用例搜索命令（find）

替代已移除的 TUI 搜索能力：`symtest find` 走与 runner 完全相同的加载路径
（`load_config` 自动展开 import + 继承解析，`parse_test_cases` 全系统唯一
解析器），在展开后的用例集上按三种模式匹配（子串 / 模糊 / 正则，字段覆盖
name / command / args / tags / description），支持叠加标签过滤与 JSON 输出
（供 AI / 脚本消费）。退出码沿用 grep 语义：有匹配 0、无匹配 1、错误 2。

原 TUI 的另一职责（给不习惯写配置的同事提供图形化定义/修改用例）由官方
skill（仓库根 `skill/`）承担：AI 编程助手按 skill 知识直接生成/修改
JSON/YAML 配置，学习成本更低且无交互界面维护负担。

## 8. 扩展点

| 扩展点 | 基类 | 用途 |
|---|---|---|
| 新配置格式 | `BaseRunner` | 支持新的测试定义格式（如 XML、TOML） |
| 自定义 Setup | `BaseSetup` | 数据库初始化、服务启停等 |
| 自定义断言 | 扩展 `Assertions` | 特定业务校验逻辑 |
| 新比较器 | `FileComparator` / `ExtractorComparator` / `ComparatorBase` | 按泳道选择基类（文件格式 / 数据提取+通道 / 全权分析），放入 `comparators/` 目录自动发现 |
| 新 Runner | `ParallelRunner` / `BaseRunner` | 自定义并行调度策略 |

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
| 移除 TUI，由官方 skill + `symtest find` 替代 | TUI 的两大职责均有更轻替代：定义/修改用例由 AI 编程助手按官方 skill 完成，跨文件搜索由复用同一解析管线的 `find` 命令覆盖；移除后砍掉 textual 重依赖与交互界面维护负担 |
| `execution.outputs` 产物清理挂在 execute_command 入口 | 声明产物、运行前删除，消除"陈旧产物假通过"。清理是执行环境准备（与 env 注入同类），归属 execution 层；`execute_command` 是所有执行路径的唯一汇聚点，挂在该处使 retry 重清与 resume 不删（被跳过 step 不进入该函数）两个语义自动成立，编排层零改动。失败大声报 `execution_error`，防止静默保留假通过通道。**只允许声明文件**：声明目录（如输出目录树）或 workspace 根（`"."`）会递归抹掉大量无关文件甚至整个工作区，故 validate 与运行时双层拒绝 |
| JUnit XML 输出 | 兼容 GitLab CI / Jenkins / CircleCI 等主流 CI 系统的测试报告格式 |
| 项目级默认配置（`.symtest/symtest.json`） | 常用运行参数（并行、误差分析、依赖展开、报告路径）项目内固化，`symtest run` 免重复输入。三级优先级（CLI > 项目配置 > 内置默认）靠 tri-state 布尔项实现（argparse 默认 `None`，`--no-xxx` 显式关闭）；未知键/坏 JSON 宽容处理只警告——配置是纯加分项，不阻断运行。替代各仓库自建入口脚本保存默认参数的用法 |
| `--defaults FILE` 显式默认参数文件 | 同一 workspace 需要多套默认参数（如回归 vs 验证）时免建项目 runner。显式文件**完全替代** `.symtest/symtest.json`（不叠加合并，防止验证配置漏写键时静默继承回归设置），并切换为**严格校验**（缺失/坏 JSON/未知键/类型错报错退出）——显式指定即用户意图，静默回退到另一套设置比报错更危险。默认入口保持宽容语义不变，与 `--no-config` 互斥 |
| Logging 统一化 | 通过 `logging` 模块集中管理，CLI 入口激活控制台输出，库用户按需启用 |
| Windows Job Object 测量进程组峰值 | 挂起创建→绑定 Job→恢复执行消除后代逃逸竞态；峰值由操作系统持续维护，无需采样即可捕捉短暂尖峰；`PeakJobMemoryUsed` 为提交内存口径，如实命名为 `peak_memory_source=windows_job_commit`，不冒充物理内存峰值 |
| CPU+内存联合原子准入 | 两个独立信号量会产生"持 CPU 等内存、持内存等 CPU"的部分占有死锁；联合池在同一把锁下原子评估池令牌 + 系统快照（物理可用与提交余量分别检查，二者防护目标不同） |
| 机会式内存准入（不做完整峰值预留） | 旧的"系统余量须覆盖运行中任务的完整预留 + 新请求"会重复计入已分配内存（实测把 2/4 worker 并发压到 1），且把提交峰值误用于物理内存检查。机会式准入只检查新任务自身需求 + 保留量；已占用内存由系统余量自然体现；峰值可能拥挤时授予间保持最小启动间隔错开扎堆；允许偶发 OOM，不保证零失败 |
| 内存排队而非降级 | CPU 令牌超时降级到 1 核是吞吐启发式；内存降级启动正是并行 OOM 失败的来源，故内存不足持续等待（周期唤醒重评外部内存变化），结构性不可满足（需求加提交保留量超提交上限）才跳过检查放行 |
| 内存历史用最大值而非平均 | 峰值口径天然只增，偶发高峰被平均稀释后会在下次调度再次 OOM；估算加安全系数（默认 1.2，可配） |
| 内存测量失败回退普通路径 | 测量是加分项不是验收条件：Job 后端失败/非 Windows/进程模式时峰值保持未知（None，不用 0 伪装），执行与判定语义完全不变 |
| 控制台 log/report 通道分离 | 控制台（stderr logging）只承载进度与摘要日志；报告仅在显式 `--output-format text/json/html` 时走 stdout（可重定向落盘），细节经 `--text-report`/`--html-report`/`--junit-xml` 写文件。修复原 `print_report` 把整份文本报告经 `logger.info` 重放到终端的通道混流——`--error-analysis-all` 下逐用例 error_stats 会淹没 pass/failed 摘要 |

---

## 10. 架构不变量

> **定位**：本节自 Symtest 1.4 Phase 0 评审定稿。这些不变量定义了模块归属与依赖方向；
> 新增 feature 应遵守它们，除非变更说明中显式记录了某条不变量为何需要演进。

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
                                          stdout(text/json/html) / JUnit / AI diagnosis
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
TestResult ──▶ Reporter ──┬── stdout（按需 text/json/html）
                          ├── JUnit
                          └── AI diagnosis
```

Reporter 的合法输入只能是 Result 类型；`next_action_hint` 属于 result consumer
（diagnosis），不得存在于 execution 层。

#### 原则 6 — 核心模型不依赖表现层

`core` 绝对不能 import：`cli` / `reporter` / AI-specific adapter。

解析器全系统唯一：不允许存在宽松解析后门（如 workspace=None 时放宽校验）；
宽松形态由调用方先 normalize 再调用。

### 10.3 模块依赖方向

允许：

- `orchestration` import `execution` / `validation`（它是唯一组合者）；
- `reporting` 仅 import result 类型
  （ExecutionResult / ValidationResult / TestResult）。

禁止：

- `execution` 与 `validation` 互不 import；
- `executor` 不得 import `assertions` / validation 侧模块；
- `validator` 不得启动被测进程（见原则 3）；
- `core` 不得 import `cli` / `reporter`。

### 10.4 归属速查

任何新需求先问归属：

| 提问 | 归属 |
|---|---|
| 增加 GPU resource requirement？ | SchedulingSpec |
| 增加 stderr regex assertion？ | ExpectationSpec / Validator |
| 支持 Docker command execution？ | Executor |
| AI 告诉我下一步该干嘛？ | Result consumer / diagnosis |

判据：若仍经常出现"这个功能到底放 execution、runner 还是 testcase？"的争论，
说明不变量没有被正确适用，应回到 10.2 逐条对照。

### 10.5 不变量可执行化

这些不变量不只是文档约定，配套 architecture guard 测试并由 CI 强制：

- 断言 import 图：如 `execution/executor.py` 的 import 不得出现
  `assertions` / `validation`；`core/**` 不得 import `cli` /
  `reporter`；
- guard 测试纳入常规回归套件（`python tests\run_all.py`），违规即失败；
- 冲突裁决次序：guard 测试 > 本节文字 > 个人偏好。
