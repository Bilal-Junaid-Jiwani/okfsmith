"""Ensure the worktree's ``src`` shadows any installed okfsmith copy."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
