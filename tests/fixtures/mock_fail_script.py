#!/usr/bin/env python3
"""Mock script that exits 1 with stdout containing 'MISMATCH'."""
import sys

if len(sys.argv) > 1:
    print(f"MISMATCH: {sys.argv[1]} did not match expected value")
    print(f"file1={sys.argv[1]}, file2={len(sys.argv) > 2 and sys.argv[2] or 'N/A'}")
else:
    print("MISMATCH: comparison failed")
sys.exit(1)
