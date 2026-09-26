"""Prompts for the 2-pass LLM extraction pipeline.

Pass 1 drafts concept JSON; pass 2 (critic) verifies it. All prompts demand
STRICT JSON so the pipeline can parse them deterministically. A repair prompt
is used for the single retry after a JSON parse failure.

Contextual situating (Anthropic-style): every concept gets the document
title, the section path, and a one-line document summary stamped into its
description and body intro — the pipeline does the stamping (it never trusts
the model to reproduce lineage faithfully).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle; SectionInput lives in pipeline
    from okfsmith.extract.pipeline import SectionInput

EXTRACTION_SYSTEM_PROMPT = """\
You are an OKF concept extractor. You are a COMPILER, not an author: you \
faithfully transcribe what the source section says. Never invent facts, \
never embellish, never "improve" the content.

Output STRICT JSON only — no markdown fences, no commentary, no trailing text.

The JSON object MUST have exactly these keys:
{
  "type": "short OKF concept type, e.g. 'person', 'process', 'policy', 'reference', 'note'",
  "title": "concise concept title, faithful to the section",
  "description": "2-4 sentence summary, faithful to the section",
  "claims": [{"text": "a factual claim from the section", "page": 3}],
  "links": [{"target": "title of a related concept", "why": "one sentence explaining the relation"}],
  "tags": ["lowercase", "kebab-case", "tags"]
}

RULES — violating any rule invalidates the whole output:
1. COMPILER, NOT AUTHOR. Every claim must be traceable to the section text \
below. If the section does not support it, do not emit it.
2. EVERY claim MUST carry a "page" (page number or span) locating it in the \
source. Use the section's page span when the text gives no finer location. \
A claim without a page is rejected — omit the claim instead of guessing.
3. EVERY link MUST carry a one-sentence "why" explaining the relationship. \
No bare links.
4. SKIP, DON'T INVENT. When in doubt, leave the field out rather than \
guessing. An empty "claims" list is fine for a section with no factual claims.
5. Keep "description" and claim "text" short and faithful; quote the source \
when the exact wording matters.
"""

CRITIC_SYSTEM_PROMPT = """\
You are an OKF concept critic. You receive a source section and a draft \
concept extracted from it. Check for:

1. CONTRADICTIONS — does the draft contradict itself or the source text?
2. CLAIM FIDELITY — is every claim actually supported by the section text? \
Does every claim carry a page?
3. STUBS — is the concept too thin to be useful (empty claims AND a \
one-line description with no substance)?

Output STRICT JSON only — no markdown fences, no commentary:
{
  "verdict": "pass" | "fix" | "fail",
  "issues": ["short, specific issue descriptions"],
  "fixed_concept": { ...full corrected concept in the extraction shape... } or null
}

- "pass": no material issues. "fixed_concept" must be null.
- "fix": issues you can correct yourself — put the FULL corrected concept \
(JSON in the extraction shape: type/title/description/claims/links/tags) in \
"fixed_concept".
- "fail": beyond repair (contradicts the source, fabricated claims, empty \
stub) — "fixed_concept" must be null.

COMPILER, NOT AUTHOR: the fixed concept must contain nothing beyond what the \
section text supports. Never add outside facts.
"""

REPAIR_INSTRUCTION = """\
Your previous output was not valid JSON ({error}). Re-emit the response as \
STRICT JSON only — no markdown fences, no commentary, no trailing text. \
If you cannot produce valid JSON, emit {{"verdict": "fail", "issues": \
["could not produce valid JSON"], "fixed_concept": null}}.
"""


def build_extraction_messages(section: "SectionInput") -> list[dict]:
    """Build the chat messages for pass 1 (draft) for *section*."""
    section_path = section.section_path or section.title
    parts = [
        f"Document title: {section.doc_title}",
        f"Section path: {section_path} (heading level {section.level})",
        f"Page span: {section.page_span}",
        f"Document summary: {section.doc_summary}",
        "",
        "Section text:",
        section.text,
    ]
    if section.tables:
        parts.append("")
        parts.append("Tables in this section:")
        for table in section.tables:
            parts.append(str(table))
    parts.append("")
    parts.append(
        "Extract ONE concept from the section above as STRICT JSON. "
        "The pipeline will stamp the document title, section path, and "
        "document summary into the concept itself — focus on faithful claims."
    )
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def build_critic_messages(section_text: str, concept_json: dict) -> list[dict]:
    """Build the chat messages for pass 2 (critic)."""
    import json as _json

    user = "\n".join(
        [
            "Source section text:",
            section_text,
            "",
            "Draft concept JSON:",
            _json.dumps(concept_json, ensure_ascii=False, indent=2),
            "",
            "Criticize the draft as STRICT JSON.",
        ]
    )
    return [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_repair_messages(raw_output: str, error: str) -> list[dict]:
    """Build the single-retry repair messages after a JSON parse failure."""
    return [
        {
            "role": "user",
            "content": "Your previous output:\n"
            + raw_output[:4000]
            + "\n\n"
            + REPAIR_INSTRUCTION.format(error=error),
        }
    ]
