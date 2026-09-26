"""Tests for the okfsmith.extract 2-pass LLM extraction pipeline.

All LLM traffic goes through a fake ``httpx.MockTransport`` (no network).
The fake is injected by monkeypatching
``okfsmith.extract.llm.resolve_backend``; ``run()`` itself is never changed.

Covers: frontmatter shape, sources[]/footnote wiring, situating prefix,
generated/verified stamping, trust-tier transitions (unverified →
machine-confirmed → human-reviewed), dedup skip, entity-resolution merge,
critic pass/fix/fail, JSON-repair retry, double-failure fallback draft,
the no-LLM clean error, and secret redaction.
"""

import httpx
import pytest

from okfsmith.core import indexlog
from okfsmith.core.bundle import Bundle
from okfsmith.core.spec import trust_tier
from okfsmith.extract import human_review, llm as llm_module, prompts
from okfsmith.extract.llm import (
    LLMResponseError,
    LLMUnavailableError,
    OpenAICompatibleBackend,
    redact_key,
    resolve_backend,
    resolve_model,
)
from okfsmith.extract.pipeline import SectionInput, run


# ---------------------------------------------------------------------------
# Fake LLM plumbing
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
    ``(status, body)`` tuple. An empty script → IndexError, which proves no
    unexpected HTTP call was made.
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
            base_url="http://fake",
            model="fake-model",
            client=httpx.Client(transport=transport),
        )
        monkeypatch.setattr(
            llm_module, "resolve_backend", lambda **kwargs: backend
        )
        return backend

    return _factory


CONCEPT_JSON = {
    "type": "process",
    "title": "Nightly Revenue Rollup",
    "description": "A nightly job aggregates revenue into the warehouse.",
    "claims": [
        {"text": "The rollup runs at 02:00 UTC.", "page": 3},
        {"text": "It writes to the revenue table.", "page": 3},
    ],
    "links": [{"target": "Revenue Table", "why": "The rollup writes to it."}],
    "tags": ["revenue", "etl"],
}

CRITIC_PASS = {"verdict": "pass", "issues": [], "fixed_concept": None}


def _section(**overrides) -> SectionInput:
    base = dict(
        title="Nightly Rollup",
        level=2,
        text="The nightly revenue rollup runs at 02:00 UTC and writes to the revenue table.",
        page_span=(3, 4),
        tables=[],
        source_id="doc-1",
        source_path="docs/report.pdf",
        doc_title="Q3 Report",
        doc_summary="Quarterly financial report.",
        section_path="Finance > Nightly Rollup",
    )
    base.update(overrides)
    return SectionInput(**base)


# ---------------------------------------------------------------------------
# Pass 1: frontmatter shape, provenance, situating prefix
# ---------------------------------------------------------------------------


def test_extraction_writes_concept_frontmatter_shape(tmp_path, fake_llm):
    import json as _json

    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    ids = run(bundle, [_section()], model="fake-model", verify=True)

    assert ids == ["extracted/nightly-revenue-rollup"]
    concept = bundle.get(ids[0])
    fm = concept.frontmatter
    assert fm["type"] == "process"
    assert fm["title"] == "Nightly Revenue Rollup"
    assert fm["tags"] == ["etl", "revenue"]
    assert fm["resource"] == "docs/report.pdf"
    assert fm["status"] == "draft"
    assert fm["generated"]["by"] == "okfsmith-extract/fake-model"
    assert fm["generated"]["at"]  # ISO timestamp stamped
    assert fm["source_digest"]  # dedup guard persisted

    sources = fm["sources"]
    assert len(sources) == 2
    assert sources[0]["id"] == "claim-1"
    assert sources[0]["resource"] == "docs/report.pdf#page=3"
    assert sources[0]["title"] == "Q3 Report"

    # Per-claim footnotes in the body wire to the sources[] ids.
    assert "[^claim-1]" in concept.body
    assert "[^claim-2]" in concept.body
    assert "[^claim-1]: docs/report.pdf#page=3" in concept.body
    assert "[^claim-2]: docs/report.pdf#page=3" in concept.body

    # LLM-declared link lands in the body with its why sentence.
    assert "[Revenue Table](revenue-table) — The rollup writes to it." in concept.body

    # Creation logged.
    assert "extracted" in (bundle.root / "log.md").read_text(encoding="utf-8")


def test_situating_prefix_stamped_in_description_and_body(tmp_path, fake_llm):
    import json as _json

    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model")

    concept = bundle.get(concept_id)
    prefix = 'From "Q3 Report", section "Finance > Nightly Rollup": Quarterly financial report.'
    assert concept.frontmatter["description"].startswith(prefix)
    assert concept.body.startswith(f"> {prefix}")


