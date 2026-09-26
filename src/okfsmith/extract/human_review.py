"""Human review: promote a concept to the human-reviewed trust tier.

:func:`mark_reviewed` appends a ``verified`` entry
``{by: "human:<reviewer>", at: <utc-now>}`` to the concept's frontmatter and
records a log **Update**. Per OKF v0.2 §5.3 (see
:mod:`okfsmith.core.spec`), any ``human:<id>`` verifier moves the concept to
the ``human-reviewed`` tier.
"""

from __future__ import annotations

from okfsmith.core import indexlog
from okfsmith.core.bundle import Bundle, Concept
from okfsmith.core.spec import utc_now_iso


def _one_line(value: str) -> str:
    """Collapse whitespace so log messages stay one entry per line.

    Security (audit-3 finding 7): reviewer/section names may carry attacker-
    influenced text (e.g. LLM output); embedded newlines could forge entries
    in the append-only log.md.
    """
    return " ".join(str(value).split())


def mark_reviewed(bundle: Bundle, concept_id: str, reviewer: str) -> Concept:
    """Mark *concept_id* as reviewed by *reviewer* (human-reviewed tier).

    Appends ``verified: {by: "human:<reviewer>", at: <now>}`` — normalizing a
    bare ``verified`` mapping to a one-element list per OKF §5.2 — and
    appends a log **Update**. Existing verifications are merged in and
    preserved, never discarded.

    Raises :class:`KeyError` if the concept does not exist, :class:`ValueError`
    if *reviewer* is empty.
    """
    # Collapse attacker-influenced whitespace (incl. newlines) *before*
    # storing, so the frontmatter record and the log line carry the same
    # single-line identifier (QA L13; log-forgery hardening mirrors M5).
    reviewer = _one_line(reviewer or "")
    if not reviewer:
        raise ValueError("reviewer must be a non-empty identifier")
    concept = bundle.get(concept_id)
    if concept is None:
        # No absolute bundle path: paths in exceptions tend to surface in
        # logs/traces (audit-3 finding 8).
        raise KeyError(f"no concept {concept_id!r} in bundle")

    frontmatter = dict(concept.frontmatter)
    verified = frontmatter.get("verified")
    if isinstance(verified, list):
        entries = list(verified)
    elif verified is None:
        entries = []
    else:
        # Bare mapping (§5.2) or legacy scalar: keep it verbatim as the first
        # entry rather than silently discarding it (QA L13). Non-mapping
        # legacy values are flagged W011 by the validator but never dropped.
        entries = [verified]
    entries.append({"by": f"human:{reviewer}", "at": utc_now_iso()})
    frontmatter["verified"] = entries

    updated = bundle.write_concept(concept_id, frontmatter, concept.body)
    indexlog.append_log(
        bundle,
        "",
        "Update",
        f'human review by "{_one_line(reviewer)}": '
        f'"{_one_line(concept_id)}" marked human-reviewed',
    )
    return updated
