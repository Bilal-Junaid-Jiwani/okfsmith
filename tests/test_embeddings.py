"""Tests for :mod:`okfsmith.extract.embeddings` and the embedding-similarity
duplicate-detection branch of
:func:`okfsmith.extract.pipeline._find_duplicate`.

Covers the cosine helper, the embedder contract, the OpenAI-compatible
``/embeddings`` client (security rules mirror the chat backends:
cleartext-HTTP refusal, provider-scoped legacy key), the spec resolver,
and branch-4 merge behavior via a stub embedder (no network).
"""

import json

import httpx
import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.extract import llm as llm_module
from okfsmith.extract.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    Embedder,
    EmbeddingError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
    OpenAIEmbedder,
    cosine_similarity,
    embed_text,
    resolve_embedder,
)
from okfsmith.extract.llm import OpenAICompatibleBackend
from okfsmith.extract.pipeline import SectionInput, _find_duplicate, run

# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_zero_vector_never_merges():
    # Embedded empty text must score 0.0 against everything.
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_dimension_mismatch_raises():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_result_is_clamped():
    # Float drift must not escape [-1, 1].
    assert -1.0 <= cosine_similarity([1e10, 0.0], [1e10, 0.0]) <= 1.0


# ---------------------------------------------------------------------------
# embed_text
# ---------------------------------------------------------------------------


def test_embed_text_keeps_title_whole_and_truncates_body():
    body = "x" * 10_000
    text = embed_text("Short title", body)
    assert text.startswith("Short title")
    assert len(text) == 4000


def test_embed_text_empty_is_empty():
    assert embed_text("", "") == ""


# ---------------------------------------------------------------------------
# Stub embedder for pipeline-branch tests (no network)
# ---------------------------------------------------------------------------


class StubEmbedder(Embedder):
    """Embedder returning canned vectors (no network).

    Either a dict keyed by exact input text, or a ``fn(texts)``
    callable returning the vectors.
    """

    name = "stub"

    def __init__(self, vectors=None, *, fn=None, threshold: float = 0.8):
        super().__init__()
        self._vectors = vectors or {}
        self._fn = fn
        self.merge_threshold = threshold
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._fn is not None:
            return self._fn(texts)
        return [self._vectors[t] for t in texts]


def _bundle_with_concept(tmp_path, title, body):
    bundle = Bundle(tmp_path)
    bundle.write_concept(
        "concept-0", {"title": title, "resource": "doc.md"}, body
    )
    return bundle


def _paraphrase_setup(tmp_path):
    """A duplicate pair token-Jaccard misses (0.25 < 0.8)."""
    existing_title = "Vault synchronization guide"
    existing_body = "The sync command keeps the bundle current."
    new_title = "How to sync your vault"
    new_body = "Run sync to keep the bundle current."
    bundle = _bundle_with_concept(tmp_path, existing_title, existing_body)
    return bundle, existing_title, existing_body, new_title, new_body


def test_embedding_branch_merges_paraphrase(tmp_path):
    bundle, et, eb, nt, nb = _paraphrase_setup(tmp_path)
    new_text = embed_text(nt, nb)
    cand_text = embed_text(et, eb)
    stub = StubEmbedder(
        {new_text: [1.0, 0.0], cand_text: [0.9, 0.435889894]}, threshold=0.8
    )
    found = _find_duplicate(
        bundle, nt, "other.md", text=nb, embedder=stub
    )
    assert found is not None
    assert found.frontmatter["title"] == et
    # One batched call: new text + every candidate.
    assert len(stub.calls) == 1
    assert stub.calls[0][0] == new_text
    assert cand_text in stub.calls[0]


def test_embedding_branch_below_threshold_does_not_merge(tmp_path):
    bundle, et, eb, nt, nb = _paraphrase_setup(tmp_path)
    new_text = embed_text(nt, nb)
    cand_text = embed_text(et, eb)
    stub = StubEmbedder(
        {new_text: [1.0, 0.0], cand_text: [0.7, 0.7141428]}, threshold=0.8
    )
    assert _find_duplicate(bundle, nt, "other.md", text=nb, embedder=stub) is None


