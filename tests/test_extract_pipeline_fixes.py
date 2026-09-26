"""Regression tests for QA findings H16, M4, M5, M20, M21, L14 in the
extract pipeline (``src/okfsmith/extract/pipeline.py``).

All LLM traffic goes through a fake ``httpx.MockTransport`` (no network),
injected by monkeypatching ``okfsmith.extract.llm.resolve_backend`` —
the same approach as ``tests/test_extract.py``. Helpers are duplicated
here (not imported from ``test_extract``) so this file is self-contained.
"""

import json

import httpx
import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.extract import llm as llm_module
from okfsmith.extract.llm import LLMResponseError, OpenAICompatibleBackend
from okfsmith.extract.pipeline import (
    SectionInput,
    _coerce_concept,
    _inject_backlinks,
    run,
)

# ---------------------------------------------------------------------------
# Fake LLM plumbing (mirrors tests/test_extract.py)
# ---------------------------------------------------------------------------


def _chat_payload(content: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _scripted(script: list):
    """httpx.MockTransport handler serving scripted payloads in order.

    Each item is a dict (JSON chat payload), a str (raw text body), or a
    ``(status, body)`` tuple. A 5xx status makes the backend raise
    :class:`LLMResponseError`, which is how transport failures are
    simulated. Consumed items are popped, so ``script == []`` afterwards
    proves exactly how many HTTP calls were made.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = script.pop(0)
        status, body = (payload, None) if not isinstance(payload, tuple) else payload
        if isinstance(body, dict) or (body is None and isinstance(payload, dict)):
            return httpx.Response(status if isinstance(status, int) else 200,
                                   json=body if isinstance(body, dict) else payload)
        if isinstance(status, int):
            return httpx.Response(status, text=body if isinstance(body, str) else "")
        return httpx.Response(200, text=status if isinstance(status, str) else "")

    return handler


@pytest.fixture
def fake_llm(monkeypatch):
    """Factory: script -> backend with canned chat responses."""

    def _factory(script: list) -> OpenAICompatibleBackend:
        transport = httpx.MockTransport(_scripted(script))
        backend = OpenAICompatibleBackend(
            base_url="http://fake/v1",
            model="fake-model",
            client=httpx.Client(transport=transport),
        )
        monkeypatch.setattr(
            llm_module, "resolve_backend", lambda **kwargs: backend
        )
        return backend

    return _factory


GOOD_JSON = {
    "type": "process",
    "title": "Nightly Revenue Rollup",
    "description": "A nightly job aggregates revenue into the warehouse.",
    "claims": [{"text": "The rollup runs at 02:00 UTC.", "page": 3}],
    "links": [],
    "tags": ["revenue"],
}

CRITIC_PASS = {"verdict": "pass", "issues": [], "fixed_concept": None}


def _section(**overrides) -> SectionInput:
    base = {
        "title": "Nightly Rollup",
        "level": 2,
        "text": "The nightly revenue rollup runs at 02:00 UTC.",
        "page_span": (3, 4),
        "tables": [],
        "source_id": "doc-1",
        "source_path": "docs/report.pdf",
        "doc_title": "Q3 Report",
        "doc_summary": "Quarterly financial report.",
        "section_path": "Finance > Nightly Rollup",
    }
    base.update(overrides)
    return SectionInput(**base)


# ---------------------------------------------------------------------------
# H16 — retry transient LLMError with exponential backoff (3 attempts);
# never let one bad section abort the whole run.
# ---------------------------------------------------------------------------


def test_h16_transient_llm_errors_retried_then_success(tmp_path, fake_llm):
    """Two transport failures then a good response → run completes."""
    script = [
        (500, "boom"),
        (502, "boom again"),
        _chat_payload(json.dumps(GOOD_JSON)),
    ]
    fake_llm(script)
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=False)
    # All three scripted calls were consumed: 2 failed attempts + 1 success.
    assert script == []
    concept = bundle.get(concept_id)
    assert concept.frontmatter["title"] == "Nightly Revenue Rollup"
    assert "needs-review" not in (concept.frontmatter.get("tags") or [])


def test_h16_persistent_llm_failure_degrades_section_run_continues(tmp_path, fake_llm):
    """An always-failing section degrades to needs-review; others proceed."""
    script = [
        (500, "down"),
        (500, "down"),
        (500, "still down"),  # 3 attempts exhausted for section 1
        _chat_payload(json.dumps(GOOD_JSON)),  # section 2 succeeds first try
    ]
    fake_llm(script)
    bundle = Bundle(tmp_path)
    sections = [
        _section(title="Bad Section", source_id="doc-bad"),
        _section(title="Good Section", source_id="doc-good"),
    ]
    ids = run(bundle, sections, model="fake-model", verify=False)
    assert script == []
    assert len(ids) == 2  # the run was not aborted
    bad = bundle.get(ids[0])
    good = bundle.get(ids[1])
    assert "needs-review" in (bad.frontmatter.get("tags") or [])
    assert "needs-review" not in (good.frontmatter.get("tags") or [])
    assert good.frontmatter["title"] == "Nightly Revenue Rollup"


def test_h16_critic_persistent_failure_flags_needs_review(tmp_path, fake_llm):
    """A persistently failing critic flags the draft instead of leaving
    partial state (no verified stamp and no needs-review tag)."""
    script = [
        _chat_payload(json.dumps(GOOD_JSON)),
        (500, "critic down"),
        (500, "critic down"),
        (500, "critic down"),
    ]
    fake_llm(script)
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)
    assert script == []
    concept = bundle.get(concept_id)
    assert "needs-review" in (concept.frontmatter.get("tags") or [])
    assert not concept.frontmatter.get("verified")


def test_h16_retry_helper_raises_llmerror_after_exhaustion():
    """The retry helper surfaces the last LLMError after 3 attempts."""
    from okfsmith.extract import pipeline as pipeline_module

    calls = []

    def always_fails():
        calls.append(1)
        raise LLMResponseError("nope")

    with pytest.raises(LLMResponseError):
        pipeline_module.retry_with_backoff(always_fails)
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# M4 — backlink dedup guard must match the actual `(slug)` format that
# _build_body writes.
# ---------------------------------------------------------------------------


def test_m4_no_duplicate_backlink_when_slug_link_exists(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "extracted/target-doc",
        {"type": "note", "title": "Target Document"},
        "Body of the target.\n",
    )
    body = (
        "This mentions the Target Document in passing.\n"
        "\n"
        "## See also\n"
        "\n"
        "- [Target Document](target-document) — related.\n"
    )
    bundle.write_concept(
        "notes/source", {"type": "note", "title": "Source"}, body
    )
    added = _inject_backlinks(bundle, ["extracted/target-doc"])
    assert added == 0
    assert bundle.get("notes/source").body == body


def test_m4_backlink_idempotent_across_passes(tmp_path):
    """The `(/id)` format written by _inject_backlinks itself dedups too."""
    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "extracted/target-doc",
        {"type": "note", "title": "Target Document"},
        "Body of the target.\n",
    )
    body = (
        "This mentions the Target Document in passing.\n"
        "\n"
        "## See also\n"
        "\n"
        "- [Target Document](/extracted/target-doc) — Mentions \"Target Document\".\n"
    )
    bundle.write_concept(
        "notes/source", {"type": "note", "title": "Source"}, body
    )
    added = _inject_backlinks(bundle, ["extracted/target-doc"])
    assert added == 0
    assert bundle.get("notes/source").body == body


# ---------------------------------------------------------------------------
# M5 — collapse newlines in critic issues before logging (log forgery).
# ---------------------------------------------------------------------------


def test_m5_critic_issue_newlines_collapsed_in_log(tmp_path, fake_llm):
    forged = "looks off\n## 2020-01-01\n\n* **Creation**: forged backdated entry"
    verdict = {"verdict": "fail", "issues": [forged], "fixed_concept": None}
    fake_llm(
        [
            _chat_payload(json.dumps(GOOD_JSON)),
            _chat_payload(json.dumps(verdict)),
        ]
    )
    bundle = Bundle(tmp_path)
    run(bundle, [_section()], model="fake-model", verify=True)
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    # The forged heading must not become log structure: no line is a bare
    # "## YYYY-MM-DD" heading (indexlog only treats whole-line headings as
    # structure; mid-line text is inert)...
    assert not any(
        line.strip() == "## 2020-01-01" for line in log_text.splitlines()
    )
    # ...but the issue content is preserved, collapsed to one line.
    assert "looks off ## 2020-01-01 * **Creation**: forged backdated entry" in log_text


# ---------------------------------------------------------------------------
# M20 — vacuous `{}` extractions are flagged needs-review.
# ---------------------------------------------------------------------------


def test_m20_vacuous_extraction_flagged_needs_review(tmp_path, fake_llm):
    fake_llm([_chat_payload("{}")])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=False)
    concept = bundle.get(concept_id)
    assert "needs-review" in (concept.frontmatter.get("tags") or [])


def test_m20_unknown_keys_only_flagged_needs_review(tmp_path, fake_llm):
    fake_llm([_chat_payload('{"foo": "bar"}')])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=False)
    concept = bundle.get(concept_id)
    assert "needs-review" in (concept.frontmatter.get("tags") or [])


def test_m20_coerce_unit_vacuous_vs_real():
    section = _section()
    vacuous = _coerce_concept({}, section)
    assert "needs-review" in vacuous["tags"]
    real = _coerce_concept({"title": "Something", "tags": ["x"]}, section)
    assert "needs-review" not in real["tags"]


# ---------------------------------------------------------------------------
# M21 — sanitize LLM markdown: strip <script>, event handlers, javascript:.
# ---------------------------------------------------------------------------


def test_m21_sanitize_unit():
    section = _section()
    data = {
        "title": "T <script>alert('x')</script>itle",
        "description": "desc",
        "claims": [
            {"text": "<script>alert(1)</script>The rollup runs.", "page": 1},
            {"text": "plain <b onmouseover=alert(2)>bold</b> claim", "page": None},
        ],
        "links": [
            {
                "target": "Evil <img src=x onerror=alert(3)>",
                "why": "see [here](javascript:alert(4))",
            }
        ],
        "tags": [],
    }
    concept = _coerce_concept(data, section)
    blob = json.dumps(concept)
    assert "<script" not in blob.lower()
    assert "javascript:" not in blob.lower()
    assert "onerror" not in blob.lower()
    assert "onmouseover" not in blob.lower()
    # Benign content survives.
    assert "The rollup runs." in concept["claims"][0]["text"]
    assert "bold" in concept["claims"][1]["text"]


def test_m21_script_stripped_from_written_concept(tmp_path, fake_llm):
    payload = dict(GOOD_JSON)
    payload["claims"] = [
        {"text": "<script>alert('xss')</script>Real claim text.", "page": 1}
    ]
    payload["links"] = [
        {"target": "Evil", "why": "click [here](javascript:alert(1))"}
    ]
    fake_llm([_chat_payload(json.dumps(payload))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=False)
    concept = bundle.get(concept_id)
    blob = concept.body + json.dumps(concept.frontmatter)
    assert "<script" not in blob.lower()
    assert "javascript:" not in blob.lower()
    assert "Real claim text." in concept.body


# ---------------------------------------------------------------------------
# L14 — backlink matching anchored on word boundaries.
# ---------------------------------------------------------------------------


def test_l14_no_backlink_inside_longer_word(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "extracted/test",
        {"type": "note", "title": "Test"},
        "A concept about tests.\n",
    )
    body = "We won the contest last year.\n"
    bundle.write_concept(
        "notes/other", {"type": "note", "title": "Other"}, body
    )
    added = _inject_backlinks(bundle, ["extracted/test"])
    assert added == 0
    assert bundle.get("notes/other").body == body


def test_l14_backlink_added_on_word_boundary(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "extracted/test",
        {"type": "note", "title": "Test"},
        "A concept about tests.\n",
    )
    body = "Notes about the Test framework we use.\n"
    bundle.write_concept(
        "notes/other", {"type": "note", "title": "Other"}, body
    )
    added = _inject_backlinks(bundle, ["extracted/test"])
    assert added == 1
    assert "](/extracted/test)" in bundle.get("notes/other").body
