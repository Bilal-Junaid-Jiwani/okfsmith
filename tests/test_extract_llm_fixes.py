"""Regression tests for extract-llm QA fixes.

Covers:
- ``retry_with_backoff``: transient-failure retry with exponential backoff.
- M22: ``httpx.InvalidURL`` (e.g. malformed proxy env) -> ``LLMError``.
- M23: empty backend responses degrade like stub backends (``""`` -> repair
  -> ``needs-review`` fallback), instead of raising ``LLMResponseError``.
- L11: a single lazily-created ``httpx.Client`` is reused across ``chat()``
  calls and closed properly (``close()`` / context manager).
"""

from __future__ import annotations

import httpx
import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.extract import llm as llm_module
from okfsmith.extract.llm import (
    LLMError,
    LLMResponseError,
    LLMUnavailableError,
    OpenAICompatibleBackend,
    retry_with_backoff,
)
from okfsmith.extract.pipeline import SectionInput, run

# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------


def _no_sleep(monkeypatch) -> list[float]:
    """Replace time.sleep with a recorder; return the recorded delays."""
    delays: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", delays.append)
    return delays


def test_retry_succeeds_after_transient_failures(monkeypatch):
    delays = _no_sleep(monkeypatch)
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise LLMResponseError(f"boom-{len(calls)}")
        return "ok"

    assert retry_with_backoff(flaky, base_delay=1.0) == "ok"
    assert len(calls) == 3
    assert delays == [1.0, 2.0]  # exponential: base * 2**(n-1)


def test_retry_gives_up_after_attempts_and_reraises_last(monkeypatch):
    delays = _no_sleep(monkeypatch)
    calls: list[int] = []

    def always_fails() -> None:
        calls.append(1)
        raise LLMResponseError(f"boom-{len(calls)}")

    with pytest.raises(LLMResponseError, match="boom-3"):
        retry_with_backoff(always_fails, attempts=3, base_delay=1.0)
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_retry_respects_max_delay_cap(monkeypatch):
    delays = _no_sleep(monkeypatch)

    def always_fails() -> None:
        raise LLMResponseError("boom")

    with pytest.raises(LLMResponseError):
        retry_with_backoff(always_fails, attempts=3, base_delay=10.0, max_delay=15.0)
    assert delays == [10.0, 15.0]


def test_retry_never_retries_unavailable(monkeypatch):
    delays = _no_sleep(monkeypatch)
    calls: list[int] = []

    def no_endpoint() -> None:
        calls.append(1)
        raise LLMUnavailableError("no endpoint configured")

    with pytest.raises(LLMUnavailableError):
        retry_with_backoff(no_endpoint)
    assert len(calls) == 1  # config error: retrying cannot help
    assert delays == []


def test_retry_ignores_non_matching_exceptions(monkeypatch):
    delays = _no_sleep(monkeypatch)
    calls: list[int] = []

    def bug() -> None:
        calls.append(1)
        raise ValueError("programmer error, not transient")

    with pytest.raises(ValueError, match="programmer error"):
        retry_with_backoff(bug)
    assert len(calls) == 1
    assert delays == []


def test_retry_custom_exceptions_tuple(monkeypatch):
    delays = _no_sleep(monkeypatch)
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("transient for this caller")
        return "recovered"

    assert (
        retry_with_backoff(flaky, attempts=2, exceptions=(ValueError,)) == "recovered"
    )
    assert len(calls) == 2
    assert delays == [1.0]


def test_retry_rejects_zero_attempts():
    with pytest.raises(ValueError, match="attempts"):
        retry_with_backoff(lambda: None, attempts=0)


def test_retry_passes_args_and_kwargs_through_to_fn(monkeypatch):
    """The pipeline call pattern: retry_with_backoff(backend.chat, messages,
    temperature=0.0) — extra args/kwargs reach fn, retry controls don't."""
    delays = _no_sleep(monkeypatch)
    calls: list[tuple] = []

    def chat(messages, *, temperature=0.0):
        calls.append((messages, temperature))
        if len(calls) < 2:
            raise LLMResponseError("flaky")
        return "done"

    result = retry_with_backoff(
        chat, [{"role": "user", "content": "hi"}], temperature=0.0, base_delay=0.5
    )
    assert result == "done"
    assert calls == [
        ([{"role": "user", "content": "hi"}], 0.0),
        ([{"role": "user", "content": "hi"}], 0.0),
    ]
    assert delays == [0.5]


