"""Regression tests for QA core-bundle fixes (bundle.py).

Covers:
- C2: ``write_concept`` refuses ids mapping to reserved ``index``/``log``
  (any casing) with ``ValueError`` — never silently overwrites them.
- C7: slug collisions get deterministic ``-2``, ``-3``, … suffixes; the
  original concept is untouched.
- C8: non-UTF-8 ``.md`` files raise catchable ``BundleError`` naming the file.
- H12: directories named ``*.md`` are skipped when walking the bundle.
- H15: over-long slugs are truncated to fit 255-byte filenames,
  deterministically.
- H17: FIFOs (non-regular files) are skipped — ``Bundle.load`` never blocks.
- L23: NFC normalization before slugify; case-insensitive reserved check.
"""

from __future__ import annotations

import os
import threading
import unicodedata

import pytest

from okfsmith.core.bundle import (
    Bundle,
    BundleError,
    _fit_filename_stem,
    concept_path_for,
    slugify,
)

# ---------------------------------------------------------------------------
# C2 — reserved ids refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reserved_id",
    [
        "index",
        "Index",
        "INDEX",
        "iNdEx",
        "log",
        "LOG",
        "Log",
        " Index ",  # slugifies to "index"
        "notes/index",
        "a/b/LOG",
        "sub/Index",
    ],
)
def test_write_concept_refuses_reserved_ids(tmp_path, reserved_id):
    bundle = Bundle(tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        bundle.write_concept(reserved_id, {"title": "x"}, "body\n")
    # The reserved files must never be created or clobbered.
    assert not (tmp_path / "index.md").exists()
    assert not (tmp_path / "log.md").exists()
    assert list(bundle.iter_concepts()) == []


def test_write_concept_reserved_error_is_clear(tmp_path):
    bundle = Bundle(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        bundle.write_concept("LOG", {}, "body\n")
    message = str(excinfo.value)
    assert "log.md" in message
    assert "reserved" in message


def test_write_concept_similar_names_are_allowed(tmp_path):
    bundle = Bundle(tmp_path)
    concept = bundle.write_concept("my-index", {}, "body\n")
    assert concept.id == "my-index"
    concept = bundle.write_concept("catalog", {}, "body\n")
    assert concept.id == "catalog"


# ---------------------------------------------------------------------------
# C7 — collision-safe writes
# ---------------------------------------------------------------------------


def test_write_concept_collision_appends_suffix(tmp_path):
    bundle = Bundle(tmp_path)
    first = bundle.write_concept("Hello, World!", {"title": "a"}, "FIRST BODY\n")
    second = bundle.write_concept("hello world", {"title": "b"}, "SECOND BODY\n")

    assert first.id == "hello-world"
    assert second.id == "hello-world-2"
    # Original untouched: same body, same file.
    assert bundle.get("hello-world").body == "FIRST BODY\n"
    assert (tmp_path / "hello-world.md").read_text(encoding="utf-8") == (
        first.path.read_text(encoding="utf-8")
    )
    assert "FIRST BODY" in (tmp_path / "hello-world.md").read_text(encoding="utf-8")
    assert "SECOND BODY" in (tmp_path / "hello-world-2.md").read_text(encoding="utf-8")


def test_write_concept_collision_increments_deterministically(tmp_path):
    bundle = Bundle(tmp_path)
    ids = [
        bundle.write_concept(title, {}, f"body {i}\n").id
        for i, title in enumerate(["Hello, World!", "hello world", "HELLO WORLD"])
    ]
    assert ids == ["hello-world", "hello-world-2", "hello-world-3"]
    # Deterministic across handles: a fresh Bundle over the same root
    # allocates the next free suffix the same way.
    assert Bundle.load(tmp_path).get("hello-world-3").body == "body 2\n"


def test_write_concept_same_id_updates_in_place(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept("Hello, World!", {"title": "a"}, "FIRST\n")
    updated = bundle.write_concept("hello-world", {"title": "a"}, "UPDATED\n")

    assert updated.id == "hello-world"
    assert bundle.get("hello-world").body == "UPDATED\n"
    assert [c.id for c in bundle.iter_concepts()] == ["hello-world"]
    assert not (tmp_path / "hello-world-2.md").exists()


def test_write_concept_collision_case_variant_gets_suffix(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept("hello-world", {}, "one\n")
    other = bundle.write_concept("Hello-World", {}, "two\n")
    assert other.id == "hello-world-2"
    assert bundle.get("hello-world").body == "one\n"


def test_write_concept_does_not_clobber_unregistered_file(tmp_path):
    # A file on disk unknown to this handle (e.g. written through another
    # Bundle) must not be overwritten either.
    (tmp_path / "taken.md").write_text("precious\n", encoding="utf-8")
    bundle = Bundle(tmp_path)  # fresh handle: nothing registered
    concept = bundle.write_concept("taken", {}, "new\n")
    assert concept.id == "taken-2"
    assert (tmp_path / "taken.md").read_text(encoding="utf-8") == "precious\n"


# ---------------------------------------------------------------------------
# C8 — BundleError on non-UTF-8 reads
# ---------------------------------------------------------------------------


def test_load_non_utf8_concept_raises_bundle_error(tmp_path):
    (tmp_path / "notes.md").write_bytes("binary \xff\xfe junk\n".encode("latin-1"))
    with pytest.raises(BundleError) as excinfo:
        Bundle.load(tmp_path)
    assert "notes.md" in str(excinfo.value)
    assert "UTF-8" in str(excinfo.value)


def test_load_non_utf8_index_raises_bundle_error(tmp_path):
    (tmp_path / "index.md").write_bytes(b"\xff\xfe not utf-8\n")
    with pytest.raises(BundleError) as excinfo:
        Bundle.load(tmp_path)
    assert "index.md" in str(excinfo.value)


def test_bundle_error_is_catchable_not_raw_decode_error(tmp_path):
    (tmp_path / "notes.md").write_bytes(b"\xff\xfe")
    try:
        Bundle.load(tmp_path)
    except BundleError as exc:  # noqa: BLE001 — must be catchable as Exception
        assert isinstance(exc, Exception)
        assert not isinstance(exc, UnicodeDecodeError)
    else:
        pytest.fail("BundleError not raised")


# ---------------------------------------------------------------------------
# H12 — directories named *.md are skipped
# ---------------------------------------------------------------------------


def test_load_skips_directory_named_md(tmp_path):
    (tmp_path / "tricky.md").mkdir()
    (tmp_path / "real.md").write_text("body\n", encoding="utf-8")
    bundle = Bundle.load(tmp_path)
    assert [c.id for c in bundle.iter_concepts()] == ["real"]


# ---------------------------------------------------------------------------
# H15 — deterministic truncation to 255-byte filenames
# ---------------------------------------------------------------------------


def test_write_concept_truncates_long_slug(tmp_path):
    bundle = Bundle(tmp_path)
    concept = bundle.write_concept("x" * 300, {"title": "long"}, "body\n")

    filename = concept.path.name
    assert len(filename.encode("utf-8")) <= 255
    assert filename.endswith(".md")
    # Deterministic: the same input maps to the same path every time.
    assert concept_path_for(tmp_path, "x" * 300) == concept.path
    assert concept_path_for(tmp_path, "x" * 300) == concept_path_for(tmp_path, "x" * 300)
    # Round-trips through load under the truncated id.
    assert Bundle.load(tmp_path).get(concept.id) is not None


def test_fit_filename_stem_drops_partial_multibyte_char(tmp_path):
    stem = "a" * 250 + "é"  # 250 ASCII bytes + 2-byte char = 252 bytes
    fitted = _fit_filename_stem(stem)
    assert len((fitted + ".md").encode("utf-8")) <= 255
    # Deterministic for the same input.
    assert _fit_filename_stem(stem) == fitted
    # Short stems are untouched.
    assert _fit_filename_stem("hello-world") == "hello-world"


def test_write_concept_long_slug_collision_stays_within_limit(tmp_path):
    bundle = Bundle(tmp_path)
    first = bundle.write_concept("y" * 300, {}, "one\n")
    second = bundle.write_concept("y" * 300 + "!", {}, "two\n")
    assert first.id != second.id
    for concept in (first, second):
        assert len(concept.path.name.encode("utf-8")) <= 255
    assert bundle.get(first.id).body == "one\n"


# ---------------------------------------------------------------------------
# H17 — FIFOs / non-regular files are skipped, never block
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no mkfifo on this platform")
def test_load_skips_fifo_without_blocking(tmp_path):
    (tmp_path / "real.md").write_text("body\n", encoding="utf-8")
    os.mkfifo(tmp_path / "pipe.md")

    results: list = []
    loader = threading.Thread(target=lambda: results.append(Bundle.load(tmp_path)))
    loader.start()
    loader.join(timeout=10)
    assert not loader.is_alive(), "Bundle.load blocked on a FIFO"
    assert results, "loader thread did not finish"
    assert [c.id for c in results[0].iter_concepts()] == ["real"]


# ---------------------------------------------------------------------------
# L23 — NFC normalization + case-insensitive reserved check
# ---------------------------------------------------------------------------


def test_slugify_nfc_normalizes():
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert nfc != nfd  # guard: the test inputs really differ
    assert slugify(nfc) == slugify(nfd) == "caf"


def test_write_concept_nfc_and_nfd_share_id(tmp_path):
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    first = Bundle(tmp_path / "a").write_concept(nfc, {}, "body\n")
    second = Bundle(tmp_path / "b").write_concept(nfd, {}, "body\n")
    assert first.id == second.id == "caf"


def test_load_skips_reserved_case_insensitive(tmp_path):
    (tmp_path / "Index.md").write_text("---\ntitle: sneaky\n---\nbody\n", encoding="utf-8")
    (tmp_path / "LOG.md").write_text("log body\n", encoding="utf-8")
    (tmp_path / "real.md").write_text("body\n", encoding="utf-8")
    bundle = Bundle.load(tmp_path)
    assert bundle.get("Index") is None
    assert bundle.get("index") is None
    assert bundle.get("LOG") is None
    assert bundle.get("log") is None
    assert [c.id for c in bundle.iter_concepts()] == ["real"]
