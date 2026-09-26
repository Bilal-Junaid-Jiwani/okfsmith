"""Two-pass LLM concept extraction pipeline.

Pass 1 (draft, cheap model): each :class:`SectionInput` becomes concept JSON,
written via :meth:`okfsmith.core.bundle.Bundle.write_concept` with OKF v0.2
frontmatter, ``status: "draft"``, a ``generated`` stamp, ``sources[]``
provenance, and per-claim ``[^id]`` footnotes in the body.

Pass 2 (critic, same or stronger model): each draft is verified —
contradictions, claim fidelity against the section text, stub detection.
Passing drafts get a machine ``verified`` stamp; failures are fixed from the
critic's corrected JSON or flagged ``needs-review``.

Dedup: a SHA-256 ``source_digest`` in frontmatter skips re-ingest; entity
resolution (normalized-title match, or same ``resource`` with
title compatibility) merges duplicates, keeping the richer concept. Embedding
similarity is a v1 TODO (logged, not implemented).

Retroactive linking: after writing, existing concepts whose body mentions a
new concept's title get a backlink to it (exact normalized-title substring
match).

Deterministic fallbacks everywhere: a JSON parse failure triggers one retry
with a repair prompt; if that also fails, the draft is kept, tagged
``needs-review``, and the incident is logged as a warning.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from okfsmith.core import indexlog
from okfsmith.core.bundle import Bundle, Concept, slugify
from okfsmith.core.spec import utc_now_iso

from . import llm as _llm
from . import prompts as _prompts

logger = logging.getLogger(__name__)

#: Tag applied to drafts that need a human to look at them.
NEEDS_REVIEW_TAG = "needs-review"

#: Subdirectory (bundle-relative) where extracted concepts are written.
EXTRACT_DIR = "extracted"

#: Minimum normalized-title length for retroactive backlink matching, to
#: avoid noise from tiny titles like "AI".
_MIN_BACKLINK_TITLE_LEN = 4


@dataclass
class SectionInput:
    """One parsed document section — the unit of extraction.

    Defined here (not imported from the parsers branch) so this package has
    a stable input contract of its own.
    """

    title: str
    level: int
    text: str
    page_span: tuple[int, int] | list[int] | str | None
    tables: list = field(default_factory=list)
    source_id: str = ""
    source_path: str = ""
    doc_title: str = ""
    doc_summary: str = ""
    #: Full breadcrumb path of the section (e.g. "Guide > Install"). Used in
    #: the contextual situating prefix; defaults to ``title`` when empty.
    section_path: str = ""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def situating_prefix(section: SectionInput) -> str:
    """Anthropic-style contextual situating prefix for *section*.

    Stamped into every concept's description and body intro: document title,
    section path, and the one-line document summary.
    """
    path = section.section_path or section.title
    doc_title = section.doc_title or "untitled document"
    summary = section.doc_summary or "no summary available"
    return f'From "{doc_title}", section "{path}": {summary}'


def source_digest(section: SectionInput) -> str:
    """SHA-256 digest identifying *section* for re-ingest dedup."""
    normalized = re.sub(
        r"\s+", " ", f"{section.source_id}\n{section.title}\n{section.text}".lower()
    ).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    """Normalize a title for entity resolution (case/punct-insensitive)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def _parse_json_strict(raw: str) -> dict:
    """Parse *raw* as a JSON object, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    return data


def _as_list(value, *, of: str = "items") -> list:
    return value if isinstance(value, list) else []


def _coerce_concept(data: dict, section: SectionInput) -> dict:
    """Coerce raw LLM JSON into the canonical concept shape, with fallbacks.

    Missing fields fall back to section metadata ("skip, don't invent" —
    the pipeline fills lineage, never facts).
    """
    claims = []
    for claim in _as_list(data.get("claims")):
        if isinstance(claim, dict) and str(claim.get("text", "")).strip():
            claims.append(
                {"text": str(claim["text"]).strip(), "page": claim.get("page")}
            )
        elif isinstance(claim, str) and claim.strip():
            claims.append({"text": claim.strip(), "page": None})

    links = []
    for link in _as_list(data.get("links")):
        if isinstance(link, dict) and str(link.get("target", "")).strip():
            links.append(
                {
                    "target": str(link["target"]).strip(),
                    "why": str(link.get("why", "")).strip()
                    or "Related concept (no reason given).",
                }
            )

    tags = sorted(
        {
            re.sub(r"[^a-z0-9-]+", "-", str(tag).lower()).strip("-")
            for tag in _as_list(data.get("tags"))
            if str(tag).strip()
        }
    )

    concept_type = str(data.get("type") or "note").strip() or "note"
    title = str(data.get("title") or section.title).strip() or "Untitled"
    description = str(data.get("description") or section.doc_summary or "").strip()
    return {
        "type": concept_type,
        "title": title,
        "description": description,
        "claims": claims,
        "links": links,
        "tags": tags,
    }


def _claim_page_resource(section: SectionInput, page) -> str:
    if page is None or (isinstance(page, str) and not page.strip()):
        return section.source_path
    return f"{section.source_path}#page={page}"


def _build_frontmatter(
    concept: dict, section: SectionInput, model: str, digest: str
) -> dict:
    """Build OKF v0.2 frontmatter for a draft concept."""
    description = concept["description"]
    prefix = situating_prefix(section)
    if not description.startswith(prefix):
        description = f"{prefix} {description}".strip()

    sources = []
    for i, claim in enumerate(concept["claims"], start=1):
        sources.append(
            {
                "id": f"claim-{i}",
                "resource": _claim_page_resource(section, claim.get("page")),
                "title": section.doc_title,
            }
        )

    return {
        "type": concept["type"],
        "title": concept["title"],
        "description": description,
        "tags": concept["tags"],
        "resource": section.source_path,
        "source_digest": digest,
        "sources": sources,
        "generated": {"by": f"okfsmith-extract/{model}", "at": utc_now_iso()},
        "status": "draft",
    }


def _build_body(concept: dict, section: SectionInput) -> str:
    """Build the concept body: situating intro + section text + claims."""
    lines = [f"> {situating_prefix(section)}", ""]
    lines.append(section.text.strip() or "_No section text captured._")
    lines.append("")

    if concept["claims"]:
        lines += ["## Claims", ""]
        for i, claim in enumerate(concept["claims"], start=1):
            lines.append(f"- {claim['text']}[^claim-{i}]")
        lines.append("")

    if concept["links"]:
        lines += ["## See also", ""]
        for link in concept["links"]:
            # Bundle-relative link; may dangle (spec §6: broken links are
            # warnings, never errors — validation flags them later).
            lines.append(f"- [{link['target']}]({slugify(link['target'])}) — {link['why']}")
        lines.append("")

    if concept["claims"]:
        for i, claim in enumerate(concept["claims"], start=1):
            lines.append(
                f"[^claim-{i}]: {_claim_page_resource(section, claim.get('page'))}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _concept_id_for(bundle: Bundle, title: str) -> str:
    """Allocate a fresh concept id under ``extracted/`` for *title*."""
    base = f"{EXTRACT_DIR}/{slugify(title)}"
    candidate, n = base, 1
    while bundle.get(candidate) is not None:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _already_ingested(bundle: Bundle, digest: str) -> Concept | None:
    """Return the concept carrying *digest*, if this section was ingested."""
    for concept in bundle.iter_concepts():
        if concept.frontmatter.get("source_digest") == digest:
            return concept
    return None


def _find_duplicate(
    bundle: Bundle, title: str, resource: str, *, exclude_id: str | None = None
) -> Concept | None:
    """Entity resolution: normalized-title match, or same ``resource``.

    The same-resource branch is gated on title compatibility (one normalized
    title containing the other): without that gate, every section of a
    multi-section document would collapse into a single concept, since they
    legitimately share ``resource`` (the source document path). The SHA-256
    ``source_digest`` remains the primary re-ingest guard; embedding
    similarity is a v1 TODO (logged in :func:`run`).
    """
    norm = normalize_title(title)
    for concept in bundle.iter_concepts():
        if concept.id == exclude_id:
            continue
        fm = concept.frontmatter
        existing_title = normalize_title(str(fm.get("title") or ""))
        if norm and existing_title and norm == existing_title:
            return concept
        if (
            resource
            and fm.get("resource") == resource
            and norm
            and existing_title
            and (norm in existing_title or existing_title in norm)
        ):
            return concept
    return None


def _richness(frontmatter: dict, body: str) -> tuple:
    """Richer concepts win merges: more sourced claims, longer body, verified."""
    verified = frontmatter.get("verified")
    has_verified = bool(verified) and verified != []
    return (
        len(frontmatter.get("sources") or []),
        len(body or ""),
        1 if has_verified else 0,
    )


def _tag_list(value: object) -> list[str]:
    """Normalize a frontmatter ``tags`` value to a list of strings.

    A bare string becomes ``[value]`` (not a set of characters); anything
    else is stringified element-wise; ``None`` becomes ``[]``.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(t) for t in value]
    return [str(value)]