def test_no_embedder_keeps_offline_behavior(tmp_path):
    bundle, et, eb, nt, nb = _paraphrase_setup(tmp_path)
    # Same pair, no embedder: Jaccard 0.25 misses it, nothing merges.
    assert _find_duplicate(bundle, nt, "other.md", text=nb) is None


def test_empty_text_skips_embedding_branch(tmp_path):
    bundle, et, eb, nt, nb = _paraphrase_setup(tmp_path)
    stub = StubEmbedder({}, threshold=0.0)
    assert (
        _find_duplicate(bundle, nt, "other.md", text="  ", embedder=stub)
        is None
    )
    assert stub.calls == []


def test_title_similarity_branch_wins_before_embeddings(tmp_path):
    bundle = _bundle_with_concept(tmp_path, "Sync Guide", "Body.")
    # Jaccard 1.0 on stemmed tokens: branch 3 merges, branch 4 never runs.
    stub = StubEmbedder({}, threshold=0.0)
    found = _find_duplicate(
        bundle, "Guide Sync", "other.md", text="Body.", embedder=stub
    )
    assert found is not None
    assert stub.calls == []


def test_exact_title_branch_still_first(tmp_path):
    bundle = _bundle_with_concept(tmp_path, "Vault Guide", "Body.")
    stub = StubEmbedder({}, threshold=0.0)
    found = _find_duplicate(
        bundle, "VAULT guide!", "other.md", text="Body.", embedder=stub
    )
    assert found is not None
    assert stub.calls == []


def test_embedding_tie_break_prefers_lower_id(tmp_path):
    bundle = Bundle(tmp_path)
    bundle.write_concept("b-concept", {"title": "Alpha"}, "Body alpha.")
    bundle.write_concept("a-concept", {"title": "Beta"}, "Body beta.")
    new_title, new_body = "Gamma", "Body gamma."
    new_text = embed_text(new_title, new_body)
    texts = {
        new_text: [1.0, 0.0],
        embed_text("Alpha", "Body alpha."): [0.8, 0.6],
        embed_text("Beta", "Body beta."): [0.8, 0.6],
    }
    stub = StubEmbedder(texts, threshold=0.8)
    found = _find_duplicate(
        bundle, new_title, "other.md", text=new_body, embedder=stub
    )
    assert found is not None
    assert found.id == "a-concept"


# ---------------------------------------------------------------------------
# Embedding cache: existing-concept vectors reused across sections
# ---------------------------------------------------------------------------


def _no_merge_setup(tmp_path):
    """One existing concept + two new titles; nothing reaches the merge
    threshold, so the tests only count embedding calls."""
    existing_title = "Vault synchronization guide"
    existing_body = "The sync command keeps the bundle current."
    bundle = _bundle_with_concept(tmp_path, existing_title, existing_body)
    nt1, nb1 = "How to sync your vault", "Run sync to keep current."
    nt2, nb2 = "Keeping the vault current", "Keep it current nightly."
    new_text1, new_text2 = embed_text(nt1, nb1), embed_text(nt2, nb2)
    cand_text = embed_text(existing_title, existing_body)
    stub = StubEmbedder(
        {
            new_text1: [1.0, 0.0],
            new_text2: [0.0, 1.0],
            cand_text: [0.9, 0.435889894],
        },
        threshold=0.99,  # 0.9 < 0.99: nothing merges
    )
    return bundle, stub, (nt1, nb1, new_text1), (nt2, nb2, new_text2), cand_text


