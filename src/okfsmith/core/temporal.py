"""Temporal model for OKF concepts: validity windows, supersession, as-of queries.

Frontmatter fields (all optional):

- ``valid_from`` / ``valid_until`` — ISO-8601 date or datetime. A concept is
  *window-valid* at time *t* iff ``valid_from <= t <= valid_until``
  (open-ended on either side when absent).
- ``supersedes`` — a concept id, or a list of concept ids, that this concept
  replaces. Superseded concepts are demoted in retrieval, never deleted.
- ``last_verified`` — ISO-8601 date/datetime of the last verification. Used
  only as the final retrieval tiebreak (after trust tier); recency alone
  never demotes a concept.

Precedence rule (documented contract): **validity window > supersession >
trust tier > recency**. A concept outside its validity window is demoted no
matter how trusted; a superseded concept is demoted no matter how recent;
within one currency group, BM25 score decides, then trust tier
(``human-reviewed`` > ``machine-confirmed`` > ``unverified``), then
``last_verified``. In particular a ``human-reviewed`` concept is never
auto-demoted below an ``unverified`` one purely on recency.

All parsing here **never raises**: temporal fields come from user frontmatter
and are treated as untrusted input (no ``eval``, no path use, list lengths
capped at :data:`MAX_SUPERSEDES_ENTRIES`). Garbage values parse to
``None``/``[]``; the validator reports them as W016 advisories.

Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from okfsmith.core.spec import (
    HUMAN_REVIEWED,
    MACHINE_CONFIRMED,
    UNVERIFIED,
    trust_tier,
)

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle, Concept

__all__ = [
    "MAX_SUPERSEDES_ENTRIES",
    "TEMPORAL_FIELDS",
    "TIER_RANK",
    "PartitionedHits",
    "SupersessionIndex",
    "TemporalStatus",
    "has_temporal_fields",
    "normalize_supersedes",
    "parse_temporal",
    "partition_hits",
    "utcnow",
]

#: The four temporal frontmatter fields.
TEMPORAL_FIELDS = ("valid_from", "valid_until", "supersedes", "last_verified")

#: Security cap (P2): a ``supersedes`` list longer than this is truncated by
#: the resolver; the validator warns (W016) so over-long user input cannot
#: turn chain resolution quadratic.
MAX_SUPERSEDES_ENTRIES = 100

#: Trust-tier rank used as the retrieval tiebreak after BM25 score.
TIER_RANK = {HUMAN_REVIEWED: 3, MACHINE_CONFIRMED: 2, UNVERIFIED: 1}

#: Floor timestamp for concepts with no ``last_verified`` (sorts last on recency).
# A recency floor that sorts below every real timestamp on every platform
# (``datetime.min.timestamp()`` raises on Windows and is negative elsewhere,
# so it is not a portable sort key).
_NO_RECENCY: float = float("-inf")

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date_only(value: object) -> bool:
    """True when *value* is a calendar date with no time-of-day part."""
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        return True
    return isinstance(value, str) and _DATE_ONLY_RE.match(value.strip()) is not None


def _parse_window_end(value: object) -> datetime | None:
    """Parse a ``valid_until`` value with inclusive date semantics.

    A date-only ``valid_until`` (``2026-03-31``) covers the whole calendar
    day — i.e. it means 23:59:59.999999 UTC on that date, not midnight at
    its start. Full datetimes keep their exact instant.
    """
    parsed = parse_temporal(value)
    if parsed is None:
        return None
    if _is_date_only(value):
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def utcnow() -> datetime:
    """Current time as an aware UTC datetime (the default ``as_of``)."""
    return datetime.now(timezone.utc)


def parse_temporal(value: object) -> datetime | None:
    """Parse an ISO-8601 date/datetime into an aware UTC datetime.

    Accepts ``datetime`` / ``date`` objects (YAML already parses unquoted
    ``2026-09-28`` into a ``date``) and ISO-8601 strings (``Z``/``z`` suffix
    understood). Naive datetimes are assumed UTC; bare dates become midnight
    UTC. **Never raises**: unparseable, out-of-range (e.g. ``2026-13-99`` —
    the C9 class of crash), or wrongly-typed values return ``None``.

    Over-long strings (>100 chars) are rejected without parsing — a date is
    never that long.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 100:
        return None
    iso = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_supersedes(value: object) -> list[str]:
    """Normalize the ``supersedes`` field to a list of concept ids.

    Accepts a single string or a list/tuple of strings; blank and
    non-string entries are dropped; the result is capped at
    :data:`MAX_SUPERSEDES_ENTRIES`. **Never raises.**
    """
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        items: list[object] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value[:MAX_SUPERSEDES_ENTRIES])
    else:
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def has_temporal_fields(frontmatter: dict) -> bool:
    """True when any temporal field is present with a non-blank value.

    Used for display decisions (the ``list`` Valid column shows ``—`` when
    this is False). Never raises.
    """
    for key in TEMPORAL_FIELDS:
        value = frontmatter.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not normalize_supersedes(value):
            continue
        return True
    return False


