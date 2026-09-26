"""Tests for the okfsmith-build skill pack.

- SKILL.md frontmatter is valid per the Agent Skills open spec.
- scripts/validate.py behaves on the contract fixtures:
  `.contract/fixtures/valid/` exits 0; `err-empty-type/` exits 1.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "okfsmith-build"
SKILL_MD = SKILL_DIR / "SKILL.md"
VALIDATE_PY = SKILL_DIR / "scripts" / "validate.py"
FIXTURES = ROOT / ".contract" / "fixtures"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with ---"
    end = text.index("\n---", 4)
    data = yaml.safe_load(text[4:end])
    assert isinstance(data, dict), "frontmatter must be a YAML mapping"
    return data


def _body_line_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    end = text.index("\n---", 4) + len("\n---")
    return text[end:].count("\n")


def test_skill_md_frontmatter_name_matches_dir():
    fm = _frontmatter(SKILL_MD)
    assert fm["name"] == "okfsmith-build" == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fm["name"])


def test_skill_md_frontmatter_required_fields():
    fm = _frontmatter(SKILL_MD)
    assert "name" in fm and "description" in fm
    desc = fm["description"]
    assert isinstance(desc, str)
    assert 1 <= len(desc) <= 1024, f"description is {len(desc)} chars"
    for kw in ("okf", "knowledge bundle", "convert docs to OKF"):
        assert kw in desc, f"trigger keyword missing: {kw!r}"


def test_skill_md_body_line_limit():
    assert _body_line_count(SKILL_MD) <= 500


def test_validate_script_exists_and_is_stdlib_only():
    assert VALIDATE_PY.is_file()
    src = VALIDATE_PY.read_text(encoding="utf-8")
    # stdlib-only: no third-party imports (yaml would be a red flag here)
    assert "import yaml" not in src


def _run_validate(fixture: str):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PY), str(FIXTURES / fixture)],
        capture_output=True,
        text=True,
        cwd=str(SKILL_DIR),
    )


def test_validate_valid_fixture_exit_zero():
    proc = _run_validate("valid")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["conformant"] is True
    assert report["errors"] == []


def test_validate_err_empty_type_exit_one():
    proc = _run_validate("err-empty-type")
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert report["conformant"] is False
    codes = [e["code"] for e in report["errors"]]
    assert codes == ["E002", "E002"]
    files = {e["file"] for e in report["errors"]}
    assert files == {"empty.md", "missing.md"}
    for e in report["errors"]:
        assert set(e) >= {"code", "file", "message", "spec"}


def test_validate_reports_engine_and_json_shape():
    proc = _run_validate("valid")
    report = json.loads(proc.stdout)
    assert report["engine"] in ("okfsmith.validate", "minimal-fallback")
    assert set(report) >= {"bundle", "engine", "conformant", "errors",
                           "warnings"}