def _one_line(value: object) -> str:
    """Collapse whitespace so log messages stay one entry per line."""
    return " ".join(str(value).split())


def _merge_concepts(
    bundle: Bundle, existing: Concept, new_frontmatter: dict, new_body: str, section: SectionInput
) -> Concept:
    """Merge a duplicate into *existing*, keeping the richer document.

    The richer document's content wins; ``verified`` entries and ``tags``
    are unioned (trust metadata is monotonic — a merge never drops a
    verification). The survivor keeps the *existing* id so links stay
    stable. Appends a log **Update**.
    """
    existing_score = _richness(existing.frontmatter, existing.body)
    new_score = _richness(new_frontmatter, new_body)

    if new_score > existing_score:
        merged_fm = dict(new_frontmatter)
        merged_body = new_body
        outcome = "replaced by richer duplicate"
    else:
        merged_fm = dict(existing.frontmatter)
        merged_body = existing.body
        outcome = "kept existing (richer)"

    # Monotonic trust metadata: never drop verifications or tags on merge.
    old_verified = existing.frontmatter.get("verified")
    old_list = (
        list(old_verified)
        if isinstance(old_verified, list)
        else ([old_verified] if isinstance(old_verified, dict) else [])
    )
    new_verified = merged_fm.get("verified")
    new_list = (
        list(new_verified)
        if isinstance(new_verified, list)
        else ([new_verified] if isinstance(new_verified, dict) else [])
    )
    seen = {(str(e.get("by")), str(e.get("at"))) for e in new_list if isinstance(e, dict)}
    for entry in old_list:
        key = (
            (str(entry.get("by")), str(entry.get("at")))
            if isinstance(entry, dict)
            else (str(entry), "")
        )
        if key not in seen:
            new_list.append(entry)
            seen.add(key)
    if new_list:
        merged_fm["verified"] = new_list
    # Security/robustness (audit-3 finding 10): normalize tag values before
    # unioning — a string ``tags: "abc"`` must not become a set of characters,
    # and mixed-type tags must not raise TypeError on re-ingest.
    merged_fm["tags"] = sorted(set(_tag_list(merged_fm.get("tags"))) | set(_tag_list(existing.frontmatter.get("tags"))))
    # The digest of the newest ingest is the freshest re-ingest guard.
    merged_fm["source_digest"] = new_frontmatter.get(
        "source_digest", existing.frontmatter.get("source_digest")
    )

    updated = bundle.write_concept(existing.id, merged_fm, merged_body)
    # Security (audit-3 finding 7): section titles may be attacker-influenced
    # (LLM output) — collapse newlines so the log keeps one entry per line.
    indexlog.append_log(
        bundle,
        "",
        "Update",
        f'merged duplicate concept from section "{_one_line(section.title)}" into '
        f'"{_one_line(existing.id)}" ({outcome})',
    )
    return updated


