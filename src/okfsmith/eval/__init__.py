"""``okfsmith eval``: golden Q&A evaluation harness (P4).

Golden sets live at ``<bundle>/eval/golden.json`` — a list of
``{id, question, expected_answer, must_cite, tags}`` records (see
:func:`GOLDEN_SCHEMA_DOC`). Retrieval reuses the shared BM25 engine
(:func:`okfsmith.search.search_bundle_detailed`) so CLI, chat, MCP, and eval
rank identically — including temporal supersession hiding.

For each question the RAG Triad is scored:

- *context relevancy*: fraction of retrieved concepts relevant to the
  question + expected answer;
- *faithfulness*: fraction of the answer's claims supported by the
  retrieved context;
- *answer relevancy*: question <-> answer similarity.

Every score is labeled ``heuristic`` (keyless stdlib token-overlap) or
``llm-judge`` (an LLM backend was configured and reachable). An LLM judge
that fails degrades that metric to the heuristic — the method label always
tells the truth, never the other way around.

Failing questions get a *retrieval-vs-generation* diagnosis: if a golden
``must_cite`` concept was not retrieved (or nothing retrieved shares
vocabulary with the question), the failure is labeled ``retrieval``;
otherwise it is labeled ``generation``. This is the actionable output. An
unretrieved golden ``must_cite`` concept fails its question even when every
metric score passes its threshold — the golden set demands evidence from a
concept retrieval never surfaced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from okfsmith.search import STOPWORDS, search_bundle_detailed, tokenize

__all__ = [
    "EvalError",
    "EvalReport",
    "GoldenQuestion",
    "METRICS",
    "QuestionResult",
    "Score",
    "diagnose",
    "extractive_answer",
    "load_golden_set",
    "run_eval",
    "sample_golden_set",
    "write_sample_golden",
]

#: The three RAG Triad metrics, in reporting order.
METRICS = ("context_relevancy", "faithfulness", "answer_relevancy")

#: Where a bundle's golden Q&A set lives.
GOLDEN_FILENAME = "golden.json"

GOLDEN_SCHEMA_DOC = """\
Golden sets are a JSON list of question records at <bundle>/eval/golden.json:

  [
    {
      "id": "trust-tiers",
      "question": "How are trust tiers derived?",
      "expected_answer": "From the generated and verified frontmatter fields.",
      "must_cite": ["concepts/trust-tiers"],
      "tags": ["trust", "spec"]
    }
  ]

Fields: id (unique, non-empty string), question (non-empty string),
expected_answer (reference answer text, string), must_cite (list of
concept ids a good answer must cite — drives the retrieval-vs-generation
diagnosis), tags (free-form list of strings). must_cite and tags are
optional and default to [].
"""


class EvalError(Exception):
    """An expected eval failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


# ---------------------------------------------------------------------------
# Golden sets
# ---------------------------------------------------------------------------


@dataclass
class GoldenQuestion:
    """One golden Q&A record."""

    id: str
    question: str
    expected_answer: str = ""
    must_cite: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def golden_path(bundle_dir: Path) -> Path:
    """Path of the golden set inside *bundle_dir*."""
    return Path(bundle_dir) / "eval" / GOLDEN_FILENAME