@dataclass(frozen=True)
class TemporalStatus:
    """The temporal state of one concept at one instant."""

    name: str
    """One of ``current`` / ``not_yet_valid`` / ``expired`` / ``superseded``."""

    current: bool
    """True only for ``current``: window-valid and not superseded."""

    superseded_by: str | None = None
    """Head of the supersession chain valid at the query time (``None`` unless
    ``name == "superseded"``)."""

    has_temporal: bool = False
    """Whether the concept carries any temporal frontmatter at all (used for
    the ``list`` Valid column: concepts without temporal fields show ``—``)."""


class SupersessionIndex:
    """Supersession graph + as-of resolution for one bundle.

    Built once per retrieval/validation pass from the bundle's concepts.
    Edges to nonexistent concept ids are dropped (the validator warns W018);
    chain walks are cycle-safe and memoized, so hostile frontmatter can
    neither loop forever nor blow up exponentially.
    """

    def __init__(self, concepts) -> None:
        """Build the index from an iterable of concepts (or ``(id, fm)`` pairs)."""
        ids: set[str] = set()
        frontmatters: dict[str, dict] = {}
        for item in concepts:
            if isinstance(item, tuple):
                concept_id, fm = item
            else:
                concept_id, fm = item.id, (item.frontmatter or {})
            ids.add(concept_id)
            frontmatters[concept_id] = fm
        self._ids = ids
        self._frontmatters = frontmatters
        self._edges: dict[str, list[str]] = {}
        for concept_id, fm in frontmatters.items():
            # Keep only edges to real concepts; self-edges stay — they are
            # cycles and the validator flags them (W019).
            targets = [
                target for target in normalize_supersedes(fm.get("supersedes")) if target in ids
            ]
            if targets:
                # Dedupe, keep deterministic order.
                self._edges[concept_id] = sorted(set(targets))
        # Reverse index: superseded id -> ids that supersede it. Chain
        # resolution walks this direction (from an old concept toward its
        # replacements); cycle detection walks _edges.
        self._superseders: dict[str, list[str]] = {}
        for source, targets in self._edges.items():
            for target in targets:
                self._superseders.setdefault(target, []).append(source)
        for target in self._superseders:
            self._superseders[target] = sorted(self._superseders[target])
        # Memoized chain-head resolutions: (concept_id, at) -> (depth, head)
        # or None when nothing reachable is valid at *at*. Shared across
        # resolve_head calls on this index, so a whole retrieval pass over
        # a hostile graph costs O(V + E) total, not O(V * E).
        self._head_memo: dict[tuple[str, datetime], tuple[int, str] | None] = {}

    @classmethod
    def from_bundle(cls, bundle: Bundle) -> SupersessionIndex:
        """Build the index over every concept in *bundle*."""
        return cls(bundle.iter_concepts())

    # -- window validity ----------------------------------------------------

    def _window_status(self, frontmatter: dict, at: datetime) -> str:
        """``current`` / ``not_yet_valid`` / ``expired`` from the validity window."""
        valid_from = parse_temporal(frontmatter.get("valid_from"))
        if valid_from is not None and at < valid_from:
            return "not_yet_valid"
        valid_until = _parse_window_end(frontmatter.get("valid_until"))
        if valid_until is not None and at > valid_until:
            return "expired"
        return "current"

    def window_valid(self, concept_id: str, at: datetime) -> bool:
        """True when *concept_id*'s validity window covers *at* (open-ended OK)."""
        fm = self._frontmatters.get(concept_id)
        if fm is None:
            return True
        return self._window_status(fm, at) == "current"

    # -- chain resolution ----------------------------------------------------

    def resolve_head(self, concept_id: str, at: datetime) -> str:
        """Resolve the head of *concept_id*'s supersession chain valid at *at*.

        Follows ``supersedes`` edges toward the furthest reachable concept
        whose validity window covers *at*, breaking depth ties toward the
        lexicographically smallest id. Returns *concept_id* itself when
        nothing further along the chain is valid at *at* (including when
        *concept_id* is unknown to the index).

        The walk is a memoized dynamic program over ``(concept, at)``:
        each node is expanded once per distinct *at*, so resolution is
        O(V + E) — hostile frontmatter can neither loop forever (cycle-safe)
        nor trigger the exponential simple-path enumeration a naive DFS
        suffers on branching DAGs (QA HIGH-2). On an acyclic graph the
        result is exact; on a cyclic graph (a data error, flagged by the
        validator as W019) the first-completed exploration wins, which is
        deterministic but may differ from exhaustive path enumeration.
        """
        if concept_id not in self._ids:
            return concept_id
        memo = self._head_memo
        start_key = (concept_id, at)
        if start_key not in memo:
            # Iterative post-order DFS with a cycle guard (nodes on the
            # current stack are dead ends for that branch). Deterministic:
            # superseder lists are sorted, so first-visit order is fixed.
            in_progress = {start_key}
            stack: list[tuple[str, bool]] = [(concept_id, False)]
            while stack:
                node, expanded = stack.pop()
                key = (node, at)
                if expanded:
                    cand: tuple[int, str] | None = (
                        (0, node) if self.window_valid(node, at) else None
                    )
                    for nxt in self._superseders.get(node, ()):
                        res = memo.get((nxt, at))
                        if res is not None:
                            stepped = (res[0] + 1, res[1])
                            if (
                                cand is None
                                or stepped[0] > cand[0]
                                or (
                                    stepped[0] == cand[0]
                                    and stepped[1] < cand[1]
                                )
                            ):
                                cand = stepped
                    memo[key] = cand
                    in_progress.discard(key)
                    continue
                if key in memo:  # resolved by an earlier query on this index
                    in_progress.discard(key)
                    continue
                stack.append((node, True))
                for nxt in self._superseders.get(node, ()):
                    nxt_key = (nxt, at)
                    if nxt_key in memo or nxt_key in in_progress:
                        continue
                    in_progress.add(nxt_key)
                    stack.append((nxt, False))
        res = memo[start_key]
        return res[1] if res is not None else concept_id

    def superseded_by(self, concept_id: str, at: datetime) -> str | None:
        """The chain head valid at *at*, or ``None`` when *concept_id* is the head."""
        head = self.resolve_head(concept_id, at)
        return None if head == concept_id else head

    def status(self, concept: Concept, at: datetime) -> TemporalStatus:
        """The temporal status of *concept* at *at*.

        Precedence (window > supersession): a concept outside its validity
        window reports ``expired`` / ``not_yet_valid`` even when it is also
        superseded.
        """
        fm = concept.frontmatter or {}
        has_temporal = has_temporal_fields(fm)
        window = self._window_status(fm, at)
        if window != "current":
            return TemporalStatus(name=window, current=False, has_temporal=has_temporal)
        head = self.superseded_by(concept.id, at)
        if head is not None:
            return TemporalStatus(
                name="superseded",
                current=False,
                superseded_by=head,
                has_temporal=has_temporal,
            )
        return TemporalStatus(name="current", current=True, has_temporal=has_temporal)

    # -- cycle detection (validator W019) -------------------------------------

    def find_cycles(self) -> list[tuple[str, ...]]:
        """Find every supersession cycle, each reported once.

        Returns canonical cycle tuples: rotated so the lexicographically
        smallest id comes first, sorted by that id. Deterministic.
        """
        found: set[tuple[str, ...]] = set()

        def visit(node: str, path: list[str], on_path: set[str]) -> None:
            for nxt in self._edges.get(node, ()):
                if nxt in on_path:
                    cycle = path[path.index(nxt) :]
                    # Canonical rotation: smallest id first.
                    anchor = min(cycle)
                    idx = cycle.index(anchor)
                    canonical = tuple(cycle[idx:] + cycle[:idx])
                    found.add(canonical)
                elif nxt not in visited:
                    visited.add(nxt)
                    path.append(nxt)
                    on_path.add(nxt)
                    visit(nxt, path, on_path)
                    path.pop()
                    on_path.discard(nxt)

        visited: set[str] = set()
        for start in sorted(self._ids):
            if start not in visited:
                visited.add(start)
                visit(start, [start], {start})
        return sorted(found)