# ---------------------------------------------------------------------------
# Pass 1 — draft
# ---------------------------------------------------------------------------


def _extract_one(
    backend: _llm.LLMBackend, section: SectionInput
) -> tuple[dict, bool]:
    """Run pass 1 for *section*.

    Returns ``(concept_json, used_fallback)``. On JSON parse failure the
    repair prompt is tried once; if that also fails, a section-derived
    fallback draft is returned (``used_fallback=True``) so the pipeline
    never invents content.
    """
    raw = backend.chat(_prompts.build_extraction_messages(section), temperature=0.0)
    try:
        data = _parse_json_strict(raw)
    except (ValueError, json.JSONDecodeError) as first_error:
        logger.warning("Extraction JSON parse failed; retrying with repair prompt")
        try:
            raw = backend.chat(
                _prompts.build_repair_messages(raw, str(first_error)),
                temperature=0.0,
            )
            data = _parse_json_strict(raw)
        except (ValueError, json.JSONDecodeError, _llm.LLMError) as second_error:
            logger.warning(
                "Extraction repair failed (%s); keeping section-derived draft",
                second_error,
            )
            return _fallback_concept(section), True
    except _llm.LLMError:
        raise
    return _coerce_concept(data, section), False


def _fallback_concept(section: SectionInput) -> dict:
    """Honest draft when the LLM output is unusable: lineage only, no claims."""
    return {
        "type": "note",
        "title": section.title or "Untitled",
        "description": section.doc_summary or "",
        "claims": [],
        "links": [],
        "tags": [NEEDS_REVIEW_TAG],
    }