def test_embedding_cache_embeds_existing_concepts_once(tmp_path):
    bundle, stub, (nt1, nb1, _), (nt2, nb2, new_text2), cand_text = (
        _no_merge_setup(tmp_path)
    )
    cache: dict[str, list[float]] = {}
    assert (
        _find_duplicate(
            bundle, nt1, "a.md", text=nb1,
            embedder=stub, embedding_cache=cache,
        )
        is None
    )
    assert (
        _find_duplicate(
            bundle, nt2, "b.md", text=nb2,
            embedder=stub, embedding_cache=cache,
        )
        is None
    )
    # First call embeds new + existing; second call embeds only the new
    # text — the existing concept's vector comes from the cache.
    assert [len(c) for c in stub.calls] == [2, 1]
    assert stub.calls[1] == [new_text2]
    assert cand_text not in stub.calls[1]
    assert "concept-0" in cache


def test_embedding_no_cache_embeds_everything_each_call(tmp_path):
    # cache=None preserves the old behavior: every call re-embeds all
    # existing concepts.
    bundle, stub, (nt1, nb1, _), (nt2, nb2, _), _ = _no_merge_setup(tmp_path)
    assert _find_duplicate(bundle, nt1, "a.md", text=nb1, embedder=stub) is None
    assert _find_duplicate(bundle, nt2, "b.md", text=nb2, embedder=stub) is None
    assert [len(c) for c in stub.calls] == [2, 2]


def test_embedding_cache_invalidated_after_merge(tmp_path):
    """Simulates run()'s contract: when a merge changes a concept's body,
    the caller pops its cache entry, so the next check re-embeds the
    refreshed content instead of comparing against a stale vector."""
    bundle = _bundle_with_concept(
        tmp_path, "Vault synchronization guide", "Old body."
    )
    old_text = embed_text("Vault synchronization guide", "Old body.")
    new_text = embed_text("How to sync your vault", "Run sync to keep current.")
    stub = StubEmbedder(
        {old_text: [0.9, 0.435889894], new_text: [1.0, 0.0]},
        threshold=0.99,
    )
    cache: dict[str, list[float]] = {}
    assert (
        _find_duplicate(
            bundle, "How to sync your vault", "a.md",
            text="Run sync to keep current.",
            embedder=stub, embedding_cache=cache,
        )
        is None
    )
    assert [len(c) for c in stub.calls] == [2]
    # Merge replaces the body -> run() drops the stale cache entry.
    bundle.write_concept(
        "concept-0",
        {"title": "Vault synchronization guide", "resource": "doc.md"},
        "New richer body here.",
    )
    cache.pop("concept-0", None)
    refreshed_text = embed_text(
        "Vault synchronization guide", "New richer body here."
    )
    second_new_text = embed_text(
        "Keeping the vault current", "Keep it current nightly."
    )
    stub._vectors[refreshed_text] = [0.9, 0.435889894]
    stub._vectors[second_new_text] = [0.0, 1.0]
    assert (
        _find_duplicate(
            bundle, "Keeping the vault current", "b.md",
            text="Keep it current nightly.",
            embedder=stub, embedding_cache=cache,
        )
        is None
    )
    second = stub.calls[1]
    assert second[0] == second_new_text
    assert refreshed_text in second  # re-embedded, not stale
    assert old_text not in second


# ---------------------------------------------------------------------------
# OpenAIEmbedder: wire format + security rules
# ---------------------------------------------------------------------------


def _embed_payload(*vectors):
    return {
        "data": [
            {"object": "embedding", "index": i, "embedding": list(v)}
            for i, v in enumerate(vectors)
        ]
    }


def _embedder_with(handler, **kwargs):
    kwargs.setdefault("base_url", "https://api.openai.com/v1")
    kwargs.setdefault("api_key", "sk-test")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIEmbedder(client=client, **kwargs)


