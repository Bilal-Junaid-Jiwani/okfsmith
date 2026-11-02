"""Tests for the dashboard SPA's Explore search-hit rendering.

Regression test for the 0.17.1 bug: the Explore page rendered each search
hit with ``tierPill(r.tier)``, but ``GET /api/v1/search`` never returns a
``tier`` field — its trust field is ``trust_tier`` (``tier`` is the
recency bucket the concept endpoints return). Every search hit therefore
showed an "unknown" pill instead of its trust tier, and the ``type`` /
``temporal_status`` fields the API returns were dropped entirely.

These tests assert against the shipped app.js source (there is no JS test
harness in this repo): the search-hit construction must read the fields
the API actually returns.
"""

from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
APP_JS = WORKTREE / "src" / "okfsmith" / "dashboard" / "static" / "app.js"


def _app_js() -> str:
    assert APP_JS.is_file(), f"missing dashboard SPA: {APP_JS}"
    return APP_JS.read_text(encoding="utf-8")


def test_search_hits_render_trust_tier_not_recency_tier():
    """Search hits must pill the API's `trust_tier`, never `r.tier`."""
    js = _app_js()
    assert "trustTierPill(r.trust_tier)" in js, (
        "Explore search hits must render trustTierPill(r.trust_tier)"
    )
    assert "tierPill(r.tier)" not in js, (
        "Explore search hits still render tierPill(r.tier), but /search "
        "returns no `tier` field — every hit would show 'unknown'"
    )


def test_search_hits_surface_type_and_temporal_status():
    """Search hits must not drop the `type` / `temporal_status` fields."""
    js = _app_js()
    assert "r.temporal_status" in js, (
        "Explore search hits must surface the API's temporal_status "
        "(e.g. a superseded hit should say so)"
    )
    # The hit meta line shows the concept type when the API provides one.
    assert "r.type" in js, "Explore search hits must surface the API's type"
