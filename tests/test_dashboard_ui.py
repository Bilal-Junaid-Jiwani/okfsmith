"""Tests for the dashboard SPA's Explore search-hit and concept-detail rendering.

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


def _explore_js() -> str:
    """The Explore page's own section of app.js (up to the graph code)."""
    js = _app_js()
    start = js.index("page: explore")
    end = js.index("// graph", start)
    return js[start:end]


def test_explore_search_exposes_type_and_trust_tier_filters():
    """Explore search must offer the ?type= / ?trust_tier= filters.

    GET /api/v1/search has accepted both since 0.14 (the dashboard
    analogue of `okfsmith search --type` / `--tier`), but the Explore
    page never exposed them, so narrowing a search meant re-running it
    on the CLI or in chat. The request URL must carry both parameters,
    and the trust-tier select must offer the API's closed tier set.
    """
    js = _explore_js()
    assert "'&type=' + encodeURIComponent" in js, (
        "Explore search must pass its type filter as ?type= to /search"
    )
    assert "'&trust_tier=' + encodeURIComponent" in js, (
        "Explore search must pass its trust-tier filter as ?trust_tier= "
        "to /search"
    )
    for tier in ("unverified", "machine-confirmed", "human-reviewed"):
        assert f"value: '{tier}'" in js, (
            f"Explore search trust-tier select must offer {tier!r}"
        )


def _detail_js(fn_name, end_marker):
    """One concept-detail renderer's section of app.js."""
    js = _app_js()
    start = js.index(fn_name)
    return js[start:js.index(end_marker, start)]


def test_concept_detail_views_render_trust_tier_and_type():
    """Both concept-detail views must show trust tier and type.

    The graph detail panel and the concept modal used to pill only the
    opaque high/medium/low recency bucket, so a reader opening a
    concept could not tell whether it was human-reviewed or merely
    unverified, nor what type it is — even though the listing and
    search hits already surface both. Each detail renderer must pill
    the detail endpoint's `trust_tier` and show its `type`.
    """
    for fn_name, end_marker in (
        ("async function conceptDetailBody", "function openConceptModal"),
        ("async function showConceptInPanel", "function buildGraph"),
    ):
        section = _detail_js(fn_name, end_marker)
        assert "trustTierPill(c.trust_tier)" in section, (
            f"{fn_name} must pill the detail endpoint's trust_tier"
        )
        assert "c.type" in section, (
            f"{fn_name} must surface the detail endpoint's type"
        )


def test_concept_detail_views_render_temporal_status():
    """Both concept-detail views must flag a non-current concept.

    The graph detail panel and the concept modal used to show a
    concept with no hint whether it was current, superseded (and by
    what), expired, or not yet valid — a superseded concept opened
    from the graph looked identical to a current one, even though
    the search hits already label both. Each detail renderer must
    pill the detail endpoint's `temporal_status` (with the
    superseding id when there is one).
    """
    for fn_name, end_marker in (
        ("async function conceptDetailBody", "function openConceptModal"),
        ("async function showConceptInPanel", "function buildGraph"),
    ):
        section = _detail_js(fn_name, end_marker)
        assert "temporalStatusPill(c)" in section, (
            f"{fn_name} must pill the detail endpoint's temporal_status"
        )
    js = _app_js()
    helper = js[js.index("function temporalStatusPill"):]
    helper = helper[:helper.index("\n}\n") + 3]
    assert "c.temporal_status" in helper
    assert "c.superseded_by" in helper
    assert "superseded by" in helper


def test_explore_search_reruns_when_trust_tier_changes():
    """Changing the trust-tier select re-runs an already-shown search."""
    js = _explore_js()
    assert "searchTrustSel.addEventListener('change'" in js, (
        "Explore search must re-run when its trust-tier select changes, "
        "so narrowing does not need the query retyped"
    )
    assert "exploreSearched" in js, (
        "Explore search must track whether a search has been shown, so "
        "a filter change before the first search does not fire a query "
        "with no keywords"
    )