def test_embeddings_request_shape_and_auth():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_embed_payload([0.1, 0.2], [0.3, 0.4]))

    emb = _embedder_with(handler, model="text-embedding-3-small")
    vectors = emb.embed(["hello", "world"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert seen["url"] == "https://api.openai.com/v1/embeddings"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["payload"] == {
        "model": "text-embedding-3-small",
        "input": ["hello", "world"],
    }
    emb.close()


def test_no_key_sends_no_authorization_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_embed_payload([0.1]))

    emb = _embedder_with(handler, api_key=None)
    assert emb.has_key is False
    emb.embed(["x"])
    assert seen["auth"] is None
    emb.close()


def test_cleartext_http_with_key_refused():
    with pytest.raises(EmbeddingError, match="cleartext http"):
        OpenAIEmbedder(base_url="http://proxy.example/v1", api_key="sk-x")


def test_localhost_http_with_key_allowed():
    emb = OpenAIEmbedder(base_url="http://localhost:11434/v1", api_key="x")
    assert emb.has_key is True
    emb.close()


def test_repr_never_leaks_key():
    emb = OpenAIEmbedder(
        base_url="https://api.openai.com/v1", api_key="sk-super-secret"
    )
    assert "sk-super-secret" not in repr(emb)
    assert "<redacted>" in repr(emb)
    emb.close()


def test_transient_500_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_embed_payload([0.5]))

    emb = _embedder_with(handler)
    assert emb.embed(["x"]) == [[0.5]]
    assert len(calls) == 2
    emb.close()


def test_persistent_500_raises_after_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, text="boom")

    emb = _embedder_with(handler)
    with pytest.raises(EmbeddingResponseError, match="HTTP 500"):
        emb.embed(["x"])
    assert len(calls) == 3
    emb.close()


def test_malformed_payload_raises():
    def handler(request):
        return httpx.Response(200, json={"oops": True})

    emb = _embedder_with(handler)
    with pytest.raises(EmbeddingResponseError, match="malformed"):
        emb.embed(["x"])
    emb.close()


def test_vector_count_mismatch_raises():
    def handler(request):
        return httpx.Response(200, json=_embed_payload([0.1]))

    emb = _embedder_with(handler)
    with pytest.raises(EmbeddingResponseError, match="1 embedding"):
        emb.embed(["a", "b"])
    emb.close()


def test_empty_input_returns_empty_without_request():
    def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("no request should be made")

    emb = _embedder_with(handler)
    assert emb.embed([]) == []
    emb.close()


# ---------------------------------------------------------------------------
# resolve_embedder
# ---------------------------------------------------------------------------


