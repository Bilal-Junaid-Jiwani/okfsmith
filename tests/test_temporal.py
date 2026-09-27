"""Tests for the P2 temporal model: validity windows, supersession, as-of queries.

Covers ``okfsmith.core.temporal`` (field parsing, supersession chains,
partitioning), the W016–W020 validator advisories, temporal ranking in
``okfsmith.search``, the ``search``/``list``/``read`` CLI surface
(``--as-of``, ``--include-superseded``, Valid column, read badge, JSON
shapes), tier-precedence rules, and sync preserving temporal fields on
update. Keyless throughout: no LLM involved.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core import temporal as T
from okfsmith.core.bundle import Bundle
from okfsmith.search import search_bundle, search_bundle_detailed
from okfsmith.validate import check

runner = CliRunner()
WIDE = {"COLUMNS": "200"}
UTC = timezone.utc


def _dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def _bundle(tmp_path: Path, concepts: dict[str, dict]) -> Bundle:
    """Build an on-disk bundle from {concept_id: frontmatter} (+ trivial bodies)."""
    bundle = Bundle(tmp_path / "kb")
    for cid, fm in concepts.items():
        bundle.write_concept(cid, dict(fm), f"Body of {cid}.")
    (bundle.root / "index.md").write_text("# Index\n", encoding="utf-8")
    return bundle


# ---------------------------------------------------------------------------
# Field parsing
# ---------------------------------------------------------------------------


class TestParseTemporal:
    def test_date_string(self):
        assert T.parse_temporal("2026-09-28") == _dt(2026, 9, 28)

    def test_datetime_string_z(self):
        assert T.parse_temporal("2026-09-28T10:30:00Z") == _dt(2026, 9, 28, 10, 30)

    def test_datetime_string_lowercase_z(self):
        assert T.parse_temporal("2026-09-28t10:30:00z") == _dt(2026, 9, 28, 10, 30)

    def test_datetime_with_offset_kept(self):
        parsed = T.parse_temporal("2026-09-28T10:30:00+05:00")
        assert parsed is not None
        assert parsed.utcoffset() == timedelta(hours=5)
        # Comparisons against aware UTC still work.
        assert parsed > _dt(2026, 9, 28, 5, 29)

    def test_date_object(self):
        assert T.parse_temporal(date(2025, 1, 2)) == _dt(2025, 1, 2)

    def test_datetime_object_naive_assumed_utc(self):
        assert T.parse_temporal(datetime(2025, 1, 2, 3, 4)) == _dt(2025, 1, 2, 3, 4)

    def test_datetime_object_aware_kept(self):
        aware = datetime(2025, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=-8)))
        assert T.parse_temporal(aware) == aware

    def test_whitespace_tolerated(self):
        assert T.parse_temporal("  2026-09-28  ") == _dt(2026, 9, 28)

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-date",
            "2026-13-99",
            "2026-02-30",
            "99999-01-01",
            "",
            "   ",
            123,
            4.5,
            True,
            False,
            None,
            ["2026-01-01"],
            {"d": "2026-01-01"},
            "x" * 101,
        ],
    )
    def test_garbage_returns_none_never_raises(self, bad):
        # The C9 class of bug: impossible YAML dates must never crash.
        assert T.parse_temporal(bad) is None


class TestNormalizeSupersedes:
    def test_string(self):
        assert T.normalize_supersedes("a/b") == ["a/b"]

    def test_list(self):
        assert T.normalize_supersedes(["a", " b ", "", 5, None]) == ["a", "b"]

    def test_tuple(self):
        assert T.normalize_supersedes(("a", "b")) == ["a", "b"]

    @pytest.mark.parametrize("bad", [None, True, 42, 4.5, {"a": 1}, ["", "  "]])
    def test_wrong_shapes_give_empty(self, bad):
        assert T.normalize_supersedes(bad) == []

    def test_list_length_capped(self):
        assert len(T.normalize_supersedes([f"id-{i}" for i in range(500)])) == (
            T.MAX_SUPERSEDES_ENTRIES
        )


# ---------------------------------------------------------------------------
# Supersession chains
# ---------------------------------------------------------------------------


def _chain_index():
    return T.SupersessionIndex(
        [
            ("a", {}),
            ("b", {"supersedes": "a"}),
            ("c", {"supersedes": "b", "valid_from": "2026-01-01"}),
        ]
    )


class TestSupersessionChains:
    def test_three_deep_chain_resolves_to_head(self):
        idx = _chain_index()
        assert idx.resolve_head("a", _dt(2026, 6, 1)) == "c"
        assert idx.resolve_head("b", _dt(2026, 6, 1)) == "c"
        assert idx.resolve_head("c", _dt(2026, 6, 1)) == "c"

    def test_as_of_before_head_validity_falls_back(self):
        idx = _chain_index()
        # c's window starts 2026-01-01: at 2025-06-01 the head valid then is b.
        assert idx.resolve_head("a", _dt(2025, 6, 1)) == "b"

    def test_boundary_dates_are_inclusive(self):
        idx = T.SupersessionIndex(
            [("a", {"valid_from": "2026-01-01", "valid_until": "2026-12-31"})]
        )
        assert idx.window_valid("a", _dt(2026, 1, 1))
        assert idx.window_valid("a", _dt(2026, 12, 31))
        assert not idx.window_valid("a", _dt(2025, 12, 31, 23, 59))
        assert not idx.window_valid("a", _dt(2027, 1, 1))

    def test_dangling_target_ignored(self):
        idx = T.SupersessionIndex([("a", {"supersedes": "ghost"})])
        assert idx.resolve_head("a", _dt(2026, 1, 1)) == "a"
        assert idx.superseded_by("a", _dt(2026, 1, 1)) is None

    def test_unknown_id_resolves_to_itself(self):
        assert _chain_index().resolve_head("nope", _dt(2026, 1, 1)) == "nope"

    def test_cycle_does_not_hang_and_resolves(self):
        idx = T.SupersessionIndex([("x", {"supersedes": "y"}), ("y", {"supersedes": "x"})])
        assert idx.resolve_head("x", _dt(2026, 1, 1)) in ("x", "y")

    def test_self_supersession_is_a_cycle(self):
        idx = T.SupersessionIndex([("s", {"supersedes": "s"})])
        assert idx.find_cycles() == [("s",)]

    def test_find_cycles_canonical(self):
        idx = T.SupersessionIndex(
            [
                ("b", {"supersedes": "a"}),
                ("a", {"supersedes": "b"}),
                ("lonely", {}),
            ]
        )
        assert idx.find_cycles() == [("a", "b")]

    def test_diamond_resolves_to_furthest(self):
        idx = T.SupersessionIndex(
            [
                ("a", {}),
                ("b", {"supersedes": "a"}),
                ("c", {"supersedes": "a"}),
                ("d", {"supersedes": ["b", "c"]}),
            ]
        )
        assert idx.resolve_head("a", _dt(2026, 1, 1)) == "d"

    def test_status_precedence_window_over_supersession(self):
        # a is expired AND superseded by valid b: window wins the mark.
        idx = T.SupersessionIndex(
            [
                ("a", {"valid_until": "2025-01-01", "supersedes": []}),
                ("b", {"supersedes": "a"}),
            ]
        )
        from okfsmith.core.bundle import Concept

        concept = Concept(
            id="a",
            path=Path("/tmp/a.md"),
            frontmatter={"valid_until": "2025-01-01"},
            body="",
        )
        status = idx.status(concept, _dt(2026, 1, 1))
        assert status.name == "expired"
        assert not status.current


# ---------------------------------------------------------------------------
# Validator advisories W016–W020
# ---------------------------------------------------------------------------


def _codes(report, code):
    return [f for f in report.warnings if f.code == code]


class TestValidatorTemporal:
    def test_w016_malformed_date_fields(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {
                    "type": "Note",
                    "title": "A",
                    "valid_from": "not-a-date",
                    "last_verified": "yesterday-ish",
                },
            },
        )
        report = check(bundle.root)
        w016 = _codes(report, "W016")
        assert len(w016) == 2
        assert any("valid_from" in f.message for f in w016)
        assert any("last_verified" in f.message for f in w016)
        assert report.is_conformant  # advisories never affect conformance

    def test_w016_impossible_yaml_date_never_crashes(self, tmp_path):
        # The C9 case, through the real validator path: an unquoted
        # impossible timestamp in a temporal field.
        bdir = tmp_path / "kb"
        bdir.mkdir()
        (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
        (bdir / "bad.md").write_text(
            "---\ntype: Note\ntitle: Bad\nvalid_from: 2026-13-99\n---\nbody\n",
            encoding="utf-8",
        )
        report = check(bdir)  # must not raise
        assert report.is_conformant

    def test_w016_malformed_supersedes_shapes(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {"type": "Note", "title": "A", "supersedes": {"weird": 1}},
                "b": {
                    "type": "Note",
                    "title": "B",
                    "supersedes": ["a", 42, "  "],
                },
                "c": {
                    "type": "Note",
                    "title": "C",
                    "supersedes": [f"id-{i}" for i in range(150)],
                },
            },
        )
        report = check(bundle.root)
        by_file = {}
        for f in _codes(report, "W016"):
            by_file.setdefault(f.file, []).append(f.message)
        assert any("expected a concept id or a list" in m for m in by_file["a.md"])
        assert any("malformed `supersedes` entries" in m for m in by_file["b.md"])
        assert any("only the first 100 are used" in m for m in by_file["c.md"])

    def test_w017_window_inverted(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {
                    "type": "Note",
                    "title": "A",
                    "valid_from": "2026-06-01",
                    "valid_until": "2026-01-01",
                },
            },
        )
        report = check(bundle.root)
        w017 = _codes(report, "W017")
        assert len(w017) == 1
        assert "never window-valid" in w017[0].message

    def test_w018_dangling_supersedes(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {"type": "Note", "title": "A"},
                "b": {"type": "Note", "title": "B", "supersedes": ["a", "ghost"]},
            },
        )
        report = check(bundle.root)
        w018 = _codes(report, "W018")
        assert len(w018) == 1
        assert "'ghost'" in w018[0].message
        assert w018[0].file == "b.md"

    def test_w019_cycle(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "c": {"type": "Note", "title": "C", "supersedes": "d"},
                "d": {"type": "Note", "title": "D", "supersedes": "c"},
            },
        )
        report = check(bundle.root)
        w019 = _codes(report, "W019")
        assert len(w019) == 1
        assert "c supersedes d supersedes c" in w019[0].message

    def test_w020_last_verified_in_future(self, tmp_path):
        future = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
        bundle = _bundle(
            tmp_path,
            {"a": {"type": "Note", "title": "A", "last_verified": future}},
        )
        report = check(bundle.root)
        w020 = _codes(report, "W020")
        assert len(w020) == 1
        assert "in the future" in w020[0].message

    def test_clean_temporal_fields_no_warnings(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {
                    "type": "Note",
                    "title": "A",
                    "valid_from": "2025-01-01",
                    "valid_until": "2027-01-01",
                    "last_verified": "2026-01-15",
                },
                "b": {"type": "Note", "title": "B", "supersedes": "a"},
            },
        )
        report = check(bundle.root)
        temporal = [
            f for f in report.warnings if f.code in ("W016", "W017", "W018", "W019", "W020")
        ]
        assert temporal == []

    def test_section_11_hard_rules_untouched(self, tmp_path):
        bdir = tmp_path / "kb"
        bdir.mkdir()
        (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
        (bdir / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
        report = check(bdir)
        assert not report.is_conformant
        assert [e.code for e in report.errors] == ["E001"]


# ---------------------------------------------------------------------------
# Conflict-aware retrieval (search engine)
# ---------------------------------------------------------------------------


def _search_bundle_fixture(tmp_path: Path) -> Bundle:
    return _bundle(
        tmp_path,
        {
            "policy/refunds": {
                "type": "Policy",
                "title": "Refund policy",
                "description": "Refunds are available for all purchases.",
                "valid_until": "2025-06-30",
            },
            "policy/refunds-v2": {
                "type": "Policy",
                "title": "Refund policy v2",
                "description": "Refunds are available for all purchases.",
                "supersedes": "policy/refunds",
            },
            "guide/shipping": {
                "type": "Guide",
                "title": "Shipping guide",
                "description": "Refunds are never about shipping.",
            },
        },
    )


class TestConflictAwareRetrieval:
    def test_current_ranks_before_window_demoted(self, tmp_path):
        bundle = _search_bundle_fixture(tmp_path)
        hits = search_bundle(bundle, "refunds", limit=10)
        ids = [c.id for _, c in hits]
        # v2 (current) first; v1 (expired window) demoted but present.
        assert ids[0] == "policy/refunds-v2"
        assert "policy/refunds" in ids

    def test_superseded_excluded_by_default_not_deleted(self, tmp_path):
        bdir = tmp_path / "kb"
        bundle = Bundle(bdir)
        bundle.write_concept(
            "api/limits",
            {"type": "Reference", "title": "API rate limits"},
            "Rate limits are 100 requests per minute.",
        )
        bundle.write_concept(
            "api/limits-v2",
            {"type": "Reference", "title": "API rate limits v2", "supersedes": "api/limits"},
            "Rate limits are 1000 requests per minute.",
        )
        hits = search_bundle(bundle, "rate limits")
        assert [c.id for _, c in hits] == ["api/limits-v2"]
        # Demoted, NOT deleted: still on disk and in the bundle.
        assert (bdir / "api" / "limits.md").exists()
        assert bundle.get("api/limits") is not None

    def test_include_superseded_shows_them_last(self, tmp_path):
        bdir = tmp_path / "kb"
        bundle = Bundle(bdir)
        bundle.write_concept(
            "api/limits",
            {"type": "Reference", "title": "API rate limits"},
            "Rate limits are 100 requests per minute.",
        )
        bundle.write_concept(
            "api/limits-v2",
            {"type": "Reference", "title": "API rate limits v2", "supersedes": "api/limits"},
            "Rate limits are 1000 requests per minute.",
        )
        hits = search_bundle(bundle, "rate limits", include_superseded=True)
        assert [c.id for _, c in hits] == ["api/limits-v2", "api/limits"]

    def test_detailed_reports_hidden_count(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "a": {"type": "Note", "title": "Widgets", "description": "widgets everywhere"},
                "b": {
                    "type": "Note",
                    "title": "Widgets v2",
                    "description": "widgets everywhere",
                    "supersedes": "a",
                },
            },
        )
        result = search_bundle_detailed(bundle, "widgets")
        assert result.superseded_hidden == 1
        assert [c.id for _, c in result.hits] == ["b"]
        result2 = search_bundle_detailed(bundle, "widgets", include_superseded=True)
        assert result2.superseded_hidden == 0
        assert [c.id for _, c in result2.hits] == ["b", "a"]

    def test_as_of_past_resolves_chain_head_then_valid(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "plan": {
                    "type": "Note",
                    "title": "Roadmap plan",
                    "description": "roadmap planning notes",
                },
                "plan-v2": {
                    "type": "Note",
                    "title": "Roadmap plan v2",
                    "description": "roadmap planning notes",
                    "supersedes": "plan",
                    "valid_from": "2026-01-01",
                },
            },
        )
        # Before v2's window: v2 is demoted (not yet valid), v1 is the head.
        hits = search_bundle(bundle, "roadmap", as_of=_dt(2025, 6, 1))
        assert [c.id for _, c in hits][0] == "plan"
        # After: v2 is the head, v1 is superseded (excluded by default).
        hits = search_bundle(bundle, "roadmap", as_of=_dt(2026, 6, 1))
        assert [c.id for _, c in hits] == ["plan-v2"]

    def test_as_of_boundary_inclusive(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "promo": {
                    "type": "Note",
                    "title": "Promo",
                    "description": "promo details here",
                    "valid_from": "2026-03-01",
                    "valid_until": "2026-03-31",
                },
            },
        )
        # Date-only bounds are calendar-day inclusive: a valid_until of
        # 2026-03-31 covers the whole day, not midnight at its start.
        assert [c.id for _, c in search_bundle(bundle, "promo", as_of=_dt(2026, 3, 1))] == ["promo"]
        assert [c.id for _, c in search_bundle(bundle, "promo", as_of=_dt(2026, 3, 31))] == [
            "promo"
        ]
        midday = datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)
        assert [c.id for _, c in search_bundle(bundle, "promo", as_of=midday)] == ["promo"]
        assert [c.id for _, c in search_bundle(bundle, "promo", as_of=_dt(2026, 4, 1))] == ["promo"]

    def test_date_only_valid_until_covers_whole_day_in_status(self):
        idx = T.SupersessionIndex([("a", {"valid_until": "2026-03-31"})])
        assert idx.window_valid("a", datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc))
        assert not idx.window_valid("a", datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc))

    def test_datetime_valid_until_keeps_exact_instant(self):
        idx = T.SupersessionIndex([("a", {"valid_until": "2026-03-31T12:00:00Z"})])
        assert idx.window_valid("a", datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc))
        assert not idx.window_valid("a", datetime(2026, 3, 31, 12, 0, 1, tzinfo=timezone.utc))

    def test_naive_as_of_read_as_utc(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "promo": {
                    "type": "Note",
                    "title": "Promo",
                    "description": "promo details here",
                    "valid_until": "2026-03-31",
                },
            },
        )
        # Naive as_of must not raise TypeError in aware/naive comparisons.
        hits = search_bundle(bundle, "promo", as_of=datetime(2026, 3, 15))
        assert [c.id for _, c in hits] == ["promo"]

    def test_future_window_concept_demoted_not_hidden(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                "future": {
                    "type": "Note",
                    "title": "Future thing",
                    "description": "upcoming feature details",
                    "valid_from": "2027-01-01",
                },
            },
        )
        hits = search_bundle(bundle, "upcoming")
        # Demoted (ranked after current) but still returned.
        assert [c.id for _, c in hits] == ["future"]
        result = search_bundle_detailed(bundle, "upcoming")
        assert result.superseded_hidden == 0

    def test_limit_applies_after_temporal_exclusion(self, tmp_path):
        bundle = _bundle(
            tmp_path,
            {
                f"c{i}": {
                    "type": "Note",
                    "title": f"Widget {i}",
                    "description": "widgets everywhere",
                }
                for i in range(5)
            },
        )
        hits = search_bundle(bundle, "widgets", limit=2)
        assert len(hits) == 2


class TestTierPrecedence:
    def _tied_bundle(self, tmp_path: Path) -> Bundle:
        # Identical text => identical BM25 scores; tier/recency decide.
        return _bundle(
            tmp_path,
            {
                "trusted": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                    "verified": [{"by": "human:alice", "at": "2020-01-01T00:00:00Z"}],
                    "last_verified": "2020-06-01",
                },
                "fresh": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                    "last_verified": "2026-09-01",
                },
            },
        )

    def test_human_reviewed_beats_unverified_despite_staleness(self, tmp_path):
        # Recency alone never demotes a human-reviewed concept below an
        # unverified one: tier outranks recency in the tiebreak.
        bundle = self._tied_bundle(tmp_path)
        hits = search_bundle(bundle, "identical")
        assert [c.id for _, c in hits] == ["trusted", "fresh"]

    def test_window_violation_outranks_tier(self, tmp_path):
        # Validity window > trust tier: an expired human-reviewed concept is
        # demoted below a current unverified one.
        bundle = _bundle(
            tmp_path,
            {
                "trusted": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                    "verified": [{"by": "human:alice", "at": "2020-01-01T00:00:00Z"}],
                    "valid_until": "2021-01-01",
                },
                "fresh": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                },
            },
        )
        hits = search_bundle(bundle, "identical")
        assert [c.id for _, c in hits] == ["fresh", "trusted"]

    def test_supersession_outranks_tier(self, tmp_path):
        # Supersession > trust tier: a superseded human-reviewed concept is
        # hidden by default even though the head is unverified.
        bundle = _bundle(
            tmp_path,
            {
                "old": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                    "verified": [{"by": "human:alice", "at": "2020-01-01T00:00:00Z"}],
                },
                "new": {
                    "type": "Note",
                    "title": "Identical notes",
                    "description": "identical body words here",
                    "supersedes": "old",
                },
            },
        )
        hits = search_bundle(bundle, "identical")
        assert [c.id for _, c in hits] == ["new"]


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _cli_bundle(tmp_path: Path) -> Path:
    bdir = tmp_path / "kb"
    bundle = Bundle(bdir)
    bundle.write_concept(
        "policy/refunds",
        {
            "type": "Policy",
            "title": "Refund policy",
            "description": "Refunds are available for all purchases.",
            "valid_until": "2025-06-30",
            "verified": [{"by": "human:alice", "at": "2024-01-01T00:00:00Z"}],
        },
        "Old refund policy body.",
    )
    bundle.write_concept(
        "policy/refunds-v2",
        {
            "type": "Policy",
            "title": "Refund policy v2",
            "description": "Refunds are available for all purchases.",
            "supersedes": "policy/refunds",
            "last_verified": "2026-09-01",
        },
        "New refund policy body.",
    )
    bundle.write_concept(
        "guide/plain",
        {"type": "Guide", "title": "Plain guide", "description": "Nothing temporal."},
        "Plain body.",
    )
    (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
    return bdir


class TestSearchCli:
    def test_as_of_flag(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bdir), "refund", "--as-of", "2025-01-01", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        # At 2025-01-01 v1 is window-valid but v2 (no window) still heads
        # the chain, so v1 is superseded-hidden and v2 is shown.
        assert [r["id"] for r in payload["results"]] == ["policy/refunds-v2"]
        assert payload["superseded_hidden"] == 1
        assert payload["as_of"].startswith("2025-01-01")

    def test_as_of_garbage_is_usage_error(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bdir), "refund", "--as-of", "not-a-date"],
            env=WIDE,
        )
        assert result.exit_code == 2
        assert "Traceback" not in result.output

    def test_include_superseded_flag(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bdir), "refund", "--include-superseded", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        by_id = {r["id"]: r for r in payload["results"]}
        assert by_id["policy/refunds"]["temporal_status"] == "expired"
        assert payload["superseded_hidden"] == 0

    def test_superseded_marked_in_text_table(self, tmp_path):
        bdir = tmp_path / "kb"
        bundle = Bundle(bdir)
        bundle.write_concept(
            "api/limits",
            {"type": "Reference", "title": "API rate limits"},
            "Rate limits are 100 requests per minute.",
        )
        bundle.write_concept(
            "api/limits-v2",
            {"type": "Reference", "title": "API rate limits v2", "supersedes": "api/limits"},
            "Rate limits are 1000 requests per minute.",
        )
        (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["search", str(bdir), "rate limits", "--include-superseded"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        assert "superseded→api/limits-v2" in result.output

    def test_hidden_superseded_hint_on_stderr(self, tmp_path):
        bdir = tmp_path / "kb"
        bundle = Bundle(bdir)
        bundle.write_concept(
            "api/limits",
            {"type": "Reference", "title": "API rate limits"},
            "Rate limits are 100 requests per minute.",
        )
        bundle.write_concept(
            "api/limits-v2",
            {"type": "Reference", "title": "API rate limits v2", "supersedes": "api/limits"},
            "Rate limits are 1000 requests per minute.",
        )
        (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["search", str(bdir), "rate limits"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        assert "1 superseded result hidden" in (result.stderr or "")
        assert "--include-superseded" in (result.stderr or "")

    def test_json_shape(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bdir), "refund", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert set(payload) >= {
            "query",
            "as_of",
            "results",
            "count",
            "superseded_hidden",
        }
        for row in payload["results"]:
            assert set(row) >= {
                "id",
                "type",
                "title",
                "tier",
                "score",
                "temporal_status",
                "superseded_by",
            }


class TestListCli:
    def test_valid_column(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(app, ["list", str(bdir)], env=WIDE)
        assert result.exit_code == 0, result.output
        assert "Valid" in result.output
        assert "expired" in result.output  # policy/refunds
        assert "current" in result.output  # policy/refunds-v2
        assert "—" in result.output  # guide/plain has no temporal fields

    def test_list_json_temporal_status(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["list", str(bdir), "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        by_id = {c["id"]: c for c in payload["concepts"]}
        assert by_id["policy/refunds"]["temporal_status"] == "expired"
        assert by_id["policy/refunds-v2"]["temporal_status"] == "current"
        assert by_id["guide/plain"]["temporal_status"] == "current"


class TestReadCli:
    def test_badge_shown_for_temporal_concept(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["read", str(bdir), "policy/refunds"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        assert "[temporal: expired (valid_until 2025-06-30 has passed)]" in result.output

    def test_badge_shows_current_when_window_valid(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["read", str(bdir), "policy/refunds-v2"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        assert "[temporal: current]" in result.output

    def test_badge_shows_supersession_target(self, tmp_path):
        bdir = tmp_path / "kb"
        bundle = Bundle(bdir)
        bundle.write_concept(
            "api/limits",
            {"type": "Reference", "title": "API rate limits"},
            "Rate limits are 100 requests per minute.",
        )
        bundle.write_concept(
            "api/limits-v2",
            {"type": "Reference", "title": "API rate limits v2", "supersedes": "api/limits"},
            "Rate limits are 1000 requests per minute.",
        )
        (bdir / "index.md").write_text("# Index\n", encoding="utf-8")
        result = runner.invoke(app, ["read", str(bdir), "api/limits"], env=WIDE)
        assert result.exit_code == 0, result.output
        assert "[temporal: superseded by api/limits-v2]" in result.output

    def test_no_badge_for_plain_concept(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["read", str(bdir), "guide/plain"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        assert "[temporal:" not in result.output

    def test_read_json_temporal_status(self, tmp_path):
        bdir = _cli_bundle(tmp_path)
        result = runner.invoke(
            app,
            ["read", str(bdir), "policy/refunds", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["temporal_status"] == "expired"
        assert payload["frontmatter"]["valid_until"] == "2025-06-30"


# ---------------------------------------------------------------------------
# Sync preserves temporal fields on update
# ---------------------------------------------------------------------------


def _write_source(path: Path, sections: list[tuple[str, str]]) -> None:
    """Write a markdown source file big enough to clear the ingest minimum."""
    parts = []
    for heading, body in sections:
        filler = " lorem ipsum dolor sit amet" * 40
        parts.append(f"# {heading}\n\n{body}{filler}\n")
    path.write_text("\n".join(parts), encoding="utf-8")


class TestSyncPreservesTemporal:
    def test_update_keeps_temporal_fields_on_same_ids(self, tmp_path):
        srcdir = tmp_path / "src"
        srcdir.mkdir()
        src = srcdir / "notes.md"
        _write_source(src, [("Apples", "All about apples."), ("Oranges", "All about oranges.")])
        bdir = tmp_path / "kb"
        result = runner.invoke(
            app,
            ["sync", str(bdir), str(src), "--no-llm", "--quiet"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        bundle = Bundle.load(bdir)
        ids_before = sorted(c.id for c in bundle.iter_concepts())
        assert len(ids_before) == 2

        # Hand-stamp temporal fields onto the "apples" concept.
        apples = next(c for c in bundle.iter_concepts() if "apple" in c.id)
        fm = dict(apples.frontmatter)
        fm["valid_from"] = "2025-01-01"
        fm["valid_until"] = "2027-01-01"
        fm["last_verified"] = "2026-09-01"
        bundle.write_concept(apples.id, fm, apples.body)

        # Update the source: change oranges' body, keep headings (ids) stable.
        _write_source(
            src,
            [("Apples", "All about apples."), ("Oranges", "All about ORANGES now.")],
        )
        result = runner.invoke(
            app,
            ["sync", str(bdir), str(src), "--no-llm", "--quiet"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output

        bundle = Bundle.load(bdir)
        ids_after = sorted(c.id for c in bundle.iter_concepts())
        assert ids_after == ids_before  # no -2 duplicates
        apples_after = bundle.get(apples.id)
        assert apples_after is not None
        assert apples_after.frontmatter.get("valid_from") == "2025-01-01"
        assert apples_after.frontmatter.get("valid_until") == "2027-01-01"
        assert apples_after.frontmatter.get("last_verified") == "2026-09-01"
        # Oranges (no temporal fields) is untouched by the restore.
        oranges = next(c for c in bundle.iter_concepts() if "orange" in c.id)
        assert "valid_from" not in oranges.frontmatter

    def test_sync_does_not_autostamp_supersedes(self, tmp_path):
        # Re-ingesting a changed file replaces concepts; the new generation
        # must NOT gain supersedes -> old (deleted) ids (would be W018).
        srcdir = tmp_path / "src"
        srcdir.mkdir()
        src = srcdir / "notes.md"
        _write_source(src, [("Apples", "All about apples.")])
        bdir = tmp_path / "kb"
        assert (
            runner.invoke(
                app,
                ["sync", str(bdir), str(src), "--no-llm", "--quiet"],
                env=WIDE,
            ).exit_code
            == 0
        )
        _write_source(src, [("Apples", "Apples, revised.")])
        assert (
            runner.invoke(
                app,
                ["sync", str(bdir), str(src), "--no-llm", "--quiet"],
                env=WIDE,
            ).exit_code
            == 0
        )
        bundle = Bundle.load(bdir)
        for concept in bundle.iter_concepts():
            assert "supersedes" not in concept.frontmatter
        report = check(bdir)
        assert [f for f in report.warnings if f.code == "W018"] == []
