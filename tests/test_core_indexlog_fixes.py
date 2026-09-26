"""Regression tests for the QA fixes in ``okfsmith.core.indexlog``.

Covers: C1 (symlink escapes refused on write paths), M5 (log-forgery
hardening via newline collapsing), M6 (``](`` escaping in index link titles),
H2/M30 (atomic writes + best-effort fcntl locking for ``append_log``).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from okfsmith.core import indexlog
from okfsmith.core.bundle import Bundle


def _bundle_with_concept(
    root: Path, concept_id: str = "notes/hello", title: str = "Hello"
) -> Bundle:
    bundle = Bundle(root)
    bundle.write_concept(concept_id, {"title": title, "description": "d"}, "body\n")
    return bundle


class TestSymlinkConfinement:
    """C1: writes must never escape the bundle root through symlinks."""

    def test_ensure_index_refuses_symlinked_subdir(self, tmp_path):
        root = tmp_path / "bundle"
        outside = tmp_path / "outside"
        outside.mkdir()
        root.mkdir()
        (root / "linksub").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="bundle root"):
            indexlog.ensure_index(Bundle(root), "linksub")
        assert list(outside.iterdir()) == []  # nothing written outside

    def test_ensure_index_refuses_symlink_in_subdir_component(self, tmp_path):
        root = tmp_path / "bundle"
        outside = tmp_path / "outside"
        outside.mkdir()
        root.mkdir()
        (root / "a").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="bundle root"):
            indexlog.ensure_index(Bundle(root), "a/b")
        assert list(outside.iterdir()) == []

    def test_append_log_refuses_symlinked_subdir(self, tmp_path):
        root = tmp_path / "bundle"
        outside = tmp_path / "outside"
        outside.mkdir()
        root.mkdir()
        (root / "linksub").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="bundle root"):
            indexlog.append_log(Bundle(root), "linksub", "Update", "x")
        assert list(outside.iterdir()) == []

    def test_append_log_refuses_symlinked_log_escaping_root(self, tmp_path):
        root = tmp_path / "bundle"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        victim = outside / "victim.md"
        victim.write_text("precious\n", encoding="utf-8")
        (root / "log.md").symlink_to(victim)

        with pytest.raises(ValueError, match="symlink"):
            indexlog.append_log(Bundle(root), "", "Update", "hello")
        # The outside file is untouched: nothing appended through the link.
        assert victim.read_text(encoding="utf-8") == "precious\n"

    def test_append_log_refuses_symlinked_log_inside_root(self, tmp_path):
        # Strict parity with Bundle.load: any symlinked log.md is refused,
        # even one pointing inside the bundle.
        root = tmp_path / "bundle"
        root.mkdir()
        (root / "real-log.md").write_text("# Log\n", encoding="utf-8")
        (root / "log.md").symlink_to(root / "real-log.md")

        with pytest.raises(ValueError, match="symlink"):
            indexlog.append_log(Bundle(root), "", "Update", "hello")

    def test_ensure_index_refuses_symlinked_index_md(self, tmp_path):
        root = tmp_path / "bundle"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "index.md").write_text("precious\n", encoding="utf-8")
        (root / "index.md").symlink_to(outside / "index.md")

        with pytest.raises(ValueError, match="symlink"):
            indexlog.ensure_index(_bundle_with_concept(root), "")
        assert (outside / "index.md").read_text(encoding="utf-8") == "precious\n"

    def test_symlinked_subdir_within_root_is_allowed(self, tmp_path):
        # A symlinked subdir whose target stays inside the root is harmless.
        root = tmp_path / "bundle"
        root.mkdir()
        (root / "real").mkdir()
        (root / "alias").symlink_to(root / "real", target_is_directory=True)
        bundle = _bundle_with_concept(root)

        path = indexlog.ensure_index(bundle, "alias")
        assert os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)

    def test_legit_writes_still_work(self, tmp_path):
        root = tmp_path / "bundle"
        root.mkdir()
        bundle = _bundle_with_concept(root)

        index_path = indexlog.ensure_index(bundle, "")
        assert index_path == root / "index.md"
        assert "* [Hello](notes/hello) - d" in index_path.read_text(encoding="utf-8")

        log_path = indexlog.append_log(bundle, "", "Creation", "hello")
        assert log_path == root / "log.md"
        assert "hello" in log_path.read_text(encoding="utf-8")

        sub_index = indexlog.ensure_index(bundle, "notes")
        assert sub_index == root / "notes" / "index.md"
        assert sub_index.is_file()
        sub_log = indexlog.append_log(bundle, "notes", "Update", "sub hello")
        assert sub_log == root / "notes" / "log.md"
        assert "sub hello" in sub_log.read_text(encoding="utf-8")


class TestLogForgeryHardening:
    """M5: multi-line messages must collapse to a single log line."""

    def test_append_log_collapses_newlines(self, tmp_path):
        bundle = Bundle(tmp_path)
        indexlog.append_log(bundle, "", "Creation", "bundle created")
        forged = "legit\n## 2020-01-01\n\n* **Creation**: forged backdated entry"
        indexlog.append_log(bundle, "", "Update", forged)

        text = (tmp_path / "log.md").read_text(encoding="utf-8")
        # The forged date must not become a markdown heading: it may only
        # survive as inert inline text inside the single collapsed entry.
        assert not any(
            line.startswith("## 2020-01-01") for line in text.splitlines()
        ), "forged text became a log heading"
        assert "forged backdated entry" in text  # content preserved, one line
        forged_lines = [line for line in text.splitlines() if "forged" in line]
        assert len(forged_lines) == 1
        assert forged_lines[0].startswith("* **Update**: legit ## 2020-01-01")

    def test_append_log_collapses_tabs_and_runs(self, tmp_path):
        bundle = Bundle(tmp_path)
        indexlog.append_log(bundle, "", "Update", "a\tb  c\r\nd")
        text = (tmp_path / "log.md").read_text(encoding="utf-8")
        assert "* **Update**: a b c d" in text


class TestIndexTitleEscaping:
    """M6: crafted titles must not break markdown link syntax in index.md."""

    def test_bracket_paren_in_title_renders_safely(self, tmp_path):
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "tricky", {"title": "x](http://evil.example/phish)"}, "body\n"
        )
        body = indexlog.ensure_index(bundle, "").read_text(encoding="utf-8")

        # The phishing URL stays literal link text; the real target is the id.
        assert "* [x\\](http://evil.example/phish)](tricky)" in body
        # ...and the unescaped, link-hijacking form is absent: the evil URL
        # never appears as a link target.
        assert "[x](http://evil.example/phish)" not in body

    def test_plain_titles_unchanged(self, tmp_path):
        bundle = _bundle_with_concept(tmp_path)
        body = indexlog.ensure_index(bundle, "").read_text(encoding="utf-8")
        assert "* [Hello](notes/hello) - d" in body


class TestAtomicWrites:
    """H2/M30: index/log writes are atomic; concurrent appends keep entries."""

    def test_append_log_failure_leaves_original_intact(self, tmp_path):
        bundle = Bundle(tmp_path)
        indexlog.append_log(bundle, "", "Creation", "first")
        before = (tmp_path / "log.md").read_text(encoding="utf-8")

        real_replace = os.replace

        def boom(src, dst):
            raise RuntimeError("simulated crash during rename")

        os.replace = boom  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="simulated crash"):
                indexlog.append_log(bundle, "", "Update", "second")
        finally:
            os.replace = real_replace

        # No partial file: original intact, temp file cleaned up.
        assert (tmp_path / "log.md").read_text(encoding="utf-8") == before
        assert list(tmp_path.glob("*.tmp")) == []

    def test_ensure_index_failure_leaves_original_intact(self, tmp_path):
        bundle = _bundle_with_concept(tmp_path)
        indexlog.ensure_index(bundle, "")
        before = (tmp_path / "index.md").read_text(encoding="utf-8")

        real_replace = os.replace

        def boom(src, dst):
            raise RuntimeError("simulated crash during rename")

        os.replace = boom  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="simulated crash"):
                indexlog.ensure_index(bundle, "")
        finally:
            os.replace = real_replace

        assert (tmp_path / "index.md").read_text(encoding="utf-8") == before
        assert list(tmp_path.glob("*.tmp")) == []

    def test_concurrent_append_log_keeps_all_entries(self, tmp_path):
        if indexlog.fcntl is None:
            pytest.skip("fcntl unavailable; locking is best-effort")
        bundle = Bundle(tmp_path)
        n_threads, per_thread = 8, 10
        errors: list[BaseException] = []

        def worker(t: int) -> None:
            try:
                for i in range(per_thread):
                    indexlog.append_log(bundle, "", "Update", f"t{t}-i{i}")
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        text = (tmp_path / "log.md").read_text(encoding="utf-8")
        for t in range(n_threads):
            for i in range(per_thread):
                assert f"t{t}-i{i}" in text
