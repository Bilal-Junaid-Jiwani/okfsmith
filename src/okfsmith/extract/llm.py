"""LLM provider abstraction for okfsmith extraction.

Default backend: local **Ollama** over its OpenAI-compatible API
(``POST http://localhost:11434/v1/chat/completions``). Any hosted model
works too: pick a ``--provider`` preset (OpenRouter, Groq, Mistral,
DeepSeek, Together, Fireworks, DeepInfra, Anyscale, Perplexity, xAI,
Gemini, OpenAI, Agent Router, LM Studio, Ollama) or point ``--api-base`` at any
OpenAI-compatible endpoint (Azure OpenAI, self-hosted vLLM, llama.cpp
server, any compat proxy — even an Anthropic-compat gateway, since
Anthropic's *native* API is not OpenAI-compatible).

Secrets discipline: API keys come from **environment variables** (or an
explicit ``--api-key`` flag) — never from files, never echoed into logs,
exceptions, or error messages (see :func:`redact_key` and
:func:`key_status`).

Network discipline: the only network calls in this package go to the
configured LLM endpoint. No other host is ever contacted.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

#: Default Ollama host. The reachability probe hits ``/api/tags`` here;
#: the OpenAI-compatible API base is :data:`DEFAULT_OLLAMA_API_BASE`.
DEFAULT_OLLAMA_BASE = "http://localhost:11434"

#: Ollama's OpenAI-compatible API base (``/chat/completions`` is appended).
DEFAULT_OLLAMA_API_BASE = DEFAULT_OLLAMA_BASE + "/v1"

#: Env var overriding the default model.
MODEL_ENV_VAR = "OKFSMITH_MODEL"

#: Default model when neither an explicit model nor ``OKFSMITH_MODEL`` is set.
DEFAULT_MODEL = "qwen3:8b"

#: Env var selecting a provider preset (see :data:`PROVIDER_PRESETS`).
PROVIDER_ENV_VAR = "OKFSMITH_PROVIDER"

#: Env var for a custom OpenAI-compatible base URL — the full base, e.g.
#: ``https://api.openai.com/v1`` (okfsmith appends ``/chat/completions``).
API_BASE_ENV_VAR = "OKFSMITH_API_BASE"

#: Env var for the hosted endpoint's API key (preferred over ``--api-key``).
API_KEY_ENV_VAR = "OKFSMITH_API_KEY"

#: Provider-specific key env var, honored when the resolved provider is
#: ``agentrouter`` (community docs list it as the key for Agent Router's
#: OpenAI-compatible surface).
AGENTROUTER_KEY_ENV_VAR = "AGENTROUTER_API_KEY"

#: Env vars accepted for hosted OpenAI-compatible endpoints (legacy).
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"
OPENAI_BASE_ENV_VAR = "OPENAI_BASE_URL"

#: Legacy alias for :data:`API_BASE_ENV_VAR` (promised by docs/llm.md).
LEGACY_BASE_ENV_VAR = "OKFSMITH_BASE_URL"

#: Env var we notice but cannot use natively yet (v1 wires OpenAI-compatible
#: endpoints only; the user can still point ``--api-base`` at a compatible
#: gateway).
ANTHROPIC_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

#: Named provider presets: name -> canonical base URL. The backend
#: appends ``/chat/completions`` to the base verbatim, so each entry is
#: the exact documented base (note the odd ones out: Perplexity has no
#: ``/v1`` segment, Fireworks nests under ``/inference/v1``, DeepInfra
#: under ``/v1/openai``, Gemini under ``/v1beta/openai``). Custom bases
#: given via ``--api-base`` / env are normalized by
#: :func:`_normalize_custom_base` so both bare hosts and full bases work.
PROVIDER_PRESETS: dict[str, str] = {
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

#: Logged once when an Anthropic key is present but no explicit base URL is
#: given: Anthropic's *native* API is not OpenAI-compatible, so it cannot
#: be called directly — point ``--api-base`` at an OpenAI-compatible
#: gateway/proxy in front of Anthropic (or use the ``openrouter`` preset,
#: which routes to Claude models with one key).
ANTHROPIC_NATIVE_TODO = (
    "ANTHROPIC_API_KEY is set, but Anthropic's native API is not "
    "OpenAI-compatible, so it cannot be called directly. Falling back to "
    "the default Ollama endpoint; use --provider openrouter (one key, many "
    "models, incl. Claude) or point --api-base at an OpenAI-compatible "
    "gateway in front of Anthropic."
)

#: Timeout (seconds) for the Ollama reachability probe.
REACHABILITY_TIMEOUT = 2.0

#: Timeout (seconds) for chat-completion calls.
CHAT_TIMEOUT = 180.0


class LLMError(Exception):
    """Base class for all extraction LLM errors."""


class LLMUnavailableError(LLMError):
    """No usable LLM endpoint: no key configured and Ollama unreachable.

    Raised *before* any extraction work starts, with an actionable message.
    """


class LLMResponseError(LLMError):
    """The endpoint answered, but the response was unusable."""


def redact_key(key: str | None) -> str:
    """Return a safe placeholder for *key* — the value never leaves this.

    Always returns ``"<redacted>"`` (or ``"<none>"``); even key length is
    not disclosed, so there is nothing to correlate.
    """
    return "<redacted>" if key else "<none>"


def key_status(key: str | None) -> str:
    """User-facing key-presence indicator for banners/doctor/``/model``.

    Never the key itself — only whether one is configured.
    """
    return "set (hidden)" if key else "not set"


@dataclass
class LLMConfig:
    """Resolved LLM configuration — pure data, no network involved.

    Produced by :func:`resolve_llm_config`; consumed by
    :func:`resolve_backend` and by UI surfaces (``doctor``, chat banner)
    that need to describe the configuration without probing anything.
    """

    #: Provider label: a preset name (``"groq"``), ``"custom"``, or
    #: ``"ollama"`` for the default local path.
    provider: str
    #: Full base URL the completions path is appended to (``/chat/completions``),
    #: or ``None`` for the default Ollama probing path.
    base_url: str | None
    #: Resolved model name.
    model: str
    #: The API key, if any. Held in memory only — never logged, never
    #: persisted; display only via :func:`key_status`.
    api_key: str | None
    #: Where the key came from: ``"flag --api-key"``, an env var name, or
    #: ``"none"``.
    key_source: str


class LLMBackend:
    """Abstract chat backend. Subclass and implement :meth:`chat`."""

    #: Human-readable backend label, e.g. ``"ollama"`` or ``"openai-compatible"``.
    name = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Send *messages* and return the assistant's text content."""
        raise NotImplementedError

    def __repr__(self) -> str:  # never includes credentials
        return f"{type(self).__name__}(name={self.name!r}, model={self.model!r})"


