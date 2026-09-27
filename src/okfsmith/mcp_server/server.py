"""MCP server over an OKF v0.2 knowledge bundle (FastMCP).

The bundle is loaded **once** at server startup; every read tool call
afterwards reads from the in-memory :class:`~okfsmith.core.bundle.Bundle`.

Eight tools are read-only (``index``, ``list``, ``search``, ``get``,
``neighbors``, ``traverse``, ``provenance``, ``diff``). Four more provide
**governed write-back**: ``preview_write_concept`` (side-effect-free dry
run), ``write_concept`` (create), ``update_concept`` (patch, with
human-reviewed trust protection), and ``audit_log`` (read the append-only
audit trail). Writes are atomic (temp file + rename), always land at the
``unverified`` trust tier, carry a ``provenance`` history in frontmatter,
are gated on the bundle validator (new errors ⇒ refused and rolled back),
never overwrite an existing concept, and are recorded in the append-only
``<bundle>/.okfsmith/audit.jsonl``.

FastMCP is imported lazily so the base ``okfsmith`` install stays light.
Without the ``mcp`` extra installed, :func:`build_server` / :func:`serve`
raise a clear :class:`RuntimeError` explaining how to install it.

Tool outputs are compact markdown (not giant JSON), suitable as an agent's
reading UI. Entry point for progressive disclosure: ``index()`` → the root
``index.md`` → ``get()`` / ``search()`` for detail.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from okfsmith.core import frontmatter as _fm
from okfsmith.core import temporal as _temporal
from okfsmith.core.bundle import Bundle, Concept, _slug_id, concept_path_for
from okfsmith.core.spec import (
    HUMAN_REVIEWED,
    MACHINE_CONFIRMED,
    RESERVED_FILES,
    UNVERIFIED,
    trust_tier,
    utc_now_iso,
)

#: Regex for markdown links ``[text](target)``; footnote refs ``[^x]`` are
#: excluded by requiring the char before ``[`` to not be ``^``.
_LINK_RE = re.compile(r"(?<!\^)\[([^\]]+)\]\(([^)\s]+)\)")


def _coerce_tags(frontmatter: Mapping) -> list[str]:
    """Return the concept's ``tags`` frontmatter as a list of strings.

    Hand-written frontmatter often carries a scalar (``tags: 5``,
    ``tags: single``) — valid YAML that would otherwise crash iteration.
    A scalar becomes a single-entry list; ``None`` becomes ``[]``. Never
    raises on malformed input (C10).
    """
    tags = frontmatter.get("tags")
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return [str(tags)]


def _trust_tier_safe(frontmatter: Any) -> str:
    """Derive the trust tier, tolerating non-mapping frontmatter.

    Delegates to :func:`~okfsmith.core.spec.trust_tier` — the canonical
    trust-tier implementation shared with the CLI — so MCP tools and the
    CLI always agree on a concept's tier (QA L6). That function treats a
    scalar ``verified`` (``verified: yes`` in hand-written YAML) as
    ``"unverified"``: with no actor information there is no basis for a
    trust tier. Never raises on malformed input (C10).
    """
    if not isinstance(frontmatter, Mapping):
        return UNVERIFIED
    return trust_tier(frontmatter)


def _coerce_limit(limit: Any, default: int) -> int:
    """Coerce *limit* to a non-negative int; unparseable input → *default*.

    Direct Python callers (tests, the chat REPL) can pass any object where
    the MCP transport would normally enforce an int — a clean fallback here
    keeps the tools' "never an exception" contract (L16).
    """
    try:
        coerced = int(limit)
    except (TypeError, ValueError):
        coerced = default
    return max(coerced, 0)


#: Hard ceiling for ``max_chunks`` on every tool (evidence-budget cap).
_MAX_CHUNKS = 50

#: Hard ceiling for ``traverse`` depth: bounds the BFS fan-out on dense graphs.
_MAX_TRAVERSE_DEPTH = 3

#: Lines per text chunk for the single-document tools (``get``, ``index``);
#: paging cuts at chunk boundaries so markdown is never split mid-line.
_TEXT_CHUNK_LINES = 50

#: Token-budget estimate: tokens ≈ characters / 4 (documented approximation).
_TOKEN_CHARS_PER_TOKEN = 4

#: Continuation-token payload version, so future formats stay distinguishable.
_CONT_TOKEN_VERSION = 1


def _coerce_chunks(value: Any, default: int) -> int:
    """Coerce ``max_chunks`` to ``1.._MAX_CHUNKS``; unparseable → *default*.

    Mirrors :func:`_coerce_limit` but with the evidence-budget ceiling: the
    tools' "never an exception" contract covers garbage budget input too.
    """
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return min(max(coerced, 1), _MAX_CHUNKS)


def _coerce_max_tokens(value: Any) -> int | None:
    """Coerce ``max_tokens`` to a token budget; ``None`` means unbounded.

    ``None``, unparseable input, and negative values all mean "no token
    budget" (unbounded) — documented here and in the docs table, not
    surprising. ``0`` is the explicit "no content output" budget: the page
    keeps no units, only the title, the truncation marker, and (when a
    token could progress) the continuation token. Positive values are
    used as-is.
    """
    if value is None:
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced >= 0 else None


def _encode_continuation(offset: int) -> str:
    """Encode a unit offset as an opaque continuation token."""
    payload = json.dumps(
        {"v": _CONT_TOKEN_VERSION, "o": max(int(offset), 0)},
        separators=(",", ":"),
    )
    encoded = base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii")
    return encoded.rstrip("=")


def _decode_continuation(token: Any) -> int | None:
    """Decode a continuation token to a unit offset; ``None`` when invalid.

    Never raises: over-long tokens, bad base64, bad JSON, a wrong payload
    version, or a non-integer/negative offset all decode to ``None`` so the
    caller can return a clean error instead of a traceback.
    """
    if not isinstance(token, str) or not token or len(token) > 256:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("v") != _CONT_TOKEN_VERSION:
        return None
    offset = payload.get("o")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return None
    return offset


def _fit_budget(
    page: list[str], start: int, total: int, max_tokens: int | None
) -> tuple[list[str], int, int]:
    """Trim *page* to the approximate token budget, whole units only.

    Units are added in order while the running estimate (characters // 4)
    stays within *max_tokens*. A positive budget always keeps at least one
    unit so a tiny budget still returns something; a zero budget keeps
    none ("no content output" — the truncation marker still says how many
    remain). Returns ``(kept, resume_offset, remaining)`` where the offset
    resumes at the first unshown unit.
    """
    kept = page
    if max_tokens is not None:
        kept = []
        used = 0
        for unit in page:
            if max_tokens <= 0:
                break
            cost = max(1, len(unit) // _TOKEN_CHARS_PER_TOKEN)
            if kept and used + cost > max_tokens:
                break
            kept.append(unit)
            used += cost
    resume = start + len(kept)
    return kept, resume, total - resume


def _text_chunks(text: str, lines_per_chunk: int = _TEXT_CHUNK_LINES) -> list[str]:
    """Split *text* into chunks of at most *lines_per_chunk* lines."""
    lines = text.splitlines()
    return [
        "\n".join(lines[i : i + lines_per_chunk])
        for i in range(0, max(len(lines), 1), lines_per_chunk)
    ]


def _concept_sha256(concept: Concept) -> str:
    """Hex SHA-256 of the concept's markdown body; never raises."""
    try:
        return hashlib.sha256(concept.body.encode("utf-8")).hexdigest()
    except Exception:
        return "unavailable"


def _concept_title(concept: Concept) -> str:
    """Frontmatter title, falling back to the concept id; never raises."""
    try:
        title = concept.frontmatter.get("title")
    except Exception:
        return concept.id
    if title is None:
        return concept.id
    return str(title).strip() or concept.id


def _sha256_file(path: Path) -> str | None:
    """Hex SHA-256 of a file's bytes (streamed); ``None`` on any I/O failure."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*?)\s*$", re.MULTILINE)
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")


def _footnote_definitions(body: str) -> dict[str, str]:
    """Map footnote label → definition text (first definition wins)."""
    definitions: dict[str, str] = {}
    for label, text in _FOOTNOTE_DEF_RE.findall(body or ""):
        definitions.setdefault(label.strip(), text.strip())
    return definitions


def _footnote_refs(body: str) -> list[str]:
    """Footnote labels referenced in *body*, in order, deduplicated."""
    seen: list[str] = []
    for label in _FOOTNOTE_REF_RE.findall(body or ""):
        label = label.strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def _coerce_sources(frontmatter: Any) -> list[Any]:
    """The concept's ``sources`` frontmatter as a list; never raises (C10).

    Hand-written frontmatter often carries a scalar (``sources: some-url``)
    — a scalar becomes a single-entry list, ``None`` becomes ``[]``.
    """
    if not isinstance(frontmatter, Mapping):
        return []
    sources = frontmatter.get("sources")
    if sources is None:
        return []
    if isinstance(sources, (str, Mapping)):
        return [sources]
    if isinstance(sources, (list, tuple)):
        return list(sources)
    return [sources]


def _render_source_entry(entry: Any) -> str:
    """One-line human rendering of a ``sources[]`` entry; never raises."""
    if isinstance(entry, Mapping):
        bits = []
        for key in ("id", "title", "resource", "author"):
            value = entry.get(key)
            if value:
                bits.append(f"{key}: {_one_line(str(value), 100)}")
        if bits:
            return "; ".join(bits)
        return _one_line(str(dict(entry)), 120)
    return _one_line(str(entry), 140)


def _relation_matches(link_text: str, target: str, relation_filter: str) -> bool:
    """True when *relation_filter* describes the link.

    The OKF link model has no explicit relation type, so the filter matches
    the prose-derived relation (the link text) or the target id — prefix or
    substring — case-insensitively.
    """
    needle = relation_filter.lower()
    return needle in link_text.lower() or needle in target.lower()


def _load_sync_state(bundle: Bundle) -> dict[str, Any] | None:
    """Read ``<bundle>/.okfsmith/sync-state.json``; ``None`` when unusable.

    Never raises: a missing file, a symlink (never followed — same rule as
    :meth:`Bundle.load`), invalid JSON, or a non-mapping payload all degrade
    to ``None`` so callers fall back to their documented behaviour.
    """
    try:
        from okfsmith.core.sync import SYNC_STATE_FILENAME
        from okfsmith.parsers.dedup import MANIFEST_DIRNAME
    except ImportError:
        return None
    try:
        path = bundle.root / MANIFEST_DIRNAME / SYNC_STATE_FILENAME
        if path.is_symlink() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _decode_state_key(key: Any) -> str:
    """Reverse the sync-state key encoding (``sync-key-b64:``); never raises."""
    prefix = "sync-key-b64:"
    if isinstance(key, str) and key.startswith(prefix):
        try:
            raw = base64.b64decode(key[len(prefix) :].encode("ascii"))
            return raw.decode("utf-8", errors="replace")
        except (ValueError, binascii.Error, UnicodeError):
            return key
    return str(key)


def _manifest_relpath(bundle: Bundle, raw_path: Any) -> str | None:
    """Bundle-relative form of a sync-state manifest path, or ``None``.

    Manifest paths live in untrusted bundle input
    (``<bundle>/.okfsmith/sync-state.json``), so they are never trusted
    blindly: only paths that stay inside the bundle root come back (as a
    bundle-relative POSIX path, safe to echo). Absolute outside paths and
    ``..`` escapes return ``None`` — callers emit an "untrusted manifest
    entry" marker instead of hashing or echoing them, so a crafted bundle
    can never turn ``diff()`` into a host-file SHA-256/existence oracle.

    The parent directory is resolved (catching escapes through a symlinked
    parent directory); the entry itself is never followed — a symlinked
    entry is rejected outright. The final path is then re-resolved so
    trailing ``..`` components (e.g. ``"sub/.."``, ``"a.md/.."``, or even
    ``".."``) normalize to the bundle root — or to an ancestor — instead of
    slipping past as a literal string; ``"."`` (the root itself) and any
    outside path return ``None``. Never raises.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path.strip())
    if not candidate.is_absolute():
        candidate = bundle.root / candidate
    try:
        parent = candidate.parent.resolve()
        root = bundle.root
        if parent != root and root not in parent.parents:
            return None
        final = parent / candidate.name
        if final.is_symlink():
            return None
        resolved = final.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        rel = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return None if rel == "." else rel


