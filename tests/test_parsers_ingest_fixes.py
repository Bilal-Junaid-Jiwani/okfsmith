"""Regression tests for QA fixes in ``parsers/ingest_no_llm.py`` + ``parsers/dedup.py``.

- C3: same-stem files in different directories must never silently overwrite
  each other's concepts; collisions get ``-2``, ``-3``, … suffixes.
- M8: surrogate/non-UTF-8 filenames must not break ingest: ingest completes,
  the log is written, and the dedup manifest stays valid UTF-8 JSON.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from okfsmith.core.bundle import Bundle
from okfsmith.parsers import dedup, parse_file
from okfsmith.parsers.ingest_no_llm import ingest_no_llm

FILLER = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 40


def _write_source(root: Path, *parts: str, marker: str) -> Path:
    """Write a >1000-char markdown source with a greppable *marker*."""
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Findings\n\n{(marker + chr(10)) * 40}\n\n{FILLER}\n", encoding="utf-8")
    return path


def _bodies(bundle: Bundle, ids: list[str]) -> list[str]:
    return [bundle.get(i).body for i in ids]


# ------------------------------------------------------------------ C3 ---


def test_c3_same_stem_different_dirs_no_overwrite(tmp_path: Path):
    src = tmp_path / "d"
    a = _write_source(src, "A", "report.md", marker="ALPHA")
    b = _write_source(src, "B", "report.md", marker="BETA")
    bundle = Bundle(tmp_path / "kb")

    ids_a = ingest_no_llm(bundle, parse_file(a), str(a))
    ids_b = ingest_no_llm(bundle, parse_file(b), str(b))

    assert len(ids_a) == 1 and len(ids_b) == 1
    assert ids_a[0] != ids_b[0]  # two distinct concepts, not one overwrite
    bodies = _bodies(bundle, ids_a + ids_b)
    assert any("ALPHA" in body for body in bodies), "first file's content lost"
    assert any("BETA" in body for body in bodies), "second file's content lost"


def test_c3_collision_suffixes_numbered(tmp_path: Path):
    src = tmp_path / "d"
    paths = [_write_source(src, name, "report.md", marker=f"M{i}") for i, name in enumerate("ABC")]
    bundle = Bundle(tmp_path / "kb")

    ids = [ingest_no_llm(bundle, parse_file(p), str(p))[0] for p in paths]

    assert ids == ["report/findings", "report/findings-2", "report/findings-3"]
    bodies = _bodies(bundle, ids)
    for i in range(3):
        assert f"M{i}" in bodies[i]


def test_c3_reingest_changed_file_does_not_overwrite(tmp_path: Path):
    src = tmp_path / "d"
    first = _write_source(src, "A", "report.md", marker="ALPHA")
    bundle = Bundle(tmp_path / "kb")
    ids_first = ingest_no_llm(bundle, parse_file(first), str(first))

    # Same path, modified content (the "re-ingest" case): must not clobber.
    second = _write_source(src, "A", "report.md", marker="BETA")
    ids_second = ingest_no_llm(bundle, parse_file(second), str(second))

    assert ids_first != ids_second
    assert "ALPHA" in bundle.get(ids_first[0]).body  # old concept untouched
    assert "BETA" in bundle.get(ids_second[0]).body
    assert ids_second[0] == "report/findings-2"


def test_c3_intra_file_duplicate_titles_still_deduped(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text(f"# Dup\n\n{FILLER}\n\n# Dup\n\n{FILLER}\n", encoding="utf-8")
    bundle = Bundle(tmp_path / "kb")

    ids = ingest_no_llm(bundle, parse_file(path), str(path))

    assert ids == ["notes/dup", "notes/dup-2"]


# ------------------------------------------------------------------ M8 ---


def _write_surrogate_source(tmp_path: Path) -> tuple[Path, str]:
    """Create a file whose name holds undecodable bytes; return (Path, source_id).

    The returned *source_id* is the surrogate-escaped str form a CLI would pass.
    """
    raw_name = b"weird_\xff\xfe.md"
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    with open(os.path.join(os.fsencode(str(src_dir)), raw_name), "wb") as fh:
        fh.write(f"# Findings\n\n{FILLER}\n".encode())
    source_id = os.fsdecode(os.path.join(os.fsencode(str(src_dir)), raw_name))
    assert source_id != raw_name.decode("utf-8", "replace")  # really has surrogates
    return Path(source_id), source_id


def test_m8_surrogate_filename_ingest_completes_and_logs(tmp_path: Path):
    path, source_id = _write_surrogate_source(tmp_path)
    bundle = Bundle(tmp_path / "kb")

    ids = ingest_no_llm(bundle, parse_file(path), source_id)  # must not raise

    assert len(ids) == 1
    concept = bundle.get(ids[0])
    assert concept.frontmatter["title"] == "Findings"
    assert "Lorem ipsum" in concept.body
    # log.md was written and is valid UTF-8 (append_log never raised)
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "draft concept(s)" in log_text
    # the surrogate filename was sanitized, not embedded raw
    assert "udcff" in log_text


def test_m8_record_ingested_surrogate_path(tmp_path: Path):
    bundle = Bundle(tmp_path / "kb")
    weird = os.fsdecode(b"/tmp/okfsmith-qa/weird_\xff\xfe.md")

    dedup.record_ingested(bundle, "abc123", weird)  # must not raise

    manifest = json.loads(
        (bundle.root / ".okfsmith" / "manifest.json").read_text(encoding="utf-8")
    )
    expected = weird.encode("utf-8", errors="backslashreplace").decode("utf-8")
    assert manifest["sources"]["abc123"]["path"] == expected
    assert dedup.already_ingested(bundle, "abc123")
