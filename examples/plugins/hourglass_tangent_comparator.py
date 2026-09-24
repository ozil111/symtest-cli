#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专用 hourglass 切线刚度比较器（workspace 插件范例，自主泳道）。

通过 subprocess 调用 ``analyze_*_tangent.py`` 分析脚本，捕获其 stdout，
用正则解析 RESULT 判定 + 数值指标（full_rel / aa_rel / hh_rel 等），
构造框架标准的 ComparisonResult，享受 diffs / error_stats / 报告渲染全套设施。

**泳道定位**：本插件拥有自己的判定逻辑（阈值 + RESULT 标签），属于
**自主泳道**（直接继承 ``ComparatorBase``，实现 ``compare(ctx)``）。
若只需要框架标准容差判定（rtol/atol），请改用数据泳道（继承
``ExtractorComparator``）或内置 ``script_extract`` 类型。

**零改动 analyze 脚本**：subprocess 调用时 ``sys.argv[0]`` 天然指向脚本路径，
``run_hg_analysis`` 内部的 case_dir 推断正确。

**路径解析**：``path_params`` 声明 ``script`` / ``case_dir`` 为路径参数，
框架在调用 ``compare()`` 前统一按 workspace 解析相对路径——插件内部
不得自行对 CWD 做 ``Path.resolve()``。

使用方式：
    1. 将本文件复制到你的 workspace 的 ``comparators/`` 目录下。
    2. 在配置中写：

       {
         "type": "hourglass_tangent",
         "script": "case/T05_alignment/cases/hourglass/WP31_pure/HG-M1_D1_A1e-4/analyze_HG-M1_D1_A1e-4_tangent.py",
         "case_dir": "case/T05_alignment/cases/hourglass/WP31_pure/HG-M1_D1_A1e-4",
         "pass_threshold": 1e-6,
         "timeout": 600
       }

    3. script / case_dir 路径相对于 workspace 解析（框架负责）。

判定逻辑：
    - 退出码 2 → error (文件缺失/解析失败)
    - stdout 匹配 "RESULT: PASS" → identical = True
    - full_rel < pass_threshold → identical = True (冗余判定)
    - 其他 → identical = False，differences + error_stats 列出全部指标
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

# When loaded as a workspace plugin, the framework package is importable
# because the worker process inherits the same Python environment.
# Use a guarded import for documentation/testing outside a full runtime.
try:
    from symtest.file_comparator.base_comparator import ComparatorBase, CompareContext
    from symtest.file_comparator.result import ComparisonResult, Difference
except ImportError:  # pragma: no cover
    ComparatorBase = object  # type: ignore
    CompareContext = None  # type: ignore
    ComparisonResult = None  # type: ignore
    Difference = None  # type: ignore


# ── regex patterns for stdout parsing ──
_RE_RESULT = re.compile(
    r"RESULT:\s*(PASS|WARNING|MISMATCH|SIGNIFICANT MISMATCH)"
)
_RE_FULL_REL = re.compile(
    r"Recovered-full relative error:\s*([\d.eE+\-]+)"
)
_RE_OBSERVED_REL = re.compile(
    r"observed-entry error\s*\(.*?\)\s*=\s*([\d.eE+\-]+)"
)
_RE_ASYMMETRY = re.compile(
    r"UEL asymmetry.*=\s*([\d.eE+\-]+)"
)
_RE_AA_REL = re.compile(
    r"K_AA relative error:\s*(.+?)$", re.MULTILINE
)
_RE_HH_REL = re.compile(
    r"K_HH relative error:\s*(.+?)$", re.MULTILINE
)
_RE_NATIVE_NORM = re.compile(
    r"Native\s+\|\|K\|\|_F\s+=\s*([\d.eE+\-]+)"
)
_RE_UEL_NORM = re.compile(
    r"UEL\s+\|\|K\|\|_F\s+=\s*([\d.eE+\-]+)"
)


def _parse_float(s: str) -> Optional[float]:
    """Try to extract a float from a string; return None on failure."""
    try:
        return float(s.strip())
    except (ValueError, TypeError):
        # The aa/hh relative may include a format string like "3.21e-04 (+/-...)"
        try:
            return float(s.strip().split()[0])
        except (ValueError, TypeError):
            return None


def _parse_stdout(stdout: str) -> Dict[str, Any]:
    """Extract structured metrics from hourglass analysis stdout."""
    data: Dict[str, Any] = {
        "verdict": None,
        "full_rel": None,
        "observed_rel": None,
        "asymmetry": None,
        "aa_rel": None,
        "hh_rel": None,
        "native_norm": None,
        "uel_norm": None,
    }

    m = _RE_RESULT.search(stdout)
    if m:
        data["verdict"] = m.group(1)

    for pattern, key in [
        (_RE_FULL_REL, "full_rel"),
        (_RE_OBSERVED_REL, "observed_rel"),
        (_RE_ASYMMETRY, "asymmetry"),
        (_RE_NATIVE_NORM, "native_norm"),
        (_RE_UEL_NORM, "uel_norm"),
    ]:
        m = pattern.search(stdout)
        if m:
            data[key] = _parse_float(m.group(1))

    for pattern, key in [(_RE_AA_REL, "aa_rel"), (_RE_HH_REL, "hh_rel")]:
        m = pattern.search(stdout)
        if m:
            data[key] = _parse_float(m.group(1))

    return data


