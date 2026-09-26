"""Validation rules for OKF v0.2 bundles.

Implements the rule codes from ``.contract/spec_decisions.md`` §18 verbatim:

- Errors **E001–E004** map 1:1 to §11's three hard conformance rules.
- Warnings **W001–W015** are advisory; they never affect conformance.

Determinism: findings are emitted in rule-code order, then by bundle-relative
file path, then by position within the file. Pure and deterministic — no
network, no LLM. The only clock read is the staleness check (W006:
``now >= stale_after``).

Stdlib + pyyaml only.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

from okfsmith.validate import Finding

# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------

_DELIMITER = "---"


def _split_frontmatter(raw: str) -> tuple[str | None, str]:
    """Split *raw* into ``(frontmatter_text, body)``.

    Returns ``(None, raw)`` when there is no frontmatter block: the file does
    not start with a ``---`` line, or the closing ``---`` line is missing.
    """
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        return None, raw
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIMITER:
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    return None, raw


def _safe_yaml(text: str) -> tuple[bool, object]:
    """Parse *text* as YAML, returning ``(ok, value)`` (never raises)."""
    try:
        return True, yaml.safe_load(text)
    except yaml.YAMLError:
        return False, None


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def _strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans from *text*."""
    return _INLINE_CODE_RE.sub("", _FENCE_RE.sub("", text))


_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\n]*)\)")
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\n]+)\](?!:)")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_LOG_HEADING_RE = re.compile(r"^##[ \t]+(\S(?:.*\S)?)[ \t]*$", re.MULTILINE)
_DATE_SHAPE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_CITATIONS_RE = re.compile(r"^#{1,6}[ \t]+citations[ \t]*$", re.IGNORECASE | re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^(?:[ \t]*[-*+][ \t]+|[ \t]*\d+[.)][ \t]+)")
_HEADING_ANY_RE = re.compile(r"^#{1,6}[ \t]")


def _clean_target(target: str) -> str:
    """Strip a link target of fragment and query string."""
    text = target.strip()
    text = text.split("#", 1)[0]
    text = text.split("?", 1)[0]
    return text.strip()


def _is_external(target: str) -> bool:
    """True for absolute URLs / other-scheme targets (never bundle links)."""
    return bool(_SCHEME_RE.match(target)) or target.startswith("//")


def _rel_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolve_target(root: Path, base_rel: str, target: str) -> str | None:
    """Resolve a link *target* to a bundle-relative POSIX path.

    Returns ``None`` when the target escapes the bundle root. Absolute
    (bundle-relative) targets start with ``/``; anything else resolves from
    *base_rel* (the linking file's directory, bundle-relative).
    """
    if target.startswith("/"):
        rel = posixpath.normpath(target.lstrip("/"))
    else:
        rel = posixpath.normpath(posixpath.join(base_rel or ".", target))
    if rel in ("", "."):
        rel = ""
    if rel == ".." or rel.startswith("../"):
        return None
    return rel


def _valid_calendar_date(text: str) -> bool:
    """True when *text* is ``YYYY-MM-DD`` and a real calendar date."""
    match = _DATE_SHAPE_RE.match(text)
    if not match:
        return False
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return True


