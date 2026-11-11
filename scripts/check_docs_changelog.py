#!/usr/bin/env python3
"""Fail unless every version in root CHANGELOG.md appears in the docs changelog.

The docs site changelog (docs/src/changelog.md) once listed only 9 of the
55 released versions — it jumped from 0.25.0 straight to 0.7.1 — because
nothing enforced completeness. This check (run by the `docs-changelog` CI
job) keeps that gap from silently reopening.

Rules:
- Every ``## [X.Y.Z]`` heading in the root CHANGELOG.md must have a
  matching ``## [X.Y.Z]`` heading in docs/src/changelog.md.
- Extra versions in the docs changelog are fine (e.g. docs-only 0.4.0).

Usage (from the repo root):

    python3 scripts/check_docs_changelog.py

Stdlib only. Exits 0 when complete, 1 listing the missing versions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def versions_in(text: str) -> set[str]:
    return set(VERSION_HEADING.findall(text))


def missing_versions(root: Path, docs: Path) -> list[str]:
    root_versions = versions_in(root.read_text(encoding="utf-8"))
    docs_versions = versions_in(docs.read_text(encoding="utf-8"))
    return sorted(root_versions - docs_versions, key=lambda v: tuple(int(p) for p in v.split(".")))


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    root_changelog = repo_root / "CHANGELOG.md"
    docs_changelog = repo_root / "docs" / "src" / "changelog.md"
    missing = missing_versions(root_changelog, docs_changelog)
    if missing:
        print(
            "docs changelog is incomplete: %d version(s) in CHANGELOG.md "
            "missing from docs/src/changelog.md: %s"
            % (len(missing), ", ".join(missing)),
            file=sys.stderr,
        )
        return 1
    docs_count = len(versions_in(docs_changelog.read_text(encoding="utf-8")))
    print(
        "docs changelog complete: all %d released version(s) present "
        "(%d entries in docs, incl. docs-only ones)" % (len(versions_in(root_changelog.read_text(encoding="utf-8"))), docs_count)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
