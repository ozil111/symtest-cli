"""结构化 HTML 报告生成器。

单文件、零外部依赖（内联 CSS + 少量原生 JS），输入只消费 runner results
dict（design.md 原则 5：Reporting 只能消费 Result）。数据解释规则与文本
报告 ``report_generator.py`` 严格同源：

- ``channels`` 只从结构化 ``channels`` 列表渲染，``error_stats`` 为 flat fallback；
- 通过用例的误差统计仅在 ``results['error_analysis_all']`` 为真时输出；
- 所有用户数据（name / description / message / output）一律 HTML 转义。

页面信息分三层密度，避免"信息太多太乱"：

1. 顶部摘要 + 失败导航（永远可见）；
2. 用例一览：状态 + 名称 + **description** + tags + 时长（默认视图）；
3. 每个用例的详情区（``<details>``，默认收起；命令输出再嵌套折叠）。
"""

import html
import json
import logging
from datetime import datetime

logger = logging.getLogger("symtest.utils.html_report")

# ── 状态 → (图标, CSS class) ──
_STATUS_META = {
    "passed": ("✓", "passed"),
    "xfailed": ("✓", "xfailed"),
    "xpassed": ("✗", "xpassed"),
    "timeout": ("✗", "failed"),
    "failed": ("✗", "failed"),
    "skipped": ("⊘", "skipped"),
}
_BAD_STATUSES = ("failed", "timeout", "xpassed")

_CSS = """
:root { --ok:#1a7f37; --bad:#cf222e; --warn:#9a6700; --muted:#656d76;
        --border:#d0d7de; --bg:#f6f8fa; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0;
       background: #fff; color: #1f2328; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 1.5em 2em 4em; }
h1 { font-size: 1.4em; }
.muted { color: var(--muted); }
/* 摘要 */
.cards { display: flex; flex-wrap: wrap; gap: .6em; margin: 1em 0; }
.card { background: var(--bg); border: 1px solid var(--border);
        border-radius: 6px; padding: .5em 1em; min-width: 90px; }
.card .num { font-size: 1.4em; font-weight: 600; }
.card.ok .num { color: var(--ok); }
.card.bad .num { color: var(--bad); }
.card.warn .num { color: var(--warn); }
.bar { height: 8px; background: #e7ebef; border-radius: 4px; overflow: hidden; }
.bar > div { height: 100%; background: var(--ok); }
/* 失败导航 */
.failed-nav { border: 1px solid #ffc1bc; background: #fff1f0;
              border-radius: 6px; padding: .6em 1em; margin: 1em 0; }
.failed-nav a { color: var(--bad); }
/* 工具栏 */
.toolbar { display: flex; gap: .5em; margin: 1em 0; flex-wrap: wrap; }
.toolbar button { border: 1px solid var(--border); background: var(--bg);
                  border-radius: 6px; padding: .3em .9em; cursor: pointer; }
.toolbar button:hover { background: #eaeef2; }
/* 用例列表 */
details.case { border: 1px solid var(--border); border-radius: 6px;
               margin: .4em 0; }
details.case > summary { list-style: none; cursor: pointer; display: flex;
                         gap: .8em; align-items: baseline;
                         padding: .45em .9em; }
details.case > summary::before { content: "▸"; color: var(--muted); }
details.case[open] > summary::before { content: "▾"; }
details.case > summary:hover { background: var(--bg); }
details.case .icon { font-weight: 700; }
.icon.passed, .icon.xfailed { color: var(--ok); }
.icon.failed, .icon.xpassed { color: var(--bad); }
.icon.xpassed { font-weight: 800; }
.icon.skipped { color: var(--muted); }
details.case.failed  { border-left: 4px solid var(--bad); }
details.case.xpassed { border-left: 4px solid var(--bad); }
details.case.passed  { border-left: 4px solid var(--ok); }
details.case.xfailed { border-left: 4px solid var(--warn); }
.case .name { font-weight: 600; }
.case .desc { color: var(--muted); flex: 1; }
.case .tags { color: var(--muted); font-size: .85em; }
.case .dur  { color: var(--muted); font-size: .85em; white-space: nowrap; }
.chip { display: inline-block; padding: 0 .5em; border-radius: 10px;
        font-size: .8em; font-weight: 600; }
.chip-pass { background: #dafbe1; color: var(--ok); }
.chip-fail { background: #ffebe9; color: var(--bad); }
/* 详情区 */
.body { padding: .4em 1.2em 1em; border-top: 1px solid var(--border); }
table.kv { border-collapse: collapse; margin: .3em 0; }
table.kv th, table.kv td { border: 1px solid var(--border); padding: .2em .7em;
                           text-align: left; vertical-align: top; }
table.kv th { background: var(--bg); font-weight: 600; white-space: nowrap; }
.sub-title { font-weight: 600; margin: .8em 0 .2em; }
pre { background: var(--bg); border: 1px solid var(--border);
      border-radius: 6px; padding: .6em .9em; margin: .3em 0; }
pre.scroll { max-height: 18em; overflow: auto; }
pre.small { font-size: .85em; }
.failure-msg { color: var(--bad); margin: .4em 0; white-space: pre-wrap; }
.assertion, .cf, .channel { border-left: 3px solid var(--border);
                            padding-left: .8em; margin: .4em 0; }
.assertion-head, .cf-head { font-weight: 600; }
.ch-head { margin: .2em 0; }
.diff { font-family: Consolas, monospace; font-size: .85em;
        margin: .1em 0; }
.hint { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px;
        padding: .5em .9em; margin: .5em 0; }
ul.plain { margin: .2em 0; padding-left: 1.4em; }
.step-line { margin: .15em 0; }
footer { margin-top: 2em; }
"""

