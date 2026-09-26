"""okfsmith.extract — 2-pass LLM concept extraction.

Pass 1 (draft): :mod:`okfsmith.extract.pipeline` turns each
:class:`~okfsmith.extract.pipeline.SectionInput` into concept JSON via the
configured LLM backend (:mod:`okfsmith.extract.llm`, default local Ollama),
writing OKF v0.2 concepts with ``sources[]`` provenance and ``generated``
stamps. Pass 2 (critic): the same (or a stronger) model verifies each draft
— contradictions, claim fidelity, stub detection — promoting passes to the
machine-confirmed tier or flagging failures ``needs-review``.
:mod:`okfsmith.extract.human_review` promotes concepts to human-reviewed.

Input contract: :class:`~okfsmith.extract.pipeline.SectionInput` is defined
here (not imported from the parsers branch) — ``(title, level, text,
page_span, tables, source_id, source_path, doc_title, doc_summary)`` plus an
optional ``section_path`` for the situating prefix.
"""

from okfsmith.extract import human_review, llm, pipeline, prompts
from okfsmith.extract.human_review import mark_reviewed
from okfsmith.extract.llm import (
    PROVIDER_PRESETS,
    LLMBackend,
    LLMConfig,
    LLMError,
    LLMResponseError,
    LLMUnavailableError,
    OpenAICompatibleBackend,
    key_status,
    redact_key,
    resolve_backend,
    resolve_llm_config,
    resolve_model,
)
from okfsmith.extract.pipeline import SectionInput, run, situating_prefix

__all__ = [
    "LLMBackend",
    "LLMConfig",
    "LLMError",
    "LLMResponseError",
    "LLMUnavailableError",
    "OpenAICompatibleBackend",
    "PROVIDER_PRESETS",
    "SectionInput",
    "human_review",
    "key_status",
    "llm",
    "mark_reviewed",
    "pipeline",
    "prompts",
    "redact_key",
    "resolve_backend",
    "resolve_llm_config",
    "resolve_model",
    "run",
    "situating_prefix",
]
