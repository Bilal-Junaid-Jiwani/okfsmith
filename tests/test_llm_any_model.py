"""Tests for "any model, any API key" support.

Covers provider presets (URLs verified against provider docs), the
flag → OKFSMITH_* → legacy env precedence chain, unknown-provider errors,
the Gemini completions-URL special case, mocked chat calls (no real
network), and the security invariant: raw API keys never appear in logs,
banners, doctor output, or ``/model`` output.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

from okfsmith.cli import commands as _commands
from okfsmith.cli.app import app
from okfsmith.cli.chat import ChatSession, resolve_chat_backend
from okfsmith.core.bundle import Bundle
from okfsmith.extract import llm as llm_module
from okfsmith.extract.llm import (
    PROVIDER_PRESETS,
    LLMError,
    LLMUnavailableError,
    OpenAICompatibleBackend,
    key_status,
    redact_key,
    resolve_backend,
    resolve_llm_config,
)

runner = CliRunner()
DUMMY_KEY = "test-key-123"

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


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    """No ambient LLM env may leak into resolution tests."""
    for var in LLM_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_commands, "_api_key_warned", False)


@pytest.fixture()
def tiny_bundle(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "api").mkdir(parents=True)
    (kb / "api" / "auth.md").write_text(
        "---\ntype: Guide\ntitle: Authentication\n---\n\n"
        "# Authentication\n\nUse a Bearer token.\n",
        encoding="utf-8",
    )
    return kb


def _fake_chat_backend(
    base_url: str, model: str, api_key: str | None, provider: str
) -> tuple[OpenAICompatibleBackend, list[httpx.Request]]:
    """Backend with a MockTransport; returns (backend, captured requests)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok [api/auth]"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    return (
        OpenAICompatibleBackend(
            base_url=base_url,
            model=model,
            api_key=api_key,
            provider=provider,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        seen,
    )


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------


def test_provider_preset_urls() -> None:
    assert PROVIDER_PRESETS == {
        "ollama": "http://localhost:11434/v1",
        "lmstudio": "http://localhost:1234/v1",
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "mistral": "https://api.mistral.ai/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "together": "https://api.together.xyz/v1",
        "fireworks": "https://api.fireworks.ai/inference/v1",
        "deepinfra": "https://api.deepinfra.com/v1/openai",
        "anyscale": "https://api.endpoints.anyscale.com/v1",
        "perplexity": "https://api.perplexity.ai",
        "xai": "https://api.x.ai/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "agentrouter": "https://agentrouter.org/v1",
    }


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("groq", "https://api.groq.com/openai/v1/chat/completions"),
        ("openai", "https://api.openai.com/v1/chat/completions"),
        ("deepseek", "https://api.deepseek.com/v1/chat/completions"),
        ("mistral", "https://api.mistral.ai/v1/chat/completions"),
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
        ("together", "https://api.together.xyz/v1/chat/completions"),
        ("fireworks", "https://api.fireworks.ai/inference/v1/chat/completions"),
        ("deepinfra", "https://api.deepinfra.com/v1/openai/chat/completions"),
        ("anyscale", "https://api.endpoints.anyscale.com/v1/chat/completions"),
        # Perplexity's endpoint has no /v1 segment — stored verbatim.
        ("perplexity", "https://api.perplexity.ai/chat/completions"),
        ("agentrouter", "https://agentrouter.org/v1/chat/completions"),
        ("xai", "https://api.x.ai/v1/chat/completions"),
        ("ollama", "http://localhost:11434/v1/chat/completions"),
        ("lmstudio", "http://localhost:1234/v1/chat/completions"),
        # Gemini's OpenAI-compatibility endpoint has no /v1 segment either.
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        ),
    ],
)
def test_completions_url_shapes(provider: str, expected: str) -> None:
    backend = OpenAICompatibleBackend(
        base_url=PROVIDER_PRESETS[provider], model="m", provider=provider
    )
    assert backend._completions_url() == expected