# ---------------------------------------------------------------------------
# M22: httpx.InvalidURL -> LLMError
# ---------------------------------------------------------------------------


def test_malformed_proxy_env_raises_llm_error_not_invalid_url(monkeypatch):
    # QA repro: bracketed IPv6 in no_proxy makes httpx raise InvalidURL
    # ("Invalid port: ':1]'") at client-construction time.
    monkeypatch.setenv("no_proxy", "[::1]")
    backend = OpenAICompatibleBackend("http://fake/v1", "m")
    try:
        with pytest.raises(LLMError) as excinfo:
            backend.chat([{"role": "user", "content": "hi"}])
        assert not isinstance(excinfo.value, httpx.InvalidURL)
        assert "unreachable" in str(excinfo.value)
    finally:
        backend.close()


def test_garbage_base_url_raises_llm_error(monkeypatch):
    for var in PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    backend = OpenAICompatibleBackend("::not a url::", "m")
    try:
        with pytest.raises(LLMError):
            backend.chat([{"role": "user", "content": "hi"}])
    finally:
        backend.close()


# ---------------------------------------------------------------------------
# M23: empty backend response -> graceful needs-review fallback
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


def test_empty_content_returned_not_raised():
    """chat() returns "" for empty content instead of raising LLMResponseError."""
    backend = OpenAICompatibleBackend(
        base_url="http://fake/v1",
        model="m",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=_chat_payload(""))
            )
        ),
    )
    assert backend.chat([{"role": "user", "content": "hi"}]) == ""
    backend.close()


def test_empty_content_pipeline_falls_back_to_needs_review(tmp_path, monkeypatch):
    """Empty responses from the real backend degrade exactly like a stub
    backend returning "": repair attempt, then an honest needs-review draft."""
    script = [_chat_payload(""), _chat_payload("   ")]  # pass-1, then repair

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=script.pop(0))

    backend = OpenAICompatibleBackend(
        base_url="http://fake/v1",
        model="fake-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(llm_module, "resolve_backend", lambda **kwargs: backend)

    bundle = Bundle(tmp_path)
    (concept_id,) = run(bundle, [_section()], model="fake-model", verify=True)

    concept = bundle.get(concept_id)
    assert concept.frontmatter["tags"] == ["needs-review"]
    assert concept.frontmatter["title"] == "Nightly Rollup"  # section-derived
    backend.close()


# ---------------------------------------------------------------------------
# L11: single reused httpx.Client, closed properly
# ---------------------------------------------------------------------------

#: Proxy env vars that can break real httpx.Client construction in this
#: sandbox (its ambient no_proxy contains a bracketed IPv6 httpx rejects).
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for var in PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_client_reused_across_calls(clean_proxy_env):
    backend = OpenAICompatibleBackend("http://fake/v1", "m")
    try:
        first = backend._client_or_new()
        second = backend._client_or_new()
        assert first is second
    finally:
        backend.close()


def test_close_discards_owned_client(clean_proxy_env):
    backend = OpenAICompatibleBackend("http://fake/v1", "m")
    first = backend._client_or_new()
    backend.close()
    assert backend._owned_client is None
    second = backend._client_or_new()
    try:
        assert second is not first
    finally:
        backend.close()


def test_context_manager_closes_owned_client(clean_proxy_env):
    with OpenAICompatibleBackend("http://fake/v1", "m") as backend:
        client = backend._client_or_new()
    assert backend._owned_client is None
    assert client.is_closed


def test_injected_client_is_never_closed_by_backend():
    injected = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_chat_payload("{}"))
        )
    )
    backend = OpenAICompatibleBackend("http://fake/v1", "m", client=injected)
    backend.close()
    assert not injected.is_closed  # caller-owned: still usable
    with OpenAICompatibleBackend("http://fake/v1", "m", client=injected) as _b:
        pass
    assert not injected.is_closed
    injected.close()


def test_chat_reuses_one_client_across_calls(monkeypatch):
    """Two chat() calls -> exactly one httpx.Client construction."""
    for var in PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    creations: list[httpx.Client] = []
    real_client = httpx.Client

    class CountingClient(real_client):
        def __init__(self, *args, **kwargs):
            creations.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", CountingClient)
    backend = OpenAICompatibleBackend("http://127.0.0.1:1/v1", "m")  # nothing listens
    try:
        for _ in range(2):
            with pytest.raises(LLMResponseError):
                backend.chat([{"role": "user", "content": "hi"}])
        assert len(creations) == 1
    finally:
        backend.close()