def _parse_timestamp(value: object) -> tuple[bool, datetime | None]:
    """Check an ISO-8601 timestamp with explicit UTC offset.

    Returns ``(ok, dt)``. ``ok`` is False for naive or unparseable values —
    per §5 every timestamp-valued key needs an explicit UTC offset (W011).
    YAML may already hand us a ``datetime`` (unquoted timestamps).
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return False, None
        return True, value
    if not isinstance(value, str):
        return False, None
    text = value.strip()
    if not text:
        return False, None
    iso = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return False, None
    if parsed.tzinfo is None:
        return False, None
    return True, parsed


def _normalize_verified(value: object) -> tuple[list | None, bool]:
    """Normalize ``verified`` to a list. Returns ``(entries, malformed)``.

    A bare mapping counts as a one-element list (§5.2, §11). Anything that is
    neither a mapping nor a list is malformed (W011 family, §17 A17).
    """
    if value is None:
        return [], False
    if isinstance(value, Mapping):
        return [value], False
    if isinstance(value, list):
        return value, False
    return None, True


def _missing(value: object) -> bool:
    """True when an expected scalar is absent, null, or blank."""
    return value is None or (isinstance(value, str) and not value.strip())


class _Doc(NamedTuple):
    """One analyzed ``.md`` file."""

    rel: str  # bundle-relative POSIX path
    path: Path  # absolute path
    kind: str  # "concept" | "index" | "log"
    raw: str
    body: str  # text after any frontmatter block
    fm: Mapping | None  # parsed frontmatter mapping, else None
    fm_ok: bool  # True when fm is a usable mapping (no E001/E002)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def _analyze_concept(path: Path, rel: str) -> tuple[_Doc, list[Finding]]:
    """Parse a concept file; returns ``(doc, frontmatter_errors)`` (E001/E002)."""
    raw = path.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(raw)
    errors: list[Finding] = []
    fm: Mapping | None = None
    if fm_text is None:
        errors.append(
            Finding("E001", rel, "no parseable YAML frontmatter block found", "§11.1")
        )
    else:
        ok, value = _safe_yaml(fm_text)
        if not ok:
            errors.append(
                Finding("E001", rel, "frontmatter block is not parseable YAML", "§11.1")
            )
        elif not isinstance(value, Mapping):
            errors.append(
                Finding("E002", rel, "frontmatter is not a YAML mapping", "§11.2")
            )
        else:
            fm = value
            if "type" not in value:
                errors.append(
                    Finding("E002", rel, "frontmatter `type` is missing", "§11.2")
                )
                fm = None
            elif _missing(value.get("type")):
                errors.append(
                    Finding("E002", rel, "frontmatter `type` is empty", "§11.2")
                )
                fm = None
    return _Doc(rel, path, "concept", raw, body, fm, fm is not None), errors


def _analyze_index(path: Path, rel: str, is_root: bool) -> tuple[_Doc, list[Finding], list[Finding]]:
    """Parse an index.md; returns ``(doc, errors, warnings)`` (E003 / W007)."""
    raw = path.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(raw)
    errors: list[Finding] = []
    warnings: list[Finding] = []
    fm: Mapping | None = None
    if not is_root:
        if fm_text is not None:
            errors.append(
                Finding("E003", rel, "non-root index.md must not contain frontmatter", "§8")
            )
    elif fm_text is not None:
        ok, value = _safe_yaml(fm_text)
        if not ok or not isinstance(value, Mapping):
            errors.append(
                Finding(
                    "E003",
                    rel,
                    "bundle-root index.md frontmatter must contain only the okf_version key",
                    "§8, §12",
                )
            )
        else:
            fm = value
            extra = [str(k) for k in value if k != "okf_version"]
            if extra:
                errors.append(
                    Finding(
                        "E003",
                        rel,
                        "bundle-root index.md frontmatter contains keys other than "
                        f"okf_version: [{', '.join(extra)}]",
                        "§8, §12",
                    )
                )
            elif "okf_version" in value and str(value["okf_version"]).strip() != "0.2":
                warnings.append(
                    Finding(
                        "W007",
                        rel,
                        f"unknown okf_version {value['okf_version']!r}; expected \"0.2\"",
                        "§12",
                    )
                )
    return _Doc(rel, path, "index", raw, body, fm, fm is not None), errors, warnings


def _analyze_log(path: Path, rel: str) -> tuple[_Doc, list[Finding], list[Finding]]:
    """Parse a log.md; returns ``(doc, errors, warnings)`` (E004 / W013)."""
    raw = path.read_text(encoding="utf-8")
    errors: list[Finding] = []
    warnings: list[Finding] = []
    dates: list[str] = []
    for match in _LOG_HEADING_RE.finditer(raw):
        heading = match.group(1)
        if _valid_calendar_date(heading):
            dates.append(heading)
        else:
            errors.append(
                Finding(
                    "E004",
                    rel,
                    f"log date heading is not ISO YYYY-MM-DD: {heading!r}",
                    "§9",
                )
            )
    for earlier, later in zip(dates, dates[1:], strict=False):
        if later > earlier:
            warnings.append(
                Finding(
                    "W013",
                    rel,
                    f"log date headings are not newest-first: {later!r} follows {earlier!r}",
                    "§9",
                )
            )
            break
    return _Doc(rel, path, "log", raw, raw, None, False), errors, warnings


# ---------------------------------------------------------------------------
# Warning rules on concepts
# ---------------------------------------------------------------------------


def _iter_link_targets(body: str) -> list[str]:
    """Raw targets of inline markdown links in *body* (code stripped)."""
    return [m.group(2) for m in _LINK_RE.finditer(_strip_code(body))]


def _warn_broken_links(root: Path, doc: _Doc) -> list[Finding]:
    """W001 — a body link target resolves to no file in the bundle (§6.1)."""
    findings: list[Finding] = []
    base_rel = posixpath.dirname(doc.rel)
    seen: set[str] = set()
    for raw_target in _iter_link_targets(doc.body):
        target = _clean_target(raw_target)
        if not target or _is_external(target) or target in seen:
            continue
        seen.add(target)
        rel = _resolve_target(root, base_rel, target)
        if rel is None:
            findings.append(
                Finding("W001", doc.rel, f"broken link target not found in bundle: {raw_target.strip()!r}", "§6.1")
            )
            continue
        candidate = root / rel
        if candidate.is_dir():
            continue
        if candidate.is_file() or (root / (rel + ".md")).is_file():
            continue
        findings.append(
            Finding("W001", doc.rel, f"broken link target not found in bundle: {raw_target.strip()!r}", "§6.1")
        )
    return findings


def _collect_index_coverage(root: Path, index_docs: list[_Doc]) -> tuple[set[str], set[str]]:
    """Concept ids covered by index.md link entries: ``(ids, dir_prefixes)``.

    Only ``[...](...)`` entries confer reachability (§8); an entry pointing at
    a directory covers every concept beneath it. Body links never count (§17 A12).
    """
    ids: set[str] = set()
    prefixes: set[str] = set()
    for doc in index_docs:
        base_rel = posixpath.dirname(doc.rel)
        for raw_target in _iter_link_targets(doc.body):
            target = _clean_target(raw_target)
            if not target or _is_external(target):
                continue
            rel = _resolve_target(root, base_rel, target)
            if rel is None:
                continue
            candidate = root / rel
            if candidate.is_dir():
                prefixes.add(rel)
            elif candidate.is_file():
                stem = rel[: -len(".md")] if rel.endswith(".md") else rel
                ids.add(stem)
            elif (root / (rel + ".md")).is_file():
                ids.add(rel)
    return ids, prefixes


def _is_covered(concept_id: str, ids: set[str], prefixes: set[str]) -> bool:
    if concept_id in ids:
        return True
    return any(
        prefix == "" or concept_id == prefix or concept_id.startswith(prefix + "/")
        for prefix in prefixes
    )


def _warn_orphan(doc: _Doc, ids: set[str], prefixes: set[str]) -> list[Finding]:
    """W002 — concept not reachable from any index.md entry (§8)."""
    concept_id = doc.rel[: -len(".md")]
    if _is_covered(concept_id, ids, prefixes):
        return []
    return [Finding("W002", doc.rel, "concept not reachable from any index.md entry", "§8")]


def _warn_missing_recommended(doc: _Doc) -> list[Finding]:
    """W003 — recommended `title` / `description` absent (§4.1)."""
    assert doc.fm is not None
    findings = []
    for key in ("title", "description"):
        if _missing(doc.fm.get(key)):
            findings.append(
                Finding("W003", doc.rel, f"recommended frontmatter field `{key}` is missing", "§4.1")
            )
    return findings


def _source_entries(doc: _Doc) -> tuple[list | None, bool]:
    """``(entries, malformed)`` for the ``sources`` frontmatter value."""
    assert doc.fm is not None
    value = doc.fm.get("sources")
    if value is None:
        return [], False
    if isinstance(value, list):
        return value, False
    return None, True


def _warn_sources(doc: _Doc) -> tuple[list[Finding], list[Finding], list[Finding], set[str]]:
    """W005 / W008 / W015 over ``sources`` entries; returns (w005, w008, w015, ids)."""
    w005: list[Finding] = []
    w008: list[Finding] = []
    w015: list[Finding] = []
    ids: set[str] = set()
    entries, malformed = _source_entries(doc)
    if malformed:
        return w005, w008, w015, ids  # malformed `sources` itself is W011 (see below)
    assert entries is not None
    seen: dict[str, int] = {}
    reported: set[str] = set()
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, Mapping):
            continue  # malformed entry itself is W011
        entry_id = entry.get("id")
        if _missing(entry_id):
            w005.append(
                Finding("W005", doc.rel, f"`sources` entry #{i} is missing `id`", "§5.1")
            )
        else:
            key = str(entry_id)
            ids.add(key)
            if key in seen and key not in reported:
                reported.add(key)
                w015.append(
                    Finding("W015", doc.rel, f"duplicate `sources[].id` {key!r}", "§5.1")
                )
            else:
                seen[key] = i
        if _missing(entry.get("resource")):
            w008.append(
                Finding(
                    "W008",
                    doc.rel,
                    f"`sources` entry #{i} is missing REQUIRED `resource`",
                    "§5.1",
                )
            )
    return w005, w008, w015, ids


def _warn_footnote_unresolved(doc: _Doc, source_ids: set[str]) -> list[Finding]:
    """W004 — body footnote reference ``[^id]`` with no matching ``sources[].id`` (§5.1)."""
    labels = {m.group(1).strip() for m in _FOOTNOTE_REF_RE.finditer(_strip_code(doc.body))}
    return [
        Finding(
            "W004",
            doc.rel,
            f"footnote reference [^{label}] has no matching `sources[].id`",
            "§5.1",
        )
        for label in sorted(labels - source_ids)
        if label
    ]


def _warn_actor_missing_by(doc: _Doc) -> list[Finding]:
    """W009 — ``generated`` without REQUIRED ``by``, or a ``verified`` entry without ``by`` (§5.2)."""
    assert doc.fm is not None
    findings: list[Finding] = []
    generated = doc.fm.get("generated")
    if isinstance(generated, Mapping) and _missing(generated.get("by")):
        findings.append(
            Finding("W009", doc.rel, "`generated` is missing REQUIRED `by`", "§5.2")
        )
    entries, _ = _normalize_verified(doc.fm.get("verified"))
    if entries:
        for i, entry in enumerate(entries, 1):
            if isinstance(entry, Mapping) and _missing(entry.get("by")):
                findings.append(
                    Finding("W009", doc.rel, f"`verified` entry #{i} is missing `by`", "§5.2")
                )
    return findings


def _warn_attested_runtime(doc: _Doc) -> list[Finding]:
    """W010 — ``type: Attested Computation`` without REQUIRED ``runtime`` (§10.2)."""
    assert doc.fm is not None
    type_value = doc.fm.get("type")
    type_str = type_value if isinstance(type_value, str) else str(type_value)
    if type_str == "Attested Computation" and _missing(doc.fm.get("runtime")):
        return [
            Finding(
                "W010",
                doc.rel,
                "`type` is 'Attested Computation' but REQUIRED `runtime` is missing",
                "§10.2",
            )
        ]
    return []


def _warn_malformed_datetimes(doc: _Doc) -> list[Finding]:
    """W011 — timestamp-valued keys not ISO 8601 with an explicit UTC offset (§5)."""
    assert doc.fm is not None
    fm = doc.fm
    findings: list[Finding] = []

    def check(label: str, value: object) -> None:
        if value is None:
            return
        ok, _ = _parse_timestamp(value)
        if not ok:
            findings.append(
                Finding(
                    "W011",
                    doc.rel,
                    f"malformed datetime for `{label}`: {value!r} "
                    "(expected ISO 8601 with explicit UTC offset)",
                    "§5",
                )
            )

    generated = fm.get("generated")
    if generated is not None:
        if isinstance(generated, Mapping):
            check("generated.at", generated.get("at"))
        else:
            findings.append(
                Finding("W011", doc.rel, "malformed `generated` value: expected a mapping", "§5")
            )

    entries, malformed = _normalize_verified(fm.get("verified"))
    if malformed:
        findings.append(
            Finding("W011", doc.rel, "malformed `verified` value: expected a list or mapping", "§5")
        )
    elif entries:
        for i, entry in enumerate(entries, 1):
            if isinstance(entry, Mapping):
                check(f"verified[{i}].at", entry.get("at"))
            else:
                findings.append(
                    Finding("W011", doc.rel, f"malformed `verified` entry #{i}: expected a mapping", "§5")
                )

    sources, sources_malformed = _source_entries(doc)
    if sources_malformed:
        findings.append(
            Finding("W011", doc.rel, "malformed `sources` value: expected a list", "§5")
        )
    elif sources:
        for i, entry in enumerate(sources, 1):
            if isinstance(entry, Mapping):
                check(f"sources[{i}].last_modified", entry.get("last_modified"))
            else:
                findings.append(
                    Finding("W011", doc.rel, f"malformed `sources` entry #{i}: expected a mapping", "§5")
                )

    usage_window = fm.get("usage_window")
    if usage_window is not None:
        if isinstance(usage_window, Mapping):
            check("usage_window.from", usage_window.get("from"))
            check("usage_window.to", usage_window.get("to"))
        else:
            findings.append(
                Finding("W011", doc.rel, "malformed `usage_window` value: expected a mapping", "§5")
            )

    check("stale_after", fm.get("stale_after"))
    check("timestamp", fm.get("timestamp"))
    return findings


def _warn_stale(doc: _Doc) -> list[Finding]:
    """W006 — ``now >= stale_after`` (UTC comparison, §5.5). Informational only."""
    assert doc.fm is not None
    value = doc.fm.get("stale_after")
    if value is None:
        return []
    ok, moment = _parse_timestamp(value)
    if not ok or moment is None:
        return []  # malformed values are reported as W011
    if datetime.now(timezone.utc) >= moment:
        return [
            Finding(
                "W006",
                doc.rel,
                f"content is stale: `stale_after` {moment.isoformat()} has passed",
                "§5.5",
            )
        ]
    return []


def _warn_legacy(doc: _Doc) -> list[Finding]:
    """W012 — v0.1 legacy ``timestamp`` field or body ``# Citations`` list (§13.1)."""
    assert doc.fm is not None
    findings: list[Finding] = []
    if "timestamp" in doc.fm:
        findings.append(
            Finding(
                "W012",
                doc.rel,
                "legacy v0.1 field `timestamp`; consider migrating to `generated.at` (§13.1)",
                "§13.1",
            )
        )
    body = _strip_code(doc.body)
    for match in _CITATIONS_RE.finditer(body):
        section = body[match.end() :]
        has_list = False
        for line in section.splitlines():
            if _HEADING_ANY_RE.match(line):
                break
            if _LIST_ITEM_RE.match(line):
                has_list = True
                break
        if has_list:
            findings.append(
                Finding(
                    "W012",
                    doc.rel,
                    "legacy v0.1 body `# Citations` list; consider migrating to frontmatter `sources` (§13.1)",
                    "§13.1",
                )
            )
            break
    return findings


