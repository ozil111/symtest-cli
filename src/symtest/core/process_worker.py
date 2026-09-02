"""
进程工作器模块
用于多进程并行测试执行，避免序列化问题

Phase 3 Schema v2：跨进程传递 v2 wire dict（``TestCase.to_dict()`` 输出），
本模块负责将其重建为 ``ExecutionSpec`` / ``TestStep`` 对象后进入编排层。
"""

import logging
from typing import Any, Dict

from .orchestration.sequence import execute_sequence
from .orchestration.single import execute_single_test_case
from .test_case import ExecutionSpec, TestStep

logger = logging.getLogger("symtest.core.process_worker")


def _spec_from_v2(case_data: Dict[str, Any]) -> ExecutionSpec:
    """v2 wire dict（case.to_dict()）→ ExecutionSpec（含 TestStep 重建）。"""
    execution = case_data.get("execution") or {}
    if "steps" in execution:
        steps = [
            TestStep.from_flat(
                command=s["command"],
                args=s["args"],
                expected=s.get("expected") or {},
                timeout=s.get("timeout"),
                retry_count=s.get("retry_count", 0),
            )
            for s in execution["steps"]
        ]
        return ExecutionSpec(
            name=case_data.get("name", ""),
            steps=steps,
            retry_count=execution.get("retry_count", 0),
            env=execution.get("env") or {},
        )
    return ExecutionSpec(
        name=case_data.get("name", ""),
        command=execution.get("command", ""),
        args=execution.get("args", []),
        timeout=execution.get("timeout"),
        retry_count=execution.get("retry_count", 0),
        env=execution.get("env") or {},
    )


def run_test_in_process(
    test_index: int,
    case_data: Dict[str, Any],
    workspace: str = None,
    *,
    update_baseline: bool = False,
    error_analysis: bool = False,
    resume: bool = False,
) -> Dict[str, Any]:
    """
    在独立进程中运行单个测试用例

    Args:
        test_index: 测试索引
        case_data: v2 wire dict（case.to_dict() 输出）
        workspace: 工作目录
        update_baseline: 是否更新基线文件
        resume: 是否启用断点续跑

    Returns:
        测试结果字典
    """
    expectation = case_data.get("expected") or {}
    spec = _spec_from_v2(case_data)

    # Sequence mode
    if spec.steps is not None:
        return execute_sequence(
            case_name=case_data["name"],
            steps=spec.steps,
            workspace=workspace,
            print_prefix=f"[Process Worker {test_index}]",
            executor=execute_single_test_case,
            case_expected=expectation,
            update_baseline=update_baseline,
            error_analysis=error_analysis,
            resume=resume,
            env=spec.env,
        )

    # Single command mode
    command_preview = f"{spec.command} {' '.join(spec.args)}".strip()
    logger.info("  [Process Worker %d] Executing command: %s", test_index, command_preview)

    result = execute_single_test_case(
        spec,
        workspace,
        expectation=expectation,
        update_baseline=update_baseline,
        error_analysis=error_analysis,
    )

    if result["output"].strip():
        logger.debug("  [Process Worker %d] Command output for %s:", test_index, case_data["name"])
        for line in result["output"].splitlines():
            logger.debug("    %s", line)

    if result["status"] != "passed" and result.get("message"):
        logger.error("  [Process Worker %d] Error for %s: %s", test_index, case_data["name"], result["message"])

    return result
