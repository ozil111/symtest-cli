"""断言工具（1.4：自 ``core/assertions.py`` 迁入 validation/，只读化）。

``compare_files`` 不再携带 ``update_baseline`` 写盘分支 —— Validator 永远
只读（原则 3）；baseline 覆盖由编排层的 accept 步骤完成
（见 ``core/orchestration/accept.py``）。
"""
import os
import re
import logging
from typing import Any, Dict, List, Optional

from ...file_comparator.factory import ComparatorFactory
from ...file_comparator.base_comparator import CompareContext

logger = logging.getLogger("symtest.core.validation.assertions")


def _detect_file_type(file_path: str) -> str:
    """Auto-detect comparator type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    _type_map = {
        '.h5': 'h5', '.hdf5': 'h5', '.hdf': 'h5',
        '.json': 'json',
        '.csv': 'csv', '.tsv': 'csv',
        '.xml': 'xml', '.html': 'xml', '.htm': 'xml',
        '.txt': 'text', '.log': 'text', '.out': 'text', '.py': 'text',
    }
    if ext in _type_map:
        return _type_map[ext]
    # For unknown extensions, use binary comparator
    return 'binary'


class ValidationError(AssertionError):
    """Structured assertion failure carrying failure_kind and detailed data.

    Extends ``AssertionError`` for backward compatibility with existing
    ``except AssertionError`` catch blocks, while adding structured fields
    that reporters and AI consumers can use directly.
    """

    def __init__(
        self,
        message: str = "",
        *,
        failure_kind: str = "",
        compare_failures: Optional[List[Dict[str, Any]]] = None,
        baseline_updated: Optional[List[str]] = None,
        assertion_results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.compare_failures = compare_failures or []
        self.baseline_updated = baseline_updated or []
        self.assertion_results = assertion_results or []


def _build_diff_summary(result: Any) -> Dict[str, Any]:
    """Extract a numerical diff summary from a ``ComparisonResult``.

    Walks the ``differences`` list and computes:
    - ``total_differences``
    - ``max_rel_error`` / ``max_abs_error`` (for cells that are numeric)
    - ``max_rel_error_at`` / ``max_abs_error_at`` (position string)

    Data-lane results additionally carry per-channel ``channels``; each
    channel contributes a ``passed`` flag and its own error stats.
    """
    differences = getattr(result, "differences", []) or []
    summary: Dict[str, Any] = {
        "total_differences": len(differences),
        "max_rel_error": None,
        "max_rel_error_at": None,
        "max_abs_error": None,
        "max_abs_error_at": None,
    }
    for diff in differences:
        exp = getattr(diff, "expected", None)
        act = getattr(diff, "actual", None)
        pos = getattr(diff, "position", None)
        try:
            ve = float(exp)
            va = float(act)
            abs_err = abs(va - ve)
            rel_err = abs_err / max(abs(ve), 1e-300) if abs(ve) > 0 else float("inf")
            if summary["max_abs_error"] is None or abs_err > summary["max_abs_error"]:
                summary["max_abs_error"] = abs_err
                summary["max_abs_error_at"] = pos
            if summary["max_rel_error"] is None or rel_err > summary["max_rel_error"]:
                summary["max_rel_error"] = rel_err
                summary["max_rel_error_at"] = pos
        except (ValueError, TypeError):
            pass

    channels = getattr(result, "channels", None)
    if channels:
        summary["channels"] = {
            ch.name: {
                "passed": bool(ch.passed),
                "rtol": ch.rtol,
                "atol": ch.atol,
                "max_abs_error": (ch.stats or {}).get("max_abs_error"),
                "max_rel_error": (ch.stats or {}).get("max_rel_error"),
            }
            for ch in channels
        }
    return summary


class Assertions:
    @staticmethod
    def equals(actual: Any, expected: Any, message: str = "") -> bool:
        if actual != expected:
            raise AssertionError(f"{message} Expected: {expected}, but got: {actual}")
        return True

    @staticmethod
    def contains(container: str, item: str, message: str = "") -> bool:
        """
        Check if the item is contained within the container string.
        This method returns True if the item is found anywhere within the container,
        even if the container contains other information.
        """
        if item not in container:
            raise AssertionError(f"{message} Expected to contain: {item}")
        return True

    @staticmethod
    def matches(text: str, pattern: str, message: str = "") -> bool:
        if not re.search(pattern, text):
            raise AssertionError(f"{message} Text does not match pattern: {pattern}")
        return True

    @staticmethod
    def return_code_equals(actual: int, expected: int, message: str = "") -> bool:
        if actual != expected:
            raise AssertionError(f"{message} Expected return code: {expected}, got: {actual}")
        return True

    @staticmethod
    def compare_files(
        actual_path: str,
        baseline_path: str,
        file_type: Optional[str] = None,
        workspace: Optional[str] = None,
        *,
        error_analysis: bool = False,
        **comparator_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Compare two files using the appropriate file comparator (read-only).

        :param actual_path:   Path to the file generated by the test command.
        :param baseline_path: Path to the golden / reference file.
        :param file_type:     Comparator type ('h5','json','csv','xml','text','binary').
                              Auto-detected from file extension if omitted.
        :param workspace:     Working directory; both paths are resolved relative to
                              this directory when they are not absolute.
        :param error_analysis: If True, enable streaming error statistics over ALL
                               numeric cells (CSV/H5 comparators).
        :param comparator_kwargs: Extra keyword arguments forwarded to the comparator
                                  (e.g. ``rtol=1e-5``, ``atol=1e-8``, ``encoding='utf-8'``).
        :return: A dict with ``identical``, ``error``, ``diff_summary``,
                 ``differences``, ``actual``, ``baseline``, ``type``,
                 ``comparator_kwargs``.
        :raises ValidationError: when files differ or the comparator fails.
        """
        # Resolve paths relative to workspace
        orig_actual = actual_path
        orig_baseline = baseline_path
        if actual_path and workspace and not os.path.isabs(actual_path):
            actual_path = os.path.join(workspace, actual_path)
        if baseline_path and workspace and not os.path.isabs(baseline_path):
            baseline_path = os.path.join(workspace, baseline_path)

        # Auto-detect file type from extension (covers omitted type AND an
        # explicit "auto" — never let "auto" degrade to a silent guess inside
        # the factory when the file paths are available right here).
        if not file_type or file_type == "auto":
            if not actual_path:
                raise ValidationError(
                    "File type cannot be auto-detected: 'actual' path is empty. "
                    "Specify 'type' explicitly (e.g. 'script' or a custom plugin type).",
                    failure_kind="file_compare",
                )
            file_type = _detect_file_type(actual_path)

        # Extract compare_files() method-level parameters (not constructor kwargs).
        # These control line/column ranges in the comparator's compare_files() call.
        _method_keys = {"start_line", "end_line", "start_column", "end_column"}
        method_params: Dict[str, Any] = {}
        for k in list(comparator_kwargs):
            if k in _method_keys:
                method_params[k] = comparator_kwargs.pop(k)

        # Convert 1-based user input to 0-based (matches CLI behaviour)
        if "start_line" in method_params:
            method_params["start_line"] = max(0, int(method_params["start_line"]) - 1)
        if "end_line" in method_params and method_params["end_line"] is not None:
            method_params["end_line"] = max(0, int(method_params["end_line"]) - 1)
        if "start_column" in method_params:
            method_params["start_column"] = max(0, int(method_params["start_column"]) - 1)
        if "end_column" in method_params and method_params["end_column"] is not None:
            method_params["end_column"] = max(0, int(method_params["end_column"]) - 1)

        # Plugin configuration namespace: "options" is framework-owned
        # structure; its entries are merged into constructor kwargs.
        # Explicit top-level keys take precedence (legacy compatibility).
        options = comparator_kwargs.pop("options", None)
        if options is not None:
            if not isinstance(options, dict):
                raise ValidationError(
                    f"'options' must be an object of comparator parameters, "
                    f"got: {type(options).__name__}",
                    failure_kind="file_compare",
                )
            comparator_kwargs = {**options, **comparator_kwargs}

        # Collect tolerances for reporting (before they're consumed by factory)
        reported_kwargs = {
            k: v for k, v in comparator_kwargs.items()
            if k not in ("verbose", "debug", "num_threads", "chunk_size", "encoding")
        }

        try:
            # Lifecycle: the factory resolves path_params-declared parameters
            # against the workspace BEFORE construction, so constructor-captured
            # state (self.script, self.cwd, ...) already holds absolute paths.
            comparator = ComparatorFactory.create_comparator(
                file_type,
                workspace=workspace,
                error_analysis=error_analysis,
                **comparator_kwargs,
            )

            ctx = CompareContext(
                workspace=workspace,
                actual=actual_path or None,
                baseline=baseline_path or None,
                # Invocation-level parameters only (file-lane window ranges).
                # Comparator configuration lives solely in comparator state —
                # one authoritative source per configuration value.
                params=method_params,
                error_analysis=error_analysis,
            )
            result = comparator.compare(ctx)

            # Build structured response
            diff_summary = _build_diff_summary(result)
            response: Dict[str, Any] = {
                "identical": result.identical,
                "error": result.error,
                "actual": orig_actual,
                "baseline": orig_baseline,
                "type": file_type,
                "comparator_kwargs": reported_kwargs,
                "diff_summary": diff_summary,
                "differences": (
                    [d.to_dict() for d in result.differences]
                    if result.differences else []
                ),
                "error_stats": result.error_stats,
                "command_output": result.command_output,
                "channels": (
                    [ch.to_dict() for ch in result.channels]
                    if result.channels else []
                ),
            }

            if result.error:
                raise ValidationError(
                    f"File comparison error ({orig_actual} vs {orig_baseline}): {result.error}",
                    failure_kind="file_compare",
                    compare_failures=[response],
                )

            if not result.identical:
                raise ValidationError(
                    f"File comparison failed ({orig_actual} vs {orig_baseline}):\n{result}",
                    failure_kind="file_compare",
                    compare_failures=[response],
                )

            return response

        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                f"File comparison error ({orig_actual} vs {orig_baseline}): {exc}",
                failure_kind="file_compare",
            )
