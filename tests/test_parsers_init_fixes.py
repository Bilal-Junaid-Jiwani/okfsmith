"""Regression tests for M27: per-file skip warning goes through logging.

Before the fix, ``parse_file`` emitted ``warnings.warn(..., RuntimeWarning)``
on every unparseable file. The warnings machinery renders the *caller's*
file:line onto stderr (e.g. ``.../src/okfsmith/cli/commands.py:653:``),
leaking internal repo paths and bypassing ``--quiet``. The skip notice now
goes through ``logging`` only, and ``parse_file(path, quiet=True)`` suppresses
it while still recording the error in ``meta["error"]``.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

from okfsmith.parsers import parse_file

LOGGER_NAME = "okfsmith.parsers"


def _bad_pdf(tmp_path: Path) -> Path:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf at all \x00\x01\x02")
    return bad


def test_skip_warning_goes_to_logging(tmp_path: Path, caplog) -> None:
    bad = _bad_pdf(tmp_path)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        doc = parse_file(bad)
    assert doc.pages == []
    assert "error" in doc.meta
    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    skipping = [r.getMessage() for r in records if "skipping" in r.getMessage()]
    assert skipping, f"expected a 'skipping' warning log, got: {[r.getMessage() for r in records]}"
    # No repo paths baked into the message: only the file name may appear.
    for message in skipping:
        assert bad.name in message
        assert str(bad) not in message
        assert "src/okfsmith" not in message


def test_no_runtime_warning_raised(tmp_path: Path) -> None:
    bad = _bad_pdf(tmp_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = parse_file(bad)
    assert doc.pages == []
    assert "error" in doc.meta
    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not runtime_warnings, [str(w.message) for w in runtime_warnings]


def test_quiet_mode_suppresses_skip_warning(tmp_path: Path, caplog) -> None:
    bad = _bad_pdf(tmp_path)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        doc = parse_file(bad, quiet=True)
    # Still skipped, just silent: the caller can report via meta["error"].
    assert doc.pages == []
    assert "error" in doc.meta
    skipping = [
        r for r in caplog.records
        if r.name == LOGGER_NAME and "skipping" in r.getMessage()
    ]
    assert not skipping, [r.getMessage() for r in skipping]


def test_quiet_mode_suppresses_missing_file_warning(tmp_path: Path, caplog) -> None:
    missing = tmp_path / "nope.pdf"
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        doc = parse_file(missing, quiet=True)
    assert doc.pages == []
    assert "error" in doc.meta
    assert not [r for r in caplog.records if r.name == LOGGER_NAME]


def test_non_quiet_still_warns_on_missing_file(tmp_path: Path, caplog) -> None:
    missing = tmp_path / "nope.pdf"
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        doc = parse_file(missing)
    assert doc.pages == []
    assert "error" in doc.meta
    assert any(
        "skipping" in r.getMessage() for r in caplog.records if r.name == LOGGER_NAME
    )
