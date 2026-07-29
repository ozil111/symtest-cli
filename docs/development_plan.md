# CLI Test Framework 开发计划

> 本文档基于真实使用案例（NovaFea UEL 算法复刻项目的 TDD 工作流）的分析，
> 规划框架下一阶段的六项增强能力及其迭代实施顺序。

## 目录

- [1. 背景](#1-背景)
- [2. 需求清单](#2-需求清单)
- [3. 已确认的设计决策](#3-已确认的设计决策)
- [4. 迭代计划](#4-迭代计划)
  - [迭代 1：diff 展示 bug 修复（P0）](#迭代-1diff-展示-bug-修复p0)
  - [迭代 2：官方示例 runner](#迭代-2官方示例-runner)
  - [迭代 3：xfail 四态报告 + 误差分析](#迭代-3xfail-四态报告--误差分析)
  - [迭代 4：自定义比较器插件体系](#迭代-4自定义比较器插件体系)
  - [迭代 5：配置继承](#迭代-5配置继承)
- [5. 验证方式](#5-验证方式)
- [6. 非目标](#6-非目标)

---

## 1. 背景

真实案例场景：使用本框架复刻 Abaqus 单元算法（UEL）。每个测试用例是一条
「native 求解 → 提取基线 CSV → 生成 UEL 输入 → UEL 求解 → 提取对比 CSV → compare_files 断言」
的流水线，190 个用例全量运行约 3.9 小时。当前处于 TDD 阶段，**失败是常态，
失败详情是主要的调试信息来源**。

该场景暴露出框架的若干不足：

1. CSV 比较失败时摘要区只显示 `Difference at row 4, column 3`，丢失期望值/实际值；
   且存在 `Difference at None`、差异计数虚高的 bug。
2. 「预期失败」与「新回归」在报告中无法区分，TDD 的红→绿状态机不可见。
3. 数值比较缺少全量误差统计（现有 diff_summary 只统计前 10 条截断差异）。
4. 用户被迫在框架外用独立脚本做专用比较（如 `analyze_*_tangent.py`），
   只能靠 `output_contains: PASS` 这类弱断言接入。
5. 用例配置高度同构（5 步流水线仅路径/参数不同），单配置文件达 5000+ 行。
6. 项目入口脚本未透传框架已有能力（`--last-failed` / `--resume` / `--update-baseline`）。

## 2. 需求清单

| # | 需求 | 优先级 |
|---|------|--------|
| 1 | 修复 diff 展示 bug（丢值 + 占位差异污染计数） | P0 |
| 2 | 增强项目入口脚本范式，收编为官方示例 | P1 |
| 3 | xfail（预期失败）+ 报告四态分类 | P1 |
| 4 | 误差分析开关（数值比较的全量统计） | P1 |
| 5 | 自定义比较器插件体系 | P2 |
| 6 | 配置继承（类 C++ 继承思路消除重复配置） | P2 |

## 3. 已确认的设计决策

| 决策点 | 结论 |
|---|---|
| xpass 语义 | **视为失败**，退出码非零。xfail 是严格语义：预期失败却通过 = 套件失败，强制及时移除过期标记、把用例转正为正式回归用例。退出码判定：`failed + xpassed > 0 → 非零` |
| 误差分析范围 | **仅失败的比较**输出统计，融入现有 `Compare Failures` 区块 |
| 插件体系顺序 | 先做**工作区插件目录 + 脚本型比较器**，entry points 在迭代 4 内随后完成 |
| 继承合并粒度 | **steps 整体替换**；dict 深合并、list 整体替换 |

---

## 4. 迭代计划

### 迭代 1：diff 展示 bug 修复（P0）

**目标**：比较失败的摘要区直接展示期望值/实际值，差异计数准确。

**改动点**：

1. `file_comparator/result.py`
   - `Difference.__str__`：只要 `expected`/`actual` 存在就展示数值，不再按
     `diff_type` 白名单（`content`/`missing`/`extra`）走分支。目标效果：
     ```
     At row 4, column 3: expected '0.0219259', got '0.0213002'
     At row count: expected '100 rows', got '99 rows'
     ```
   - `ComparisonResult` 增加 `truncated: bool` 字段。
2. `file_comparator/csv_comparator.py`
   - 移除 `position=None` 的截断占位假差异，改置 `truncated=True`；
     渲染层（`__str__` / 报告）负责显示 `... more differences not shown`。
   - 检查 `text_comparator.py` / `json_comparator.py` / `h5_comparator.py`
     是否有同样的占位写法，一并修复。
3. 同步更新断言该文案/计数的单测。

**涉及文件**：`result.py`、`csv_comparator.py`（及同模式比较器）、相关单测。

**验收标准**：
- 摘要区显示带数值的差异描述；
- `Found N differences` 的 N 与实际差异条数一致；
- 截断时显示 `... more differences not shown` 且不计入 N；
- `diff_summary.total_differences` 不再被占位差异污染。

---

### 迭代 2：官方示例 runner

**目标**：把「项目入口脚本」的最佳实践固化，其他项目可直接复制使用。

**改动点**：

1. `examples/full_runner_example.py`（新增），包含：
   - 全参数透传：`--test-target` / `--tag` / `--last-failed` / `--resume` /
     `--update-baseline` / `--junit-xml` / `--workers`；
   - 可选的环境引导示例（把 venv `Scripts` 目录前置到 PATH，附注释说明
     Windows 下 `compare-files` 子进程找不到时的 WinError 2 问题）；
   - 报告落盘与退出码处理。
2. `docs/user_manual.md` 增加「项目入口脚本」一节：何时直接用 `cli-test run`，
   何时包一层 `test.py`。

**验收标准**：示例脚本可直接复制到他项目改配置即用；文档说明清晰。

---

### 迭代 3：xfail 四态报告 + 误差分析

**目标**：TDD 的红→绿状态机在报告层面可见；数值比较失败时给出全量统计。

**改动点**：

1. **配置层**
   - 用例级新增字段：`"expected_failure": true`，可选 `"xfail_reason": "..."`
     （报告中展示原因）。
   - `config_schema.py` / `validate` 命令同步支持。
2. **执行层**（`execution.py` / `parallel_runner.py`）
   - 结果状态从二值变四态：
     - `passed` / `failed`：无 xfail 标记的正常结果；
     - `xfailed`：标记 xfail 且确实失败 → 不算失败、不影响退出码，
       但**详情照常输出**（保持「失败才输出详细信息」的调试价值）；
     - `xpassed`：标记 xfail 却通过 → 计入失败，退出码非零，报告高亮。
3. **报告层**（`report_generator.py`）
   - 汇总区示例：
     ```
     Total: 190 | Passed: 118 | Failed: 5 | XFailed: 67 | XPassed: 1 (unexpected!)
     ```
   - xfailed 用例展示 `xfail_reason`；xpassed 用例高亮提示移除标记。
4. **`--last-failed` 语义**（`last_run_store.py`）
   - 只记录真正的 `failed`；`xfailed` 不进失败集，`xpassed` 进失败集。
5. **JUnit XML**（`junit_xml_writer.py`）：xfailed 映射为 skipped。
6. **误差分析**
   - 全局开关 `--error-analysis`（runner 参数 `error_analysis=True`）。
   - 数值型比较器（CSV、H5）逐单元比较时**流式统计**（不依赖截断后的差异列表）：
     `total_numeric_cells`、`mismatched_cells`、`max_abs_error(+位置)`、
     `max_rel_error(+位置)`、`mean_abs_error`、`rms_abs_error`。
     纯 `math` 实现，无新依赖。
   - `ComparisonResult` 增加 `error_stats` 字段，随 `compare_failures`
     结构化数据流入报告，仅失败的比较渲染统计表。

**涉及文件**：`test_case.py`、`config_loader.py`、`config_schema.py`、
`execution.py`、`parallel_runner.py`、`report_generator.py`、`last_run_store.py`、
`junit_xml_writer.py`、`csv_comparator.py`、`h5_comparator.py`、`result.py`、
`cli.py`、schema/文档/单测。

**验收标准**：
- 四态汇总正确，退出码 = `failed + xpassed > 0 → 非零`；
- xfailed 详情照常输出且带 reason；
- `--last-failed` 只重跑真正失败的用例；
- 开启 `--error-analysis` 后失败的数值比较输出全量统计，未开启时行为不变。

---

### 迭代 4：自定义比较器插件体系

**目标**：用户的专用比较逻辑（如 `analyze_*_tangent.py`）进入 `compare_files`
断言体系，享受结构化结果、diff 统计、报告渲染全套设施；并为「优秀专用比较器
转正内置」铺路。

**三层设计**：

1. **工作区级插件（先做）**
   - runner 新增 `plugin_dirs` 参数 / CLI `--plugin-dir`；
   - 默认探测 workspace 下 `comparators/` 目录，其中 `*_comparator.py`
     按与内置相同的约定自动发现注册；
   - 配置里直接使用：`{"type": "hourglass_tangent", ...}`。
2. **脚本型比较器（内置 `script` 类型）**
   - 配置：`{"type": "script", "script": "analyze_xxx.py", "baseline": ..., "actual": ...}`；
   - 框架负责调用脚本（传入两个文件路径），按退出码 + 标准输出判定；
   - 脚本 stdout 自动进入失败详情的 `Command Output`；
   - 现有 `analyze_*.py` 几乎零改动即可迁移。
3. **entry points（随后完成）**
   - pyproject 注册 `cli_test_framework.comparators` entry point 组；
   - 第三方插件 `pip install` 即生效——这是「插件形式发布 → 成熟后合入本体
     `file_comparator/`」的通道。
4. 补《比较器插件开发指南》文档 + `examples/plugins/` 示例插件。

**验收标准**：
- workspace `comparators/` 下的自定义比较器可被配置直接引用；
- `script` 类型比较器能驱动既有 analyze 脚本并正确判定/展示输出；
- entry point 插件安装后可被发现。

---

### 迭代 5：配置继承

**目标**：消除高度同构的用例配置重复（5000+ 行 → 预计几百行）。

**设计**：

```json
{
  "test_cases": [
    {
      "name": "_base_T05",
      "abstract": true,
      "steps": [
        {"command": "python", "args": [".\\run_abaqus.py", "{case_dir}\\{case}.inp"], "expected": {...}}
      ],
      "expected": {"compare_files": [{"baseline": "{case_dir}/{case}_elements.csv"}]}
    },
    {
      "name": "T05_AF-U_01",
      "extends": "_base_T05",
      "variables": {"case": "AF-U_01", "case_dir": ".\\cases\\affine\\AF-U_01"}
    }
  ]
}
```

**语义规则**：

- `abstract: true` 的用例只作基类，不参与运行；
- `extends` 单继承，支持链式（A extends B extends C），加载时检测循环并报错；
- 合并规则：dict 深合并，list（含 steps）整体替换；
- 子类 `variables` 先替换继承来的内容，再叠加全局 `--var`——复用现有占位符管线。

**改动点**：`config_loader.py`（继承解析）、`config_schema.py`、`validate` 命令
（检查 extends 目标存在 / 无环）、文档、单测。

**后续事项**（本迭代不做）：TUI 对继承用例的编辑支持，先在文档标注
「继承用例请直接编辑 JSON」。

**验收标准**：
- 继承配置正确展开运行，与手写全量配置行为一致；
- 循环继承、extends 目标不存在给出明确报错；
- `validate` 能检查继承合法性。

---

## 5. 验证方式

每个迭代完成后执行全量测试：

```bash
conda activate xiaotong
python tests\run_all.py
```

迭代 3、4、5 还需补充对应的新单测。

## 6. 非目标

以下事项经评估后**暂不实施**：

- **SKILL 沉淀**：框架本身已是 AI-friendly 设计（结构化 ValidationError、
  `validate --json`、JUnit XML、报告结构化区块），SKILL 边际收益低。
  项目特有约定（venv 环境、预期失败策略等）应沉淀在使用方项目的
  rules/AGENTS.md 中，而非框架仓库的 SKILL。
  待迭代 3 落地后，可再评估是否将 TDD 工作流 SOP 固化为跨项目可复用的 SKILL。
- **「与上一轮对比」变化统计**：暂缓，优先做误差分析。
  后续可在 `.symtest` 增记 `last_status` 实现。
- **步骤级增量**（native 基线步骤在输入未变时跳过）：改动大、收益不确定。
- **报告摘要区失败前置/分组**：锦上添花，随迭代 3 顺带评估。