# ---------------------------------------------------------------------------
# Pass 2 — critic
# ---------------------------------------------------------------------------


def _critic_review(
    backend: _llm.LLMBackend, section: SectionInput, concept: dict
) -> dict:
    """Run pass 2 (critic) on a draft; always returns a verdict dict."""
    raw = backend.chat(
        _prompts.build_critic_messages(section.text, concept), temperature=0.0
    )
    try:
        verdict = _parse_json_strict(raw)
    except (ValueError, json.JSONDecodeError) as first_error:
        logger.warning("Critic JSON parse failed; retrying with repair prompt")
        try:
            raw = backend.chat(
                _prompts.build_repair_messages(raw, str(first_error)),
                temperature=0.0,
            )
            verdict = _parse_json_strict(raw)
        except (ValueError, json.JSONDecodeError, _llm.LLMError) as second_error:
            logger.warning(
                "Critic repair failed (%s); flagging draft for review", second_error
            )
            return {
                "verdict": "fail",
                "issues": ["critic output unparseable after repair"],
                "fixed_concept": None,
            }
    if not isinstance(verdict, dict) or verdict.get("verdict") not in {
        "pass",
        "fix",
        "fail",
    }:
        return {
            "verdict": "fail",
            "issues": ["critic returned an unrecognized verdict"],
            "fixed_concept": None,
        }
    return verdict


def _apply_critic_verdict(
    bundle: Bundle,
    concept: Concept,
    verdict: dict,
    section: SectionInput,
    model: str,
) -> None:
    """Apply a critic verdict: verify, fix, or flag ``needs-review``."""
    kind = verdict["verdict"]
    issues = verdict.get("issues") or []

    if kind == "pass":
        frontmatter = dict(concept.frontmatter)
        verified = frontmatter.get("verified")
        entries = (
            list(verified)
            if isinstance(verified, list)
            else ([verified] if isinstance(verified, dict) else [])
        )
        entries.append(
            {"by": f"process:okfsmith-critic/{model}", "at": utc_now_iso()}
        )
        frontmatter["verified"] = entries
        bundle.write_concept(concept.id, frontmatter, concept.body)
        indexlog.append_log(
            bundle,
            "",
            "Update",
            f'critic passed "{concept.id}" '
            f"(process:okfsmith-critic/{model}) → machine-confirmed",
        )
        return

    if kind == "fix" and isinstance(verdict.get("fixed_concept"), dict):
        fixed = _coerce_concept(verdict["fixed_concept"], section)
        fixed["tags"] = sorted(set(fixed["tags"]) | {NEEDS_REVIEW_TAG})
        digest = source_digest(section)
        frontmatter = _build_frontmatter(fixed, section, model, digest)
        body = _build_body(fixed, section)
        bundle.write_concept(concept.id, frontmatter, body)
        indexlog.append_log(
            bundle,
            "",
            "Update",
            f'critic fixed "{concept.id}" '
            f"(issues: {'; '.join(str(i) for i in issues) or 'unspecified'}) "
            "→ kept draft, flagged needs-review",
        )
        return

    # "fail" (or "fix" without a usable corrected concept): flag, keep draft.
    frontmatter = dict(concept.frontmatter)
    frontmatter["tags"] = sorted(set(frontmatter.get("tags") or []) | {NEEDS_REVIEW_TAG})
    bundle.write_concept(concept.id, frontmatter, concept.body)
    indexlog.append_log(
        bundle,
        "",
        "Update",
        f'critic flagged "{concept.id}" needs-review '
        f"(issues: {'; '.join(str(i) for i in issues) or 'unspecified'})",
    )


# ---------------------------------------------------------------------------
# Retroactive linking
# ---------------------------------------------------------------------------


