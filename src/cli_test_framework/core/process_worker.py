"""
进程工作器模块
用于多进程并行测试执行，避免序列化问题
"""

import logging
from typing import Dict, Any, List
from .config_loader import execute_sequence
from .execution import execute_single_test_case
from .types import TestCaseData

logger = logging.getLogger("cli_test_framework.core.process_worker")

def _run_sequence_in_process(
    test_index: int,
    case_data: Dict[str, Any],
    workspace: str = None,
    *,
    update_baseline: bool = False,
    resume: bool = False,
) -> Dict[str, Any]:
    """Run a sequence test case with multiple steps (fail-fast) in a process worker."""
    return execute_sequence(
        case_name=case_data["name"],
        steps=case_data["steps"],
        workspace=workspace,
        print_prefix=f"[Process Worker {test_index}]",
        executor=execute_single_test_case,
        case_expected=case_data.get("expected"),
        update_baseline=update_baseline,
        resume=resume,
    )


def run_test_in_process(
    test_index: int,
    case_data: Dict[str, Any],
    workspace: str = None,
    *,
    update_baseline: bool = False,
    resume: bool = False,
) -> Dict[str, Any]:
    """
    在独立进程中运行单个测试用例
    
    Args:
        test_index: 测试索引
        case_data: 测试用例数据字典
        workspace: 工作目录
        update_baseline: 是否更新基线文件
        resume: 是否启用断点续跑
    
    Returns:
        测试结果字典
    """
    # Sequence mode
    if case_data.get("steps"):
        return _run_sequence_in_process(
            test_index, case_data, workspace,
            update_baseline=update_baseline,
            resume=resume,
        )

    # Single command mode
    case: TestCaseData = {
        "name": case_data["name"],
        "command": case_data["command"],
        "args": case_data["args"],
        "expected": case_data["expected"],
        "description": case_data.get("description"),
        "timeout": case_data.get("timeout"),
        "resources": case_data.get("resources"),
        "retry_count": case_data.get("retry_count", 0),
    }

    command_preview = f"{case['command']} {' '.join(case['args'])}".strip()
    logger.info("  [Process Worker %d] Executing command: %s", test_index, command_preview)

    result = execute_single_test_case(case, workspace)

    if result["output"].strip():
        logger.debug("  [Process Worker %d] Command output for %s:", test_index, case["name"])
        for line in result["output"].splitlines():
            logger.debug("    %s", line)

    if result["status"] != "passed" and result.get("message"):
        logger.error("  [Process Worker %d] Error for %s: %s", test_index, case["name"], result["message"])

    return result 