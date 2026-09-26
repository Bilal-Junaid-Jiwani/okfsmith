"""Test bootstrap: import okfsmith from this worktree's ``src/``.

The environment's editable install points at the main checkout; this branch
adds new subpackages (e.g. ``okfsmith.validate``), so tests must resolve
imports from the worktree under test. This keeps the change local — no
reinstall, no global side effects.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
