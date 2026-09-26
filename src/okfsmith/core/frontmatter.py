"""YAML frontmatter parsing and serialization for OKF concept documents.

Unknown keys are always preserved — this module never rejects a document for
carrying keys it does not understand (OKF v0.2 §11). Key order is preserved
on serialization so diffs stay clean.

No network calls; depends only on ``pyyaml``.
"""

from __future__ import annotations

import yaml

_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split *text* into a ``(frontmatter, body)`` tuple.

    The document must start with a ``---`` line and contain a closing ``---``
    line. If either is missing (or the YAML is not a mapping), this returns
    ``({}, text)`` — the document is never rejected, the whole text is kept
    as the body.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        return {}, text
    closing = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIMITER:
            closing = i
            break
    if closing is None:
        return {}, text
    try:
        data = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        data = {}
    body = "".join(lines[closing + 1 :])
    return data, body


def serialize_frontmatter(frontmatter: dict, body: str = "") -> str:
    """Serialize *frontmatter* and *body* back to an OKF document.

    Round-trip safe: ``parse_frontmatter(serialize_frontmatter(fm, body))``
    returns ``(fm, body)``. Key insertion order of *frontmatter* is preserved
    (``sort_keys=False``); unknown keys pass through untouched.
    """
    dumped = yaml.safe_dump(
        dict(frontmatter),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"{_DELIMITER}\n{dumped}{_DELIMITER}\n{body}"