def test_unknown_provider_raises_with_valid_names() -> None:
    with pytest.raises(LLMError) as exc_info:
        resolve_llm_config(provider="groqq")
    msg = str(exc_info.value)
    assert "groqq" in msg
    for name in PROVIDER_PRESETS:
        assert name in msg


def test_bare_host_custom_base_gets_v1(monkeypatch) -> None:
    # Old-style bare-host bases keep working (pre-0.3 contract).
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.local")
    assert resolve_llm_config().base_url == "https://proxy.local/v1"
    # ...but a full base is never doubled.
    cfg = resolve_llm_config(api_base="https://proxy.local/v1/")
    assert cfg.base_url == "https://proxy.local/v1"
    cfg = resolve_llm_config(api_base="https://api.deepinfra.com/v1/openai")
    assert cfg.base_url == "https://api.deepinfra.com/v1/openai"


def test_agentrouter_key_env(monkeypatch) -> None:
    # Provider-scoped: honored for agentrouter...
    monkeypatch.setenv("AGENTROUTER_API_KEY", DUMMY_KEY)
    cfg = resolve_llm_config(provider="agentrouter")
    assert cfg.key_source == "AGENTROUTER_API_KEY"
    assert cfg.api_key == DUMMY_KEY
    assert cfg.base_url == "https://agentrouter.org/v1"
    # ...but never leaks into other providers.
    cfg = resolve_llm_config(provider="groq")
    assert cfg.key_source == "none"
    assert cfg.api_key is None
    # ...and the generic key still wins for agentrouter.
    monkeypatch.setenv("OKFSMITH_API_KEY", "generic-key")
    cfg = resolve_llm_config(provider="agentrouter")
    assert cfg.key_source == "OKFSMITH_API_KEY"


def test_preset_urls_used_verbatim() -> None:
    # Perplexity's bare-host preset must NOT gain a /v1.
    cfg = resolve_llm_config(provider="perplexity")
    assert cfg.base_url == "https://api.perplexity.ai"
    assert cfg.provider == "perplexity"
    cfg = resolve_llm_config(provider="lmstudio")
    assert cfg.base_url == "http://localhost:1234/v1"
    assert cfg.provider == "lmstudio"


# ---------------------------------------------------------------------------
# precedence
# ---------------------------------------------------------------------------


def test_precedence_flag_over_env_over_legacy(monkeypatch) -> None:
    monkeypatch.setenv("OKFSMITH_PROVIDER", "groq")
    monkeypatch.setenv("OKFSMITH_API_BASE", "https://env-base/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy-base/v1")
    # env OKFSMITH_API_BASE beats legacy OPENAI_BASE_URL
    assert resolve_llm_config().base_url == "https://env-base/v1"
    # explicit flag beats everything
    cfg = resolve_llm_config(api_base="https://flag-base/v1")
    assert cfg.base_url == "https://flag-base/v1"
    # legacy OPENAI_BASE_URL still honored when nothing else set
    monkeypatch.delenv("OKFSMITH_API_BASE")
    assert resolve_llm_config().base_url == "https://legacy-base/v1"


def test_legacy_base_url_alias(monkeypatch) -> None:
    # docs/llm.md promised OKFSMITH_BASE_URL; it keeps working.
    monkeypatch.setenv("OKFSMITH_BASE_URL", "https://old-docs-base/v1")
    assert resolve_llm_config().base_url == "https://old-docs-base/v1"


def test_explicit_api_base_beats_provider_preset() -> None:
    cfg = resolve_llm_config(provider="groq", api_base="https://proxy.local/v1")
    assert cfg.base_url == "https://proxy.local/v1"
    assert cfg.provider == "groq"