def load_golden_set(bundle_dir: Path) -> list[GoldenQuestion]:
    """Load and schema-validate ``<bundle_dir>/eval/golden.json``.

    Raises :class:`EvalError` with code ``golden-not-found``,
    ``golden-invalid`` (bad JSON), or ``golden-schema`` (wrong shape) —
    never a traceback.
    """
    path = golden_path(bundle_dir)
    if not path.is_file():
        raise EvalError(
            "golden-not-found",
            f"no golden set at '{path}'.",
            f"Run 'okfsmith eval {bundle_dir} --init-sample' to write a "
            "starter set, or add <bundle>/eval/golden.json manually.",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise EvalError(
            "golden-invalid",
            f"'{path}' is not valid UTF-8: {exc}.",
            "Save the file as UTF-8 JSON.",
        ) from None
    except json.JSONDecodeError as exc:
        raise EvalError(
            "golden-invalid",
            f"'{path}' is not valid JSON: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno}).",
            "Fix the JSON syntax and retry.",
        ) from None
    except OSError as exc:
        raise EvalError(
            "io-error",
            f"cannot read '{path}': {exc}.",
            "Check the file is readable.",
        ) from None
    return _validate_golden(raw, path)


def _validate_golden(raw: Any, path: Path) -> list[GoldenQuestion]:
    """Schema-check the parsed JSON; raise EvalError("golden-schema")."""
    where = f"'{path}'"
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list):
        raw = raw["questions"]
    if not isinstance(raw, list):
        raise EvalError(
            "golden-schema",
            f"{where}: top level must be a JSON list of question records.",
            GOLDEN_SCHEMA_DOC,
        )
    if not raw:
        raise EvalError(
            "golden-schema",
            f"{where}: golden set is empty — add at least one question.",
            GOLDEN_SCHEMA_DOC,
        )
    questions: list[GoldenQuestion] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        label = f"record #{idx}"
        if not isinstance(item, dict):
            raise EvalError(
                "golden-schema",
                f"{where}: {label} must be an object, got "
                f"{type(item).__name__}.",
                GOLDEN_SCHEMA_DOC,
            )
        qid = item.get("id")
        if not isinstance(qid, str) or not qid.strip():
            raise EvalError(
                "golden-schema",
                f"{where}: {label} needs a non-empty string 'id'.",
                GOLDEN_SCHEMA_DOC,
            )
        label = f"record '{qid}'"
        if qid in seen:
            raise EvalError(
                "golden-schema",
                f"{where}: duplicate question id '{qid}'.",
                "Question ids must be unique within a golden set.",
            )
        seen.add(qid)
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            raise EvalError(
                "golden-schema",
                f"{where}: {label} needs a non-empty string 'question'.",
                GOLDEN_SCHEMA_DOC,
            )
        expected = item.get("expected_answer", "")
        if not isinstance(expected, str):
            raise EvalError(
                "golden-schema",
                f"{where}: {label} 'expected_answer' must be a string.",
                GOLDEN_SCHEMA_DOC,
            )
        must_cite = item.get("must_cite", [])
        if not isinstance(must_cite, list) or not all(
            isinstance(c, str) for c in must_cite
        ):
            raise EvalError(
                "golden-schema",
                f"{where}: {label} 'must_cite' must be a list of strings.",
                GOLDEN_SCHEMA_DOC,
            )
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(
            isinstance(t, str) for t in tags
        ):
            raise EvalError(
                "golden-schema",
                f"{where}: {label} 'tags' must be a list of strings.",
                GOLDEN_SCHEMA_DOC,
            )
        questions.append(
            GoldenQuestion(
                id=qid,
                question=question,
                expected_answer=expected,
                must_cite=list(must_cite),
                tags=list(tags),
            )
        )
    return questions


def _sample_question(concept_id: str, title: str, answer_text: str) -> str:
    """A question the extractive answer provably covers.

    The keyless answer-relevancy heuristic scores the fraction of the
    question's content tokens covered by the answer. A template like
    ``"What is {title}?"`` fails its own gate — "what" never appears in an
    extractive answer — so the question is phrased from the concept title's
    content words ("About" is a stopword and never affects the score),
    filtered to words the answer excerpt actually contains. When the title
    shares no vocabulary with its own excerpt, the concept id is used
    instead: the extractive answer always cites ``[concept.id]``, so the
    id's tokens are guaranteed present.
    """
    answer_tokens = _content_tokens(answer_text)
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9_]+", title or "")
        if word.lower() not in STOPWORDS
    ]
    kept = [word for word in words if _content_tokens(word) <= answer_tokens]
    if kept:
        return "About " + " ".join(kept) + "?"
    return concept_id + "?"


