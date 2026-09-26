"""Smoke tests for the okfsmith core.

Proves: bundle write/read round-trip (frontmatter + body), unknown-key
preservation, trust-tier derivation, index.md generation (root vs subdir
conventions), and log.md append with newest-first ordering.
"""

import pytest

from okfsmith import __version__
from okfsmith.core import frontmatter, indexlog, spec
from okfsmith.core.bundle import Bundle


def _two_concepts(bundle: Bundle) -> Bundle:
    bundle.write_concept(
        "notes/Hello World",
        {
            "type": "note",
            "title": "Hello",
            "description": "A greeting",
            "custom_flag": True,  # unknown key — must survive the round trip
        },
        "# Hello\n\nBody text.\n",
    )
    bundle.write_concept("notes/Second", {"type": "note", "title": "Second"}, "Second body.\n")
    return bundle


def test_version():
    assert __version__ == "0.3.0"


def test_write_and_load_round_trip(tmp_path):
    _two_concepts(Bundle(tmp_path))
    reloaded = Bundle.load(tmp_path)

    concept = reloaded.get("notes/hello-world")
    assert concept is not None
    assert concept.frontmatter["type"] == "note"
    assert concept.frontmatter["title"] == "Hello"
    assert concept.frontmatter["custom_flag"] is True
    assert concept.body == "# Hello\n\nBody text.\n"

    ids = [c.id for c in reloaded.iter_concepts()]
    assert ids == ["notes/hello-world", "notes/second"]


def test_load_skips_reserved_files(tmp_path):
    bundle = _two_concepts(Bundle(tmp_path))
    indexlog.ensure_index(bundle, "")
    indexlog.append_log(bundle, "", "Creation", "test")
    reloaded = Bundle.load(tmp_path)
    assert reloaded.get("index") is None
    assert reloaded.get("log") is None
    assert reloaded.index_text is not None
    assert reloaded.log_text is not None


def test_frontmatter_round_trip_preserves_key_order():
    fm = {"type": "note", "z_last": 1, "a_first": 2, "nested": {"b": 1, "a": 2}}
    data, body = frontmatter.parse_frontmatter(frontmatter.serialize_frontmatter(fm, "body\n"))
    assert list(data) == ["type", "z_last", "a_first", "nested"]
    assert body == "body\n"


def test_frontmatter_never_rejects():
    data, body = frontmatter.parse_frontmatter("# no frontmatter here\n")
    assert data == {} and body == "# no frontmatter here\n"
    data, body = frontmatter.parse_frontmatter("---\n- just\n- a\n- list\n---\nbody\n")
    assert data == {} and body == "body\n"


def test_trust_tier():
    assert spec.trust_tier({}) == "unverified"
    assert spec.trust_tier({"verified": {"by": "process:nightly"}}) == "machine-confirmed"
    assert (
        spec.trust_tier({"verified": [{"by": "process:nightly"}, {"by": "human:ada"}]})
        == "human-reviewed"
    )
    assert spec.trust_tier({"verified": {"by": "human:ada", "at": "2026-01-01"}}) == "human-reviewed"
    assert spec.is_human_actor("human:ada") and not spec.is_human_actor("process:x")
    assert spec.actor_name("human:ada") == "ada"


def test_ensure_index_root_and_subdir(tmp_path):
    bundle = _two_concepts(Bundle(tmp_path))

    root_path = indexlog.ensure_index(bundle, "")
    data, body = frontmatter.parse_frontmatter(root_path.read_text(encoding="utf-8"))
    assert data == {"okf_version": "0.2"}  # root ONLY
    assert "* [Hello](notes/hello-world) - A greeting" in body
    assert "* [Second](notes/second)" in body

    sub_path = indexlog.ensure_index(bundle, "notes")
    data2, body2 = frontmatter.parse_frontmatter(sub_path.read_text(encoding="utf-8"))
    assert data2 == {}  # no frontmatter outside root
    assert "okf_version" not in body2
    assert "* [Hello](hello-world) - A greeting" in body2


def test_append_log_newest_first(tmp_path):
    bundle = Bundle(tmp_path)
    indexlog.append_log(bundle, "", "Creation", "bundle created")
    indexlog.append_log(bundle, "", "Update", "added notes")

    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert f"## {spec.today_iso()}" in text
    assert text.index("added notes") < text.index("bundle created")  # newest first

    with pytest.raises(ValueError):
        indexlog.append_log(bundle, "", "Bogus", "rejected kind")