_JS = """
function expandAll(open) {
  document.querySelectorAll('details.case').forEach(function (d) { d.open = open; });
}
function setFilter(mode) {
  document.querySelectorAll('details.case').forEach(function (d) {
    var s = d.getAttribute('data-status');
    var show = true;
    if (mode === 'failed') {
      show = ['failed', 'timeout', 'xpassed'].indexOf(s) >= 0;
    } else if (mode === 'passed') {
      show = (s === 'passed' || s === 'xfailed');
    }
    d.style.display = show ? '' : 'none';
  });
}
"""


def _esc(value) -> str:
    """HTML 转义；所有来自 results 的字符串都必须经过此函数。"""
    return html.escape(str(value), quote=True)


def _fmt_num(value) -> str:
    """与文本报告一致的浮点格式（%.6g）；None 渲染为空串。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _stats_table(stats: dict) -> str:
    """渲染 ``key: value`` 统计表（浮点按 %.6g）。"""
    rows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(_fmt_num(v))}</td></tr>"
        for k, v in stats.items()
    )
    return f'<table class="kv">{rows}</table>'


def _output_details(title: str, text: str) -> str:
    """长文本块的嵌套折叠容器（默认收起）。"""
    return (
        f'<details class="sub"><summary>{_esc(title)}</summary>'
        f'<pre class="scroll">{_esc(text)}</pre></details>'
    )


def _render_channel(ch: dict) -> str:
    """逐通道渲染：verdict + 容差 + stats + extra_stats + 样例差异。

    与文本报告 ``_render_channels`` 的数据解释规则一致。
    """
    passed = bool(ch.get("passed"))
    verdict = "PASS" if passed else "FAIL"
    cls = "chip-pass" if passed else "chip-fail"
    head = (
        f"channel '{_esc(ch.get('name'))}': "
        f'<span class="chip {cls}">{verdict}</span> '
        f"(rtol={_esc(_fmt_num(ch.get('rtol', 0)))}, "
        f"atol={_esc(_fmt_num(ch.get('atol', 0)))})"
    )
    parts = [f'<div class="ch-head">{head}</div>']
    stats = ch.get("stats")
    if stats:
        parts.append(_stats_table(stats))
    extra = ch.get("extra_stats")
    if extra:
        parts.append('<div class="sub-title">extra_stats:</div>')
        parts.append(_stats_table(extra))
    diffs = ch.get("differences", [])
    for d in diffs[:3]:
        parts.append(
            f'<div class="diff">{_esc(d.get("position"))}: '
            f'expected={_esc(d.get("expected"))}, actual={_esc(d.get("actual"))}</div>'
        )
    if len(diffs) > 3:
        parts.append(f'<div class="diff muted">... and {len(diffs) - 3} more</div>')
    return '<div class="channel">' + "".join(parts) + "</div>"


def _scope_label(entry: dict) -> str:
    """``(baseline: X vs actual: Y)`` 文件对标签；无文件信息时为空。"""
    baseline = entry.get("baseline")
    actual = entry.get("actual")
    if not baseline and not actual:
        return ""
    return f' <span class="muted">(baseline: {_esc(baseline)} vs actual: {_esc(actual)})</span>'


def _render_assertion_results(assertion_results: list) -> str:
    """通过用例的误差统计块（--error-analysis-all 时调用）。"""
    blocks = []
    for ar in assertion_results:
        channels = ar.get("channels")
        inner = []
        if channels:
            inner.append('<div class="sub-title">channels:</div>')
            inner.extend(_render_channel(ch) for ch in channels)
        else:
            es = ar.get("error_stats")
            if es:
                inner.append('<div class="sub-title">error_stats:</div>')
                inner.append(_stats_table(es))
        if not inner:
            continue
        head = f'compare_files{_scope_label(ar)}'
        blocks.append(
            f'<div class="assertion"><div class="assertion-head">{head}</div>'
            + "".join(inner) + "</div>"
        )
    return "".join(blocks)


def _render_compare_failure(cf: dict) -> str:
    """单条失败文件比较的结构化详情（与文本报告字段一一对应）。"""
    header_bits = []
    if cf.get("baseline") or cf.get("actual"):
        header_bits.append(f"baseline: {_esc(cf.get('baseline'))}")
        header_bits.append(f"actual: {_esc(cf.get('actual'))}")
    if cf.get("type"):
        header_bits.append(f"type: {_esc(cf.get('type'))}")
    parts = [f'<div class="cf-head">{" ｜ ".join(header_bits)}</div>']

    ds = cf.get("diff_summary") or {}
    rows = {}
    if ds.get("total_differences") is not None:
        rows["total_differences"] = ds["total_differences"]
    if ds.get("max_rel_error") is not None:
        rows["max_rel_error"] = (
            f"{_fmt_num(ds['max_rel_error'])} at {ds.get('max_rel_error_at')}"
        )
    if ds.get("max_abs_error") is not None:
        rows["max_abs_error"] = (
            f"{_fmt_num(ds['max_abs_error'])} at {ds.get('max_abs_error_at')}"
        )
    if rows:
        parts.append(_stats_table(rows))

    channels = cf.get("channels")
    if channels:
        parts.append('<div class="sub-title">channels:</div>')
        parts.extend(_render_channel(ch) for ch in channels)
    else:
        es = cf.get("error_stats")
        if es:
            parts.append('<div class="sub-title">error_stats:</div>')
            parts.append(_stats_table(es))

    diffs = cf.get("differences", [])
    if diffs:
        lines = [
            f'{d.get("position")}: expected={d.get("expected")}, actual={d.get("actual")}'
            for d in diffs[:5]
        ]
        if len(diffs) > 5:
            lines.append(f"... and {len(diffs) - 5} more")
        parts.append('<div class="sub-title">sample differences:</div>')
        parts.append('<pre class="scroll small">' + _esc("\n".join(lines)) + "</pre>")

    if cf.get("command_output"):
        parts.append(_output_details("Comparator Output", cf["command_output"]))
    return '<div class="cf">' + "".join(parts) + "</div>"


def _render_steps(step_results: list) -> str:
    items = []
    for sr in step_results:
        ok = sr.get("status") == "passed"
        icon, cls = ("✓", "passed") if ok else ("✗", "failed")
        line = (
            f"Step {sr.get('step')}: {sr.get('status')} "
            f"({sr.get('duration', 0) or 0:.2f}s)"
        )
        item = (
            f'<div class="step-line"><span class="icon {cls}">{icon}</span> '
            f"{_esc(line)}"
        )
        if sr.get("message"):
            item += f'<pre class="scroll small">{_esc(sr["message"])}</pre>'
        item += "</div>"
        items.append(item)
    return "".join(items)


def _render_hint(hint: dict) -> str:
    """next_action_hint 结构化建议框。"""
    bits = []
    if hint.get("action"):
        bits.append(f"action: {_esc(hint['action'])}")
    if hint.get("command"):
        bits.append(f"command: <code>{_esc(hint['command'])}</code>")
    if hint.get("reason"):
        bits.append(_esc(hint["reason"]))
    return '<div class="hint">Next action — ' + " ｜ ".join(bits) + "</div>"


def _render_case_body(detail: dict, error_analysis_all: bool) -> str:
    sections = []
    status = detail.get("status", "")

    # 元信息表
    rows = []
    if detail.get("command"):
        rows.append(("Command", f"<code>{_esc(detail['command'])}</code>"))
    if detail.get("return_code") is not None:
        rows.append(("Return Code", _esc(detail["return_code"])))
    if detail.get("failure_kind"):
        rows.append(("Failure Kind", _esc(detail["failure_kind"])))
    if detail.get("failed_step"):
        rows.append(("Failed Step", _esc(detail["failed_step"])))
    if detail.get("xfail_reason"):
        rows.append(("XFail Reason", _esc(detail["xfail_reason"])))
    attempts = detail.get("attempts", 1)
    if attempts and attempts > 1:
        flaky = " (flaky)" if detail.get("flaky") else ""
        rows.append(("Attempts", _esc(f"{attempts}{flaky}")))
    if rows:
        table = "".join(
            f"<tr><th>{th}</th><td>{td}</td></tr>" for th, td in rows
        )
        sections.append(f'<table class="kv">{table}</table>')

    expected = detail.get("expected")
    if expected:
        sections.append('<div class="sub-title">Expected (验收标准):</div>')
        sections.append(
            '<pre class="scroll small">'
            + _esc(json.dumps(expected, indent=2, ensure_ascii=False, default=str))
            + "</pre>"
        )

    step_results = detail.get("step_results") or []
    if step_results:
        sections.append('<div class="sub-title">Step Results:</div>')
        sections.append(_render_steps(step_results))

    # 通过用例：误差统计（仅 --error-analysis-all 时，与文本报告一致）
    if status == "passed" and error_analysis_all:
        stats_html = _render_assertion_results(detail.get("assertion_results") or [])
        if stats_html:
            sections.append('<div class="sub-title">Error Analysis:</div>')
            sections.append(stats_html)

    # 非通过用例：失败详情
    if status != "passed":
        if detail.get("message"):
            sections.append(
                f'<div class="failure-msg">→ {_esc(detail["message"])}</div>'
            )
        compare_failures = detail.get("compare_failures") or []
        if compare_failures:
            sections.append('<div class="sub-title">Compare Failures:</div>')
            sections.extend(_render_compare_failure(cf) for cf in compare_failures)
        baseline_updated = detail.get("baseline_updated") or []
        if baseline_updated:
            sections.append('<div class="sub-title">Baseline Updated:</div>')
            sections.append(
                '<ul class="plain">'
                + "".join(f"<li>{_esc(p)}</li>" for p in baseline_updated)
                + "</ul>"
            )
        # xfail_quiet 语义与文本报告一致：抑制 Command Output
        is_xfail_quiet = (
            status == "xfailed" and detail.get("xfail_quiet")
        )
        if detail.get("output") and not is_xfail_quiet:
            sections.append(_output_details("Command Output", detail["output"]))
        if detail.get("error_trace"):
            sections.append(_output_details("Error Trace", detail["error_trace"]))

    hint = detail.get("next_action_hint")
    if hint:
        sections.append(_render_hint(hint))

    return '<div class="body">' + "".join(sections) + "</div>"


def _render_case(detail: dict, idx: int, error_analysis_all: bool) -> str:
    status = detail.get("status", "")
    icon, cls = _STATUS_META.get(status, ("?", "failed"))
    duration = detail.get("duration", 0) or 0
    description = detail.get("description") or ""
    tags = detail.get("tags") or []

    tag_html = " ".join(_esc(t) for t in tags)
    summary = (
        f'<summary>'
        f'<span class="icon {cls}">{icon}</span>'
        f'<span class="name">{_esc(detail.get("name"))}</span>'
        f'<span class="desc">{_esc(description)}</span>'
        + (f'<span class="tags">[{tag_html}]</span>' if tag_html else "")
        + f'<span class="dur">{duration:.2f}s</span>'
        f"</summary>"
    )
    return (
        f'<details class="case {cls}" data-status="{_esc(status)}" id="case-{idx}">'
        f"{summary}{_render_case_body(detail, error_analysis_all)}</details>"
    )


def generate_html_report(results: dict) -> str:
    """把 runner results dict 渲染为自包含的可折叠 HTML 报告页面。"""
    details = results.get("details", [])
    total = results.get("total", len(details))
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    xfailed = results.get("xfailed", 0)
    xpassed = results.get("xpassed", 0)
    updated = results.get("updated", 0)
    skipped = sum(1 for d in details if d.get("status") == "skipped")
    total_duration = sum((d.get("duration") or 0) for d in details)
    pass_pct = (passed / total * 100.0) if total else 0.0
    error_analysis_all = bool(results.get("error_analysis_all"))

    def card(label, num, cls=""):
        return (
            f'<div class="card {cls}"><div class="num">{num}</div>'
            f'<div class="muted">{label}</div></div>'
        )

    cards = "".join([
        card("Total", total),
        card("Passed", passed, "ok"),
        card("Failed", failed, "bad" if failed else ""),
        card("XFailed", xfailed, "warn" if xfailed else ""),
        card("XPassed", xpassed, "bad" if xpassed else ""),
    ])
    if skipped:
        cards += card("Skipped", skipped)
    if updated:
        cards += card("Baseline Updated", updated, "warn")

    # 失败用例快速导航
    failed_items = []
    for idx, d in enumerate(details):
        if d.get("status") in _BAD_STATUSES:
            failed_items.append(
                f'<a href="#case-{idx}">{_esc(d.get("name"))}</a>'
            )
    failed_nav = (
        '<div class="failed-nav"><strong>Failed cases:</strong> '
        + " · ".join(failed_items) + "</div>"
    ) if failed_items else ""

    cases = "".join(
        _render_case(d, idx, error_analysis_all)
        for idx, d in enumerate(details)
    )

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>SymTest Report</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
        "<h1>SymTest Report</h1>\n"
        f'<p class="muted">Generated: {datetime.now():%Y-%m-%d %H:%M:%S}</p>\n'
        f'<div class="cards">{cards}</div>\n'
        f'<div class="bar"><div style="width:{pass_pct:.1f}%"></div></div>\n'
        f'<p class="muted">Pass rate {pass_pct:.1f}% ｜ '
        f"Total duration {total_duration:.2f}s</p>\n"
        f"{failed_nav}\n"
        '<div class="toolbar">'
        '<button onclick="setFilter(\'all\')">全部</button>'
        '<button onclick="setFilter(\'failed\')">仅失败</button>'
        '<button onclick="setFilter(\'passed\')">仅通过</button>'
        "<button onclick=\"expandAll(true)\">全部展开</button>"
        "<button onclick=\"expandAll(false)\">全部收起</button>"
        "</div>\n"
        f"{cases}\n"
        '<footer class="muted">SymTest HTML report — click a case row to '
        "expand details.</footer>\n"
        f"</div>\n<script>{_JS}</script>\n</body>\n</html>"
    )