def _warn_unknown_status(doc: _Doc) -> list[Finding]:
    """W014 — ``status`` not one of draft / stable / deprecated (§5.4)."""
    assert doc.fm is not None
    status = doc.fm.get("status")
    if status is not None and str(status) not in {"draft", "stable", "deprecated"}:
        return [
            Finding(
                "W014",
                doc.rel,
                f"unknown `status` {status!r}; expected draft | stable | deprecated",
                "§5.4",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_checks(root: Path) -> tuple[list[Finding], list[Finding]]:
    """Run every rule over the bundle at *root*; returns ``(errors, warnings)``."""
    concepts: list[_Doc] = []
    index_docs: list[_Doc] = []
    errors: list[Finding] = []
    w007_findings: list[Finding] = []
    w013_findings: list[Finding] = []

    md_files = sorted(
        (p for p in root.rglob("*.md") if p.is_file()),
        # Bundle-root reserved files sort before nested ones of the same name,
        # so the root index.md / log.md findings come first; otherwise plain
        # bundle-relative path order.
        key=lambda p: (
            _rel_posix(root, p.parent) != ".",
            _rel_posix(root, p),
        ),
    )
    for path in md_files:
        rel = _rel_posix(root, path)
        if path.name == "index.md":
            doc, doc_errors, doc_warnings = _analyze_index(path, rel, path.parent == root)
            index_docs.append(doc)
            errors.extend(doc_errors)
            w007_findings.extend(doc_warnings)
        elif path.name == "log.md":
            _doc, doc_errors, doc_warnings = _analyze_log(path, rel)
            errors.extend(doc_errors)
            w013_findings.extend(doc_warnings)
        else:
            doc, doc_errors = _analyze_concept(path, rel)
            concepts.append(doc)  # sorted by rel already
            errors.extend(doc_errors)

    warnings: list[Finding] = []

    # W001 broken-link (concept bodies only; index entries are never link-checked)
    for doc in concepts:
        warnings.extend(_warn_broken_links(root, doc))

    # W002 orphan-concept (reachability from index.md entries only)
    covered_ids, covered_prefixes = _collect_index_coverage(root, index_docs)
    for doc in concepts:
        warnings.extend(_warn_orphan(doc, covered_ids, covered_prefixes))

    # Frontmatter-dependent warnings, in rule-code order (skip files with E001/E002).
    # `_warn_sources` is evaluated once per concept; its outputs feed W004/W005/W008/W015.
    ok_docs = [doc for doc in concepts if doc.fm_ok]
    per_doc_sources = [(doc, *_warn_sources(doc)) for doc in ok_docs]

    for doc in ok_docs:  # W003
        warnings.extend(_warn_missing_recommended(doc))
    for doc, _w005, _w008, _w015, source_ids in per_doc_sources:  # W004
        warnings.extend(_warn_footnote_unresolved(doc, source_ids))
    for _doc, w005, _w008, _w015, _source_ids in per_doc_sources:  # W005
        warnings.extend(w005)
    for doc in ok_docs:  # W006
        warnings.extend(_warn_stale(doc))
    warnings.extend(w007_findings)  # W007
    for _doc, _w005, w008, _w015, _source_ids in per_doc_sources:  # W008
        warnings.extend(w008)
    for doc in ok_docs:  # W009
        warnings.extend(_warn_actor_missing_by(doc))
    for doc in ok_docs:  # W010
        warnings.extend(_warn_attested_runtime(doc))
    for doc in ok_docs:  # W011
        warnings.extend(_warn_malformed_datetimes(doc))
    for doc in ok_docs:  # W012
        warnings.extend(_warn_legacy(doc))
    warnings.extend(w013_findings)  # W013
    for doc in ok_docs:  # W014
        warnings.extend(_warn_unknown_status(doc))
    for _doc, _w005, _w008, w015, _source_ids in per_doc_sources:  # W015
        warnings.extend(w015)

    return errors, warnings