class OpenAICompatibleBackend(LLMBackend):
    """Any OpenAI-compatible ``.../chat/completions`` endpoint (incl. Ollama).

    ``base_url`` is the full API base (e.g. ``https://api.openai.com/v1`` —
    the backend appends only ``/chat/completions``). ``api_key`` may be
    ``None``/empty for local endpoints that need no auth. A prebuilt
    :class:`httpx.Client` can be injected (tests use a mock transport);
    otherwise one is created per backend.

    ``provider`` is a display label (``"groq"``, ``"ollama"``, ``"custom"``,
    …) — it never affects the wire format, which is OpenAI-compatible for
    every provider.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = CHAT_TIMEOUT,
        client: httpx.Client | None = None,
        provider: str = "custom",
    ) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key  # never logged; never serialized
        self._client = client
        self._timeout = timeout
        self.provider = provider

    @property
    def has_key(self) -> bool:
        """Whether an API key is configured (never exposes the value)."""
        return bool(self._api_key)

    def _completions_url(self) -> str:
        # The base is canonical (see PROVIDER_PRESETS / _normalize_custom_base):
        # the completions path is always exactly "/chat/completions".
        return self.base_url.rstrip("/") + "/chat/completions"

    def _client_or_new(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout)

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        url = self._completions_url()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        logger.debug(
            "POST %s model=%s (key=%s)",
            url,
            self.model,
            redact_key(self._api_key),
        )
        try:
            response = self._client_or_new().post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMResponseError(
                f"LLM endpoint {self.base_url} unreachable: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code >= 400:
            body = response.text[:500]
            raise LLMResponseError(
                f"LLM endpoint {self.base_url} returned HTTP "
                f"{response.status_code}: {body}"
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                f"LLM endpoint {self.base_url} returned a malformed "
                f"chat-completion payload: {exc}"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError(
                f"LLM endpoint {self.base_url} returned empty content"
            )
        return content


def resolve_model(explicit: str | None = None) -> str:
    """Resolve the model name: explicit arg → ``OKFSMITH_MODEL`` → default."""
    return explicit or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL


def is_ollama_reachable(base_url: str = DEFAULT_OLLAMA_BASE) -> bool:
    """Probe whether an Ollama server answers at *base_url*.

    Only ever contacts the configured LLM endpoint. Any failure (connection
    refused, timeout, bad status) means "not reachable" — never an exception.
    """
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=REACHABILITY_TIMEOUT)
        return response.status_code < 500
    except Exception:
        # Any failure — connection refused, timeout, bad status, or even a
        # broken client setup (e.g. unparseable proxy env vars) — means
        # "not reachable". This probe must never raise.
        return False


def _preset_name_for_base(base_url: str) -> str | None:
    """Return the preset name whose URL matches *base_url*, if any."""
    want = base_url.rstrip("/").lower()
    for name, url in PROVIDER_PRESETS.items():
        if url.rstrip("/").lower() == want:
            return name
    return None


def _normalize_custom_base(base_url: str) -> str:
    """Normalize a user-supplied base URL to the canonical full-base form.

    Strips trailing slashes. A bare host with no path (the pre-0.3
    contract, e.g. an old ``OPENAI_BASE_URL``) gets ``/v1`` appended so
    those values keep working; anything else — ``.../v1``,
    ``.../v1beta/openai``, ``.../inference/v1`` — is used verbatim, so
    there is never a doubled ``/v1/v1``. Preset URLs are already canonical
    and are never passed through this.
    """
    base = base_url.strip().rstrip("/")
    if not urlsplit(base).path:
        base += "/v1"
    return base


def resolve_llm_config(
    *,
    model: str | None = None,
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> LLMConfig:
    """Resolve the LLM configuration from flags → env → legacy env.

    Precedence per setting (highest wins):

    - provider: ``--provider`` → ``OKFSMITH_PROVIDER``
    - base URL: ``--api-base`` → ``OKFSMITH_API_BASE`` → ``OKFSMITH_BASE_URL``
      (legacy alias) → ``OPENAI_BASE_URL`` (legacy) → the provider preset.
      Custom bases are normalized by :func:`_normalize_custom_base`
      (bare hosts gain ``/v1``); the backend appends ``/chat/completions``.
    - key: ``--api-key`` → ``OKFSMITH_API_KEY`` → ``AGENTROUTER_API_KEY``
      (only when the provider is ``agentrouter``) → ``OPENAI_API_KEY`` (legacy)
    - model: ``--model`` → ``OKFSMITH_MODEL`` → built-in default

    No network is touched. Raises :class:`LLMError` for an unknown provider
    name (the message lists the valid names).
    """
    provider_name = (provider or os.environ.get(PROVIDER_ENV_VAR) or "").strip().lower() or None
    if provider_name and provider_name not in PROVIDER_PRESETS:
        valid = ", ".join(sorted(PROVIDER_PRESETS))
        raise LLMError(
            f"Unknown provider '{provider_name}'. Valid providers: {valid}. "
            "Omit --provider and pass --api-base directly for anything else."
        )

    custom_base = (
        api_base
        or os.environ.get(API_BASE_ENV_VAR)
        or os.environ.get(LEGACY_BASE_ENV_VAR)
        or os.environ.get(OPENAI_BASE_ENV_VAR)
    )
    if custom_base:
        base_url: str | None = _normalize_custom_base(custom_base)
    elif provider_name:
        base_url = PROVIDER_PRESETS[provider_name]
    else:
        base_url = None

    if provider_name:
        label = provider_name
    elif base_url and _preset_name_for_base(base_url):
        label = _preset_name_for_base(base_url)  # type: ignore[assignment]
    elif base_url:
        label = "custom"
    else:
        label = "ollama"

    key: str | None
    key_source: str
    if api_key is not None:
        key, key_source = api_key, "flag --api-key"
    elif os.environ.get(API_KEY_ENV_VAR):
        key, key_source = os.environ[API_KEY_ENV_VAR], API_KEY_ENV_VAR
    elif label == "agentrouter" and os.environ.get(AGENTROUTER_KEY_ENV_VAR):
        # Provider-scoped on purpose: a generic key must never be silently
        # overridden for other providers by a router-specific one.
        key, key_source = os.environ[AGENTROUTER_KEY_ENV_VAR], AGENTROUTER_KEY_ENV_VAR
    elif os.environ.get(OPENAI_KEY_ENV_VAR):
        key, key_source = os.environ[OPENAI_KEY_ENV_VAR], OPENAI_KEY_ENV_VAR
    else:
        key, key_source = None, "none"

    return LLMConfig(
        provider=label,
        base_url=base_url,
        model=resolve_model(model),
        api_key=key,
        key_source=key_source,
    )


def resolve_backend(
    *,
    model: str | None = None,
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = CHAT_TIMEOUT,
) -> LLMBackend:
    """Pick the LLM backend for an extraction run. Single source of truth.

    - Explicit provider / base URL (flags or ``OKFSMITH_*`` env) →
      OpenAI-compatible backend; the key comes from ``--api-key``,
      ``OKFSMITH_API_KEY``, or legacy ``OPENAI_API_KEY``. Local endpoints
      may omit the key entirely.
    - Nothing configured → default Ollama at ``http://localhost:11434``
      (OpenAI-compatible API under ``/v1``).
    - Ollama unreachable and legacy ``OPENAI_API_KEY`` set → OpenAI preset
      (backwards compatible with pre-0.3 behavior).
    - Otherwise raise :class:`LLMUnavailableError` with an actionable
      message (use ``--no-llm``, start Ollama, or configure a provider).

    A set-but-unused ``ANTHROPIC_API_KEY`` produces a logged warning: the
    native Anthropic API is not OpenAI-compatible, so it needs a compat
    proxy via ``--api-base`` (or the ``openrouter`` preset).
    """
    cfg = resolve_llm_config(
        model=model, provider=provider, api_base=api_base, api_key=api_key
    )

    if os.environ.get(ANTHROPIC_KEY_ENV_VAR) and not cfg.base_url:
        logger.warning(ANTHROPIC_NATIVE_TODO)

    if cfg.base_url:
        logger.info(
            "Using %s endpoint %s model=%s (key=%s)",
            cfg.provider,
            cfg.base_url,
            cfg.model,
            redact_key(cfg.api_key),
        )
        return OpenAICompatibleBackend(
            base_url=cfg.base_url,
            model=cfg.model,
            api_key=cfg.api_key,
            timeout=timeout,
            provider=cfg.provider,
        )

    if is_ollama_reachable(DEFAULT_OLLAMA_BASE):
        logger.info(
            "Using default Ollama backend %s model=%s",
            DEFAULT_OLLAMA_API_BASE,
            cfg.model,
        )
        return OpenAICompatibleBackend(
            base_url=DEFAULT_OLLAMA_API_BASE,
            model=cfg.model,
            timeout=timeout,
            provider="ollama",
        )

    legacy_key = os.environ.get(OPENAI_KEY_ENV_VAR)
    if legacy_key:
        logger.info(
            "Ollama unreachable; falling back to OpenAI via OPENAI_API_KEY"
        )
        return OpenAICompatibleBackend(
            base_url=PROVIDER_PRESETS["openai"],
            model=cfg.model,
            api_key=legacy_key,
            timeout=timeout,
            provider="openai",
        )

    raise LLMUnavailableError(
        "No LLM endpoint available: could not reach Ollama at "
        f"{DEFAULT_OLLAMA_BASE}, and no hosted provider is configured.\n\n"
        "Options:\n"
        "  - Extract without an LLM: run with --no-llm\n"
        f"  - Start a local Ollama server (e.g. `ollama serve`) at {DEFAULT_OLLAMA_BASE},\n"
        "    then retry\n"
        "  - Use any hosted model via a provider preset:\n"
        "      export OKFSMITH_API_KEY=...\n"
        "      export OKFSMITH_PROVIDER=openrouter   # one key -> many models\n"
        "      okfsmith ingest ./kb docs/ --model anthropic/claude-sonnet-4\n"
        "    (flags work too: --provider groq --api-key ... --model ...)\n"
        f"    Presets: {', '.join(sorted(PROVIDER_PRESETS))}.\n"
        "    Anything else: --api-base https://your-endpoint/v1"
    )
