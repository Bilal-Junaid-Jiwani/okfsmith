"""Tests for the okfsmith validate package (OKF v0.2 conformance checker).

Contract: every fixture in ``.contract/fixtures/`` carries an EXPECTED.json
with ``{fixture, description, errors[], warnings[], trust_tiers?}``; findings
are ``{code, file, message, spec}``. This suite asserts codes + files match
exactly (messages are informational), trust tiers derive per §5.3, and the two
example bundles are conformant (0 errors — warnings never affect conformance).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from okfsmith.core import spec
from okfsmith.core.bundle import Bundle
from okfsmith.validate import Finding, ValidationReport, check

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / ".contract" / "fixtures"
EXAMPLE_BUNDLES = sorted(
    p for p in (REPO_ROOT / "examples" / "bundles").iterdir() if p.is_dir()
)


def _fixture_names() -> list[str]:
    return sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())


def _expected(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name / "EXPECTED.json").read_text(encoding="utf-8"))


def _pairs(findings: list[Finding]) -> list[tuple[str, str]]:
    return [(f.code, f.file) for f in findings]


# ---------------------------------------------------------------------------
# Fixture conformance: every fixture must match its EXPECTED.json exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_findings_match_expected(name: str):
    expected = _expected(name)
    report = check(str(FIXTURES_DIR / name))

    assert _pairs(report.errors) == [
        (f["code"], f["file"]) for f in expected["errors"]
    ], f"errors mismatch in fixture {name}"
    assert _pairs(report.warnings) == [
        (f["code"], f["file"]) for f in expected["warnings"]
    ], f"warnings mismatch in fixture {name}"

    # Conformance derives from errors alone: warnings never fail a bundle.
    assert report.is_conformant == (not expected["errors"])

    # Findings serialize to the EXPECTED.json schema {code, file, message, spec}.
    for finding, raw in zip(
        report.errors + report.warnings, expected["errors"] + expected["warnings"]
    ):
        serialized = finding.as_dict()
        assert set(serialized) == {"code", "file", "message", "spec"}
        assert serialized["code"] == raw["code"]
        assert serialized["file"] == raw["file"]
        assert serialized["spec"] == raw["spec"]
        assert isinstance(serialized["message"], str) and serialized["message"]


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_trust_tiers(name: str):
    expected = _expected(name)
    if "trust_tiers" not in expected:
        pytest.skip("fixture declares no trust tiers")
    bundle = Bundle.load(str(FIXTURES_DIR / name))
    tiers = {c.id: spec.trust_tier(c.frontmatter) for c in bundle.iter_concepts()}
    assert tiers == expected["trust_tiers"]


# ---------------------------------------------------------------------------
# Example bundles: conformant (0 errors)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bundle_path", EXAMPLE_BUNDLES, ids=lambda p: p.name)
def test_example_bundle_is_conformant(bundle_path: Path):
    report = check(bundle_path)  # check() accepts a Path as well as a str
    assert report.errors == [], [
        f.as_dict() for f in report.errors
    ]
    assert report.is_conformant


# ---------------------------------------------------------------------------
# Public API semantics
# ---------------------------------------------------------------------------


def test_check_accepts_str_and_path():
    from_str = check(str(FIXTURES_DIR / "valid"))
    from_path = check(FIXTURES_DIR / "valid")
    assert from_str.summary() == from_path.summary()
    assert isinstance(from_path, ValidationReport)


def test_finding_fields():
    finding = Finding(code="E001", file="x.md", message="msg", spec_ref="§11.1")
    assert (finding.code, finding.file, finding.message, finding.spec_ref) == (
        "E001",
        "x.md",
        "msg",
        "§11.1",
    )


def test_warnings_never_affect_conformance():
    report = check(str(FIXTURES_DIR / "warn-dead-link"))
    assert report.warnings, "fixture should produce warnings"
    assert report.errors == []
    assert report.is_conformant is True


def test_errors_break_conformance():
    report = check(str(FIXTURES_DIR / "err-no-frontmatter"))
    assert report.errors
    assert report.is_conformant is False


def test_summary_shape():
    report = check(str(FIXTURES_DIR / "legacy-v01"))
    summary = report.summary()
    assert summary["conformant"] is True
    assert summary["error_count"] == 0
    assert summary["warning_count"] == 2
    assert summary["error_codes"] == []
    assert summary["warning_codes"] == ["W012"]
    assert len(summary["errors"]) == 0
    assert len(summary["warnings"]) == 2
    assert all(set(f) == {"code", "file", "message", "spec"} for f in summary["warnings"])


def test_deterministic_across_runs():
    first = check(str(FIXTURES_DIR / "valid")).summary()
    second = check(str(FIXTURES_DIR / "valid")).summary()
    assert first == second


def test_bare_verified_mapping_is_normalized_not_an_error():
    # trust-tiers/human.md uses the bare-mapping `verified` form (§5.2, §11):
    # consumers MUST normalize it; it is never an error and yields human-reviewed.
    report = check(str(FIXTURES_DIR / "trust-tiers"))
    assert report.errors == [] and report.warnings == []
    bundle = Bundle.load(str(FIXTURES_DIR / "trust-tiers"))
    concept = bundle.get("human")
    assert concept is not None
    assert isinstance(concept.frontmatter["verified"], dict)  # bare mapping on disk
    assert spec.trust_tier(concept.frontmatter) == "human-reviewed"


def test_legacy_v01_never_errors():
    report = check(str(FIXTURES_DIR / "legacy-v01"))
    assert report.errors == []
    assert report.is_conformant is True
    assert [f.code for f in report.warnings] == ["W012", "W012"]


def test_rule_code_vocabulary():
    """Exactly the 4 error codes and 15 warning codes from the contract."""
    report = check(str(FIXTURES_DIR / "err-bad-index"))
    assert {f.code for f in report.errors} <= {"E001", "E002", "E003", "E004"}
    codes = set()
    for name in _fixture_names():
        expected = _expected(name)
        codes.update(f["code"] for f in expected["errors"] + expected["warnings"])
    assert codes <= {f"E{i:03d}" for i in range(1, 5)} | {
        f"W{i:03d}" for i in range(1, 16)
    }
    # Every code is exercised by at least one fixture.
    assert {f"E{i:03d}" for i in range(1, 5)} <= codes
    assert {f"W{i:03d}" for i in range(1, 16)} <= codes