class HourglassTangentComparator(ComparatorBase):  # type: ignore
    """Work against an ``analyze_*_tangent.py`` script and report structured results.

    Autonomous-lane plugin: implements ``compare(ctx)`` directly and owns its
    verdict.  Constructor parameters are forwarded from the config
    ``compareSpec``; ``script`` / ``case_dir`` are workspace-resolved by the
    framework (declared in ``path_params``).

    :param script:       Path to the ``analyze_*_tangent.py`` script (required).
    :param case_dir:     Working directory for the subprocess (script resolves
                         its own ``case_dir`` from ``sys.argv[0]``, but the
                         process cwd must contain the case files).
    :param pass_threshold: If ``full_rel < pass_threshold``, treat as PASS
                         (default ``1e-6``).
    :param interpreter:  Python interpreter (default ``sys.executable``).
    :param timeout:      Subprocess timeout in seconds (default 600).
    """

    path_params = ("script", "case_dir")

    def __init__(
        self,
        script: str = "",
        case_dir: Optional[str] = None,
        pass_threshold: float = 1e-6,
        interpreter: Optional[str] = None,
        timeout: int = 600,
    ):
        super().__init__()
        self.script = script      # workspace-resolved by the framework (path_params)
        self.case_dir = case_dir  # workspace-resolved by the framework (path_params)
        self.pass_threshold = pass_threshold
        self.interpreter = interpreter or sys.executable
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Core comparison
    # ------------------------------------------------------------------
    def compare(self, ctx: CompareContext) -> ComparisonResult:  # type: ignore[override]
        """Execute the hourglass analysis script and parse results."""
        result = ComparisonResult(
            file1=ctx.baseline,
            file2=ctx.actual,
        )

        try:
            cmd = [self.interpreter, self.script]

            self.logger.info("Executing hourglass analysis: %s", " ".join(cmd))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.case_dir,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            command_output = stdout + ("\n" + stderr if stderr else "")
            result.command_output = command_output

            # ── Error exit ──
            if proc.returncode == 2:
                result.error = (
                    f"Hourglass analysis error (exit code 2): "
                    f"file missing, parse failure, or invalid UEL data"
                )
                result.identical = False
                result.command_output = command_output
                return result

            # ── Parse stdout ──
            data = _parse_stdout(stdout)
            verdict = data["verdict"]
            full_rel = data["full_rel"]

            # ── Verdict ──
            if verdict == "PASS" and full_rel is not None and full_rel < self.pass_threshold:
                result.identical = True
            elif full_rel is not None and full_rel < self.pass_threshold:
                # Pass by numeric threshold even if verdict label differs
                result.identical = True
            else:
                result.identical = False

            # ── Error stats (always) ──
            stats: Dict[str, Any] = {}
            for key in ("full_rel", "observed_rel", "aa_rel", "hh_rel",
                        "asymmetry", "native_norm", "uel_norm"):
                if data.get(key) is not None:
                    stats[key] = data[key]
            if verdict:
                stats["verdict"] = verdict
            result.error_stats = stats if stats else None

            # ── Differences (only on failure) ──
            if not result.identical:
                differences: List[Difference] = []
                err_prefix = f"(threshold={self.pass_threshold:.0e})"
                if full_rel is not None:
                    differences.append(
                        Difference(
                            position="full_rel",
                            expected=f"< {self.pass_threshold:.0e}",
                            actual=f"{full_rel:.6e}",
                            diff_type="full_mismatch",
                        )
                    )
                if data.get("aa_rel") is not None:
                    differences.append(
                        Difference(
                            position="K_AA relative error",
                            expected=err_prefix,
                            actual=f"{data['aa_rel']}",
                            diff_type="block_error",
                        )
                    )
                if data.get("hh_rel") is not None:
                    differences.append(
                        Difference(
                            position="K_HH relative error",
                            expected=err_prefix,
                            actual=f"{data['hh_rel']}",
                            diff_type="block_error",
                        )
                    )
                if data.get("observed_rel") is not None:
                    differences.append(
                        Difference(
                            position="observed_entry_error",
                            expected=err_prefix,
                            actual=f"{data['observed_rel']:.6e}",
                            diff_type="entry_error",
                        )
                    )
                if data.get("asymmetry") is not None:
                    differences.append(
                        Difference(
                            position="UEL_asymmetry",
                            expected="≈ 0",
                            actual=f"{data['asymmetry']:.3e}",
                            diff_type="asymmetry",
                        )
                    )
                if verdict and verdict != "PASS":
                    differences.append(
                        Difference(
                            position="verdict",
                            expected="PASS",
                            actual=verdict,
                            diff_type="verdict",
                        )
                    )
                result.differences = differences

            return result

        except subprocess.TimeoutExpired:
            result.error = (
                f"Hourglass analysis timed out after {self.timeout}s: "
                f"{self.script}"
            )
            result.identical = False
            result.command_output = result.error
            return result
        except Exception as exc:
            self.logger.error(
                "Error executing hourglass analysis %s: %s", self.script, exc
            )
            result.error = str(exc)
            result.identical = False
            result.command_output = result.error
            return result
