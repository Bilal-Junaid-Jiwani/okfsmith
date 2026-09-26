"""OKF v0.2 spec constants and helpers.

Grounded in ``GoogleCloudPlatform/open-knowledge-format`` SPEC.md v0.2:

- §11 — ``type`` is the only always-required frontmatter key; consumers MUST
  tolerate unknown keys and MUST NOT reject trust-less concepts.
- §5.2 — ``generated`` / ``verified`` trust frontmatter; a bare ``verified``
  mapping MUST be treated as a one-element list.
- §5.3 — trust tiers: no ``verified`` ⇒ ``unverified``; non-``human:`` actors
  only ⇒ ``machine-confirmed``; any ``human:<id>`` actor ⇒ ``human-reviewed``.
- §5.4 — lifecycle ``status``: ``draft → stable → deprecated``.
- §7 — actors: ``human:<id>``, ``process:<id>``, or a bare tool/agent name.
- Reserved filenames ``index.md`` / ``log.md`` are never concept documents.

This module performs no I/O and makes no network calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

#: Reserved filenames: directory listing and chronological history.
#: They are never concept documents, at any depth of the bundle.
RESERVED_FILES = {"index.md", "log.md"}

#: The only always-required frontmatter key (OKF v0.2 §11).
REQUIRED_KEY = "type"

#: Lifecycle statuses (OKF v0.2 §5.4: ``draft → stable → deprecated``).
VALID_STATUSES = frozenset({"draft", "stable", "deprecated"})

#: OKF version stamp written to the *root* ``index.md`` frontmatter only.
OKF_VERSION = "0.2"

#: Trust tiers derived from ``verified`` frontmatter (OKF v0.2 §5.3).
UNVERIFIED = "unverified"
MACHINE_CONFIRMED = "machine-confirmed"
HUMAN_REVIEWED = "human-reviewed"

#: Prefix marking a human actor, e.g. ``human:ahormati``.
HUMAN_PREFIX = "human:"


def is_human_actor(actor: str) -> bool:
    """Return ``True`` if *actor* carries the ``human:`` prefix.

    >>> is_human_actor("human:ahormati")
    True
    >>> is_human_actor("process:finance-nightly")
    False
    """
    return str(actor).startswith(HUMAN_PREFIX)


def actor_name(actor: str) -> str:
    """Return the identifier part of an actor string.

    >>> actor_name("human:ahormati")
    'ahormati'
    >>> actor_name("process:finance-nightly")
    'finance-nightly'
    >>> actor_name("reference_agent")
    'reference_agent'
    """
    text = str(actor)
    _head, sep, tail = text.partition(":")
    return tail if sep else text


def trust_tier(frontmatter: Mapping) -> str:
    """Derive the trust tier from frontmatter (OKF v0.2 §5.3).

    - No ``verified`` key → ``"unverified"``.
    - ``verified`` by non-``human:`` actors only → ``"machine-confirmed"``.
    - Any ``human:<id>`` verifier → ``"human-reviewed"``.

    A bare ``verified`` mapping counts as a one-element list, per §5.2.
    Unknown frontmatter keys are ignored here — never rejected.

    Defensive: a scalar ``verified`` (``bool``/``str``/``int``, e.g.
    ``verified: yes`` in hand-written YAML) carries no actor info and is
    treated as ``"unverified"``; a ``verified`` of any other non-list,
    non-mapping shape is likewise ``"unverified"``. This function never
    raises on malformed ``verified`` input.
    """
    verified = frontmatter.get("verified")
    if verified is None:
        return UNVERIFIED
    if isinstance(verified, Mapping):
        verified = [verified]
    elif not isinstance(verified, (list, tuple)):
        # Scalar or otherwise malformed ``verified``: no actor info to judge,
        # so there is no basis for a trust tier — treat as unverified.
        return UNVERIFIED
    if not verified:
        return UNVERIFIED
    for entry in verified:
        by = entry.get("by", "") if isinstance(entry, Mapping) else ""
        if is_human_actor(by):
            return HUMAN_REVIEWED
    return MACHINE_CONFIRMED


def utc_now_iso() -> str:
    """Return the current UTC time as ISO-8601 with an explicit offset.

    >>> import re
    >>> bool(re.match(r"\\d{4}-\\d{2}-\\d{2}T.*\\+00:00$", utc_now_iso()))
    True
    """
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    """Return today's UTC date as ``YYYY-MM-DD`` (used for ``log.md`` headings)."""
    return datetime.now(timezone.utc).date().isoformat()
