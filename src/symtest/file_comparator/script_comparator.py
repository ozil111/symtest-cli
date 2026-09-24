#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file script_comparator.py
@brief Built-in script comparator – autonomous lane, delegates verdict to an external script
@author Xiaotong Wang
@date 2025
"""

import re
import subprocess
import sys
from typing import List, Optional

from .base_comparator import ComparatorBase, CompareContext
from .result import ComparisonResult, Difference


class ScriptComparator(ComparatorBase):
    """Run an external script as a comparison step (autonomous lane).

    The script is invoked as a subprocess.  By default exit code 0 signals
    *pass*.  Optionally, ``pass_pattern`` / ``fail_pattern`` regexes can be
    used to refine the verdict from ``stdout``.  The plugin owns the verdict —
    for framework-owned numeric tolerance use the ``script_extract`` type.

    Configuration example::

        {"type": "script", "script": "analyze_xxx.py",
         "actual": "...", "baseline": "...", "cwd": ".", "pass_pattern": "PASS",
         "fail_pattern": "(MISMATCH|FAILED)"}
    """

    path_params = ("script", "cwd")

    def __init__(
        self,
        script: str = "",
        cwd: Optional[str] = None,
        args: Optional[List[str]] = None,
        interpreter: Optional[str] = None,
        pass_exit_code: int = 0,
        pass_pattern: Optional[str] = None,
        fail_pattern: Optional[str] = None,
        timeout: int = 3600,
    ):
        super().__init__()
        self.script = script      # workspace-resolved by the framework (path_params)
        self.cwd = cwd            # workspace-resolved by the framework (path_params)
        self.args = list(args) if args else []
        self.interpreter = interpreter or sys.executable
        self.pass_exit_code = pass_exit_code
        self.pass_pattern = re.compile(pass_pattern) if pass_pattern else None
        self.fail_pattern = re.compile(fail_pattern) if fail_pattern else None
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Core comparison
    # ------------------------------------------------------------------
    def compare(self, ctx: CompareContext) -> ComparisonResult:  # type: ignore[override]
        """Execute the external script and evaluate its output."""
        result = ComparisonResult(
            file1=ctx.baseline,
            file2=ctx.actual,
        )

        try:
            cmd = [self.interpreter, self.script, *self.args]
            # Trailing file slots, baseline first (historical convention:
            # compare_files(file1=baseline, file2=actual) → argv[-2:]).
            if ctx.baseline:
                cmd.append(str(ctx.baseline))
            if ctx.actual:
                cmd.append(str(ctx.actual))

            self.logger.info("Executing script: %s", " ".join(cmd))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.cwd,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            command_output = stdout + ("\n" + stderr if stderr else "")
            result.command_output = command_output

            # ── Verdict ──
            exit_ok = proc.returncode == self.pass_exit_code

            pass_match = None
            fail_match = None
            if self.pass_pattern:
                pass_match = self.pass_pattern.search(stdout)
            if self.fail_pattern:
                fail_match = self.fail_pattern.search(stdout)

            if fail_match:
                result.identical = False
            elif self.pass_pattern and not pass_match:
                # pass_pattern was set but did not match → fail
                result.identical = False
            elif pass_match:
                result.identical = exit_ok
            else:
                result.identical = exit_ok

            if not result.identical:
                differences: List[Difference] = []
                if not exit_ok:
                    differences.append(
                        Difference(
                            position="exit_code",
                            expected=str(self.pass_exit_code),
                            actual=str(proc.returncode),
                            diff_type="exit_code_mismatch",
                        )
                    )
                if fail_match:
                    differences.append(
                        Difference(
                            position="stdout pattern",
                            expected=f"no match for fail_pattern '{self.fail_pattern.pattern}'",
                            actual=f"matched: {fail_match.group()}",
                            diff_type="fail_pattern_match",
                        )
                    )
                elif pass_match is None and self.pass_pattern:
                    differences.append(
                        Difference(
                            position="stdout pattern",
                            expected=f"match for pass_pattern '{self.pass_pattern.pattern}'",
                            actual="no match found in stdout",
                            diff_type="pass_pattern_missing",
                        )
                    )
                if not differences:
                    differences.append(
                        Difference(
                            position="stdout",
                            expected="script determined failure",
                            actual=stdout[:500] if stdout else "(empty)",
                            diff_type="script_failure",
                        )
                    )
                result.differences = differences

            return result

        except subprocess.TimeoutExpired:
            result.error = f"Script timed out after {self.timeout}s: {self.script}"
            result.identical = False
            result.command_output = result.error
            return result
        except Exception as exc:
            self.logger.error("Error executing script %s: %s", self.script, exc)
            result.error = str(exc)
            result.identical = False
            result.command_output = result.error
            return result