def sample_golden_set(concepts: list[Any], max_questions: int = 3) -> list[dict]:
    """Build a small demo golden set derived from real *concepts*.

    Each record asks about one concept with a question whose content words
    all appear in the concept (see :func:`_sample_question`), so the
    starter set passes its own default thresholds under keyless heuristic
    scoring. ``expected_answer`` is the description (falling back to the
    body lead); ``must_cite`` points at the concept. Marked as a demo
    starter.
    """
    records: list[dict] = []
    for concept in concepts[:max_questions]:
        title = str(concept.frontmatter.get("title") or concept.id)
        expected = str(concept.frontmatter.get("description") or "").strip()
        if not expected:
            expected = _first_sentences(concept.body, n=2)
        answer_text, _ = extractive_answer([concept])
        records.append(
            {
                "id": f"demo-{concept.id.replace('/', '-').replace('.', '-')}",
                "question": _sample_question(concept.id, title, answer_text),
                "expected_answer": expected,
                "must_cite": [concept.id],
                "tags": ["demo"],
            }
        )
    return records


def write_sample_golden(bundle_dir: Path, concepts: list[Any]) -> Path:
    """Write a starter ``<bundle_dir>/eval/golden.json``; returns the path.

    Refuses to overwrite an existing golden set (the user owns that file).
    """
    path = golden_path(bundle_dir)
    if path.exists():
        raise EvalError(
            "golden-exists",
            f"'{path}' already exists — not overwriting.",
            "Edit it directly, or delete it first to regenerate a sample.",
        )
    records = sample_golden_set(concepts)
    if not records:
        raise EvalError(
            "golden-no-concepts",
            f"bundle '{bundle_dir}' has no concepts to build a sample from.",
            f"Add sources with 'okfsmith ingest {bundle_dir} <file> --no-llm' "
            "first.",
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise EvalError(
            "io-error",
            f"cannot write '{path}': {exc}.",
            "Check the bundle directory is writable.",
        ) from None
    return path


# ---------------------------------------------------------------------------
# Text helpers (keyless heuristics, stdlib only)
# ---------------------------------------------------------------------------


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _content_tokens(text: str) -> set[str]:
    """Stemmed, stopword-free token set (shared engine tokenizer)."""
    return set(tokenize(text or ""))


def _concept_text(concept: Any) -> str:
    fm = concept.frontmatter or {}
    parts = [
        concept.id,
        str(fm.get("title") or ""),
        str(fm.get("description") or ""),
        " ".join(str(t) for t in (fm.get("tags") or [])),
        concept.body or "",
    ]
    return "\n".join(parts)


def _first_sentences(text: str, n: int = 2) -> str:
    """First *n* sentences of *text*, whitespace-collapsed."""
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return ""
    sentences = _SENTENCE_RE.split(collapsed)
    return " ".join(sentences[:n])


def _snippet(text: str, width: int = 300) -> str:
    """First meaningful line of *text*, whitespace-collapsed, truncated."""
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if line and not line.startswith("#"):
            return line if len(line) <= width else line[: width - 1] + "…"
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= width else collapsed[: width - 1] + "…"


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split((text or "").strip()) if s.strip()]


def extractive_answer(concepts: list[Any]) -> tuple[str, list[str]]:
    """Extractive answer over *concepts*: id-cited excerpts.

    Returns ``(answer_text, cited_ids)`` — the same excerpt style chat's
    extractive mode shows, so eval measures what users actually see.
    """
    parts: list[str] = []
    cited: list[str] = []
    for concept in concepts:
        fm = concept.frontmatter or {}
        excerpt = _snippet(
            str(fm.get("description") or "") or concept.body or ""
        )
        if not excerpt:
            continue
        parts.append(f"[{concept.id}] {excerpt}")
        cited.append(concept.id)
    return "\n".join(parts), cited


# ---------------------------------------------------------------------------
# Heuristic metrics (keyless)
# ---------------------------------------------------------------------------


def heuristic_context_relevancy(
    question: str, expected_answer: str, concepts: list[Any]
) -> tuple[float, str]:
    """Fraction of *concepts* sharing vocabulary with question+expected.

    A concept counts as relevant when it shares at least one content token
    with the question or the expected answer. Empty retrieval scores 0.0.
    """
    if not concepts:
        return 0.0, "no concepts retrieved"
    query_tokens = _content_tokens(question) | _content_tokens(expected_answer)
    if not query_tokens:
        return 0.0, "question and expected answer have no content tokens"
    relevant = sum(
        1 for c in concepts if _content_tokens(_concept_text(c)) & query_tokens
    )
    return relevant / len(concepts), f"{relevant}/{len(concepts)} relevant"


