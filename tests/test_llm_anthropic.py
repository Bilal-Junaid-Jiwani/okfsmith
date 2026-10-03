"""Tests for the native Anthropic Messages API backend.

Covers the wire format (URL, headers, system-message hoisting, role
alternation), response parsing, error mapping, the resolution rules
(``--provider anthropic`` / ``OKFSMITH_PROVIDER`` / implied by
``ANTHROPIC_API_KEY``), key precedence, and the key-secrecy invariant.
All HTTP is mocked — no real network.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from okfsmith.extract import llm as llm_module
from okfsmith.extract.llm import (
    ANTHROPIC_API_BASE,
    DEFAULT_ANTHROPIC_MODEL,
    LLMError,
    LLMResponseError,
    AnthropicBackend,
    OpenAICompatibleBackend,
    resolve_backend,
    resolve_llm_config,
)

LLM_ENV_VARS = (
    "OKFSMITH_PROVIDER",
    "OKFSMITH_API_BASE",
    "OKFSMITH_BASE_URL",
    "OKFSMITH_API_KEY",
    "AGENTROUTER_API_KEY",
    "OKFSMITH_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
)

DUMMY_KEY = "sk-ant-test-key"


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    """No ambient LLM env may leak into resolution tests."""
    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _anthropic_backend(
    seen: list[httpx.Request],
    *,
    status: int = 200,
    payload: dict | None = None,
    raw: bytes | None = None,
    api_key: str | None = DUMMY_KEY,
    base_url: str = ANTHROPIC_API_BASE,
    model: str = DEFAULT_ANTHROPIC_MODEL,
) -> AnthropicBackend:
    """Backend with a MockTransport; returns the backend, appends requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if raw is not None:
            return httpx.Response(status, content=raw)
        body = (
            payload
            if payload is not None
            else {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "stop_reason": "end_turn",
            }
        )
        return httpx.Response(status, json=body)

    return AnthropicBackend(
        base_url=base_url,
        model=model,
        api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# wire format
# ---------------------------------------------------------------------------


def test_messages_url_and_headers() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    backend.chat([{"role": "user", "content": "hi"}])
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == DUMMY_KEY
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == DEFAULT_ANTHROPIC_MODEL
    assert body["max_tokens"] == 4096
    # temperature=0.0 is the default: Anthropic already defaults to 1.0, so
    # the deterministic default is simply not sent.
    assert "temperature" not in body
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "system" not in body


def test_temperature_sent_when_nonzero() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    backend.chat([{"role": "user", "content": "hi"}], temperature=0.2)
    body = json.loads(seen[0].content)
    assert body["temperature"] == 0.2


def test_system_message_hoisted() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    backend.chat(
        [
            {"role": "system", "content": "You are a JSON extractor."},
            {"role": "user", "content": "extract this"},
        ]
    )
    body = json.loads(seen[0].content)
    assert body["system"] == "You are a JSON extractor."
    assert body["messages"] == [{"role": "user", "content": "extract this"}]


def test_multiple_system_messages_joined() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    backend.chat(
        [
            {"role": "system", "content": "part one"},
            {"role": "user", "content": "q"},
            {"role": "system", "content": "part two"},
        ]
    )
    body = json.loads(seen[0].content)
    assert body["system"] == "part one\n\npart two"
    assert body["messages"] == [{"role": "user", "content": "q"}]


def test_consecutive_same_role_merged() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    backend.chat(
        [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
    )
    body = json.loads(seen[0].content)
    assert body["messages"] == [{"role": "user", "content": "first\n\nsecond"}]


def test_unknown_role_rejected() -> None:
    backend = _anthropic_backend([])
    with pytest.raises(LLMResponseError, match="cannot carry role"):
        backend.chat([{"role": "tool", "content": "x"}])


def test_empty_messages_rejected() -> None:
    backend = _anthropic_backend([])
    with pytest.raises(LLMResponseError, match="no messages"):
        backend.chat([])


def test_non_string_content_rejected() -> None:
    backend = _anthropic_backend([])
    with pytest.raises(LLMResponseError, match="string message content"):
        backend.chat([{"role": "user", "content": ["block"]}])


# ---------------------------------------------------------------------------
# response parsing
# ---------------------------------------------------------------------------


def test_text_blocks_concatenated_in_order() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(
        seen,
        payload={
            "content": [
                {"type": "text", "text": "hello "},
                {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
                {"type": "text", "text": "world"},
            ]
        },
    )
    assert backend.chat([{"role": "user", "content": "hi"}]) == "hello world"


def test_empty_content_returns_empty_string() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen, payload={"content": []})
    assert backend.chat([{"role": "user", "content": "hi"}]) == ""


def test_malformed_payload_raises() -> None:
    backend = _anthropic_backend([], payload={"nope": True})
    with pytest.raises(LLMResponseError, match="malformed"):
        backend.chat([{"role": "user", "content": "hi"}])


def test_non_json_payload_raises() -> None:
    backend = _anthropic_backend([], raw=b"not json")
    with pytest.raises(LLMResponseError, match="malformed"):
        backend.chat([{"role": "user", "content": "hi"}])


def test_http_error_surfaces_anthropic_message() -> None:
    backend = _anthropic_backend(
        [],
        status=401,
        payload={"type": "error", "error": {"type": "auth", "message": "invalid x-api-key"}},
    )
    with pytest.raises(LLMResponseError) as exc_info:
        backend.chat([{"role": "user", "content": "hi"}])
    assert "401" in str(exc_info.value)
    assert "invalid x-api-key" in str(exc_info.value)


def test_http_error_without_json_body() -> None:
    backend = _anthropic_backend([], status=500, raw=b"boom")
    with pytest.raises(LLMResponseError, match="500"):
        backend.chat([{"role": "user", "content": "hi"}])


def test_transport_error_raises_llm_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    backend = AnthropicBackend(
        api_key=DUMMY_KEY,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMResponseError, match="unreachable"):
        backend.chat([{"role": "user", "content": "hi"}])


def test_chat_without_key_raises() -> None:
    backend = _anthropic_backend([], api_key=None)
    with pytest.raises(LLMError, match="no API key"):
        backend.chat([{"role": "user", "content": "hi"}])


def test_custom_base_for_messages_api_proxy() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen, base_url="https://proxy.local/anthropic")
    backend.chat([{"role": "user", "content": "hi"}])
    assert str(seen[0].url) == "https://proxy.local/anthropic/v1/messages"


def test_injected_client_not_closed_by_backend() -> None:
    seen: list[httpx.Request] = []
    backend = _anthropic_backend(seen)
    with backend:
        backend.chat([{"role": "user", "content": "hi"}])
    assert not backend._client.is_closed
    backend.close()  # idempotent, never closes the injected client
    assert not backend._client.is_closed


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def test_config_provider_anthropic_defaults(monkeypatch) -> None:
    cfg = resolve_llm_config(provider="anthropic")
    assert cfg.provider == "anthropic"
    assert cfg.base_url == ANTHROPIC_API_BASE
    assert cfg.model == DEFAULT_ANTHROPIC_MODEL
    assert cfg.key_source == "none"


def test_config_anthropic_key_chain(monkeypatch) -> None:
    monkeypatch.setenv("OKFSMITH_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    cfg = resolve_llm_config()
    assert cfg.provider == "anthropic"
    assert cfg.api_key == "sk-ant-env"
    assert cfg.key_source == "ANTHROPIC_API_KEY"


def test_config_anthropic_key_precedence(monkeypatch) -> None:
    # flag --api-key > OKFSMITH_API_KEY > ANTHROPIC_API_KEY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setenv("OKFSMITH_API_KEY", "okf-key")
    cfg = resolve_llm_config(provider="anthropic")
    assert cfg.api_key == "okf-key"
    assert cfg.key_source == "OKFSMITH_API_KEY"
    cfg = resolve_llm_config(provider="anthropic", api_key="flag-key")
    assert cfg.api_key == "flag-key"
    assert cfg.key_source == "flag --api-key"


def test_config_anthropic_key_scoped_to_anthropic(monkeypatch) -> None:
    # ANTHROPIC_API_KEY must not leak into other providers' key chains.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    cfg = resolve_llm_config(provider="groq")
    assert cfg.key_source == "none"


def test_config_anthropic_model_overridable(monkeypatch) -> None:
    monkeypatch.setenv("OKFSMITH_MODEL", "claude-sonnet-4-5")
    cfg = resolve_llm_config(provider="anthropic")
    assert cfg.model == "claude-sonnet-4-5"
    cfg = resolve_llm_config(provider="anthropic", model="claude-opus-4-1")
    assert cfg.model == "claude-opus-4-1"


def test_anthropic_key_alone_implies_provider(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    cfg = resolve_llm_config()
    assert cfg.provider == "anthropic"
    assert cfg.key_source == "ANTHROPIC_API_KEY"


def test_explicit_base_wins_over_anthropic_implication(monkeypatch) -> None:
    # A custom base is an explicit choice: the Anthropic key must not
    # silently flip the provider when the user pointed at their own host.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    cfg = resolve_llm_config(api_base="https://proxy.local/v1")
    assert cfg.provider == "custom"
    assert cfg.base_url == "https://proxy.local/v1"


def test_api_base_pointing_at_anthropic_host_infers_provider(monkeypatch) -> None:
    # --api-base at the Anthropic host uses the native wire format, with no
    # doubled /v1/v1 from the OpenAI-compat bare-host rule.
    cfg = resolve_llm_config(api_base="https://api.anthropic.com")
    assert cfg.provider == "anthropic"
    assert cfg.base_url == "https://api.anthropic.com"
    backend = resolve_backend(api_base="https://api.anthropic.com", api_key=DUMMY_KEY)
    assert isinstance(backend, AnthropicBackend)
    assert backend._messages_url() == "https://api.anthropic.com/v1/messages"


def test_resolve_backend_anthropic_provider(monkeypatch) -> None:
    backend = resolve_backend(provider="anthropic", api_key=DUMMY_KEY)
    assert isinstance(backend, AnthropicBackend)
    assert not isinstance(backend, OpenAICompatibleBackend)
    assert backend.provider == "anthropic"
    assert backend.model == DEFAULT_ANTHROPIC_MODEL
    assert backend.has_key


def test_resolve_backend_anthropic_requires_key(monkeypatch) -> None:
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        resolve_backend(provider="anthropic")


def test_resolve_backend_anthropic_custom_base(monkeypatch) -> None:
    backend = resolve_backend(
        provider="anthropic", api_base="https://proxy.local", api_key=DUMMY_KEY
    )
    assert isinstance(backend, AnthropicBackend)
    assert backend._messages_url() == "https://proxy.local/v1/messages"


def test_key_never_in_logs(monkeypatch, caplog) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    with caplog.at_level(logging.DEBUG, logger="okfsmith.extract.llm"):
        resolve_backend()
    assert DUMMY_KEY not in caplog.text
    assert "<redacted>" in caplog.text


def test_backend_repr_never_contains_key() -> None:
    backend = _anthropic_backend([])
    assert DUMMY_KEY not in repr(backend)


def test_unavailable_error_mentions_anthropic(monkeypatch) -> None:
    from okfsmith.extract.llm import LLMUnavailableError

    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    with pytest.raises(LLMUnavailableError) as exc_info:
        resolve_backend()
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)
