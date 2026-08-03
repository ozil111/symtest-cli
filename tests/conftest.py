"""
Test configuration shared across suites.

Adds the project src directory to sys.path so tests can import symtest.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