def heuristic_faithfulness(answer: str, concepts: list[Any]) -> tuple[float, str]:
    """Fraction of the answer's sentences supported by retrieved context.

    A sentence is supported when at least half its content tokens appear
    somewhere in the retrieved concepts' text. Empty answers score 0.0.
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return 0.0, "answer has no sentences to check"
    context_tokens: set[str] = set()
    for concept in concepts:
        context_tokens |= _content_tokens(_concept_text(concept))
    supported = 0
    for sentence in sentences:
        tokens = _content_tokens(sentence)
        if not tokens:
            continue
        if len(tokens & context_tokens) / len(tokens) >= 0.5:
            supported += 1
    return supported / len(sentences), f"{supported}/{len(sentences)} supported"


def heuristic_answer_relevancy(question: str, answer: str) -> tuple[float, str]:
    """Recall-oriented question↔answer overlap: fraction of the question's
    content tokens covered by the answer. A relevant answer addresses the
    question's terms even when it adds much more text."""
    q_tokens = _content_tokens(question)
    a_tokens = _content_tokens(answer)
    if not q_tokens:
        return 0.0, "question has no content tokens"
    if not a_tokens:
        return 0.0, "answer has no content tokens"
    covered = len(q_tokens & a_tokens)
    return covered / len(q_tokens), f"{covered}/{len(q_tokens)} covered"


#: Below this fraction of expected-answer tokens supported by retrieved
#: context, the golden record is flagged as suspicious (warning only).
_REFERENCE_SUPPORT_WARN_BELOW = 0.2


def heuristic_reference_support(
    expected_answer: str, concepts: list[Any]
) -> tuple[float, str]:
    """Fraction of the golden ``expected_answer``'s content tokens that
    appear anywhere in the retrieved concepts' text.

    This is a *golden-set sanity signal*, not a quality metric: no scoring
    mode compares the generated answer against ``expected_answer``
    semantically, so a fabricated reference answer would otherwise pass the
    gate with full confidence. Near-zero support means the reference answer
    shares no vocabulary with what retrieval returned — the golden record
    is likely fabricated or copy-pasted from elsewhere. Callers surface
    this as a warning; it never fails a question or the gate, because the
    gate measures *bundle* quality, not golden-set quality.
    """
    expected_tokens = _content_tokens(expected_answer)
    if not expected_tokens:
        return 1.0, "expected answer has no content tokens — nothing to check"
    if not concepts:
        return 0.0, "no concepts retrieved"
    context_tokens: set[str] = set()
    for concept in concepts:
        context_tokens |= _content_tokens(_concept_text(concept))
    supported = len(expected_tokens & context_tokens)
    return (
        supported / len(expected_tokens),
        f"{supported}/{len(expected_tokens)} expected tokens in context",
    )


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = (
    "You are a strict RAG evaluator. Reply with ONLY the requested JSON, "
    "no prose, no markdown fences."
)