#: Cap for the pre-scan of a ``diff(against=...)`` directory: bounds the
#: filesystem walk so ``against="/"`` fails fast with a clean error
#: instead of crawling the whole disk.
_DIFF_AGAINST_MAX_FILES = 5000


def _scan_against_dir(other_root: Path) -> str | None:
    """Validate *other_root* as a ``diff()`` comparison target.

    Returns an ``Error: ...`` string when the directory must not be
    walked, ``None`` when it is safe to hand to :meth:`Bundle.load`. The
    scan is lazy and bails out past ``_DIFF_AGAINST_MAX_FILES`` total files
    ("too many files" error) instead of crawling huge trees; a directory
    with no markdown concept files at all is not a bundle (clean error).
    Never raises.
    """
    try:
        total = 0
        md = 0
        for _root, _dirs, files in os.walk(other_root):
            for name in files:
                total += 1
                if total > _DIFF_AGAINST_MAX_FILES:
                    return (
                        "Error: `against` has too many files "
                        f"(over {_DIFF_AGAINST_MAX_FILES}) — pass a bundle "
                        "directory, not a filesystem root."
                    )
                if name.endswith((".md", ".markdown")):
                    md += 1
    except OSError as exc:
        return f"Error: could not scan `against` directory {other_root!r}: {exc}."
    if md == 0:
        return (
            "Error: `against` does not look like a bundle directory "
            f"(no markdown concept files found under {other_root!r})."
        )
    return None


def _rank_concepts_legacy(
    bundle: Bundle, query: str, limit: int
) -> list[tuple[float, Concept]]:
    """Original case-insensitive substring scoring, best first.

    Fallback used when the BM25 engine (``okfsmith.search``) is unavailable
    or raises on malformed frontmatter. A word matching the concept id or
    title scores 3, description/tags 2, body 1; results are sorted by score
    descending, then concept id, and capped at *limit*.
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    scored: list[tuple[float, Concept]] = []
    for concept in bundle.iter_concepts():
        fm = concept.frontmatter
        title = str(fm.get("title", ""))
        description = str(fm.get("description", ""))
        tag_text = " ".join(_coerce_tags(fm))
        score = 0.0
        for word in words:
            if word in concept.id.lower() or word in title.lower():
                score += 3
            if word in description.lower() or word in tag_text.lower():
                score += 2
            if word in concept.body.lower():
                score += 1
        if score:
            scored.append((score, concept))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return scored[: max(limit, 0)]


def rank_concepts(
    bundle: Bundle, query: str, limit: int = 10
) -> list[tuple[float, Concept]]:
    """Score bundle concepts against *query*, best first.

    Thin shim over the BM25 engine
    :func:`okfsmith.search.search_bundle` (stdlib-only, shared with the
    ``okfsmith search`` CLI and the interactive chat REPL so all three rank
    identically): BM25 with field weights (id/title ×3, description/tags
    ×2, body ×1), stemming, quoted phrases, and ``-exclusions``. When the
    engine is not importable — or raises on malformed hand-written
    frontmatter it does not tolerate yet — the original substring scoring
    is used as a fallback, so this never raises (C10). Results are always
    returned score-descending with ties broken by concept id, whatever the
    engine hands back. The ``(bundle, query, limit=10)`` signature is kept
    for back-compat. Returns ``[]`` for an empty query.
    """
    limit = _coerce_limit(limit, 10)
    if not isinstance(query, str):
        query = "" if query is None else str(query)
    if not query.split():
        return []
    try:
        from okfsmith.search import search_bundle
    except ImportError:
        return _rank_concepts_legacy(bundle, query, limit)
    try:
        hits = search_bundle(bundle, query, limit)
    except (TypeError, AttributeError):
        # Scalar frontmatter (e.g. ``tags: 5``) the engine does not
        # tolerate: degrade to the legacy scorer rather than crash — the
        # MCP tools' "never an exception" contract wins over ranking
        # parity on malformed input (C10).
        return _rank_concepts_legacy(bundle, query, limit)
    # Enforce the documented contract (score desc, id tiebreak) on whatever
    # the engine returns; a no-op once the engine sorts correctly itself.
    hits.sort(key=lambda item: (-item[0], item[1].id))
    return hits[:limit]


def _require_fastmcp() -> Any:
    """Import ``fastmcp`` (the ``mcp`` extra) or raise a helpful error."""
    try:
        from fastmcp import FastMCP

        return FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP server requires the 'mcp' extra: "
            "install it with `pip install \"okfsmith[mcp]\"`."
        ) from exc


def _one_line(text: str, width: int = 140) -> str:
    """First non-empty line of *text*, whitespace-collapsed and truncated."""
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            return line if len(line) <= width else line[: width - 1] + "…"
    return ""


def _concept_label(concept: Concept) -> str:
    """One-line markdown summary of a concept: id, type, title, trust tier.

    The trust tier is derived defensively via :func:`_trust_tier_safe`
    (scalar ``verified`` frontmatter degrades to ``unverified`` per the
    canonical spec rule instead of raising — C10).
    """
    fm = concept.frontmatter
    ctype = str(fm.get("type", "?"))
    title = str(fm.get("title", concept.id))
    tier = _trust_tier_safe(fm)
    return f"**{concept.id}** — `{ctype}` · *{tier}* — {title}"


def _description(concept: Concept) -> str:
    """The concept's one-line description (frontmatter or first body line)."""
    desc = concept.frontmatter.get("description")
    if desc:
        return _one_line(str(desc))
    return _one_line(concept.body)


def _bundle_links(target: str) -> str | None:
    """Normalize a markdown link target to a bundle concept id, or None.

    Accepts bundle-relative absolute links (``/finance/profit``) and plain
    relative ids (``finance/profit``). External URLs, anchors, and fragment
    links return ``None``.
    """
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    candidate = target.split("#", 1)[0].strip().lstrip("/")
    return candidate or None


# ---------------------------------------------------------------------------
# Governed write-back helpers (module-level; used by the BundleTools methods
# ``preview_write_concept`` / ``write_concept`` / ``update_concept`` /
# ``audit_log``).
# ---------------------------------------------------------------------------

#: Markdown filename suffix (mirrors ``okfsmith.core.bundle._SUFFIX``).
_MD_SUFFIX = ".md"

#: Default frontmatter ``type`` for concepts created through write-back.
_WRITEBACK_TYPE = "Note"

#: Actor recorded in provenance for every write-back operation.
_WRITEBACK_ACTOR_PREFIX = "mcp:"

#: Audit log filename inside the bundle manifest dir (``<bundle>/.okfsmith/``,
#: the same directory that holds ``sync-state.json``).
_AUDIT_FILENAME = "audit.jsonl"

#: Input size guards for write-back (fail fast with a clean error).
_WRITEBACK_MAX_TITLE_CHARS = 500
_WRITEBACK_MAX_BODY_CHARS = 1_000_000
#: Max entries in a ``sources``/``links`` list. Input coercion copies and
#: recursively sanitizes every item, so an unbounded list is a CPU/memory
#: denial of service (QA M2): reject oversized lists before touching them.
_WRITEBACK_MAX_ITEMS = 1000

#: Age after which a leftover ``.preview-*.md`` validation temp file is
#: considered an orphan from a crashed preview and swept at session start
#: (QA L5). A live preview's temp file only exists for milliseconds, so a
#: 10-minute threshold can never catch one in flight.
_PREVIEW_ORPHAN_MAX_AGE_S = 10 * 60

#: Marker comment identifying the auto-generated links section at the end of
#: a write-back body, so ``update_concept`` can replace it instead of
#: stacking a second ``## Links`` section.
_LINKS_SECTION_MARKER = "<!-- okfsmith:mcp:links -->"

#: A rendered auto link row: ``- [text](target)`` (target has no spaces by
#: construction of the coercion below).
_LINK_ROW_RE = re.compile(r"\s*-\s*\[[^\]]*\]\([^)\s]+\)\s*")


def _coerce_nonempty_text(value: Any) -> str | None:
    """``str(value).strip()``, or ``None`` when blank.

    Never raises: ``None`` and whitespace-only input both become ``None``
    so callers can emit a clean "empty title/body" error.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text.strip() or None


def _coerce_bool(value: Any) -> bool:
    """Coerce *value* to bool; never raises.

    Real bools pass through; numbers follow truthiness; strings accept
    ``1/true/yes/y/on`` (case-insensitive); anything else falls back to
    ``bool(value)``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _coerce_item_list(value: Any) -> list[Any]:
    """Coerce ``sources``/``links`` input to a list; never raises.

    ``None`` → ``[]``; a scalar → a single-entry list (mirroring
    :func:`_coerce_tags`); a list/tuple → a shallow copy.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _check_item_count(name: str, value: Any) -> str | None:
    """Return an ``Error: ...`` string when a ``sources``/``links`` input
    exceeds :data:`_WRITEBACK_MAX_ITEMS`; else ``None``.

    Checked *before* coercion copies and recursively sanitizes the items
    (QA M2). Non-list scalars become single-entry lists, so only sized
    list/tuple inputs can trip the cap. Never raises.
    """
    if isinstance(value, (list, tuple)) and len(value) > _WRITEBACK_MAX_ITEMS:
        return (
            f"Error: `{name}` has {len(value)} items "
            f"(max {_WRITEBACK_MAX_ITEMS}) — split it into smaller calls."
        )
    return None


def _realpath_within(root: Path, path: Path) -> bool:
    """``True`` when *path* resolves inside *root* after symlinks.

    A lexical ``relative_to`` check is fooled by a symlinked parent
    directory (``bundle/sub -> /tmp/outside`` makes ``sub/evil.md`` escape
    while looking contained — QA M1). Resolving both sides with
    :func:`os.path.realpath` (which also resolves symlink components of
    not-yet-existing paths) closes that hole. Never raises.
    """
    try:
        real_root = os.path.realpath(root)
        real_path = os.path.realpath(path)
    except OSError:
        return False
    try:
        Path(real_path).relative_to(real_root)
    except ValueError:
        return False
    return True


def _prune_empty_parents(start: Path, stop: Path) -> None:
    """Remove empty directories from *start* up to (not incl.) *stop*.

    Undoes the parent-directory creation that preview validation performs
    for nested ids (QA L4): a directory that still holds files — pre-
    existing or written concurrently — is not empty, so the walk stops
    there. Never raises.
    """
    try:
        current = start
        while current != stop and current.is_dir():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    except OSError:
        pass


def _sweep_stale_preview_files(root: Path) -> None:
    """Delete orphaned ``.preview-*.md`` validation temp files.

    A crashed preview can leave its temp ``.md`` file behind, and the next
    bundle load would read it as a phantom concept (QA L5). Files older
    than :data:`_PREVIEW_ORPHAN_MAX_AGE_S` are orphans by definition — a
    live preview's temp file only exists for milliseconds — so sweeping
    them at session start can never catch an in-flight preview, even with
    concurrent server sessions. Never raises.
    """
    try:
        now = time.time()
        for tmp in root.rglob(".preview-*.md"):
            try:
                if tmp.is_file() and not tmp.is_symlink():
                    if now - tmp.stat().st_mtime > _PREVIEW_ORPHAN_MAX_AGE_S:
                        tmp.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        pass


def _strip_verified_markers(node: Any) -> Any:
    """Deep-copy *node* with every ``verified`` mapping key removed.

    Write-back output must always be ``unverified`` (spec §5.3: only
    ``human:``-prefixed actors grant verification), so any ``verified``
    markers smuggled into caller-supplied ``sources``/``links`` structures
    are stripped before they can reach frontmatter. Never raises.
    """
    if isinstance(node, Mapping):
        return {
            key: _strip_verified_markers(val)
            for key, val in node.items()
            if key != "verified"
        }
    if isinstance(node, (list, tuple)):
        return [_strip_verified_markers(val) for val in node]
    return node


def _sanitize_yaml_value(value: Any) -> Any:
    """Deep-convert *value* to YAML-safe plain types.

    ``yaml.safe_dump`` raises on exotic objects (sets, arbitrary class
    instances) that can arrive through direct Python calls; this converts
    anything that is not ``None``/``bool``/``int``/``float``/``str``/list/
    dict via ``str()`` (mapping keys via ``str()`` too), so serialization
    of caller input can never crash. Never raises.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        try:
            items = list(value.items())
        except Exception:
            return str(value)
        return {str(k): _sanitize_yaml_value(v) for k, v in items}
    if isinstance(value, (list, tuple)):
        return [_sanitize_yaml_value(v) for v in value]
    try:
        return str(value)
    except Exception:
        return ""


