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


class _LenientTimestampLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that degrades impossible timestamps to strings.

    PyYAML's timestamp constructor raises a plain ``ValueError`` on
    impossible dates such as ``2026-13-99``. Frontmatter is untrusted user
    input, so a typo'd date degrades to a plain string here instead of
    raising out of the parser — the rest of the mapping stays parseable and
    callers can report a precise advisory (e.g. validator W016) rather than
    treating the whole block as unparseable. Valid timestamps still
    construct ``date``/``datetime`` objects exactly as ``SafeLoader`` does.
    """


def _construct_lenient_timestamp(loader: yaml.SafeLoader, node: yaml.Node):
    try:
        return yaml.SafeLoader.construct_yaml_timestamp(loader, node)
    except ValueError:
        return loader.construct_scalar(node)


_LenientTimestampLoader.add_constructor("tag:yaml.org,2002:timestamp", _construct_lenient_timestamp)


def lenient_safe_load(text: str):
    """``yaml.safe_load`` that never raises on impossible timestamps.

    Untrusted-data hardening: a typo'd date degrades to a string (reported
    downstream as a malformed field) instead of raising ``ValueError``.
    Genuinely malformed YAML still raises ``yaml.YAMLError`` as usual.
    """
    return yaml.load(text, Loader=_LenientTimestampLoader)


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
    YAML — including pathologically nested input (which raises
    ``RecursionError``) — or if it parses to something that is not a mapping
    (e.g. a bare list), the document is still never rejected: ``({}, text)``
    is returned and the whole text, frontmatter lines included, is kept as
    the body. A load + re-save therefore never deletes the user's original
    frontmatter lines. An empty YAML section is treated as an empty mapping.

    Impossible timestamps such as ``2026-13-99`` do NOT make the block
    unparseable: the lenient loader degrades them to plain strings so the
    rest of the mapping is preserved (callers such as the validator report
    them as malformed-field advisories, e.g. W016, instead of E001).

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
        data = lenient_safe_load(block)
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