@dataclass
class PartitionedHits:
    """BM25 hits partitioned by temporal status (each group pre-sorted)."""

    current: list = field(default_factory=list)
    """Window-valid, not superseded — the default answer set."""

    windowed: list = field(default_factory=list)
    """Outside the validity window (``expired`` / ``not_yet_valid``): demoted,
    ranked after every current hit, but still shown."""

    superseded: list = field(default_factory=list)
    """Superseded hits as ``(score, concept, superseded_by)``: excluded from
    default results (demoted, never deleted), shown last with
    ``include_superseded``."""


def _recency_ts(frontmatter: dict) -> float:
    """``last_verified`` as a Unix timestamp (floor when absent/unparseable)."""
    parsed = parse_temporal(frontmatter.get("last_verified"))
    return parsed.timestamp() if parsed is not None else _NO_RECENCY


def _sort_group(
    hits: list[tuple[float, Concept]],
) -> list[tuple[float, Concept]]:
    """Sort one currency group: BM25 score, then trust tier, then recency, then id.

    Trust tier outranks recency, so a stale ``human-reviewed`` concept is
    never ordered below a fresh ``unverified`` one on recency alone.
    Deterministic across processes.
    """

    def key(item: tuple[float, Concept]) -> tuple:
        score, concept = item
        fm = concept.frontmatter or {}
        return (
            -score,
            -TIER_RANK.get(trust_tier(fm), 1),
            -_recency_ts(fm),
            concept.id,
        )

    return sorted(hits, key=key)


def partition_hits(
    hits: list[tuple[float, Concept]],
    index: SupersessionIndex,
    at: datetime,
) -> PartitionedHits:
    """Partition BM25 ``(score, concept)`` hits by temporal status at *at*.

    Group order is the retrieval contract: current → window-demoted →
    superseded. Superseded info is ranked last because a better answer (the
    chain head) is already shown; expired info is merely stale and may still
    be the best available. Pure function; never raises on hostile frontmatter.
    """
    part = PartitionedHits()
    for score, concept in hits:
        status = index.status(concept, at)
        if status.name == "superseded":
            assert status.superseded_by is not None
            part.superseded.append((score, concept, status.superseded_by))
        elif not status.current:
            part.windowed.append((score, concept))
        else:
            part.current.append((score, concept))
    part.current = _sort_group(part.current)
    part.windowed = _sort_group(part.windowed)
    part.superseded = sorted(
        part.superseded,
        key=lambda item: (
            -item[0],
            -TIER_RANK.get(trust_tier(item[1].frontmatter or {}), 1),
            -_recency_ts(item[1].frontmatter or {}),
            item[1].id,
        ),
    )
    return part