def test_explore_search_exposes_superseded_toggle():
    """Explore search must offer the API's ?include_superseded= flag.

    GET /api/v1/search hides superseded matches by default, but the
    Explore page never exposed the flag, so those matches were
    unreachable from the dashboard — a search whose only matches were
    superseded looked like it matched nothing at all.
    """
    js = _explore_js()
    assert "id: 'search-superseded'" in js, (
        "Explore search must have a superseded checkbox"
    )
    assert "text: 'Include superseded'" in js, (
        "Explore search superseded toggle must be labeled"
    )
    assert "'&include_superseded=true'" in js, (
        "Explore search must pass its superseded toggle as "
        "?include_superseded= to /search"
    )
    assert "searchSupersededChk.addEventListener('change'" in js, (
        "Explore search must re-run when its superseded toggle changes, "
        "so revealing hidden matches does not need the query retyped"
    )


def test_explore_search_surfaces_hidden_superseded_count():
    """Explore search must not silently drop `superseded_hidden`.

    GET /api/v1/search reports how many matches it hid as superseded;
    the Explore page used to read only `.results`, so a search could
    hide matches without ever saying so.
    """
    js = _explore_js()
    assert "superseded_hidden" in js, (
        "Explore search must read the /search payload's superseded_hidden"
    )
    assert "supersededHiddenNote" in js, (
        "Explore search must render a note when superseded matches "
        "were hidden"
    )
    assert "hidden" in js and "Include superseded" in js, (
        "The hidden-matches note must say matches were hidden and how "
        "to reveal them"
    )


def test_chat_slash_chips_carry_sources():
    """Chat /search and /list chips must carry the concept's sources.

    Both slash commands used to build citation chips with
    ``sources: []`` hardcoded, so hovering a chip showed a dangling
    "Sources: " tooltip — even though the /search hits now carry
    sources and the /list listing always did. Each chip builder must
    pass the payload's sources through, and ``citationChips`` must
    only append the Sources line when the citation has sources.
    """
    js = _app_js()
    slash = js[js.index("async function runSlash"):]
    slash = slash[:slash.index("// initial paint")]
    assert "sources: []" not in slash, (
        "Chat /search and /list must not build chips with hardcoded "
        "`sources: []` — the tooltip would show an empty 'Sources: '"
    )
    assert slash.count("sources: c.sources || []") == 2, (
        "Both the /search and /list chip builders must pass the "
        "payload's `c.sources` through to citationChips"
    )
    chips = js[js.index("function citationChips"):]
    chips = chips[:chips.index("return cites;")]
    assert "srcs.length ?" in chips, (
        "citationChips must only append the Sources line when the "
        "citation actually carries sources"
    )
    assert "'\\nSources: ' + srcs.join(', ')" in chips, (
        "citationChips must render the carried sources in the chip "
        "tooltip"
    )


def test_chat_slash_chips_carry_temporal_status():
    """Chat /search and /list chips must carry the concept's temporal status.

    The listing, the detail endpoint, and the /search hits all carry
    `temporal_status` / `superseded_by`, but the chat's chip builders
    dropped both — so a superseded concept cited by /search or /list
    hovered exactly like a current one. Each chip builder must pass
    the payload's temporal fields through, and ``citationChips`` must
    add the temporal label to the chip tooltip (nothing for a current
    concept, so current chips hover exactly as before).
    """
    js = _app_js()
    slash = js[js.index("async function runSlash"):]
    slash = slash[:slash.index("// initial paint")]
    assert slash.count("temporal_status: c.temporal_status") == 2, (
        "Both the /search and /list chip builders must pass the "
        "payload's `temporal_status` through to citationChips"
    )
    assert slash.count("superseded_by: c.superseded_by") == 2, (
        "Both the /search and /list chip builders must pass the "
        "payload's `superseded_by` through to citationChips"
    )
    chips = js[js.index("function citationChips"):]
    chips = chips[:chips.index("return cites;")]
    assert "tlabel" in chips and "'Superseded'" in chips, (
        "citationChips must label a superseded chip with the "
        "superseding concept's id in the tooltip"
    )
    assert "'Expired'" in chips and "'Not yet valid'" in chips, (
        "citationChips must label expired and not-yet-valid chips too"
    )
    assert "t === 'current'" in chips or "|| 'current'" in chips, (
        "citationChips must add no temporal line for a current chip"
    )