def _provenance_entry(
    action: str, actor: str, sources: list[Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """One frontmatter ``provenance`` history entry; never raises."""
    entry: dict[str, Any] = {
        "action": str(action),
        "actor": str(actor),
        "at": utc_now_iso(),
    }
    if sources:
        entry["sources"] = list(sources)
    for key, val in extra.items():
        entry[str(key)] = _sanitize_yaml_value(val)
    return entry


def _coerce_link_rows(links: list[Any]) -> list[str]:
    """Render ``links`` input to ``- [text](target)`` markdown rows.

    Each item is a concept-id string (link text = the id) or a mapping
    with ``target`` (or ``id``) and optional ``text``. Blank targets are
    dropped; targets are whitespace-collapsed so a row can never break the
    ``[text](target)`` shape. Never raises.
    """
    rows: list[str] = []
    for link in links:
        if isinstance(link, Mapping):
            target = link.get("target", link.get("id", ""))
            text = link.get("text", target)
        else:
            target = link
            text = link
        target = " ".join(str(target).split())
        text = " ".join(str(text).split()) or target
        if target:
            rows.append(f"- [{text}]({target})")
    return rows


def _strip_links_section(body: str) -> str:
    """Remove an auto-generated links section from *body*.

    Only a ``## Links`` section carrying the
    :data:`_LINKS_SECTION_MARKER` comment is removed — a hand-written
    ``## Links`` section is never touched. The section is consumed
    wherever it appears: blank lines and ``- [text](target)`` rows after
    the marker belong to the section, so text trailing the section no
    longer causes a second ``## Links`` section to stack on update
    (QA L1). Anything that is not a blank line or a link row ends the
    section and is preserved. Never raises.
    """
    head = "## Links\n\n" + _LINKS_SECTION_MARKER
    idx = body.rfind(head)
    if idx == -1:
        return body
    tail = body[idx + len(head) :]
    pos = 0
    for line in tail.split("\n"):
        if not line.strip() or _LINK_ROW_RE.fullmatch(line):
            pos += len(line) + 1  # +1 for the "\n" split off
        else:
            break
    stripped = body[:idx] + tail[pos:]
    # A mid-body removal can leave a run of blank lines; collapse.
    return re.sub(r"\n{3,}", "\n\n", stripped)


def _links_section(body: str) -> str:
    """Return the auto-generated links section of *body*, or ``""``.

    Only a ``## Links`` section carrying :data:`_LINKS_SECTION_MARKER`
    is recognized (same rule as :func:`_strip_links_section`); a
    hand-written ``## Links`` section is never treated as generated.
    The returned text is in canonical form
    (``## Links\\n\\n<marker>\\n<rows>``) so it can be re-attached to a
    replacement body. Never raises.
    """
    head = "## Links\n\n" + _LINKS_SECTION_MARKER
    idx = body.rfind(head)
    if idx == -1:
        return ""
    rows: list[str] = []
    for line in body[idx + len(head) :].split("\n"):
        if _LINK_ROW_RE.fullmatch(line):
            rows.append(line)
        elif line.strip():
            break
    if not rows:
        return ""
    return head + "\n" + "\n".join(rows)


def _with_links_section(body: str, links: list[Any]) -> str:
    """Return *body* with the auto-generated links section (re)built.

    A previous auto-generated section (marker-identified) is replaced, not
    stacked; with no valid links the section is removed entirely.
    """
    rows = _coerce_link_rows(links)
    base = _strip_links_section(body).rstrip("\n")
    if not rows:
        return base + "\n" if base else ""
    section = "## Links\n\n" + _LINKS_SECTION_MARKER + "\n" + "\n".join(rows)
    return f"{base}\n\n{section}\n" if base else f"{section}\n"


def _build_writeback_document(
    *,
    title: str,
    body: str,
    sources: list[Any],
    links: list[Any],
    actor: str,
    ts: str,
) -> tuple[dict[str, Any], str, str]:
    """Build the would-be concept document for a write-back create.

    Returns ``(frontmatter, body_with_links, serialized_text)``. Governance
    is baked in: ``sources``/``links`` are sanitized to YAML-safe types and
    stripped of any ``verified`` markers, the ``links`` become a marked
    auto-generated section, and the frontmatter carries ``type: Note``, a
    ``generated: {by, at}`` block mirroring the CLI ingest shape, the input
    ``sources``, and a ``provenance`` history entry (``action: created``).
    No ``verified`` key is ever emitted, so
    :func:`~okfsmith.core.spec.trust_tier` always derives ``"unverified"``.
    Never raises on plain-data input.
    """
    clean_sources = _sanitize_yaml_value(_strip_verified_markers(list(sources)))
    clean_links = _sanitize_yaml_value(_strip_verified_markers(list(links)))
    full_body = _with_links_section(body, clean_links)
    frontmatter: dict[str, Any] = {
        "type": _WRITEBACK_TYPE,
        "title": title,
        "description": _one_line(full_body),
        "generated": {"by": actor, "at": ts},
    }
    if clean_sources:
        frontmatter["sources"] = clean_sources
    frontmatter["provenance"] = [
        _provenance_entry("created", actor, sources=clean_sources or None)
    ]
    return frontmatter, full_body, _fm.serialize_frontmatter(frontmatter, full_body)


def _atomic_write_bytes(
    path: Path, data: bytes, *, overwrite: bool = False
) -> None:
    """Write *data* to *path* atomically: temp file + rename.

    The temp file lives in the same directory (so the rename never crosses
    filesystems) and is removed on any failure — a crash can never leave a
    half-written concept file behind. With ``overwrite=False`` (creates) an
    already-existing *path* raises :class:`FileExistsError` instead of
    clobbering it; symlinks are always refused, never followed. The rename
    goes through the module-level :data:`_os_replace` alias so tests can
    simulate rename failure without touching the global ``os`` module.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise FileExistsError(f"refusing to touch symlink: {path}")
    if not overwrite and path.exists():
        raise FileExistsError(f"refusing to overwrite existing path: {path}")
    tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_bytes(data)
        _os_replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_text(
    path: Path, text: str, *, overwrite: bool = False
) -> None:
    """Write *text* to *path* atomically (UTF-8), via
    :func:`_atomic_write_bytes`."""
    _atomic_write_bytes(path, text.encode("utf-8"), overwrite=overwrite)


#: Alias of :func:`os.replace` used by :func:`_atomic_write_bytes`; a
#: module-level seam so tests can simulate rename failure.
_os_replace = os.replace


def _audit_path(bundle: Bundle) -> Path:
    """Path of the append-only audit log: ``<bundle>/.okfsmith/audit.jsonl``.

    The manifest directory is the same one that holds ``sync-state.json``
    (see :func:`_load_sync_state`); the filename is fixed, so caller input
    can never influence the path (no traversal surface).
    """
    from okfsmith.parsers.dedup import MANIFEST_DIRNAME

    return bundle.root / MANIFEST_DIRNAME / _AUDIT_FILENAME


def _append_audit(
    bundle: Bundle,
    *,
    actor: str,
    action: str,
    concept_id: str,
    summary: str,
) -> bool:
    """Append one JSON line to the audit log; ``True`` on success.

    The entry carries a UTC ISO-8601 timestamp, the actor, the action, the
    concept id, and a one-line summary. A symlinked audit file is never
    followed. ``False`` (never an exception) on any failure — callers roll
    the concept write back so there are no unaudited writes.
    """
    try:
        path = _audit_path(bundle)
        if path.is_symlink():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": utc_now_iso(),
            "actor": str(actor),
            "action": str(action),
            "concept_id": str(concept_id),
            "summary": _one_line(str(summary), 200),
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except (OSError, ValueError):
        return False


def _read_audit(bundle: Bundle, limit: int) -> list[dict[str, Any]]:
    """Read up to *limit* audit entries (oldest first); never raises.

    Corrupt lines are skipped; a missing file, a symlink (never followed),
    or any I/O failure yields ``[]``.
    """
    if limit <= 0:
        return []
    try:
        path = _audit_path(bundle)
        if path.is_symlink() or not path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                entries.append(obj)
    except (OSError, ValueError, UnicodeError):
        return []
    return entries[max(0, len(entries) - limit) :]


def _verifier_names(frontmatter: Mapping) -> list[str]:
    """The ``by`` actors of a concept's ``verified`` markers; never raises."""
    verified = frontmatter.get("verified") if isinstance(frontmatter, Mapping) else None
    if isinstance(verified, Mapping):
        verified = [verified]
    if not isinstance(verified, (list, tuple)):
        return []
    names: list[str] = []
    for entry in verified:
        by = entry.get("by") if isinstance(entry, Mapping) else None
        if by:
            names.append(str(by))
    return names


class BundleTools:
    """The twelve MCP tool functions, bound to one loaded bundle.

    Instances are created by :func:`build_server`; each method is registered
    as an MCP tool. They are also directly callable (as the tests do), with
    no MCP transport required.

    Eight tools are read-only (``index``, ``list``, ``search``, ``get``,
    ``neighbors``, ``traverse``, ``provenance``, ``diff``) and four provide
    governed write-back (``preview_write_concept``, ``write_concept``,
    ``update_concept``, ``audit_log``) — see each method's docstring for
    the governance contract.

    Every method returns compact markdown text. Lookup failures return a
    plain-English ``Error: ...`` string — never an exception — so agents get
    a recoverable message instead of a tool crash. Every method also accepts
    the evidence-budget parameters ``max_chunks`` (concept items per
    response — notes and section headers sit outside the budget, hard cap
    50), ``max_tokens`` (approximate output budget: ``None``/negative/
    unparseable = unbounded, ``0`` = no content output with a truncation
    marker) and ``continuation_token`` (opaque paging cursor — a result
    offset, not bound to a specific tool or query); budgets cut at whole
    units, never mid-item, and an invalid or out-of-range token returns a
    clean error.
    """

    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle
        # Sweep orphaned preview temp files from crashed sessions so they
        # can never load as phantom concepts (QA L5).
        _sweep_stale_preview_files(bundle.root)
        # The bundle may have been loaded *before* the sweep above (the
        # caller owns the Bundle.load call), leaving phantom concepts in
        # the in-memory index for files that are now gone. Evict any
        # in-memory concept backed by a `.preview-*.md` temp file — those
        # are never real concepts, so dropping them from the index is
        # always safe (the on-disk temp file itself is untouched).
        for concept in list(bundle.iter_concepts()):
            try:
                name = concept.path.name
            except OSError:
                continue
            if name.startswith(".preview-") and name.endswith(".md"):
                bundle._concepts.pop(concept.id, None)
        # Built once: the bundle is loaded once at server startup, so the
        # supersession graph is stable for the server's lifetime.
        self._sindex = _temporal.SupersessionIndex.from_bundle(bundle)

    # -- shared rendering ----------------------------------------------------
    def _render_paged(
        self,
        *,
        title: str,
        whole: str,
        sections: list[tuple[str | None, list[str]]],
        notes: list[str] | tuple[str, ...] = (),
        max_chunks: Any,
        chunk_default: int,
        max_tokens: Any,
        continuation_token: Any,
    ) -> str:
        """Render a budgeted, pageable markdown response from *sections*.

        *sections* is an ordered list of ``(header, items)`` — ``header`` a
        ``## ...`` section line (or ``None``) and ``items`` the concept item
        lines belonging to it; *notes* are first-page-only context lines
        (supersession notices, comparison notes). Only *items* consume the
        ``max_chunks``/``max_tokens`` budgets and the continuation offset —
        notes and section headers sit outside the paged flow, so a page
        boundary never drops an item and the ``…[truncated, N more]``
        marker always counts remaining *items*.

        When everything fits on the first page with no budgets applied,
        returns *whole* byte-identical (the backward-compat fast path:
        old callers see old output). Otherwise returns ``# {title}``
        (``(continued)`` when resuming), the page-1 notes, each section's
        header (every header on page 1 as a structural overview; sticky
        headers for sections with items on continuation pages), the page's
        items, and — when items remain — the ``…[truncated, N more]``
        marker plus the next ``continuation_token`` (omitted when the
        token could not progress, e.g. a zero token budget). An invalid
        or out-of-range token returns a clean error, never a traceback.
        """
        start = 0
        if continuation_token:
            decoded = _decode_continuation(continuation_token)
            if decoded is None:
                return (
                    "Error: invalid `continuation_token` — it is malformed "
                    "or for a newer token format. Tokens are opaque paging "
                    "cursors (a result offset); they are not bound to a "
                    "specific tool or query. Omit it to start from the "
                    "first page."
                )
            start = decoded
        # Flatten to (section index, item line): the offset counts items
        # only, identically on every page, so notes can never shift it.
        flat: list[tuple[int, str]] = [
            (section_no, line)
            for section_no, (_header, lines) in enumerate(sections)
            for line in lines
        ]
        total = len(flat)
        if start > total or (total and start == total):
            return (
                "Error: `continuation_token` is out of range — its offset "
                "is past the end of this result (the result set may have "
                "changed since the token was issued). Omit it to start "
                "from the first page."
            )
        chunks = _coerce_chunks(max_chunks, chunk_default)
        budget = _coerce_max_tokens(max_tokens)
        page = [line for _, line in flat[start : start + chunks]]
        kept, resume, remaining = _fit_budget(page, start, total, budget)
        if start == 0 and remaining == 0:
            return whole
        shown: dict[int, list[str]] = {}
        for section_no, line in flat[start : start + len(kept)]:
            shown.setdefault(section_no, []).append(line)
        lines = [f"# {title} (continued)" if start else f"# {title}"]
        if start == 0:
            lines.extend(notes)
        for section_no, (header, _lines) in enumerate(sections):
            if start == 0 or section_no in shown:
                if header is not None:
                    lines.append(header)
                lines.extend(shown.get(section_no, []))
        if remaining > 0:
            lines.append(f"…[truncated, {remaining} more]")
            if resume > start:
                # A token that cannot progress (a zero token budget keeps
                # no items) would loop forever: omit it rather than lie.
                lines.append(
                    f'_Pass `continuation_token="{_encode_continuation(resume)}"` '
                    "for the next page._"
                )
        return "\n".join(lines)

    def _temporal_note(self, concept: Concept, now: Any) -> str | None:
        """Human note for a non-current temporal status; ``None`` when current.

        Never raises: temporal fields are untrusted frontmatter (P2).
        """
        try:
            status = self._sindex.status(concept, now)
        except Exception:
            return None
        if status.name == "current":
            return None
        if status.name == "superseded":
            return f"superseded by `{status.superseded_by}`"
        return status.name.replace("_", " ")  # "expired" / "not yet valid"

    def _is_superseded(self, concept: Concept, now: Any) -> bool:
        """True when *concept* is superseded at *now*; never raises."""
        try:
            return self._sindex.status(concept, now).name == "superseded"
        except Exception:
            return False

    def _currency_rank(self, concept: Concept, now: Any) -> int:
        """Sort key for currency-aware ordering (P2): current, windowed, superseded."""
        try:
            name = self._sindex.status(concept, now).name
        except Exception:
            return 0
        return {"current": 0, "superseded": 2}.get(name, 1)

    # -- progressive disclosure entry point ---------------------------------
    def index(
        self,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Return the bundle's root index.md — the map of the whole knowledge base.

        This is the starting point for progressive disclosure: the index
        lists every concept with a one-line summary. Read this first to
        orient yourself, then use `search` to find concepts by keyword and
        `get` to read a concept in full. Each index entry's concept id can
        be passed to `get`, `neighbors`, or `list` for deeper exploration.

        Evidence budgets: `max_chunks` caps the 50-line text chunks returned
        (default 50, hard cap 50), `max_tokens` is an approximate output
        budget (`None`/negative = unbounded; `0` = no content, marker only),
        and `continuation_token` pages through long indexes — budgets cut at
        chunk boundaries, never mid-line.

        Returns the raw index.md text; if the bundle has no index.md, says
        so and suggests `list` instead.
        """
        if not self.bundle.index_text:
            return (
                "This bundle has no root index.md. Use the `list` tool to see "
                "all concepts, or `search` to find one by keyword."
            )
        return self._render_paged(
            title="Bundle index",
            whole=self.bundle.index_text,
            sections=[(None, _text_chunks(self.bundle.index_text))],
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- inventory -----------------------------------------------------------
    def list(
        self,
        filter_type: str = "",
        limit: int = 50,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """List every concept in the bundle: id, type, trust tier, and title.

        Use this for a full inventory of the knowledge base, or to narrow
        down by concept type. `filter_type` matches the concept's frontmatter
        `type` (case-insensitive substring, e.g. "Metric", "Playbook",
        "Attested Computation"). `limit` caps the number of rows returned
        (non-numeric input falls back to the default 50).

        Evidence budgets: `max_chunks` caps the concept rows per response
        (default 50, hard cap 50; the rows are the budget — there are no
        notes or section headers here), `max_tokens` is an approximate
        output budget (`None`/negative = unbounded; `0` = no content,
        marker only), and `continuation_token` pages through long
        inventories.

        Returns a markdown list ordered by concept id. For the full text of
        any concept, pass its id to `get`.
        """
        concepts = list(self.bundle.iter_concepts())
        if filter_type:
            needle = str(filter_type).lower()
            concepts = [
                c
                for c in concepts
                if needle in str(c.frontmatter.get("type", "")).lower()
            ]
        concepts = concepts[: _coerce_limit(limit, 50)]
        if not concepts:
            return (
                "No concepts found."
                if not filter_type
                else f"No concepts found with type matching {filter_type!r}."
            )
        units = [f"- {_concept_label(c)}" for c in concepts]
        title = f"Concepts ({len(units)})"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(units),
            sections=[(None, units)],
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- keyword search ------------------------------------------------------
    def _search_hits(
        self, query: str, limit: int, include_superseded: bool
    ) -> tuple[list[tuple[float, Concept]], int]:
        """Ranked ``(score, concept)`` hits plus the superseded-hidden count.

        Currency-aware (P2): superseded concepts are hidden unless
        *include_superseded* — the same default the ``okfsmith search`` CLI
        uses. Falls back to :func:`rank_concepts` when the BM25 engine is
        unavailable or rejects malformed frontmatter, so the tools' "never
        an exception" contract wins over ranking parity on hostile input.
        """
        try:
            from okfsmith.search import search_bundle_detailed
        except ImportError:
            return rank_concepts(self.bundle, query, limit), 0
        try:
            result = search_bundle_detailed(
                self.bundle,
                query,
                limit,
                include_superseded=bool(include_superseded),
            )
        except (TypeError, AttributeError):
            return rank_concepts(self.bundle, query, limit), 0
        return result.hits, result.superseded_hidden

    def search(
        self,
        query: str,
        limit: int = 10,
        include_superseded: bool = False,
        max_chunks: int = 10,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Search concepts by id, title, description, tags, and body text.

        Full-text BM25 ranking (stdlib-only ``okfsmith.search`` engine,
        shared with the ``okfsmith search`` CLI and the chat REPL so all
        three rank identically): field weights id/title ×3,
        description/tags ×2, body ×1, with stemming, quoted phrases, and
        ``-exclusions``. `limit` caps the number of results (default 10;
        non-numeric input falls back to 10).

        Currency-aware (P2): superseded concepts are hidden by default and
        reported as a count; pass `include_superseded=True` to reveal them
        (shown last). Evidence budgets: `max_chunks` caps the hits per
        response (default 10, hard cap 50 — the hidden-superseded note sits
        outside the budget), `max_tokens` is an approximate output budget
        (`None`/negative = unbounded; `0` = no content, marker only), and
        `continuation_token` pages through long result lists.

        Returns a compact markdown list: concept id, type, trust tier
        (`human-reviewed` > `machine-confirmed` > `unverified`), title, and
        a one-line description. Use `get` with a result's id to read the
        full concept. A missing or blank query returns a clean error,
        never an exception.
        """
        if not isinstance(query, str) or not query.split():
            return "Error: `query` is empty — provide a keyword to search for."
        limit = _coerce_limit(limit, 10)
        hits, hidden = self._search_hits(query, limit, include_superseded)
        if not hits:
            return f"No concepts match {query!r}. Try broader keywords or use `list`."
        units = [f"- {_concept_label(c)}\n  {_description(c)}" for _, c in hits]
        notes = (
            [
                f"_{hidden} superseded concept(s) hidden — "
                "pass `include_superseded=True` to reveal._"
            ]
            if hidden
            else []
        )
        title = f"Search: {query} ({len(units)} result(s))"
        whole = f"# {title}\n\n" + "\n".join(units)
        if notes:
            whole += "\n\n" + "\n".join(notes)
        return self._render_paged(
            title=title,
            whole=whole,
            sections=[(None, units)],
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=10,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- full concept --------------------------------------------------------
    def get(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Read one concept in full: its YAML frontmatter followed by its markdown body.

        `concept_id` is the concept's path id, e.g. "finance/revenue" (see
        `list` or `search` for valid ids). The frontmatter carries the OKF
        metadata — `type`, `title`, `description`, `tags`, trust info
        (`generated` / `verified`), and `sources` — and the body is the
        knowledge content itself.

        Evidence budgets: `max_chunks` caps the 50-line text chunks returned
        (default 50, hard cap 50), `max_tokens` is an approximate output
        budget (`None`/negative = unbounded; `0` = no content, marker only),
        and `continuation_token` pages through long documents — budgets cut
        at chunk boundaries, never mid-line.

        Returns the concept document (frontmatter + body). If the id does
        not exist, returns a clean "not found" error suggesting how to find
        valid ids.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        whole = _fm.serialize_frontmatter(concept.frontmatter, concept.body)
        return self._render_paged(
            title=f"Get {concept_id}",
            whole=whole,
            sections=[(None, _text_chunks(whole))],
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- link graph ----------------------------------------------------------
    def neighbors(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Show a concept's outgoing links and incoming backlinks.

        Outgoing links are the markdown links in the concept's own body.
        Incoming links (backlinks) are found by scanning every other
        concept's body for links pointing at this concept. Each link is
        shown with its id, type, and the link text — which is the
        prose-derived description of the relation (e.g. "computed by [the
        revenue computation](/computations/revenue)").

        Evidence budgets: `max_chunks` caps the link rows per response
        (default 50, hard cap 50 — the `## Outgoing`/`## Incoming` headers
        sit outside the budget), `max_tokens` is an approximate output
        budget (`None`/negative = unbounded; `0` = no content, marker only),
        and `continuation_token` pages through long neighborhoods.

        Returns two sections, "Outgoing" and "Incoming". A missing concept
        returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )

        outgoing: list[tuple[str, str]] = []
        for text, target in _LINK_RE.findall(concept.body):
            linked_id = _bundle_links(target)
            if linked_id:
                outgoing.append((linked_id, text.strip()))

        incoming: list[tuple[str, str, str]] = []
        for other in self.bundle.iter_concepts():
            if other.id == concept_id:
                continue
            for text, target in _LINK_RE.findall(other.body):
                linked_id = _bundle_links(target)
                if linked_id == concept_id:
                    incoming.append(
                        (
                            other.id,
                            str(other.frontmatter.get("type", "?")),
                            text.strip(),
                        )
                    )
                    break

        def _fmt_out(linked_id: str, text: str) -> str:
            linked = self.bundle.get(linked_id)
            label = _concept_label(linked) if linked else f"**{linked_id}** (missing)"
            return f"- {label} — linked as: \"{text}\""

        def _fmt_in(source_id: str, source_type: str, text: str) -> str:
            return f"- **{source_id}** (`{source_type}`) — linked as: \"{text}\""

        out_header = f"## Outgoing ({len(outgoing)})"
        in_header = f"## Incoming ({len(incoming)})"
        # Fillers ("_No … links._") appear only in the unpaged `whole`
        # output: in the paged flow the header's (0) count already says the
        # section is empty, and fillers must not consume the item budget.
        out_rows = [_fmt_out(lid, text) for lid, text in outgoing]
        in_rows = [_fmt_in(sid, stype, text) for sid, stype, text in incoming]
        whole_units = [
            out_header,
            *(out_rows or ["_No outgoing links._"]),
            "",
            in_header,
            *(in_rows or ["_No incoming links._"]),
        ]
        title = f"Links for {concept_id}"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(whole_units),
            sections=[(out_header, out_rows), (in_header, in_rows)],
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )


    # -- graph traversal -----------------------------------------------------
    def traverse(
        self,
        concept_id: str,
        depth: int = 1,
        relation_filter: str | None = None,
        include_superseded: bool = False,
        max_chunks: int = 10,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Walk the concept link graph outward from one concept (breadth-first).

        `concept_id` is the entry point; `depth` is how many link hops to
        expand (capped at 3 — deeper requests are capped, not rejected).
        `relation_filter` optionally restricts which links are followed: the
        OKF link model has no explicit relation type, so the filter matches
        the prose-derived relation (the link text, e.g. "computed by") or the
        target id (prefix or substring), case-insensitively.

        Currency-aware (P2): superseded concepts are hidden by default (and
        never traversed through); pass `include_superseded=True` to reveal
        them. Within each depth level, current concepts sort before
        expired/not-yet-valid ones. The walk is cycle-safe (a visited set)
        and deterministic (links expand in target-id order).

        Evidence budgets: `max_chunks` caps the concepts per response
        (default 10, hard cap 50 — the `## Depth N` headers and the result
        notes sit outside the budget), `max_tokens` is an approximate output
        budget (`None`/negative = unbounded; `0` = no content, marker only),
        and `continuation_token` pages through large neighborhoods.

        Returns one section per depth level with a one-line summary per
        concept plus the link text that led to it. A missing concept
        returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        requested_depth = _coerce_limit(depth, 1)
        max_depth = min(requested_depth, _MAX_TRAVERSE_DEPTH)
        filt = str(relation_filter).strip().lower() if relation_filter else ""
        now = _temporal.utcnow()

        visited = {concept.id}
        levels: list[list[tuple[str, str, Concept]]] = []
        hidden = 0
        dangling = 0
        frontier = [concept.id]
        for _ in range(max_depth):
            found: list[tuple[str, str, Concept]] = []
            next_frontier: list[str] = []
            for parent_id in frontier:
                parent = self.bundle.get(parent_id)
                if parent is None:
                    continue
                targets: dict[str, str] = {}
                for text, target in _LINK_RE.findall(parent.body or ""):
                    linked_id = _bundle_links(target)
                    if linked_id and linked_id not in targets:
                        targets[linked_id] = text.strip()
                for linked_id, text in sorted(targets.items()):
                    if filt and not _relation_matches(text, linked_id, filt):
                        continue
                    if linked_id in visited:
                        continue
                    visited.add(linked_id)
                    node = self.bundle.get(linked_id)
                    if node is None:
                        dangling += 1
                        continue
                    if not include_superseded and self._is_superseded(node, now):
                        hidden += 1
                        continue
                    found.append((parent_id, text, node))
                    next_frontier.append(linked_id)
            if not found:
                break
            found.sort(
                key=lambda item: (self._currency_rank(item[2], now), item[2].id)
            )
            levels.append(found)
            frontier = next_frontier

        notes: list[str] = []
        start_note = self._temporal_note(concept, now)
        if start_note:
            notes.append(f"_Note: **{concept.id}** is {start_note}._")
        if requested_depth > _MAX_TRAVERSE_DEPTH:
            notes.append(f"_Depth capped at {_MAX_TRAVERSE_DEPTH}._")
        if filt:
            notes.append(
                f'_Relation filter: "{relation_filter}" — matched against '
                "link text and target id._"
            )
        total = sum(len(items) for items in levels)
        notes.append(
            f"_Reached {total} concept(s) across {len(levels)} depth level(s) "
            f"(depth ≤ {max_depth})._"
        )
        if hidden:
            notes.append(
                f"_{hidden} superseded concept(s) hidden — "
                "pass `include_superseded=True` to reveal._"
            )
        if dangling:
            notes.append(f"_{dangling} link(s) point to missing concepts._")

        sections: list[tuple[str | None, list[str]]] = []
        whole_units: list[str] = []
        for depth_no, items in enumerate(levels, start=1):
            header = f"## Depth {depth_no} ({len(items)})"
            rows: list[str] = []
            for parent_id, text, node in items:
                line = f'- {_concept_label(node)} — via "{text}" from `{parent_id}`'
                note = self._temporal_note(node, now)
                if note:
                    line += f" _({note})_"
                rows.append(line)
            sections.append((header, rows))
            whole_units.extend([header, *rows])
        if not whole_units:
            # Only in the unpaged `whole`: the paged flow never needs a
            # filler, and it must not consume the item budget.
            whole_units.append("_No linked concepts found within the requested depth._")

        title = f"Traverse from {concept_id} (depth ≤ {max_depth})"
        head = [f"# {title}", ""]
        if notes:
            head.extend([*notes, ""])
        return self._render_paged(
            title=title,
            whole="\n".join(head + whole_units),
            sections=sections,
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=10,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- provenance ----------------------------------------------------------
    def _ingested_sources(
        self, concept_id: str
    ) -> tuple[list[tuple[str, str | None]], int]:
        """Sync-state records listing *concept_id*: ``(records, skipped)``.

        ``records`` is ``[(bundle-relative path, sha256)]`` — only for
        manifest entries whose paths stay inside the bundle root (see
        :func:`_manifest_relpath`); ``skipped`` counts entries with
        outside/unsafe paths (untrusted manifest entries, never hashed or
        echoed). ``([], 0)`` when there is no usable state. Never raises.
        """
        state = _load_sync_state(self.bundle)
        if not state:
            return [], 0
        records = state.get("sources")
        if not isinstance(records, dict):
            return [], 0
        found: list[tuple[str, str | None]] = []
        skipped = 0
        for key, record in records.items():
            if not isinstance(record, dict):
                continue
            try:
                raw_concepts = record.get("concepts")
                ids = (
                    [str(cid) for cid in raw_concepts]
                    if isinstance(raw_concepts, (list, tuple))
                    else []
                )
                if concept_id in ids:
                    sha = record.get("sha256")
                    rel = _manifest_relpath(self.bundle, _decode_state_key(key))
                    if rel is None:
                        skipped += 1
                    else:
                        found.append((rel, sha if isinstance(sha, str) else None))
            except Exception:
                continue
        found.sort(key=lambda item: item[0])
        return found, skipped

    def provenance(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Trace a concept's provenance: every claim back to its source.

        Walks the concept's `sources[]` frontmatter and its footnote
        references (`[^label]` → their `[^label]:` definitions), then shows
        the ingested-source manifest (`sync-state.json`) records for this
        concept — once, in their own section, even when `sources[]` is
        absent. Manifest paths are untrusted bundle input: only paths
        inside the bundle root are shown (bundle-relative); outside paths
        are skipped with an "untrusted manifest entry" marker, never
        echoed. Malformed `sources` frontmatter (scalars, wrong types)
        degrades to best-effort rendering; a missing or corrupt sync state
        degrades to "no record" notes — this never crashes and never
        raises.

        Evidence budgets: `max_chunks` caps the rows per response (default
        50, hard cap 50 — section headers sit outside the budget),
        `max_tokens` is an approximate output budget (`None`/negative =
        unbounded; `0` = no content, marker only), and `continuation_token`
        pages through long chains.

        Returns the chain: concept → `sources[]` entries → ingested source
        records (file/digest) → footnote references → definitions. A
        missing concept returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        ingested, ingested_skipped = self._ingested_sources(concept.id)
        sources = _coerce_sources(concept.frontmatter)
        definitions = _footnote_definitions(concept.body)
        refs = _footnote_refs(concept.body)
        try:
            rel_path = concept.path.relative_to(self.bundle.root).as_posix()
        except (ValueError, OSError):
            rel_path = concept.path.name

        # Concept metadata is first-page context (notes), not paged items:
        # it must never consume the evidence budget.
        notes = [
            _concept_label(concept),
            f"_Path: `{rel_path}` · body sha256: `{_concept_sha256(concept)[:16]}…`_",
        ]
        temporal_note = self._temporal_note(concept, _temporal.utcnow())
        if temporal_note:
            notes.append(f"_Temporal status: {temporal_note}._")

        source_rows = [f"- {_render_source_entry(entry)}" for entry in sources]
        ingested_header = f"## Ingested source records ({len(ingested)})"
        ingested_rows = [
            f"- `{rel}`" + (f" — sha256 `{sha[:16]}…`" if sha else "")
            for rel, sha in ingested
        ]
        if ingested_skipped:
            plural = "entries" if ingested_skipped != 1 else "entry"
            ingested_rows.append(
                f"_Skipped {ingested_skipped} untrusted manifest {plural} "
                "(source path outside the bundle root)._"
            )
        if not ingested_rows:
            ingested_rows.append(
                "_No sync-state record links this concept to an ingested source._"
            )
        ref_header = f"## Footnote references ({len(refs)})"
        ref_rows: list[str] = []
        for label in refs:
            definition = definitions.get(label)
            if definition:
                ref_rows.append(f"- [^{label}]: {definition}")
            else:
                ref_rows.append(f"- [^{label}]: _definition not found in body_")

        sources_header = f"## Sources ({len(sources)})"
        whole_units = [
            sources_header,
            *(source_rows or ["_No `sources[]` entries in frontmatter._"]),
            ingested_header,
            *ingested_rows,
            ref_header,
            *(ref_rows or ["_No footnote references in body._"]),
        ]
        title = f"Provenance for {concept_id}"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(notes) + "\n\n" + "\n".join(whole_units),
            sections=[
                (sources_header, source_rows),
                (ingested_header, ingested_rows),
                (ref_header, ref_rows),
            ],
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- bundle diff ---------------------------------------------------------
    def diff(
        self,
        against: str | None = None,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Diff this bundle against a previous state: added/removed/changed concepts.

        Two modes. With `against=<path to a bundle directory>`, compares the
        bound bundle ("current") against that directory ("previous"):
        added = ids only in current, removed = ids only in previous,
        changed = same id with a different body SHA-256 (or a different
        title). Each entry reports id, title, and the body sha256.

        Without `against`, falls back to the `sync-state.json` snapshot
        (`<bundle>/.okfsmith/sync-state.json`) when one exists: added/removed
        come from the snapshot's recorded concept ids, and "changed" marks
        concepts whose recorded source file's current SHA-256 differs from
        the snapshot — but only for manifest source paths inside the bundle
        root (outside paths are untrusted bundle input: never hashed, never
        echoed, reported with a marker instead). With neither an `against`
        directory nor a usable snapshot, returns a clean error explaining
        how to call it.

        Evidence budgets: `max_chunks` caps the rows per response (default
        50, hard cap 50 — the `## Added`/`## Removed`/`## Changed` headers
        and the comparison note sit outside the budget), `max_tokens` is an
        approximate output budget (`None`/negative = unbounded; `0` = no
        content, marker only), and `continuation_token` pages through large
        diffs. Read-only: nothing here modifies either bundle. A bad
        `against` value returns a clean error, never a traceback — and the
        `against` directory is pre-scanned (bounded file count, must contain
        markdown concept files) so a filesystem root can never trigger a
        full-disk walk.
        """
        if against is None:
            return self._diff_against_sync_state(
                max_chunks, max_tokens, continuation_token
            )
        if not isinstance(against, (str, Path)) or not str(against).strip():
            return "Error: `against` must be a path to a bundle directory."
        other_root = Path(str(against).strip())
        if not other_root.is_dir():
            return f"Error: `against` is not a directory: {against!r}."
        scan_error = _scan_against_dir(other_root)
        if scan_error is not None:
            return scan_error
        try:
            other = Bundle.load(other_root)
        except Exception as exc:
            return f"Error: could not load bundle at {against!r}: {exc}."
        current = {c.id: c for c in self.bundle.iter_concepts()}
        previous = {c.id: c for c in other.iter_concepts()}
        added = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(
            cid
            for cid in set(current) & set(previous)
            if _concept_sha256(current[cid]) != _concept_sha256(previous[cid])
            or _concept_title(current[cid]) != _concept_title(previous[cid])
        )

        added_header = f"## Added ({len(added)})"
        removed_header = f"## Removed ({len(removed)})"
        changed_header = f"## Changed ({len(changed)})"
        added_rows = [
            f"- **{cid}** — {_concept_title(current[cid])} — "
            f"sha256 `{_concept_sha256(current[cid])[:12]}…`"
            for cid in added
        ]
        removed_rows = [
            f"- **{cid}** — {_concept_title(previous[cid])} — "
            f"sha256 `{_concept_sha256(previous[cid])[:12]}…`"
            for cid in removed
        ]
        changed_rows = [
            f"- **{cid}** — {_concept_title(current[cid])} — "
            f"`{_concept_sha256(previous[cid])[:12]}…` → "
            f"`{_concept_sha256(current[cid])[:12]}…`"
            for cid in changed
        ]
        # "_none_" fillers appear only in the unpaged `whole`: in the paged
        # flow the header's (0) count already says the section is empty, and
        # fillers must not consume the item budget.
        whole_units = [
            added_header,
            *(added_rows or ["_none_"]),
            removed_header,
            *(removed_rows or ["_none_"]),
            changed_header,
            *(changed_rows or ["_none_"]),
        ]

        notes = [f"_Comparing the current bundle against `{other_root}`._"]
        title = "Bundle diff"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(notes) + "\n\n" + "\n".join(whole_units),
            sections=[
                (added_header, added_rows),
                (removed_header, removed_rows),
                (changed_header, changed_rows),
            ],
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    def _diff_against_sync_state(
        self, max_chunks: Any, max_tokens: Any, continuation_token: Any
    ) -> str:
        """``diff()`` with no ``against``: compare against the sync snapshot."""
        state = _load_sync_state(self.bundle)
        if state is None:
            return (
                "Error: no `against` bundle directory given and no usable "
                "`sync-state.json` snapshot found in this bundle (looked for "
                "`<bundle>/.okfsmith/sync-state.json`). Pass "
                "`against=<path to a bundle directory>` to compare against it."
            )
        # Manifest paths are untrusted bundle input: only paths inside the
        # bundle root are hashed or echoed (bundle-relative). Outside paths
        # are counted as untrusted and skipped with a marker — never hashed
        # (no host-file SHA-256/existence oracle) and never echoed verbatim.
        origins: dict[str, list[tuple[str, str | None]]] = {}
        records = state.get("sources")
        record_count = 0
        untrusted = 0
        if isinstance(records, dict):
            record_count = len(records)
            for key, record in records.items():
                if not isinstance(record, dict):
                    continue
                rel = _manifest_relpath(self.bundle, _decode_state_key(key))
                if rel is None:
                    untrusted += 1
                    continue
                sha = record.get("sha256")
                sha = sha if isinstance(sha, str) else None
                raw_concepts = record.get("concepts")
                ids = (
                    [str(cid) for cid in raw_concepts]
                    if isinstance(raw_concepts, (list, tuple))
                    else []
                )
                for cid in ids:
                    origins.setdefault(cid, []).append((rel, sha))
        current = {c.id: c for c in self.bundle.iter_concepts()}
        prev_ids = set(origins)
        added = sorted(set(current) - prev_ids)
        removed = sorted(prev_ids - set(current))
        changed: list[tuple[str, str, str, str]] = []
        for cid in sorted(set(current) & prev_ids):
            for rel, old_sha in origins[cid]:
                if not old_sha:
                    continue
                candidate = self.bundle.root / rel
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                new_sha = _sha256_file(candidate)
                if new_sha and new_sha != old_sha:
                    changed.append((cid, rel, old_sha, new_sha))
                    break

        added_header = f"## Added ({len(added)})"
        removed_header = f"## Removed ({len(removed)})"
        changed_header = f"## Changed ({len(changed)})"
        added_rows = [
            f"- **{cid}** — {_concept_title(current[cid])} — "
            f"sha256 `{_concept_sha256(current[cid])[:12]}…`"
            for cid in added
        ]
        # Removed concepts are gone from the bundle: no title or body sha
        # is available, so the entry says so honestly instead of rendering
        # a bare id (consistent dash-shape with the other sections).
        removed_rows = [
            f"- **{cid}** — _removed from the bundle (title/sha unavailable)_"
            for cid in removed
        ]
        changed_rows = [
            f"- **{cid}** — {_concept_title(current[cid])} — "
            f"source `{rel}` changed "
            f"(`{old_sha[:12]}…` → `{new_sha[:12]}…`)"
            for cid, rel, old_sha, new_sha in changed
        ]
        whole_units = [
            added_header,
            *(added_rows or ["_none_"]),
            removed_header,
            *(removed_rows or ["_none_"]),
            changed_header,
            *(changed_rows or ["_none_"]),
        ]

        notes = [
            "_Comparing against the `sync-state.json` snapshot "
            f"({record_count} source record(s))._"
        ]
        if untrusted:
            plural = "entries" if untrusted != 1 else "entry"
            notes.append(
                f"_Skipped {untrusted} untrusted manifest {plural}: source "
                "path outside the bundle root (not hashed)._"
            )
        title = "Bundle diff"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(notes) + "\n\n" + "\n".join(whole_units),
            sections=[
                (added_header, added_rows),
                (removed_header, removed_rows),
                (changed_header, changed_rows),
            ],
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )


    # -- governed write-back ------------------------------------------------
    #
    # Four tools: ``preview_write_concept`` (dry run), ``write_concept``
    # (create), ``update_concept`` (patch), ``audit_log`` (read the trail).
    # Governance contract, enforced in code:
    #
    # * Provenance: every write stamps frontmatter ``provenance`` (a history
    #   list — updates append, never rewrite) with the actor
    #   (``mcp:<tool-name>``), a UTC ISO-8601 timestamp, and the input
    #   sources; a ``generated: {by, at}`` block mirrors the CLI ingest
    #   shape.
    # * Trust: write-back output is ALWAYS ``unverified`` — no ``verified``
    #   key is ever emitted, and any ``verified`` markers smuggled into
    #   caller input are stripped before serialization. Only ``human:``-
    #   prefixed actors can grant verification (spec §5.3), and an MCP
    #   caller is never one.
    # * Collisions: an existing concept id is never overwritten —
    #   ``write_concept`` returns a structured error suggesting
    #   ``update_concept``.
    # * Human-reviewed protection: ``update_concept`` refuses to touch a
    #   human-reviewed concept unless ``downgrade_trust=true`` is passed
    #   explicitly; the downgrade removes the ``verified`` marker and is
    #   recorded in provenance.
    # * Validation gate: the bundle validator runs before and after every
    #   write; a write introducing new errors is refused and rolled back.
    #   A validator failure fails closed (the write is refused).
    # * Atomicity: concept files are written to a temp file in the same
    #   directory and renamed into place; the temp file is removed on any
    #   failure, so half-written concept files cannot survive.
    # * Audit: every applied write appends one JSON line to the append-only
    #   ``<bundle>/.okfsmith/audit.jsonl``. An audit failure rolls the
    #   concept write back — there are no unaudited writes.
    # * Containment: ids/slugs are slugified (``..`` and absolute paths
    #   cannot survive slugification); updates additionally reject
    #   ``..``/absolute ids outright, refuse symlinked concept files, and
    #   refuse paths escaping the bundle root.

    def _validator_error_set(
        self, rel: str | None = None
    ) -> set[tuple[str, str, str]] | None:
        """``(code, file, message)`` of the bundle validator's ERRORS now.

        *rel* filters to one bundle-relative file. Returns ``None`` when the
        validator cannot run — callers fail closed (refuse the write).
        Never raises.
        """
        try:
            from okfsmith.validate import check

            report = check(bundle=self.bundle)
        except Exception:
            return None
        return {
            (finding.code, finding.file, finding.message)
            for finding in report.errors
            if rel is None or finding.file == rel
        }

    def _reload_bundle(self) -> None:
        """Re-read the bundle from disk so later tools see applied writes.

        Never raises: a reload failure leaves the previous in-memory handle
        in place (the write itself is already safely on disk).
        """
        try:
            self.bundle = Bundle.load(self.bundle.root)
            self._sindex = _temporal.SupersessionIndex.from_bundle(self.bundle)
        except Exception:
            pass

    @staticmethod
    def _rollback_write(
        path: Path, creating: bool, previous_bytes: bytes | None
    ) -> None:
        """Undo a committed-then-rejected write; never raises.

        Creates are unlinked; updates restore the previous file's raw
        bytes (atomically, through the same temp+rename path) so the
        rollback is byte-identical — e.g. CRLF line endings are preserved
        instead of being reserialized to LF (QA L8).
        """
        try:
            if creating:
                path.unlink(missing_ok=True)
            elif previous_bytes is not None:
                _atomic_write_bytes(path, previous_bytes, overwrite=True)
        except OSError:
            pass

    def _write_with_governance(
        self,
        path: Path,
        rel: str,
        text: str,
        *,
        creating: bool,
        previous_bytes: bytes | None,
        audit_actor: str,
        audit_action: str,
        audit_concept_id: str,
        audit_summary: str,
    ) -> str | None:
        """Commit *text* to *path* under the governance contract.

        Returns ``None`` on success, else an ``Error: ...`` string and
        nothing (auditable) has changed: symlink-resolved bundle
        containment → baseline validator errors → atomic temp+rename write
        → re-validate (new errors for *rel* ⇒ roll back and refuse) →
        append the audit entry (audit failure ⇒ roll back and refuse) →
        reload the in-memory bundle.
        Never raises.
        """
        if not _realpath_within(self.bundle.root, path):
            return (
                f"Error: refusing to write `{rel}` — the target resolves "
                "outside the bundle root through a symlinked parent "
                "directory (QA M1). Nothing was written."
            )
        before = self._validator_error_set()
        if before is None:
            return (
                "Error: refusing to write — the bundle validator could not "
                "run (fail closed). Nothing was written."
            )
        try:
            _atomic_write_text(path, text, overwrite=not creating)
        except FileExistsError:
            return (
                f"Error: refusing to write — `{rel}` already exists. "
                "Write-back never overwrites."
            )
        except OSError as exc:
            return f"Error: could not write `{rel}`: {exc}."
        after = self._validator_error_set()
        if after is None:
            self._rollback_write(path, creating, previous_bytes)
            return (
                "Error: refusing to write — the bundle validator could not "
                "run after the write (fail closed). The write was rolled back."
            )
        new_errors = {f for f in after if f[1] == rel} - {
            f for f in before if f[1] == rel
        }
        if new_errors:
            self._rollback_write(path, creating, previous_bytes)
            codes = sorted({code for code, _, _ in new_errors})
            return (
                f"Error: refusing to write `{rel}` — the concept fails "
                f"validation (new errors: {', '.join(codes)}). "
                "The write was rolled back."
            )
        if not _append_audit(
            self.bundle,
            actor=audit_actor,
            action=audit_action,
            concept_id=audit_concept_id,
            summary=audit_summary,
        ):
            self._rollback_write(path, creating, previous_bytes)
            return (
                "Error: refusing to write — the audit entry could not be "
                "recorded (no unaudited writes). The write was rolled back."
            )
        self._reload_bundle()
        return None

    def _validate_candidate_text(
        self, rel: str, text: str
    ) -> tuple[list[Any], list[Any]]:
        """``(errors, warnings)`` validator findings for *text* as if at *rel*.

        Materializes *text* at a temp ``.md`` file next to *rel* (so
        link-liveness resolves exactly as the real write would), runs the
        full bundle validator, filters findings to the temp file, and
        unlinks it in a ``finally`` — the bundle is byte-identical
        afterwards, so this is safe inside the side-effect-free preview.
        Parent directories are created for the validation and pruned again
        afterwards when left empty, so a nested id validates against its
        real location instead of silently passing (QA L4). The target must
        resolve inside the bundle root (defense in depth for QA M1).
        Returns ``([], [])`` when the validator cannot run. Never raises.
        """
        root = self.bundle.root
        target = root.joinpath(*rel.split("/"))
        if not _realpath_within(root, target):
            return [], []
        tmp = target.with_name(f".preview-{uuid.uuid4().hex[:8]}-{target.name}")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            from okfsmith.validate import check

            report = check(bundle=self.bundle)
        except Exception:
            return [], []
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            _prune_empty_parents(tmp.parent, root)
        tmp_rel = tmp.relative_to(root).as_posix()
        errors = [f for f in report.errors if f.file == tmp_rel]
        warnings = [f for f in report.warnings if f.file == tmp_rel]
        return errors, warnings

    def _concept_id_taken(self, concept_id: str) -> bool:
        """``True`` when *concept_id* collides with an existing concept.

        The id comparison is case-insensitive (QA L7): on a
        case-sensitive filesystem ``Hello.md`` and ``hello.md`` would
        otherwise become near-duplicate concept ids. Fails closed —
        ``True`` — when the bundle cannot be iterated. Never raises.
        """
        try:
            wanted = concept_id.lower()
            return any(
                concept.id.lower() == wanted
                for concept in self.bundle.iter_concepts()
            )
        except Exception:
            return True

    def _preview_document(
        self, title: str, body: str, sources: Any, links: Any
    ) -> tuple[str | None, dict[str, Any]]:
        """Validate inputs and build the would-be document for a create.

        Returns ``(error, plan)`` — *error* an ``Error: ...`` string when
        the inputs are rejected (empty title/body, oversize input, reserved
        name), else ``None`` and a *plan* dict with ``concept_id``, ``rel``,
        ``frontmatter``, ``body`` and ``text`` (the exact serialized file).
        Side-effect free. Never raises.
        """
        title_text = _coerce_nonempty_text(title)
        if title_text is None:
            return "Error: `title` is empty — a concept needs a title.", {}
        body_text = _coerce_nonempty_text(body)
        if body_text is None:
            return "Error: `body` is empty — a concept needs body content.", {}
        if len(title_text) > _WRITEBACK_MAX_TITLE_CHARS:
            return (
                f"Error: `title` is too long ({len(title_text)} chars, "
                f"max {_WRITEBACK_MAX_TITLE_CHARS})."
            ), {}
        if len(body_text) > _WRITEBACK_MAX_BODY_CHARS:
            return (
                f"Error: `body` is too long ({len(body_text)} chars, "
                f"max {_WRITEBACK_MAX_BODY_CHARS})."
            ), {}
        for name, value in (("sources", sources), ("links", links)):
            count_error = _check_item_count(name, value)
            if count_error is not None:
                return count_error, {}
        concept_id = _slug_id(title_text)
        for segment in concept_id.split("/"):
            if f"{segment}{_MD_SUFFIX}" in RESERVED_FILES:
                return (
                    f"Error: the title slug {segment!r} maps to the reserved "
                    "bundle filename "
                    f"{segment + _MD_SUFFIX!r} — reserved files (`index.md`, "
                    "`log.md`) are never concepts. Pick a different title."
                ), {}
        path = concept_path_for(self.bundle.root, concept_id)
        try:
            rel = path.relative_to(self.bundle.root).as_posix()
        except ValueError:
            return (
                "Error: the title slug escapes the bundle root — "
                "pick a different title."
            ), {}
        if not _realpath_within(self.bundle.root, path):
            return (
                "Error: refusing to write — the title slug resolves "
                "outside the bundle through a symlinked parent directory "
                "(QA M1). Pick a different title."
            ), {}
        actor = f"{_WRITEBACK_ACTOR_PREFIX}write_concept"
        ts = utc_now_iso()
        frontmatter, full_body, text = _build_writeback_document(
            title=title_text,
            body=body_text,
            sources=_coerce_item_list(sources),
            links=_coerce_item_list(links),
            actor=actor,
            ts=ts,
        )
        return None, {
            "concept_id": concept_id,
            "rel": rel,
            "frontmatter": frontmatter,
            "body": full_body,
            "text": text,
        }

    def preview_write_concept(
        self,
        title: str,
        body: str,
        sources: list | None = None,
        links: list | None = None,
    ) -> str:
        """Dry-run of `write_concept`: show EXACTLY what would be written, writing nothing.

        `title` becomes the concept id via the same slugification the CLI
        ingest uses (`concept_path_for`); `body` is the markdown content;
        `sources` is a list of source strings or `{id,title,resource,author}`
        mappings echoed into frontmatter `sources` and the provenance entry;
        `links` is a list of concept-id strings or `{text,target}` mappings,
        rendered as an auto-generated `## Links` section at the end of the
        body (marked with an `<!-- okfsmith:mcp:links -->` comment so later
        updates can replace it instead of stacking sections).

        Governance previewed, not applied: the output shows the concept id,
        the bundle-relative file path, the full frontmatter (including the
        `provenance` block that would be stamped — the `at` timestamp is
        illustrative and regenerated at write time), the exact serialized
        file content, the trust tier (`unverified` — write-back output is
        never verified), whether the validator would accept the document,
        and whether the id collides with an existing concept (a collision
        means `write_concept` would refuse and suggest `update_concept`).

        Side-effect free: the bundle directory is byte-identical afterwards
        (no concept file, no audit entry). Input problems (empty title/body,
        oversize input, reserved filename) return a clean error.
        """
        error, plan = self._preview_document(title, body, sources, links)
        if error is not None:
            return error
        concept_id = plan["concept_id"]
        rel = plan["rel"]
        path = concept_path_for(self.bundle.root, concept_id)
        collides = self._concept_id_taken(concept_id) or path.exists()
        errors, warnings = self._validate_candidate_text(rel, plan["text"])
        lines = [
            "# Preview: write_concept (dry run — nothing was written)",
            "",
            f"- **Concept id:** `{concept_id}`",
            f"- **Would-be file:** `{rel}`",
            "- **Trust tier:** `unverified` (write-back output is never verified)",
        ]
        if errors:
            codes = sorted({f.code for f in errors})
            lines.append(
                "- **Validation:** FAIL — `write_concept` would refuse this "
                f"(errors: {', '.join(codes)})"
            )
            for finding in errors:
                lines.append(f"  - `{finding.code}`: {finding.message}")
        else:
            lines.append(
                "- **Validation:** PASS — `write_concept` would accept this"
                + (
                    f" ({len(warnings)} advisory warning(s), "
                    "warnings never block a write)"
                    if warnings
                    else ""
                )
            )
        if collides:
            lines.append(
                f"- **Collision:** `{concept_id}` already exists — "
                "`write_concept` would refuse to overwrite it; call "
                f"`update_concept(concept_id={concept_id!r}, ...)` to modify it."
            )
        else:
            lines.append("- **Collision:** none")
        lines.extend(
            [
                "",
                "## File content that would be written",
                "```markdown",
                plan["text"].rstrip("\n"),
                "```",
            ]
        )
        return "\n".join(lines)

    def write_concept(
        self,
        title: str,
        body: str,
        sources: list | None = None,
        links: list | None = None,
    ) -> str:
        """Create a new concept in the bundle, under governance.

        `title` (required, non-empty) becomes the concept id via the same
        slugification the CLI ingest uses; `body` (required, non-empty) is
        the markdown content; `sources` / `links` behave as in
        `preview_write_concept` (use it first to see exactly what would be
        written).

        Governance, enforced in code:
        - The concept id is derived from the title; when it already exists
          the write is refused with a structured error suggesting
          `update_concept` — write-back never overwrites.
        - Frontmatter carries a `provenance` history entry (`action:
          created`, actor `mcp:write_concept`, UTC ISO-8601 `at`, the input
          `sources`) plus a `generated: {by, at}` block mirroring the CLI
          ingest shape. No `verified` key is ever emitted — and any
          `verified` markers smuggled into `sources`/`links` input are
          stripped — so the trust tier is always `unverified` (only
          `human:`-prefixed actors can grant verification, spec §5.3).
        - The bundle validator runs before and after the write: a write
          introducing new validation errors is refused and rolled back; a
          validator failure fails closed (refused).
        - The file is written atomically (temp file in the same directory +
          rename); the temp file is removed on any failure.
        - One JSON line is appended to the append-only
          `<bundle>/.okfsmith/audit.jsonl`; an audit failure rolls the
          concept write back — there are no unaudited writes.

        Returns a short markdown confirmation (id, file, trust tier,
        validation and audit status). Lookup/validation failures return a
        clean `Error: ...` string, never a traceback.
        """
        error, plan = self._preview_document(title, body, sources, links)
        if error is not None:
            return error
        concept_id = plan["concept_id"]
        rel = plan["rel"]
        path = concept_path_for(self.bundle.root, concept_id)
        if self._concept_id_taken(concept_id) or path.exists():
            return (
                f"Error: concept id `{concept_id}` already exists (`{rel}`). "
                "Write-back never overwrites an existing concept — call "
                f"`update_concept(concept_id={concept_id!r}, ...)` to modify "
                "it, or pick a different title."
            )
        actor = f"{_WRITEBACK_ACTOR_PREFIX}write_concept"
        err = self._write_with_governance(
            path,
            rel,
            plan["text"],
            creating=True,
            previous_bytes=None,
            audit_actor=actor,
            audit_action="create",
            audit_concept_id=concept_id,
            audit_summary=f"created concept {concept_id!r}",
        )
        if err is not None:
            return err
        return (
            "# Concept written\n\n"
            f"- **Concept id:** `{concept_id}`\n"
            f"- **File:** `{rel}`\n"
            "- **Trust tier:** `unverified`\n"
            "- **Validation:** PASS (no new errors)\n"
            "- **Provenance:** `created` entry stamped in frontmatter\n"
            "- **Audit:** recorded in `.okfsmith/audit.jsonl`"
        )

    def update_concept(
        self,
        concept_id: str,
        title: str | None = None,
        body: str | None = None,
        sources: list | None = None,
        links: list | None = None,
        downgrade_trust: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Patch an existing concept, under governance.

        `concept_id` is the bundle concept id (slug-normalized for lookup:
        `"My Note"` finds `my-note`). Patch fields are optional and replace
        wholesale: `title` (non-empty), `body` (non-empty — a body-only
        patch keeps the existing auto-generated `## Links` section in
        place), `sources` (list of strings or mappings — replaces
        frontmatter `sources`; an empty list removes the key), `links`
        (list of id strings or `{text,target}` mappings — rebuilds the
        auto-generated `## Links` section at the end of the body, replacing
        the previous one instead of stacking). At least one patch field is
        required.

        Governance, enforced in code:
        - Human-reviewed concepts (trust tier `human-reviewed`, i.e. a
          `human:`-prefixed verifier) are refused unless
          `downgrade_trust=true` is passed explicitly — agent callers must
          never silently alter human-verified content. The downgrade
          removes the `verified` marker (the altered content can no longer
          claim human verification) and records the previous trust tier and
          verifiers in the provenance entry.
        - Updating the body, sources, or links of a machine-confirmed
          concept removes the machine `verified` marker — stale
          verification must not survive on replaced content — and records
          the previous trust tier and verifiers in the provenance entry.
        - Every update appends one entry to the frontmatter `provenance`
          history list (`action: updated`, actor `mcp:update_concept`, UTC
          `at`, changed field names, input `sources` when given) — history
          is never rewritten. `verified` markers smuggled into patch input
          are stripped; an update can never raise the trust tier.
        - `dry_run=true` returns a unified diff of the would-be file
          without writing anything (no audit entry either).
        - Otherwise the validator-gated, atomic, audited commit of
          `write_concept` applies (new validation errors ⇒ refused and
          rolled back; audit failure ⇒ rolled back).
        - `concept_id` values with `..` segments or absolute paths are
          rejected; symlinked concept files are never updated; paths
          escaping the bundle root are refused.

        Returns a markdown confirmation (or the diff for `dry_run`); a
        no-op patch (nothing actually changes) writes nothing and says so.
        Failures return a clean `Error: ...` string, never a traceback.
        """
        if not isinstance(concept_id, str) or not concept_id.strip():
            return "Error: `concept_id` is empty — pass a bundle concept id."
        raw_id = concept_id.strip()
        if raw_id.startswith("/") or ".." in raw_id.replace("\\", "/").split("/"):
            return (
                f"Error: `concept_id` must be a bundle-relative concept id "
                f"(got {concept_id!r}) — absolute paths and `..` segments "
                "are rejected."
            )
        lookup_id = _slug_id(raw_id)
        concept = self.bundle.get(lookup_id)
        if concept is None:
            return (
                f"Error: concept {raw_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        try:
            is_link = concept.path.is_symlink()
        except OSError:
            is_link = True
        if is_link:
            return (
                f"Error: refusing to update `{concept.id}` — its file is a "
                "symlink; write-back never follows symlinks."
            )
        try:
            rel = concept.path.relative_to(self.bundle.root).as_posix()
        except ValueError:
            return (
                f"Error: refusing to update `{concept.id}` — its file "
                "escapes the bundle root."
            )
        if not _realpath_within(self.bundle.root, concept.path):
            return (
                f"Error: refusing to update `{concept.id}` — its file "
                "resolves outside the bundle root through a symlinked "
                "parent directory (QA M1)."
            )

        tier = _trust_tier_safe(concept.frontmatter)
        downgrade = _coerce_bool(downgrade_trust)
        verifiers = _verifier_names(concept.frontmatter)
        if tier == HUMAN_REVIEWED and not downgrade:
            who = (
                f" (verified by {', '.join(verifiers)})" if verifiers else ""
            )
            return (
                f"Error: refusing to update `{concept.id}` — it is "
                f"human-reviewed{who}. Human-verified content is never "
                "silently altered by an agent. Pass `downgrade_trust=true` "
                "to update it anyway: the `verified` marker will be removed "
                "and the downgrade recorded in provenance."
            )

        new_title = _coerce_nonempty_text(title) if title is not None else None
        if title is not None and new_title is None:
            return "Error: `title` is empty — pass a non-empty title or omit it."
        new_body = _coerce_nonempty_text(body) if body is not None else None
        if body is not None and new_body is None:
            return "Error: `body` is empty — pass non-empty body or omit it."
        if (
            title is None
            and body is None
            and sources is None
            and links is None
        ):
            return (
                "Error: nothing to update — pass at least one of "
                "`title`, `body`, `sources`, `links`."
            )
        for name, value in (("sources", sources), ("links", links)):
            count_error = _check_item_count(name, value)
            if count_error is not None:
                return count_error

        new_fm: dict[str, Any] = dict(concept.frontmatter)
        changed: list[str] = []
        base_body = concept.body
        title_changed = new_title is not None and new_title != str(
            concept.frontmatter.get("title", "")
        ).strip()
        if new_title is not None:
            new_fm["title"] = new_title
            if title_changed:
                changed.append("title")
        if new_body is not None:
            base_body = new_body
            changed.append("body")
        if sources is not None:
            clean_sources = _sanitize_yaml_value(
                _strip_verified_markers(_coerce_item_list(sources))
            )
            if clean_sources:
                new_fm["sources"] = clean_sources
            else:
                new_fm.pop("sources", None)
            changed.append("sources")
        if links is not None:
            clean_links = _sanitize_yaml_value(
                _strip_verified_markers(_coerce_item_list(links))
            )
            base_body = _with_links_section(base_body, clean_links)
            changed.append("links")
        elif body is not None:
            # A body-only patch keeps the existing auto-generated links
            # section in place (QA L2): the new body text replaces the
            # prose, then the marked section carried over from the old
            # body is re-attached verbatim.
            old_section = _links_section(concept.body)
            base = base_body.rstrip("\n")
            base_body = f"{base}\n\n{old_section}\n" if old_section else base + "\n"
        if title_changed:
            # Description tracks the concept: refresh from the *new* body
            # (QA L3 — computed after the body patch above, not before).
            new_fm["description"] = _one_line(base_body)

        content_changed = any(f in changed for f in ("body", "sources", "links"))
        machine_downgraded = content_changed and tier == MACHINE_CONFIRMED
        if machine_downgraded:
            # The verified content is being replaced: a machine
            # verification marker must not survive on new content (QA M3).
            # (Human-reviewed content keeps its explicit downgrade_trust
            # flow below.)
            new_fm.pop("verified", None)
        if tier == HUMAN_REVIEWED and downgrade:
            # The altered content can no longer claim human verification.
            new_fm.pop("verified", None)

        old_text = _fm.serialize_frontmatter(concept.frontmatter, concept.body)
        candidate_text = _fm.serialize_frontmatter(new_fm, base_body)
        if candidate_text == old_text:
            return (
                f"No changes: the patch for `{concept.id}` is identical to "
                "the current document — nothing was written, no audit entry."
            )

        actor = f"{_WRITEBACK_ACTOR_PREFIX}update_concept"
        entry = _provenance_entry(
            "updated",
            actor,
            sources=(
                _sanitize_yaml_value(
                    _strip_verified_markers(_coerce_item_list(sources))
                )
                or None
                if sources is not None
                else None
            ),
            fields=changed,
        )
        if tier == HUMAN_REVIEWED and downgrade:
            entry["downgrade_trust"] = True
            entry["previous_trust"] = HUMAN_REVIEWED
            if verifiers:
                entry["removed_verified_by"] = verifiers
        if machine_downgraded:
            # QA M3: the machine verification marker was removed because
            # the verified content changed — record what was removed.
            entry["previous_trust"] = MACHINE_CONFIRMED
            if verifiers:
                entry["removed_verified_by"] = verifiers
        existing_prov = new_fm.get("provenance")
        history = (
            list(existing_prov)
            if isinstance(existing_prov, list)
            else ([existing_prov] if existing_prov is not None else [])
        )
        history.append(entry)
        new_fm["provenance"] = history
        new_text = _fm.serialize_frontmatter(new_fm, base_body)

        if _coerce_bool(dry_run):
            diff_lines = difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=f"before: {concept.id}",
                tofile=f"after: {concept.id}",
                lineterm="",
            )
            diff_text = "\n".join(diff_lines) or "(no textual changes)"
            trust_note = (
                f"`{tier}` → `unverified` (downgrade recorded)"
                if (tier == HUMAN_REVIEWED and downgrade) or machine_downgraded
                else f"`{tier}` (unchanged)"
            )
            return (
                "# Preview: update_concept "
                "(dry run — nothing was written, no audit entry)\n\n"
                f"- **Concept id:** `{concept.id}`\n"
                f"- **File:** `{rel}`\n"
                f"- **Fields:** {', '.join(changed)}\n"
                f"- **Trust:** {trust_note}\n\n"
                "```diff\n" + diff_text + "\n```"
            )

        try:
            previous_bytes = concept.path.read_bytes()
        except OSError:
            previous_bytes = None
        err = self._write_with_governance(
            concept.path,
            rel,
            new_text,
            creating=False,
            previous_bytes=previous_bytes,
            audit_actor=actor,
            audit_action="update",
            audit_concept_id=concept.id,
            audit_summary=f"updated concept {concept.id!r}: "
            f"{', '.join(changed)}",
        )
        if err is not None:
            return err
        lines = [
            "# Concept updated",
            "",
            f"- **Concept id:** `{concept.id}`",
            f"- **File:** `{rel}`",
            f"- **Fields:** {', '.join(changed)}",
            f"- **Trust tier:** `{_trust_tier_safe(new_fm)}`",
            "- **Validation:** PASS (no new errors)",
            "- **Provenance:** `updated` entry appended "
            f"({len(history)} total)",
            "- **Audit:** recorded in `.okfsmith/audit.jsonl`",
        ]
        if tier == HUMAN_REVIEWED and downgrade:
            lines.append(
                "- **Downgrade:** `verified` marker removed; previous trust "
                f"`{HUMAN_REVIEWED}` recorded in provenance"
            )
        if machine_downgraded:
            lines.append(
                "- **Verification cleared:** the machine `verified` marker "
                "was removed because the verified content changed; previous "
                f"trust `{MACHINE_CONFIRMED}` recorded in provenance"
            )
        return "\n".join(lines)

    def audit_log(self, limit: int = 20) -> str:
        """Return recent write-back audit entries, newest first.

        Reads the append-only `<bundle>/.okfsmith/audit.jsonl` written by
        `write_concept` / `update_concept` (dry runs and previews are never
        audited — only applied writes). Each entry carries its UTC
        timestamp, the actor (`mcp:<tool-name>`), the action (`create` /
        `update`), the concept id, and a one-line summary. `limit` caps the
        entries returned (default 20; non-numeric input falls back to 20).
        Corrupt lines are skipped; a missing or empty audit file reports
        "no entries yet" instead of an error.
        """
        count = _coerce_limit(limit, 20)
        entries = _read_audit(self.bundle, count)
        if not entries:
            return (
                "# Audit log\n\n_No write-back operations recorded yet "
                "(`.okfsmith/audit.jsonl` is missing or empty)._"
            )
        lines = [f"# Audit log ({len(entries)} most recent, newest first)"]
        for entry in reversed(entries):
            ts = entry.get("ts", "?")
            actor = entry.get("actor", "?")
            action = entry.get("action", "?")
            cid = entry.get("concept_id", "?")
            summary = _one_line(str(entry.get("summary", "")), 200)
            lines.append(
                f"- `{ts}` · `{actor}` · **{action}** · `{cid}`"
                + (f" — {summary}" if summary else "")
            )
        return "\n".join(lines)


def build_server(bundle_path: str | Path):
    """Build (but do not start) the MCP server for the bundle at *bundle_path*.

    The bundle is loaded **once**, right here at startup — every tool call
    afterwards reads from the same in-memory :class:`Bundle`. Raises
    ``RuntimeError`` with an install hint if the ``mcp`` extra is missing,
    :class:`FileNotFoundError` if *bundle_path* does not exist,
    :class:`ValueError` if *bundle_path* is empty, and
    :class:`NotADirectoryError` if *bundle_path* is not a directory.

    The returned server is a FastMCP instance with the twelve tools
    registered: the eight read-only tools (``index``, ``list``, ``search``,
    ``get``, ``neighbors``, ``traverse``, ``provenance``, ``diff``) plus the
    four governed write-back tools (``preview_write_concept``,
    ``write_concept``, ``update_concept``, ``audit_log``).
    """
    if str(bundle_path).strip() == "":
        raise ValueError("bundle_path must not be empty")
    root = Path(bundle_path)
    if not root.exists():
        raise FileNotFoundError(f"Bundle not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Bundle path is not a directory: {root}")
    # Sweep before loading: an orphaned `.preview-*.md` temp file from a
    # crashed session must never load as a phantom concept (QA L5).
    # (BundleTools.__init__ also sweeps + evicts in-memory phantoms as
    # defense-in-depth for bundles loaded by other callers.)
    _sweep_stale_preview_files(root)
    bundle = Bundle.load(root)
    FastMCP = _require_fastmcp()
    server = FastMCP("okfsmith")
    tools = BundleTools(bundle)
    server.tool(tools.index)
    server.tool(tools.list)
    server.tool(tools.search)
    server.tool(tools.get)
    server.tool(tools.neighbors)
    server.tool(tools.traverse)
    server.tool(tools.provenance)
    server.tool(tools.diff)
    server.tool(tools.preview_write_concept)
    server.tool(tools.write_concept)
    server.tool(tools.update_concept)
    server.tool(tools.audit_log)
    return server


def serve(bundle_path: str | Path, transport: str = "stdio") -> None:
    """Serve the bundle at *bundle_path* over the given MCP transport.

    ``transport`` defaults to ``"stdio"`` (the standard way MCP clients
    launch servers). Other FastMCP transports such as ``"sse"`` or
    ``"streamable-http"`` may be passed through.
    """
    server = build_server(bundle_path)
    server.run(transport=transport)
