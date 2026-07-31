#!/usr/bin/env python3
"""Mock script that always exits 0 with stdout containing 'PASS'."""
import sys

if len(sys.argv) > 1:
    print(f"PASS: processed {sys.argv[1]}")
else:
    print("PASS: all checks passed")
sys.exit(0)
