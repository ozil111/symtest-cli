#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Demo script to show the effect of different H5 data filters
"""

import h5py
import numpy as np
import tempfile
import os
import subprocess
import sys


def create_demo_files():
    """Create demo H5 files with controlled differences"""

    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as f1, tempfile.NamedTemporaryFile(
        suffix=".h5", delete=False
    ) as f2:
        file1_path = f1.name
        file2_path = f2.name

    # Only the largest value (100.0) differs between files
    data1 = np.array([1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 1.0, 10.0, 100.0])
    data2 = np.array([1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 1.0, 10.0, 100.1])

    with h5py.File(file1_path, "w") as f:
        f.create_dataset("demo_data", data=data1)

    with h5py.File(file2_path, "w") as f:
        f.create_dataset("demo_data", data=data2)

    return file1_path, file2_path


def run_comparison(file1, file2, filter_expr=None):
    """Run comparison with optional filter"""
    cmd = [sys.executable, "-m", "src.symtest.commands.compare", "--file-type", "h5"]

    if filter_expr:
        cmd.extend(["--h5-data-filter", filter_expr])

    cmd.extend([file1, file2])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0, result.stdout.strip()


def demo_filter_effects():
    """Demonstrate how different filters affect comparison results"""

    print("=== H5 Data Filter Demo ===\n")
    print("Creating demo files with controlled differences...")
    print(
        "Data: [1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 1.0, 10.0, 100.0] vs [1e-10, 1e-8, 1e-6, 1e-4, 1e-2, 1.0, 10.0, 100.1]"
    )
    print("Only the largest value (100.0 vs 100.1) differs.\n")

    file1_path, file2_path = create_demo_files()

    try:
        test_cases = [
            ("No filter", None, "Should detect difference at 100.0 vs 100.1"),
            ("Filter >1e-6", ">1e-6", "Should detect difference (includes 100.0 vs 100.1)"),
            ("Filter >1e-4", ">1e-4", "Should detect difference (includes 100.0 vs 100.1)"),
            ("Filter >1e-2", ">1e-2", "Should detect difference (includes 100.0 vs 100.1)"),
            ("Filter >1.0", ">1.0", "Should detect difference (includes 100.0 vs 100.1)"),
            ("Filter >10.0", ">10.0", "Should detect difference (includes 100.0 vs 100.1)"),
            ("Filter >100.0", ">100.0", "Should NOT detect difference (neither 100.0 nor 100.1 > 100.0)"),
            ("Filter >=100.0", ">=100.0", "Should detect difference (both >= 100.0, but 100.0 != 100.1)"),
            ("Filter <1e-6", "<1e-6", "Should NOT detect difference (no values < 1e-6 differ)"),
            ("Filter <=1e-2", "<=1e-2", "Should NOT detect difference (no values <= 1e-2 differ)"),
        ]

        print("Filter Test Results:")
        print("-" * 80)
        print(f"{'Filter':<20} {'Result':<10} {'Expected':<15} {'Status':<10}")
        print("-" * 80)

        for filter_name, filter_expr, expected in test_cases:
            identical, output = run_comparison(file1_path, file2_path, filter_expr)

            if "100.0 vs 100.1" in expected:
                expected_identical = False
            else:
                expected_identical = True

            status = "✓ PASS" if identical == expected_identical else "✗ FAIL"

            print(f"{filter_name:<20} {'Identical' if identical else 'Different':<10} {expected_identical:<15} {status:<10}")

            if not identical and "NOT" in expected:
                print("  → Unexpected: Found difference when none expected")
            elif identical and "NOT" not in expected:
                print("  → Unexpected: No difference found when one expected")

    finally:
        os.unlink(file1_path)
        os.unlink(file2_path)
        print("\nDemo files cleaned up.")


if __name__ == "__main__":
    demo_filter_effects()

