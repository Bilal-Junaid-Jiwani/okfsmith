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


def mark_reviewed(bundle: Bundle, concept_id: str, reviewer: str) -> Concept:
    """Mark *concept_id* as reviewed by *reviewer* (human-reviewed tier).

    Appends ``verified: {by: "human:<reviewer>", at: <now>}`` — normalizing a
    bare ``verified`` mapping to a one-element list per OKF §5.2 — and
    appends a log **Update**. Existing verifications are preserved.

    Raises :class:`KeyError` if the concept does not exist, :class:`ValueError`
    if *reviewer* is empty.
    """
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("reviewer must be a non-empty identifier")
    concept = bundle.get(concept_id)
    if concept is None:
        raise KeyError(f"no concept {concept_id!r} in bundle at {bundle.root}")

    frontmatter = dict(concept.frontmatter)
    verified = frontmatter.get("verified")
    if isinstance(verified, list):
        entries = list(verified)
    elif isinstance(verified, dict):
        entries = [verified]  # bare mapping counts as a one-element list (§5.2)
    else:
        entries = []
    entries.append({"by": f"human:{reviewer}", "at": utc_now_iso()})
    frontmatter["verified"] = entries

    updated = bundle.write_concept(concept_id, frontmatter, concept.body)
    indexlog.append_log(
        bundle,
        "",
        "Update",
        f'human review by "{reviewer}": "{concept_id}" marked human-reviewed',
    )
    return updated