def test_claim_without_page_omits_fragment(tmp_path, fake_llm):
    import json as _json

    concept_json = dict(CONCEPT_JSON, claims=[{"text": "A pageless claim.", "page": None}])
    fake_llm([_chat_payload(_json.dumps(concept_json)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model")
    sources = bundle.get(concept_id).frontmatter["sources"]
    assert sources == [
        {"id": "claim-1", "resource": "docs/report.pdf", "title": "Q3 Report"}
    ]


# ---------------------------------------------------------------------------
# Pass 2: critic, trust tiers
# ---------------------------------------------------------------------------


def test_verify_pass_sets_machine_confirmed(tmp_path, fake_llm):
    import json as _json

    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    fm = bundle.get(concept_id).frontmatter
    assert fm["verified"] == [
        {"by": "process:okfsmith-critic/fake-model", "at": fm["verified"][0]["at"]}
    ]
    assert fm["verified"][0]["at"]  # timestamp stamped
    assert trust_tier(fm) == "machine-confirmed"


def test_no_verify_skips_critic(tmp_path, fake_llm):
    import json as _json

    # Script holds ONLY the extraction response: any critic call would
    # IndexError on the empty script.
    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=False)

    fm = bundle.get(concept_id).frontmatter
    assert "verified" not in fm
    assert trust_tier(fm) == "unverified"
    assert fm["status"] == "draft"


def test_critic_fail_flags_needs_review(tmp_path, fake_llm):
    import json as _json

    critic_fail = {
        "verdict": "fail",
        "issues": ["claim not supported by section text"],
        "fixed_concept": None,
    }
    fake_llm(
        [_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(critic_fail))]
    )
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    fm = bundle.get(concept_id).frontmatter
    assert "needs-review" in fm["tags"]
    assert "verified" not in fm
    assert fm["status"] == "draft"
    assert trust_tier(fm) == "unverified"
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "needs-review" in log_text and "claim not supported" in log_text


def test_critic_fix_rewrites_concept(tmp_path, fake_llm):
    import json as _json

    fixed = dict(
        CONCEPT_JSON,
        description="CORRECTED description faithful to the section.",
        claims=[{"text": "The rollup runs at 02:00 UTC.", "page": 3}],
    )
    critic_fix = {"verdict": "fix", "issues": ["dropped unsupported claim"], "fixed_concept": fixed}
    fake_llm(
        [_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(critic_fix))]
    )
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    concept = bundle.get(concept_id)
    assert "CORRECTED description" in concept.frontmatter["description"]
    assert len(concept.frontmatter["sources"]) == 1
    assert "needs-review" in concept.frontmatter["tags"]
    assert "verified" not in concept.frontmatter  # critic is not a verifier
    assert concept.frontmatter["status"] == "draft"


def test_critic_unparseable_keeps_draft_flagged(tmp_path, fake_llm):
    import json as _json

    fake_llm(
        [
            _chat_payload(_json.dumps(CONCEPT_JSON)),
            _chat_payload("definitely not json"),
            _chat_payload("still not json {{{"),
        ]
    )
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    fm = bundle.get(concept_id).frontmatter
    assert "needs-review" in fm["tags"]
    assert "verified" not in fm
    assert fm["title"] == "Nightly Revenue Rollup"  # draft kept, not dropped


# ---------------------------------------------------------------------------
# Deterministic fallbacks: repair retry, then honest draft
# ---------------------------------------------------------------------------


def test_extraction_retry_with_repair_succeeds(tmp_path, fake_llm):
    import json as _json

    fake_llm(
        [
            _chat_payload("garbage, not json"),
            _chat_payload(_json.dumps(CONCEPT_JSON)),  # repair retry
            _chat_payload(_json.dumps(CRITIC_PASS)),
        ]
    )
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    concept = bundle.get(concept_id)
    assert concept.frontmatter["title"] == "Nightly Revenue Rollup"
    assert "needs-review" not in concept.frontmatter["tags"]


def test_extraction_double_failure_keeps_honest_draft(tmp_path, fake_llm):
    # Both attempts unparseable, and the fallback draft skips the critic —
    # the script stays untouched after the two failures.
    fake_llm([_chat_payload("nope"), _chat_payload("still nope")])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    concept = bundle.get(concept_id)
    fm = concept.frontmatter
    assert fm["title"] == "Nightly Rollup"  # section-derived, never invented
    assert fm["tags"] == ["needs-review"]
    assert fm["sources"] == []  # no claims invented
    assert "The nightly revenue rollup runs at 02:00 UTC" in concept.body
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "warning: unparseable LLM output" in log_text


# ---------------------------------------------------------------------------
# Dedup and entity resolution
# ---------------------------------------------------------------------------


def test_dedup_skips_reingest(tmp_path, fake_llm):
    import json as _json

    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    first = run(bundle, [_section()], model="fake-model", verify=True)
    assert len(first) == 1

    # Re-patch with an EMPTY script: any HTTP call on the second run would
    # IndexError, proving the digest skip happens before any LLM traffic.
    fake_llm([])
    second = run(bundle, [_section()], model="fake-model", verify=True)
    assert second == []
    assert [c.id for c in bundle.iter_concepts()] == first