def _judge_json(backend: Any, user_prompt: str) -> Any:
    """Ask the judge backend for JSON; raise on any failure."""
    from okfsmith.extract.llm import LLMError

    try:
        text = backend.chat(
            [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
    except Exception as exc:
        raise LLMError(f"judge call failed: {exc}") from exc
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned)


def _judge_score(
    backend: Any,
    metric: str,
    prompt: str,
    extract: Any,
    heuristic: tuple[float, str],
) -> Score:
    """Run one LLM-judge metric, degrading to the heuristic on failure."""
    try:
        data = _judge_json(backend, prompt)
        value, detail = extract(data)
        value = max(0.0, min(1.0, float(value)))
        return Score(metric=metric, value=value, method="llm-judge", detail=detail)
    except Exception as exc:  # noqa: BLE001 — judge failure degrades, never aborts
        h_value, h_detail = heuristic
        return Score(
            metric=metric,
            value=h_value,
            method="heuristic",
            detail=f"judge failed ({exc}); heuristic: {h_detail}",
        )


def judge_context_relevancy(
    backend: Any, question: str, expected: str, concepts: list[Any]
) -> Score:
    """LLM-judge context relevancy, with heuristic fallback."""
    heuristic = heuristic_context_relevancy(question, expected, concepts)
    if not concepts:
        return Score(
            metric="context_relevancy",
            value=0.0,
            method="heuristic",
            detail="no concepts retrieved",
        )
    listing = "\n\n".join(
        f"[{c.id}]\n{_snippet(_concept_text(c), 500)}" for c in concepts
    )
    prompt = (
        f"Question: {question}\nExpected answer: {expected}\n\n"
        f"Retrieved concepts:\n{listing}\n\n"
        'Which concepts are relevant to answering the question? Reply as '
        '{"relevant": ["id1", "id2"]} using the exact ids shown.'
    )

    def extract(data: Any) -> tuple[float, str]:
        relevant = data.get("relevant", [])
        if not isinstance(relevant, list):
            raise ValueError("expected {'relevant': [...]}")
        ids = {c.id for c in concepts}
        n = sum(1 for cid in relevant if cid in ids)
        return n / len(concepts), f"{n}/{len(concepts)} judged relevant"

    return _judge_score(backend, "context_relevancy", prompt, extract, heuristic)


def judge_faithfulness(backend: Any, answer: str, concepts: list[Any]) -> Score:
    """LLM-judge faithfulness, with heuristic fallback."""
    heuristic = heuristic_faithfulness(answer, concepts)
    if not _split_sentences(answer) or not concepts:
        return Score(
            metric="faithfulness", value=0.0, method="heuristic",
            detail=heuristic[1],
        )
    context = "\n\n".join(
        f"[{c.id}]\n{_snippet(_concept_text(c), 600)}" for c in concepts
    )
    prompt = (
        f"Context:\n{context}\n\nAnswer:\n{answer}\n\n"
        "List each factual claim in the answer and whether the context "
        'supports it. Reply as {"claims": [{"claim": "...", '
        '"supported": true|false}]}.'
    )

    def extract(data: Any) -> tuple[float, str]:
        claims = data.get("claims", [])
        if not isinstance(claims, list) or not claims:
            raise ValueError("expected {'claims': [...]}")
        n = sum(1 for claim in claims if claim.get("supported") is True)
        return n / len(claims), f"{n}/{len(claims)} claims supported"

    return _judge_score(backend, "faithfulness", prompt, extract, heuristic)


def judge_answer_relevancy(backend: Any, question: str, answer: str) -> Score:
    """LLM-judge answer relevancy, with heuristic fallback."""
    heuristic = heuristic_answer_relevancy(question, answer)
    prompt = (
        f"Question: {question}\nAnswer: {answer}\n\n"
        "How relevant is the answer to the question? Score 0.0 (completely "
        'irrelevant) to 1.0 (directly answers). Reply as {"score": 0.85, '
        '"reason": "..."}.'
    )

    def extract(data: Any) -> tuple[float, str]:
        return float(data["score"]), str(data.get("reason", ""))[:200]

    return _judge_score(backend, "answer_relevancy", prompt, extract, heuristic)


def generate_answer_llm(backend: Any, question: str, concepts: list[Any]) -> str:
    """Generate a grounded answer via the LLM backend (chat-style)."""
    from okfsmith.extract.llm import LLMError

    blocks = []
    for concept in concepts:
        fm = concept.frontmatter or {}
        body = (concept.body or "").strip()
        if len(body) > 1500:
            body = body[:1499] + "…"
        blocks.append(
            f"[{concept.id}]\ntitle: {fm.get('title', concept.id)}\n{body}"
        )
    context = "\n\n---\n\n".join(blocks)
    try:
        text = backend.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Answer ONLY from the Context concepts below. Every "
                        "factual claim carries a citation like [concept/id]. "
                        "If the context lacks the answer, say so plainly — "
                        "never invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
            max_tokens=1024,
        )
    except Exception as exc:
        raise LLMError(f"answer generation failed: {exc}") from exc
    return _validate_citations(text, concepts)


_CITATION_RE = re.compile(r"\[([A-Za-z0-9_][A-Za-z0-9_./-]*)\]")


def _validate_citations(text: str, concepts: list[Any]) -> str:
    """De-bracket citations that name concepts outside the retrieved set."""
    valid = {c.id for c in concepts}

    def _fix(match: re.Match) -> str:
        return match.group(0) if match.group(1) in valid else match.group(1)

    return _CITATION_RE.sub(_fix, text)


