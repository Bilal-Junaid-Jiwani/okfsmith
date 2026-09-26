"""YAML frontmatter parsing and serialization for OKF concept documents.

Unknown keys are always preserved — this module never rejects a document for
carrying keys it does not understand (OKF v0.2 §11). Key order is preserved
on serialization so diffs stay clean.

No network calls; depends only on ``pyyaml``.
"""

from __future__ import annotations

import yaml

_DELIMITER = "---"
_BOM = "\ufeff"
# DoS guard (M28): frontmatter is metadata — a block bigger than this is
# treated as unparseable instead of being fed to the YAML parser unbounded.
_MAX_FRONTMATTER_LINES = 20_000
_MAX_FRONTMATTER_CHARS = 1_000_000


def _closing_fence(lines: list[str]) -> int | None:
    """Return the index of the closing ``---`` fence, or ``None``.

    Only a ``---`` line at column 0 (no leading whitespace) counts as a
    fence. An indented ``---`` can only be the content of an indented YAML
    block scalar — a genuine YAML document marker must start at column 0 —
    so it must not terminate the frontmatter block early (M24).
    """
    for i in range(1, len(lines)):
        line = lines[i]
        if line[:1].isspace():
            continue
        if line.strip() == _DELIMITER:
            return i
    return None


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split *text* into a ``(frontmatter, body)`` tuple.

    The document must start with a ``---`` line and contain a closing ``---``
    line at column 0. If either fence is missing, this returns ``({}, text)``.

    The YAML between the fences must parse to a mapping. If it is not valid
    YAML — including impossible timestamps such as ``2026-13-99`` (PyYAML
    raises a plain ``ValueError`` for those) or pathologically nested input
    (which raises ``RecursionError``) — or if it parses to something that is
    not a mapping (e.g. a bare list), the document is still never rejected:
    ``({}, text)`` is returned and the whole text, frontmatter lines
    included, is kept as the body. A load + re-save therefore never deletes
    the user's original frontmatter lines. An empty YAML section is treated
    as an empty mapping.

    A leading UTF-8 BOM is stripped before parsing so it cannot mask the
    opening fence (L22).

    DoS guard (M28): a frontmatter block larger than
    ``_MAX_FRONTMATTER_LINES`` lines or ``_MAX_FRONTMATTER_CHARS`` characters
    is treated as unparseable (``({}, text)``) instead of being fed to the
    YAML parser unbounded.
    """
    text = text.removeprefix(_BOM)
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        return {}, text
    closing = _closing_fence(lines)
    if closing is None:
        return {}, text
    if closing - 1 > _MAX_FRONTMATTER_LINES:
        # Absurdly large metadata block: refuse to parse it (M28).
        return {}, text
    block = "".join(lines[1:closing])
    if len(block) > _MAX_FRONTMATTER_CHARS:
        return {}, text
    try:
        data = yaml.safe_load(block)
    except (yaml.YAMLError, ValueError, RecursionError):
        # Unparseable YAML: keep the whole text as the body instead of
        # crashing or silently dropping the frontmatter lines.
        return {}, text
    if data is None:
        data = {}
    if not isinstance(data, dict):
        # Non-mapping frontmatter (e.g. a bare list): keep the whole text
        # as the body so a load + re-save preserves the original lines.
        return {}, text
    return data, "".join(lines[closing + 1 :])


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