def test_entity_resolution_merges_same_title(tmp_path, fake_llm):
    import json as _json

    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "legacy/rollup",
        {
            "type": "note",
            "title": "Nightly Revenue Rollup",  # same normalized title
            "description": "old stub",
            "tags": ["legacy"],
            "resource": "docs/report.pdf",
            "sources": [],
            "status": "draft",
        },
        "old stub body",
    )
    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    ids = run(bundle, [_section(title="Nightly Rollup v2")], model="fake-model", verify=True)

    assert ids == ["legacy/rollup"]  # merged into the existing id
    concept = bundle.get("legacy/rollup")
    assert "A nightly job aggregates revenue" in concept.frontmatter["description"]  # richer won
    assert set(concept.frontmatter["tags"]) >= {"etl", "revenue", "legacy"}  # tags unioned
    assert trust_tier(concept.frontmatter) == "machine-confirmed"  # critic verified
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "merged duplicate" in log_text


# ---------------------------------------------------------------------------
# Retroactive linking
# ---------------------------------------------------------------------------


def test_retroactive_backlinks(tmp_path, fake_llm):
    import json as _json

    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "notes/overview",
        {"type": "note", "title": "Overview"},
        "This overview covers the Nightly Revenue Rollup and other jobs.\n",
    )
    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    (new_id,) = run(bundle, [_section()], model="fake-model", verify=True)
    assert new_id == "extracted/nightly-revenue-rollup"

    overview = bundle.get("notes/overview")
    assert f"](/{new_id})" in overview.body
    assert "Mentions" in overview.body  # why sentence present
    assert "## See also" in overview.body


# ---------------------------------------------------------------------------
# Human review
# ---------------------------------------------------------------------------


def test_mark_reviewed_promotes_to_human_reviewed(tmp_path, fake_llm):
    import json as _json

    fake_llm([_chat_payload(_json.dumps(CONCEPT_JSON)), _chat_payload(_json.dumps(CRITIC_PASS))])
    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)
    assert trust_tier(bundle.get(concept_id).frontmatter) == "machine-confirmed"

    updated = human_review.mark_reviewed(bundle, concept_id, reviewer="ada")
    fm = updated.frontmatter
    assert fm["verified"][-1]["by"] == "human:ada"
    assert fm["verified"][-1]["at"]
    assert len(fm["verified"]) == 2  # machine verification preserved
    assert trust_tier(fm) == "human-reviewed"
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "human review" in log_text and "ada" in log_text


def test_mark_reviewed_missing_concept_raises(tmp_path):
    bundle = Bundle(tmp_path)
    with pytest.raises(KeyError):
        human_review.mark_reviewed(bundle, "nope/missing", reviewer="ada")


def test_mark_reviewed_empty_reviewer_raises(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept("a/b", {"type": "note", "title": "B"}, "body\n")
    with pytest.raises(ValueError):
        human_review.mark_reviewed(bundle, "a/b", reviewer="  ")


# ---------------------------------------------------------------------------
# Backend resolution, errors, secrets
# ---------------------------------------------------------------------------


def test_no_llm_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    bundle = Bundle(tmp_path)
    with pytest.raises(LLMUnavailableError) as excinfo:
        run(bundle, [_section()], model="m")
    message = str(excinfo.value)
    assert "--no-llm" in message
    assert "Ollama" in message


def test_anthropic_key_logs_todo_warning(monkeypatch, caplog):
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    with caplog.at_level("WARNING", logger="okfsmith.extract.llm"):
        backend = resolve_backend()
    assert "Anthropic" in caplog.text and "TODO" in caplog.text
    assert isinstance(backend, OpenAICompatibleBackend)


def test_resolve_model_env_and_default(monkeypatch):
    monkeypatch.delenv("OKFSMITH_MODEL", raising=False)
    assert resolve_model() == "qwen3:8b"
    monkeypatch.setenv("OKFSMITH_MODEL", "custom:1b")
    assert resolve_model() == "custom:1b"
    assert resolve_model("explicit:2b") == "explicit:2b"


def test_redact_key_and_error_hygiene():
    assert redact_key("sk-super-secret-123") == "<redacted>"
    assert redact_key(None) == "<none>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal boom")

    backend = OpenAICompatibleBackend(
        base_url="http://fake",
        model="m",
        api_key="sk-super-secret-123",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMResponseError) as excinfo:
        backend.chat([{"role": "user", "content": "hi"}])
    assert "sk-super-secret-123" not in str(excinfo.value)
    assert "500" in str(excinfo.value)


def test_prompts_demand_strict_json():
    messages = prompts.build_extraction_messages(_section())
    assert messages[0]["role"] == "system"
    assert "STRICT JSON" in messages[0]["content"]
    assert "COMPILER" in messages[0]["content"]
    assert "Q3 Report" in messages[1]["content"]
    critic = prompts.build_critic_messages("section text", {"title": "T"})
    assert critic[0]["role"] == "system" and "verdict" in critic[0]["content"]
