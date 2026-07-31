#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并行测试性能验证脚本
快速验证并行测试功能和性能提升
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from symtest.runners.json_runner import JSONRunner
from symtest.runners.parallel_json_runner import ParallelJSONRunner


def create_test_config(num_tests=10):
    test_cases = []

    for i in range(num_tests):
        test_cases.append(
            {
                "name": f"测试用例 {i+1}",
                "command": "echo",
                "args": [f"test_{i+1}"],
                "expected": {"return_code": 0, "output_contains": [f"test_{i+1}"]},
            }
        )

    return {"test_cases": test_cases}


def run_performance_test():
    print("=" * 60)
    print("并行测试框架性能验证")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    config_file = os.path.join(temp_dir, "perf_test.json")

    num_tests = 8
    config = create_test_config(num_tests)

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"创建了 {num_tests} 个测试用例")
    print(f"测试配置文件: {config_file}")

    results = {}

    print(f"\n1. 顺序执行测试...")
    start_time = time.time()
    sequential_runner = JSONRunner(config_file, temp_dir)
    seq_success = sequential_runner.run_tests()
    seq_time = time.time() - start_time
    results["sequential"] = {"time": seq_time, "success": seq_success}

    print(f"\n2. 并行执行测试（线程模式，4个工作线程）...")
    start_time = time.time()
    parallel_runner = ParallelJSONRunner(config_file, temp_dir, max_workers=4, execution_mode="thread")
    par_success = parallel_runner.run_tests()
    par_time = time.time() - start_time
    results["parallel_thread"] = {"time": par_time, "success": par_success}

    print(f"\n3. 并行执行测试（进程模式，2个工作进程）...")
    start_time = time.time()
    process_runner = ParallelJSONRunner(config_file, temp_dir, max_workers=2, execution_mode="process")
    proc_success = process_runner.run_tests()
    proc_time = time.time() - start_time
    results["parallel_process"] = {"time": proc_time, "success": proc_success}

    print("\n" + "=" * 60)
    print("性能分析结果:")
    print("=" * 60)

    print(f"测试用例数量:      {num_tests}")
    print(f"顺序执行时间:      {seq_time:.2f} 秒")
    print(f"并行执行(线程):    {par_time:.2f} 秒 (加速比: {seq_time/par_time:.2f}x)")
    print(f"并行执行(进程):    {proc_time:.2f} 秒 (加速比: {seq_time/proc_time:.2f}x)")

    print(f"\n结果验证:")
    print(f"顺序执行成功:      {seq_success}")
    print(f"并行执行(线程)成功: {par_success}")
    print(f"并行执行(进程)成功: {proc_success}")

    import shutil

    shutil.rmtree(temp_dir)

    if all(results[key]["success"] for key in results):
        print(f"\n✓ 所有测试模式都成功执行")
        if par_time < seq_time:
            print(f"✓ 并行执行确实提升了性能")
        else:
            print(f"⚠ 在当前测试规模下，并行优势不明显")
    else:
        print(f"\n✗ 部分测试模式执行失败")
        return False

    return True


if __name__ == "__main__":
    try:
        success = run_performance_test()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试执行出错: {e}")
        sys.exit(1)