def _clean_env(monkeypatch):
    for var in ("OKFSMITH_EMBEDDINGS", "OKFSMITH_API_KEY", "OPENAI_API_KEY",
                "OKFSMITH_EMBEDDING_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_resolve_none_without_spec_or_env(monkeypatch):
    _clean_env(monkeypatch)
    assert resolve_embedder(None) is None


def test_resolve_openai_with_key(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OKFSMITH_API_KEY", "sk-test")
    emb = resolve_embedder("openai")
    assert isinstance(emb, OpenAIEmbedder)
    assert emb.base_url == "https://api.openai.com/v1"
    assert emb.model == DEFAULT_EMBEDDING_MODEL
    assert emb.provider == "openai"
    emb.close()


def test_resolve_openai_without_key_raises_actionable(monkeypatch):
    _clean_env(monkeypatch)
    with pytest.raises(EmbeddingUnavailableError, match="OKFSMITH_API_KEY"):
        resolve_embedder("openai")


def test_legacy_openai_key_is_provider_scoped(monkeypatch):
    # OPENAI_API_KEY works for the openai provider…
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-legacy")
    emb = resolve_embedder("openai")
    assert emb.has_key is True
    emb.close()
    # …but must never leak into another provider's requests.
    _clean_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-legacy")
    with pytest.raises(EmbeddingUnavailableError, match="No API key"):
        resolve_embedder("openrouter")


def test_explicit_key_beats_env(monkeypatch):
    _clean_env(monkeypatch)
    emb = resolve_embedder("openai", api_key="sk-explicit")
    assert emb.has_key is True
    assert "sk-explicit" not in repr(emb)
    emb.close()


def test_unknown_spec_raises(monkeypatch):
    _clean_env(monkeypatch)
    with pytest.raises(EmbeddingError, match="Unknown embeddings spec"):
        resolve_embedder("bogus")


def test_anthropic_spec_raises_not_supported(monkeypatch):
    _clean_env(monkeypatch)
    with pytest.raises(EmbeddingError, match="no embeddings endpoint"):
        resolve_embedder("anthropic")


def test_env_var_selects_embedder(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OKFSMITH_EMBEDDINGS", "openai")
    monkeypatch.setenv("OKFSMITH_API_KEY", "sk-test")
    emb = resolve_embedder(None)
    assert isinstance(emb, OpenAIEmbedder)
    emb.close()


def test_env_var_model_override(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OKFSMITH_EMBEDDINGS", "openai")
    monkeypatch.setenv("OKFSMITH_API_KEY", "sk-test")
    monkeypatch.setenv("OKFSMITH_EMBEDDING_MODEL", "text-embedding-3-large")
    emb = resolve_embedder(None)
    assert emb.model == "text-embedding-3-large"
    emb.close()


# ---------------------------------------------------------------------------
# End-to-end: run() merges paraphrase sections via the embedding branch
# ---------------------------------------------------------------------------


def _draft_payload(title: str, description: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "type": "process",
                            "title": title,
                            "description": description,
                            "claims": [{"text": description, "page": 1}],
                            "links": [],
                            "tags": [],
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }


def _fake_llm_backend(monkeypatch, script: list):
    """Monkeypatch resolve_backend with a scripted chat backend (no network)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=script.pop(0))

    backend = OpenAICompatibleBackend(
        base_url="http://fake/v1",
        model="fake-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(
        llm_module, "resolve_backend", lambda **kwargs: backend
    )
    return backend


def _paraphrase_sections():
    def section(title, text, source_id):
        return SectionInput(
            title=title,
            level=1,
            text=text,
            page_span=(1, 1),
            tables=[],
            source_id=source_id,
            source_path=f"{source_id}.md",
            doc_title="Doc",
            doc_summary="Summary.",
        )

    return [
        section(
            "Vault synchronization guide",
            "The sync command keeps the bundle current via change detection.",
            "doc-a",
        ),
        section(
            "How to sync your vault",
            "Run the sync command to keep your vault bundle up to date.",
            "doc-b",
        ),
    ]


def _paraphrase_embedder():
    """Cosine 0.9 between the two paraphrase titles, low vs anything else."""

    def fn(texts):
        out = []
        for t in texts:
            if "How to sync your vault" in t:
                out.append([1.0, 0.0])
            else:
                out.append([0.9, 0.435889894])
        return out

    return StubEmbedder(fn=fn, threshold=0.8)


def test_run_merges_paraphrase_sections_with_embedder(tmp_path, monkeypatch):
    script = [
        _draft_payload("Vault synchronization guide", "Sync keeps it current."),
        _draft_payload("How to sync your vault", "Run sync to stay current."),
    ]
    _fake_llm_backend(monkeypatch, script)
    bundle = Bundle(tmp_path / "kb")
    ids = run(
        bundle,
        _paraphrase_sections(),
        model="fake-model",
        verify=False,
        embedder=_paraphrase_embedder(),
    )
    assert script == []  # both drafts consumed
    # run() returns one id per section; a merge maps both to one concept.
    assert len(set(ids)) == 1
    assert len(list(bundle.iter_concepts())) == 1


def test_run_without_embedder_keeps_both_sections(tmp_path, monkeypatch):
    script = [
        _draft_payload("Vault synchronization guide", "Sync keeps it current."),
        _draft_payload("How to sync your vault", "Run sync to stay current."),
    ]
    _fake_llm_backend(monkeypatch, script)
    bundle = Bundle(tmp_path / "kb")
    ids = run(bundle, _paraphrase_sections(), model="fake-model", verify=False)
    assert script == []
    # Token-Jaccard (0.25) misses the paraphrase: two concepts, as before.
    assert len(ids) == 2