def _inject_backlinks(bundle: Bundle, new_ids: list[str]) -> int:
    """Add backlinks to *new_ids* from existing concepts that mention them.

    Exact normalized-title substring match; never self-links; never
    duplicates an existing backlink. Returns the number of backlinks added.
    """
    added = 0
    targets = []
    for concept_id in new_ids:
        concept = bundle.get(concept_id)
        if concept is None:
            continue
        norm_title = normalize_title(str(concept.frontmatter.get("title") or ""))
        if len(norm_title) >= _MIN_BACKLINK_TITLE_LEN:
            targets.append((concept_id, str(concept.frontmatter.get("title")), norm_title))

    for target_id, target_title, norm_title in targets:
        for existing in bundle.iter_concepts():
            if existing.id == target_id:
                continue
            if f"](/{target_id})" in existing.body:
                continue  # already linked
            haystack = normalize_title(
                f"{existing.frontmatter.get('title', '')} {existing.body}"
            )
            if norm_title not in haystack:
                continue
            why = f'Mentions "{target_title}" — see that concept for detail.'
            line = f"- [{target_title}](/{target_id}) — {why}"
            body = existing.body.rstrip() + "\n"
            if "## See also" not in body:
                body += "\n## See also\n\n"
            body += line + "\n"
            bundle.write_concept(existing.id, dict(existing.frontmatter), body)
            indexlog.append_log(
                bundle,
                "",
                "Update",
                f'added backlink from "{existing.id}" to "{target_id}" ({why})',
            )
            added += 1
    return added


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    bundle: Bundle,
    sections: list[SectionInput],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    verify: bool = True,
) -> list[str]:
    """Extract concepts from *sections* into *bundle* (2-pass LLM).

    - ``model``: model name (default: ``OKFSMITH_MODEL`` env or ``qwen3:8b``).
    - ``base_url``: OpenAI-compatible endpoint (default: local Ollama).
    - ``api_key``: key for the endpoint (or ``OPENAI_API_KEY`` env; env only,
      never logged or persisted).
    - ``verify``: run pass 2 (critic). ``False`` skips verification.

    Returns the ids of newly written or merged concepts (dedup-skipped
    sections contribute nothing). Raises :class:`LLMUnavailableError` with
    an actionable message when no LLM endpoint is reachable.
    """
    backend = _llm.resolve_backend(model=model, base_url=base_url, api_key=api_key)
    resolved_model = backend.model
    logger.info(
        "Extraction run: %d section(s), model=%s, backend=%s, verify=%s",
        len(sections),
        resolved_model,
        backend.name,
        verify,
    )
    logger.debug(
        "Embedding similarity for entity resolution is a v1 TODO (rule-based only)"
    )

    written: list[str] = []          # concept ids created/merged this run
    drafts: dict[str, tuple[dict, SectionInput, bool]] = {}  # id -> (concept, section, fallback)

    # ---- Pass 1: draft -----------------------------------------------------
    for section in sections:
        digest = source_digest(section)

        dupe = _already_ingested(bundle, digest)
        if dupe is not None:
            logger.info(
                'Skipping re-ingest of section "%s" (already %s)',
                section.title,
                dupe.id,
            )
            continue

        concept, used_fallback = _extract_one(backend, section)
        frontmatter = _build_frontmatter(concept, section, resolved_model, digest)
        body = _build_body(concept, section)

        if used_fallback:
            indexlog.append_log(
                bundle,
                "",
                "Update",
                f'warning: unparseable LLM output for section "{section.title}" '
                "— section-derived draft kept, flagged needs-review",
            )

        duplicate = _find_duplicate(
            bundle, concept["title"], section.source_path
        )
        if duplicate is not None:
            merged = _merge_concepts(bundle, duplicate, frontmatter, body, section)
            written.append(merged.id)
            drafts[merged.id] = (concept, section, used_fallback)
        else:
            concept_id = _concept_id_for(bundle, concept["title"])
            created = bundle.write_concept(concept_id, frontmatter, body)
            indexlog.append_log(
                bundle, "", "Creation", f'extracted "{created.id}" from "{section.source_path}"'
            )
            written.append(created.id)
            drafts[created.id] = (concept, section, used_fallback)

    # ---- Pass 2: critic ----------------------------------------------------
    if verify:
        for concept_id, (concept_json, section, used_fallback) in drafts.items():
            if used_fallback:
                continue  # already flagged needs-review; critic adds nothing
            concept = bundle.get(concept_id)
            if concept is None:  # pragma: no cover — defensive
                continue
            verdict = _critic_review(backend, section, concept_json)
            _apply_critic_verdict(bundle, concept, verdict, section, resolved_model)

    # ---- Retroactive linking ----------------------------------------------
    n_links = _inject_backlinks(bundle, written)
    logger.info("Run complete: %d concept(s), %d backlink(s)", len(written), n_links)

    return written