# ---------------------------------------------------------------------------
# Results & diagnosis
# ---------------------------------------------------------------------------


@dataclass
class Score:
    """One metric score with its provenance label."""

    metric: str
    value: float  # 0.0 – 1.0
    method: str  # "heuristic" | "llm-judge"
    detail: str = ""


#: Per-metric default pass thresholds. Heuristic metrics have different
#: natural scales: answer relevancy is a crude token-coverage proxy, so its
#: bar is lower than the relevance/faithfulness bars.
DEFAULT_THRESHOLDS = {
    "context_relevancy": 0.6,
    "faithfulness": 0.6,
    "answer_relevancy": 0.4,
}


@dataclass
class QuestionResult:
    """Everything measured for one golden question."""

    id: str
    question: str
    retrieved_ids: list[str]
    missing_must_cite: list[str]
    scores: dict[str, Score]
    passed: bool
    failing_metrics: list[str]
    diagnosis: str | None  # "retrieval" | "generation" | None
    diagnosis_reason: str = ""
    answer: str = ""
    # Non-gating golden-set sanity notes (e.g. a suspicious expected_answer).
    warnings: list[str] = field(default_factory=list)

    def mean(self) -> float:
        """Mean of the three metric scores (0.0 – 1.0)."""
        if not self.scores:
            return 0.0
        return sum(s.value for s in self.scores.values()) / len(self.scores)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "passed": self.passed,
            "failing_metrics": self.failing_metrics,
            "retrieved": self.retrieved_ids,
            "missing_must_cite": self.missing_must_cite,
            "diagnosis": self.diagnosis,
            "diagnosis_reason": self.diagnosis_reason,
            "scores": {
                name: {
                    "value": round(score.value, 4),
                    "method": score.method,
                    "detail": score.detail,
                }
                for name, score in self.scores.items()
            },
            "mean": round(self.mean(), 4),
            "answer": self.answer,
            "warnings": list(self.warnings),
        }


def diagnose(
    question: GoldenQuestion,
    retrieved_ids: list[str],
    relevant_retrieved: bool,
    failing_metrics: list[str],
) -> tuple[str | None, str]:
    """Split a failing question into retrieval vs generation failure.

    Returns ``(diagnosis, reason)``; ``(None, "")`` when nothing failed.
    Retrieval failed when a golden ``must_cite`` concept was not retrieved
    (or nothing retrieved is relevant); otherwise the generator dropped the
    ball — ``generation``.
    """
    if not failing_metrics:
        return None, ""
    missing = [cid for cid in question.must_cite if cid not in retrieved_ids]
    if missing:
        return (
            "retrieval",
            f"must_cite concept(s) not retrieved: {', '.join(missing)}",
        )
    if not relevant_retrieved:
        return (
            "retrieval",
            "no retrieved concept is relevant to the question",
        )
    return (
        "generation",
        f"concepts retrieved but answer failed on: "
        f"{', '.join(failing_metrics)}",
    )


