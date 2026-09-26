"""LLM provider abstraction for okfsmith extraction.

Default backend: local **Ollama** over its OpenAI-compatible API
(``POST {base}/v1/chat/completions``, default base
``http://localhost:11434``). Any other OpenAI-compatible endpoint works via
``base_url`` / ``api_key``. Anthropic *native* is not wired in v1 — see
:mod:`okfsmith.extract` and :data:`ANTHROPIC_NATIVE_TODO`.

Secrets discipline: API keys come from **environment variables only** — never
from files, never echoed into logs, exceptions, or error messages (see
:func:`redact_key`).

Network discipline: the only network calls in this package go to the
configured LLM endpoint. No other host is ever contacted.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

#: Default Ollama base URL (its OpenAI-compatible API lives under ``/v1``).
DEFAULT_OLLAMA_BASE = "http://localhost:11434"

#: Env var overriding the default model.
MODEL_ENV_VAR = "OKFSMITH_MODEL"

#: Default model when neither an explicit model nor ``OKFSMITH_MODEL`` is set.
DEFAULT_MODEL = "qwen3:8b"

#: Env vars accepted for hosted OpenAI-compatible endpoints.
OPENAI_KEY_ENV_VAR = "OPENAI_API_KEY"

#: Env var we notice but cannot use natively yet (v1 wires OpenAI-compatible
#: endpoints only; the user can still point ``--base-url`` at a compatible
#: gateway).
ANTHROPIC_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

#: Logged once when an Anthropic key is present but no explicit base URL is
#: given: native Anthropic calls are a v1 TODO.
ANTHROPIC_NATIVE_TODO = (
    "ANTHROPIC_API_KEY is set, but Anthropic-native calls are not wired in "
    "v1 (TODO). Falling back to the default Ollama endpoint; point --base-url "
    "at an OpenAI-compatible endpoint to use a hosted model."
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
    """Any OpenAI-compatible ``/v1/chat/completions`` endpoint (incl. Ollama).

    ``api_key`` may be ``None``/empty for local endpoints that need no auth.
    A prebuilt :class:`httpx.Client` can be injected (tests use a mock
    transport); otherwise one is created per backend.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = CHAT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key  # never logged; never serialized
        self._client = client
        self._timeout = timeout

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
        url = f"{self.base_url}/v1/chat/completions"
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


def resolve_backend(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = CHAT_TIMEOUT,
) -> LLMBackend:
    """Pick the LLM backend for an extraction run.

    - Explicit *base_url* → OpenAI-compatible backend; the key comes from
      *api_key* or the ``OPENAI_API_KEY`` env var (env only — never files).
      Local endpoints may omit the key entirely.
    - No *base_url* → default Ollama at ``http://localhost:11434``; if it is
      not reachable, raise :class:`LLMUnavailableError` with an actionable
      message (use ``--no-llm`` or start Ollama).

    A set-but-unused ``ANTHROPIC_API_KEY`` produces a logged TODO warning.
    """
    resolved_model = resolve_model(model)

    if os.environ.get(ANTHROPIC_KEY_ENV_VAR) and not base_url:
        logger.warning(ANTHROPIC_NATIVE_TODO)

    if base_url:
        key = api_key if api_key is not None else os.environ.get(OPENAI_KEY_ENV_VAR)
        logger.info(
            "Using OpenAI-compatible endpoint %s model=%s (key=%s)",
            base_url,
            resolved_model,
            redact_key(key),
        )
        return OpenAICompatibleBackend(
            base_url=base_url, model=resolved_model, api_key=key, timeout=timeout
        )

    if not is_ollama_reachable(DEFAULT_OLLAMA_BASE):
        raise LLMUnavailableError(
            "No LLM endpoint available: could not reach Ollama at "
            f"{DEFAULT_OLLAMA_BASE}.\n\n"
            "Options:\n"
            "  - Extract without an LLM: run with --no-llm\n"
            f"  - Start a local Ollama server (e.g. `ollama serve`) at {DEFAULT_OLLAMA_BASE},\n"
            "    then retry\n"
            "  - Use a hosted OpenAI-compatible endpoint:\n"
            "      export OPENAI_API_KEY=... "
            "(or pass --api-key)\n"
            "      okfsmith extract --base-url https://your-endpoint/v1 "
            f"--model {resolved_model}"
        )
    logger.info(
        "Using default Ollama backend %s model=%s", DEFAULT_OLLAMA_BASE, resolved_model
    )
    return OpenAICompatibleBackend(
        base_url=DEFAULT_OLLAMA_BASE, model=resolved_model, timeout=timeout
    )