def test_key_source_precedence(monkeypatch) -> None:
    assert resolve_llm_config().key_source == "none"
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    assert resolve_llm_config().key_source == "OPENAI_API_KEY"
    monkeypatch.setenv("OKFSMITH_API_KEY", "new-key")
    cfg = resolve_llm_config()
    assert cfg.key_source == "OKFSMITH_API_KEY"
    assert cfg.api_key == "new-key"
    cfg = resolve_llm_config(api_key="flag-key")
    assert cfg.key_source == "flag --api-key"
    assert cfg.api_key == "flag-key"


def test_provider_label_inference() -> None:
    assert resolve_llm_config(provider="GROQ").provider == "groq"  # case-insensitive
    assert resolve_llm_config(api_base="https://api.mistral.ai").provider == "mistral"
    assert resolve_llm_config(api_base="https://proxy.local/v1").provider == "custom"
    assert resolve_llm_config().provider == "ollama"


# ---------------------------------------------------------------------------
# resolve_backend
# ---------------------------------------------------------------------------


def test_resolve_backend_uses_provider_preset(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    backend = resolve_backend(provider="groq", api_key=DUMMY_KEY, model="llama-3.3-70b")
    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend.provider == "groq"
    assert backend.base_url == "https://api.groq.com/openai/v1"
    assert backend.model == "llama-3.3-70b"
    assert backend.has_key


def test_resolve_backend_default_ollama(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: True)
    backend = resolve_backend()
    assert backend.provider == "ollama"
    assert backend.base_url == "http://localhost:11434/v1"
    assert not backend.has_key


def test_resolve_backend_legacy_openai_key_fallback(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY_KEY)
    backend = resolve_backend()
    assert backend.provider == "openai"
    assert backend.has_key


def test_resolve_backend_unavailable_mentions_provider(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    with pytest.raises(LLMUnavailableError) as exc_info:
        resolve_backend()
    assert "--provider" in str(exc_info.value)


def test_resolve_chat_backend_unknown_provider_raises(monkeypatch) -> None:
    # Config typos must fail loudly, never silently degrade to extractive.
    with pytest.raises(LLMError):
        resolve_chat_backend(provider="groqq")


def test_resolve_chat_backend_unavailable_is_extractive(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    assert resolve_chat_backend() is None


# ---------------------------------------------------------------------------
# mocked chat calls (no real network)
# ---------------------------------------------------------------------------


def test_mocked_chat_call_groq(monkeypatch) -> None:
    backend, seen = _fake_chat_backend(
        PROVIDER_PRESETS["groq"], "llama-3.3-70b-versatile",
        DUMMY_KEY, "groq",
    )
    text = backend.chat([{"role": "user", "content": "hi"}])
    assert text == "ok [api/auth]"
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {DUMMY_KEY}"
    import json as _json

    assert _json.loads(req.content)["model"] == "llama-3.3-70b-versatile"


def test_mocked_chat_call_gemini_url(monkeypatch) -> None:
    backend, seen = _fake_chat_backend(
        PROVIDER_PRESETS["gemini"], "gemini-2.0-flash",
        DUMMY_KEY, "gemini",
    )
    backend.chat([{"role": "user", "content": "hi"}])
    assert (
        str(seen[0].url)
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


# ---------------------------------------------------------------------------
# key secrecy
# ---------------------------------------------------------------------------


def test_redact_and_key_status() -> None:
    assert redact_key(DUMMY_KEY) == "<redacted>"
    assert redact_key(None) == "<none>"
    assert key_status(DUMMY_KEY) == "set (hidden)"
    assert key_status(None) == "not set"


def test_key_never_in_logs(monkeypatch, caplog) -> None:
    monkeypatch.setattr(llm_module, "is_ollama_reachable", lambda *a, **k: False)
    with caplog.at_level(logging.DEBUG, logger="okfsmith.extract.llm"):
        resolve_backend(provider="groq", api_key=DUMMY_KEY)
    assert DUMMY_KEY not in caplog.text


def test_banner_masks_key(tiny_bundle: Path) -> None:
    backend, _ = _fake_chat_backend(
        PROVIDER_PRESETS["groq"], "llama-3.3-70b-versatile", DUMMY_KEY, "groq"
    )
    console = Console(record=True, width=100)
    session = ChatSession(
        Bundle.load(tiny_bundle), tiny_bundle, backend=backend, console=console
    )
    session._print_banner()
    text = console.export_text()
    assert DUMMY_KEY not in text
    assert "set (hidden)" in text
    assert "groq" in text


def test_slash_model_masks_key(tiny_bundle: Path) -> None:
    backend, _ = _fake_chat_backend(
        PROVIDER_PRESETS["mistral"], "mistral-large-latest", DUMMY_KEY, "mistral"
    )
    console = Console(record=True, width=100)
    session = ChatSession(
        Bundle.load(tiny_bundle), tiny_bundle, backend=backend, console=console
    )
    session.handle_slash("/model")
    text = console.export_text()
    assert DUMMY_KEY not in text
    assert "set (hidden)" in text
    assert "mistral" in text


def test_doctor_masks_key(monkeypatch) -> None:
    monkeypatch.setenv("OKFSMITH_API_KEY", DUMMY_KEY)
    monkeypatch.setenv("OKFSMITH_PROVIDER", "deepseek")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert DUMMY_KEY not in result.output
    assert "set (hidden)" in result.output
    assert "deepseek" in result.output


def test_doctor_unknown_provider_is_clean_error(monkeypatch) -> None:
    monkeypatch.setenv("OKFSMITH_PROVIDER", "groqq")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Unknown provider" in result.output


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_api_key_flag_warns_once(tiny_bundle: Path) -> None:
    result = runner.invoke(
        app,
        ["chat", str(tiny_bundle), "--api-key", DUMMY_KEY, "--provider", "groq"],
        input="/exit\n",
    )
    assert result.exit_code == 0, result.output
    assert "shell history" in result.output
    assert "OKFSMITH_API_KEY" in result.output
    # one-time per process: a second command does not repeat it
    result2 = runner.invoke(
        app,
        ["chat", str(tiny_bundle), "--api-key", DUMMY_KEY, "--provider", "groq"],
        input="/exit\n",
    )
    assert result2.output.count("shell history") == 0


def test_api_key_never_echoed_in_chat(tiny_bundle: Path) -> None:
    result = runner.invoke(
        app,
        ["chat", str(tiny_bundle), "--api-key", DUMMY_KEY, "--provider", "groq"],
        input="/model\n/exit\n",
    )
    assert result.exit_code == 0, result.output
    assert DUMMY_KEY not in result.output


def test_chat_unknown_provider_is_clean_cli_error(tiny_bundle: Path) -> None:
    result = runner.invoke(
        app, ["chat", str(tiny_bundle), "--provider", "groqq"], input="/exit\n"
    )
    assert result.exit_code != 0
    assert "bad-llm-config" in result.output
    assert "Unknown provider" in result.output


def test_ingest_llm_flags_reject_no_llm(tmp_path: Path) -> None:
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    for flag in ("--provider", "--api-base", "--api-key"):
        result = runner.invoke(
            app,
            ["ingest", str(tmp_path / "b"), str(src), "--no-llm", flag, "x"],
        )
        assert result.exit_code == 2, (flag, result.output)
        assert "cannot be combined with --no-llm" in result.output


def test_chat_llm_flags_reject_no_llm(tiny_bundle: Path) -> None:
    result = runner.invoke(
        app, ["chat", str(tiny_bundle), "--no-llm", "--provider", "groq"]
    )
    assert result.exit_code == 2
    assert "cannot be combined with --no-llm" in result.output


def test_chat_help_mentions_provider() -> None:
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0, result.output
    assert "--provider" in result.output
    assert "--api-key" in result.output


def test_ingest_help_mentions_provider() -> None:
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0, result.output
    assert "--provider" in result.output
    assert "--api-base" in result.output