@dataclass
class EvalReport:
    """Full eval run: per-question results plus aggregates."""

    bundle: str
    judge_mode: str  # "heuristic" | "llm-judge" | "mixed"
    top_k: int
    metric_thresholds: dict[str, float]
    fail_under: float
    questions: list[QuestionResult]
    as_of: str | None = None
    include_superseded: bool = False

    def overall(self) -> float:
        """Overall score 0–100: mean of per-question means."""
        if not self.questions:
            return 0.0
        return sum(q.mean() for q in self.questions) / len(self.questions) * 100

    def metric_means(self) -> dict[str, float]:
        """Mean per metric across questions (0.0 – 1.0)."""
        means: dict[str, float] = {}
        for name in METRICS:
            values = [q.scores[name].value for q in self.questions if name in q.scores]
            means[name] = sum(values) / len(values) if values else 0.0
        return means

    def verdict(self) -> str:
        """``pass`` when the overall score clears ``fail_under``."""
        return "pass" if self.overall() >= self.fail_under else "fail"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.verdict(),
            "bundle": self.bundle,
            "judge_mode": self.judge_mode,
            "top_k": self.top_k,
            "metric_thresholds": self.metric_thresholds,
            "fail_under": self.fail_under,
            "as_of": self.as_of,
            "include_superseded": self.include_superseded,
            "overall_score": round(self.overall(), 2),
            "question_count": len(self.questions),
            "passed_count": sum(1 for q in self.questions if q.passed),
            "metric_means": {
                name: round(value, 4) for name, value in self.metric_means().items()
            },
            "questions": [q.as_dict() for q in self.questions],
        }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _resolve_judge_backend(
    *,
    no_llm: bool,
    model: str | None,
    provider: str | None,
    api_base: str | None,
    api_key: str | None,
) -> Any | None:
    """Resolve the LLM judge backend, or ``None`` for keyless heuristic mode.

    ``no_llm=True`` forces heuristic mode. Otherwise the standard backend
    selection is used; an unreachable LLM degrades to heuristic mode, while
    a *configuration* mistake (unknown provider) fails loudly.
    """
    if no_llm:
        return None
    from okfsmith.extract import llm as _llm

    try:
        return _llm.resolve_backend(
            model=model, provider=provider, api_base=api_base, api_key=api_key
        )
    except _llm.LLMUnavailableError:
        # Keyless heuristic mode: chat degrades the same way.
        return None
    except _llm.LLMError as exc:
        raise EvalError(
            "bad-llm-config",
            str(exc),
            "Use --provider with a valid preset name, set OKFSMITH_PROVIDER "
            "/ OKFSMITH_API_BASE, or pass --no-llm for heuristic mode.",
        ) from None


