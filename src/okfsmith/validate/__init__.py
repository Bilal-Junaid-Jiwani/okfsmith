"""OKF v0.2 bundle validator.

``check()`` validates a bundle directory against the rule codes in
``.contract/spec_decisions.md`` §18:

- Errors **E001–E004** map 1:1 to §11's three hard conformance rules; a bundle
  is conformant iff ``errors`` is empty.
- Warnings **W001–W015** are advisory and never affect conformance.

Pure and deterministic: stdlib + pyyaml only, no network, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from okfsmith.core.bundle import Bundle


@dataclass(frozen=True)
class Finding:
    """One validation finding: rule code, bundle-relative file, message, spec ref."""

    code: str
    """Rule code, e.g. ``"E001"`` or ``"W004"`` (verbatim from the contract)."""

    file: str
    """Bundle-relative POSIX path of the offending file."""

    message: str
    """Human-readable, deterministic description of the finding."""

    spec_ref: str
    """Spec section the rule cites, e.g. ``"§11.1"``."""

    def as_dict(self) -> dict:
        """Serialize as ``{code, file, message, spec}`` (the EXPECTED.json schema)."""
        return {
            "code": self.code,
            "file": self.file,
            "message": self.message,
            "spec": self.spec_ref,
        }


@dataclass
class ValidationReport:
    """The result of validating one bundle."""

    errors: list[Finding] = field(default_factory=list)
    """Hard conformance failures (E001–E004). Non-empty ⇒ not conformant."""

    warnings: list[Finding] = field(default_factory=list)
    """Advisory findings (W001–W015). Never affect conformance."""

    is_conformant: bool = field(init=False, default=True)
    """True iff there are no errors (warnings never affect conformance)."""

    def __post_init__(self) -> None:
        self.is_conformant = not self.errors

    def summary(self) -> dict:
        """Compact dict summary of the report (handy for CLI JSON output)."""
        return {
            "conformant": self.is_conformant,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "error_codes": sorted({f.code for f in self.errors}),
            "warning_codes": sorted({f.code for f in self.warnings}),
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
        }


def check(bundle_path: str | Path) -> ValidationReport:
    """Validate the OKF bundle at *bundle_path* and return a :class:`ValidationReport`.

    Findings are deterministic: rule-code order, then bundle-relative file
    path, then position within the file.

    Raises:
        ValueError: if *bundle_path* exists and is not a directory.
    """
    from okfsmith.validate import rules as _rules

    root = Path(bundle_path)
    if root.exists() and not root.is_dir():
        raise ValueError(f"bundle_path must be a directory, got: {bundle_path}")
    bundle = Bundle.load(root)
    errors, warnings = _rules.run_checks(bundle.root)
    return ValidationReport(errors=errors, warnings=warnings)


__all__ = ["Finding", "ValidationReport", "check"]