def _is_threshold_number(value: Any) -> bool:
    """True for real ints/floats (bools excluded) usable as a threshold."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve_thresholds(
    metric_threshold: float | dict[str, float] | None,
) -> dict[str, float]:
    """Normalize a threshold spec to per-metric thresholds.

    ``None`` → the per-metric defaults; a scalar applies uniformly to all
    three metrics; a dict overrides individual metrics (missing metrics
    keep their defaults).
    """
    thresholds = dict(DEFAULT_THRESHOLDS)
    if metric_threshold is None:
        return thresholds
    if isinstance(metric_threshold, dict):
        for name, value in metric_threshold.items():
            if name not in METRICS:
                raise EvalError(
                    "bad-threshold", f"unknown metric '{name}' in thresholds."
                )
            if not _is_threshold_number(value) or not 0.0 <= value <= 1.0:
                raise EvalError(
                    "bad-threshold",
                    f"threshold for '{name}' must be between 0 and 1, got "
                    f"{value!r}.",
                )
            thresholds[name] = value
        return thresholds
    if not _is_threshold_number(metric_threshold) or not (
        0.0 <= metric_threshold <= 1.0
    ):
        raise EvalError(
            "bad-threshold",
            f"--metric-threshold must be between 0 and 1, got "
            f"{metric_threshold!r}.",
        )
    return dict.fromkeys(METRICS, metric_threshold)


def score_question(
    bundle: Any,
    question: GoldenQuestion,
    *,
    top_k: int,
    metric_thresholds: dict[str, float],
    backend: Any | None,
    as_of: datetime | None,
    include_superseded: bool,
) -> QuestionResult:
    """Retrieve, answer, and score one golden question."""
    result = search_bundle_detailed(
        bundle,
        question.question,
        limit=top_k,
        as_of=as_of,
        include_superseded=include_superseded,
    )
    concepts = [concept for _, concept in result.hits]
    retrieved_ids = [c.id for c in concepts]

    answer = ""
    answer_failed = False
    if backend is not None:
        try:
            answer = generate_answer_llm(backend, question.question, concepts)
        except Exception:
            # Generation failure degrades to extractive, not to a crash.
            answer_failed = True
            answer, _ = extractive_answer(concepts)
    else:
        answer, _ = extractive_answer(concepts)

    scores: dict[str, Score] = {}
    if backend is not None and not answer_failed:
        scores["context_relevancy"] = judge_context_relevancy(
            backend, question.question, question.expected_answer, concepts
        )
        scores["faithfulness"] = judge_faithfulness(backend, answer, concepts)
        scores["answer_relevancy"] = judge_answer_relevancy(
            backend, question.question, answer
        )
    else:
        value, detail = heuristic_context_relevancy(
            question.question, question.expected_answer, concepts
        )
        scores["context_relevancy"] = Score(
            "context_relevancy", value, "heuristic", detail
        )
        value, detail = heuristic_faithfulness(answer, concepts)
        scores["faithfulness"] = Score("faithfulness", value, "heuristic", detail)
        value, detail = heuristic_answer_relevancy(question.question, answer)
        scores["answer_relevancy"] = Score(
            "answer_relevancy", value, "heuristic", detail
        )

    failing = [
        name for name in METRICS if scores[name].value < metric_thresholds[name]
    ]
    relevant_retrieved = (
        heuristic_context_relevancy(
            question.question, question.expected_answer, concepts
        )[0]
        > 0
    )
    missing_must_cite = [
        cid for cid in question.must_cite if cid not in retrieved_ids
    ]
    diagnosis, reason = diagnose(
        question, retrieved_ids, relevant_retrieved, failing
    )
    if missing_must_cite and not failing:
        # A golden must_cite concept that retrieval never surfaced fails the
        # question on its own — the golden set demands evidence from a
        # concept retrieval did not return, even when the metric scores
        # happen to pass their thresholds.
        failing = ["must_cite"]
        diagnosis, reason = diagnose(
            question, retrieved_ids, relevant_retrieved, failing
        )
    warnings: list[str] = []
    if question.expected_answer.strip():
        support, support_detail = heuristic_reference_support(
            question.expected_answer, concepts
        )
        if support < _REFERENCE_SUPPORT_WARN_BELOW:
            warnings.append(
                "expected answer shares little vocabulary with retrieved "
                f"context ({support_detail}) — verify this golden record; "
                "the gate does not check expected_answer semantically"
            )
    return QuestionResult(
        id=question.id,
        question=question.question,
        retrieved_ids=retrieved_ids,
        missing_must_cite=missing_must_cite,
        scores=scores,
        passed=not failing,
        failing_metrics=failing,
        diagnosis=diagnosis,
        diagnosis_reason=reason,
        answer=answer,
        warnings=warnings,
    )


def run_eval(
    bundle: Any,
    bundle_dir: Path,
    *,
    top_k: int = 5,
    metric_threshold: float | dict[str, float] | None = None,
    fail_under: float = 0.0,
    as_of: datetime | None = None,
    include_superseded: bool = False,
    no_llm: bool = False,
    model: str | None = None,
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> EvalReport:
    """Run the full eval: load the golden set, score every question.

    *bundle* is a loaded :class:`okfsmith.core.Bundle`; *bundle_dir* is used
    to locate ``eval/golden.json``. *metric_threshold* is a scalar applied
    to all metrics, a per-metric dict, or ``None`` for the defaults.
    """
    if top_k < 1:
        raise EvalError("bad-top-k", f"--top-k must be >= 1, got {top_k}.")
    thresholds = _resolve_thresholds(metric_threshold)
    if not _is_threshold_number(fail_under) or not 0.0 <= fail_under <= 100.0:
        raise EvalError(
            "bad-threshold",
            f"--fail-under must be between 0 and 100, got {fail_under!r}.",
        )
    questions = load_golden_set(bundle_dir)
    backend = _resolve_judge_backend(
        no_llm=no_llm,
        model=model,
        provider=provider,
        api_base=api_base,
        api_key=api_key,
    )
    results = [
        score_question(
            bundle,
            question,
            top_k=top_k,
            metric_thresholds=thresholds,
            backend=backend,
            as_of=as_of,
            include_superseded=include_superseded,
        )
        for question in questions
    ]
    methods = {s.method for q in results for s in q.scores.values()}
    if methods == {"heuristic"}:
        judge_mode = "heuristic"
    elif methods == {"llm-judge"}:
        judge_mode = "llm-judge"
    else:
        judge_mode = "mixed"
    return EvalReport(
        bundle=str(bundle_dir),
        judge_mode=judge_mode,
        top_k=top_k,
        metric_thresholds=thresholds,
        fail_under=fail_under,
        questions=results,
        as_of=as_of.isoformat() if as_of is not None else None,
        include_superseded=include_superseded,
    )
