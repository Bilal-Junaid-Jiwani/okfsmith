"""LLM provider abstraction for okfsmith extraction.

Default backend: local **Ollama** over its OpenAI-compatible API
(``POST http://localhost:11434/v1/chat/completions``). Any hosted model
works too: pick a ``--provider`` preset (OpenRouter, Groq, Mistral,
DeepSeek, Together, Fireworks, DeepInfra, Anyscale, Perplexity, xAI,
Gemini, OpenAI, Agent Router, LM Studio, Ollama, Anthropic) or point
``--api-base`` at any OpenAI-compatible endpoint (Azure OpenAI,
self-hosted vLLM, llama.cpp server, any compat proxy). Anthropic's
*native* Messages API is also supported directly: ``--provider anthropic``
(or just ``ANTHROPIC_API_KEY``) speaks ``POST
https://api.anthropic.com/v1/messages`` with no proxy in between.

Secrets discipline: API keys come from **environment variables** (or an
explicit ``--api-key`` flag) — never from files, never echoed into logs,
exceptions, or error messages (see :func:`redact_key` and
:func:`key_status`).

Network discipline: the only network calls in this package go to the
configured LLM endpoint. No other host is ever contacted.
"""

from __future__ import annotations

import atexit
import logging
import os
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Default Ollama host. The reachability probe hits ``/api/tags`` here;
#: the OpenAI-compatible API base is :data:`DEFAULT_OLLAMA_API_BASE`.
DEFAULT_OLLAMA_BASE = "http://localhost:11434"

#: Ollama's OpenAI-compatible API base (``/chat/completions`` is appended).
DEFAULT_OLLAMA_API_BASE = DEFAULT_OLLAMA_BASE + "/v1"

#: Env var overriding the default model.
MODEL_ENV_VAR = "OKFSMITH_MODEL"

#: Default model when neither an explicit model nor ``OKFSMITH_MODEL`` is set.
DEFAULT_MODEL = "qwen3:8b"

#: Default model for the ``anthropic`` provider preset (see
#: :data:`PROVIDER_PRESETS`): Anthropic's cheapest current Haiku, addressed
#: by its version-less alias so it tracks the latest snapshot.
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"

#: Anthropic's native Messages API base. :class:`AnthropicBackend` appends
#: ``/v1/messages``; ``--api-base`` may override the host for
#: Messages-API-compatible proxies.
ANTHROPIC_API_BASE = "https://api.anthropic.com"

#: API version header required by Anthropic's Messages API.
ANTHROPIC_API_VERSION = "2023-06-01"

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

#: Env var we notice and CAN now use natively: with no explicit provider or
#: base URL configured, a set ``ANTHROPIC_API_KEY`` selects the
#: ``anthropic`` provider preset (native Messages API backend). It is also
#: honored as the key for an explicit ``--provider anthropic`` /
#: ``OKFSMITH_PROVIDER=anthropic``.
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
    # The odd one out: Anthropic's native API is NOT OpenAI-compatible, so
    # the ``anthropic`` provider dispatches to :class:`AnthropicBackend`
    # (Messages API), never to the OpenAI-compatible backend — even though
    # it lives in this table so ``--provider`` validation, the dashboard
    # provider list, and doctor all stay uniform.
    "anthropic": "https://api.anthropic.com",
}

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


#: Owned httpx clients still open, for best-effort interpreter-exit cleanup.
#: A WeakSet so backends that were never closed() don't pin memory; the
#: atexit hook below closes whatever is left.
_owned_clients: weakref.WeakSet[httpx.Client] = weakref.WeakSet()


def _close_owned_clients() -> None:
    """Close any backend-owned httpx clients still open at interpreter exit."""
    for client in list(_owned_clients):
        try:
            client.close()
        except Exception:  # noqa: BLE001 - best-effort shutdown path
            pass


atexit.register(_close_owned_clients)


def retry_with_backoff(
    fn: Callable[..., T],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (LLMError,),
    **kwargs: Any,
) -> T:
    """Call ``fn(*args, **kwargs)``, retrying transient failures with backoff.

    Makes up to *attempts* total attempts (1 initial try + ``attempts - 1``
    retries). Between attempts it sleeps
    ``min(max_delay, base_delay * 2 ** (attempt - 1))`` seconds — plain
    exponential backoff, no jitter, so delays stay deterministic and testable.

    Extra positional/keyword arguments are passed straight through to *fn*,
    so ``retry_with_backoff(backend.chat, messages, temperature=0.0)`` works
    as well as ``retry_with_backoff(lambda: backend.chat(messages))``. The
    retry controls (*attempts*, *base_delay*, *max_delay*, *exceptions*) are
    keyword-only and never forwarded to *fn*.

    Only **transient** failures are retried:

    - An exception matching *exceptions* is retried, *except*
      :class:`LLMUnavailableError`, which means *no usable endpoint is
      configured* — retrying the same call cannot fix that, so it is
      re-raised immediately even when it matches *exceptions*.
    - Anything not matching *exceptions* (``ValueError``,
      ``KeyboardInterrupt``, …) propagates untouched. Retries are only for
      errors the caller explicitly marked retryable.

    Typical use: ``retry_with_backoff(backend.chat, messages)`` — an
    :class:`LLMResponseError` from a flaky transport (HTTP 5xx, timeout,
    connection reset, empty payload) may succeed on the next attempt, while
    a missing-endpoint config error fails fast.

    After *attempts* are exhausted the **last** error is re-raised, with its
    original traceback preserved.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except LLMUnavailableError:
            # Config problem, not a transient one: retrying is pointless.
            raise
        except exceptions as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = min(max_delay, base_delay * 2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d failed (%s: %s); retrying in %.2fs",
                attempt,
                attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last_error is not None  # attempts >= 1 guarantees a first failure
    raise last_error


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
    #: Full base URL the request path is appended to
    #: (``/chat/completions`` for OpenAI-compatible backends,
    #: ``/v1/messages`` for the Anthropic backend), or ``None`` for the
    #: default Ollama probing path.
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
    otherwise one is created lazily per backend and reused across calls —
    close it with :meth:`close` or by using the backend as a context
    manager (a best-effort atexit hook also closes clients of backends
    that were never closed explicitly).

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
        self._client = client  # injected: owned by the caller, never closed here
        self._owned_client: httpx.Client | None = None  # lazily created, reused
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
        """Return the injected client, else a lazily-created instance client.

        The instance-owned client is created once and reused across
        ``chat()`` calls (no per-call client churn, no connection-pool
        leak). It is closed by :meth:`close`, by using the backend as a
        context manager, or — best effort — at interpreter exit. An injected
        client is owned by the caller and is never closed here.
        """
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.Client(timeout=self._timeout)
            _owned_clients.add(self._owned_client)
        return self._owned_client

    def close(self) -> None:
        """Close the lazily-created client, if any.

        An injected client is owned by the caller and is never closed here.
        Safe to call more than once.
        """
        client, self._owned_client = self._owned_client, None
        if client is not None:
            _owned_clients.discard(client)
            client.close()

    def __enter__(self) -> OpenAICompatibleBackend:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

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
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # httpx.InvalidURL is NOT an HTTPError subclass: it escapes e.g.
            # as "Invalid port: ':1]'" from an unparseable proxy env var —
            # including at client-construction time inside _client_or_new().
            # Catch it here so every transport failure surfaces as LLMError.
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
        if not isinstance(content, str):
            raise LLMResponseError(
                f"LLM endpoint {self.base_url} returned a non-string "
                f"chat-completion content: {type(content).__name__}"
            )
        # Empty/whitespace content is returned as-is, not raised: the
        # pipeline's JSON-parse → repair → needs-review fallback path treats
        # it exactly like any other unparseable reply, consistent with stub
        # backends (e.g. FakeBackend) that return "".
        return content


class AnthropicBackend(LLMBackend):
    """Anthropic's native Messages API (``POST .../v1/messages``).

    Anthropic is the one provider preset that is NOT OpenAI-compatible, so
    it gets its own backend instead of :class:`OpenAICompatibleBackend`:

    - auth via the ``x-api-key`` header (never ``Authorization: Bearer``),
    - the required ``anthropic-version`` header,
    - ``system`` messages hoisted out of the message list into the
      top-level ``system`` parameter (the Messages API rejects a
      ``"role": "system"`` entry inside ``messages``),
    - consecutive same-role messages merged (the API requires strict
      user/assistant alternation),
    - the reply parsed from the ``content`` block list (text blocks
      concatenated, in order).

    ``base_url`` is the API host (default :data:`ANTHROPIC_API_BASE`); the
    backend appends ``/v1/messages``. A prebuilt :class:`httpx.Client` can
    be injected (tests use a mock transport); otherwise one is created
    lazily and reused, closed by :meth:`close`, the context-manager
    protocol, or the module's atexit hook. ``provider`` is fixed to
    ``"anthropic"`` — it is a display label for chat banners/doctor, set
    here (rather than only on the config) so a hand-built backend still
    renders correctly.
    """

    name = "anthropic"
    provider = "anthropic"

    def __init__(
        self,
        base_url: str = ANTHROPIC_API_BASE,
        model: str = DEFAULT_ANTHROPIC_MODEL,
        api_key: str | None = None,
        timeout: float = CHAT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(model)
        self.base_url = (base_url or ANTHROPIC_API_BASE).rstrip("/")
        self._api_key = api_key  # never logged; never serialized
        self._client = client  # injected: owned by the caller, never closed here
        self._owned_client: httpx.Client | None = None  # lazily created, reused
        self._timeout = timeout

    @property
    def has_key(self) -> bool:
        """Whether an API key is configured (never exposes the value)."""
        return bool(self._api_key)

    def _messages_url(self) -> str:
        return self.base_url.rstrip("/") + "/v1/messages"

    def _client_or_new(self) -> httpx.Client:
        """Return the injected client, else a lazily-created instance client.

        Same ownership contract as :class:`OpenAICompatibleBackend`:
        instance-owned clients are created once, reused across ``chat()``
        calls, and closed by :meth:`close` / the context manager / atexit.
        """
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.Client(timeout=self._timeout)
            _owned_clients.add(self._owned_client)
        return self._owned_client

    def close(self) -> None:
        """Close the lazily-created client, if any.

        An injected client is owned by the caller and is never closed here.
        Safe to call more than once.
        """
        client, self._owned_client = self._owned_client, None
        if client is not None:
            _owned_clients.discard(client)
            client.close()

    def __enter__(self) -> AnthropicBackend:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @staticmethod
    def _split_messages(
        messages: list[dict],
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Hoist ``system`` messages and merge consecutive same-role turns.

        Returns ``(system, turns)`` where ``system`` is the concatenated
        system prompt (or ``None``) and ``turns`` is the remaining
        user/assistant message list with strict alternation restored.
        Raises :class:`LLMResponseError` for malformed input (empty list,
        non-string content, or a role the Messages API cannot carry).
        """
        if not messages:
            raise LLMResponseError("no messages to send to the Anthropic API")
        system_parts: list[str] = []
        turns: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if not isinstance(content, str):
                raise LLMResponseError(
                    "Anthropic backend expects string message content, got "
                    f"{type(content).__name__} for role {role!r}"
                )
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                if turns and turns[-1]["role"] == role:
                    # The Messages API requires strict alternation; merge
                    # rather than fail on adapter-produced repeats.
                    turns[-1]["content"] += "\n\n" + content
                else:
                    turns.append({"role": role, "content": content})
            else:
                raise LLMResponseError(
                    f"Anthropic backend cannot carry role {role!r}: "
                    "only 'system', 'user', and 'assistant' are supported"
                )
        if not turns:
            raise LLMResponseError(
                "no user/assistant messages to send to the Anthropic API"
            )
        system = "\n\n".join(system_parts) if system_parts else None
        return system, turns

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        if not self._api_key:
            raise LLMError(
                "Anthropic backend has no API key: set ANTHROPIC_API_KEY, "
                "OKFSMITH_API_KEY, or pass --api-key."
            )
        system, turns = self._split_messages(messages)
        url = self._messages_url()
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": turns,
        }
        if temperature != 0.0:
            # Anthropic defaults temperature to 1.0; only send it when the
            # caller actually wants non-deterministic sampling. okfsmith's
            # extraction path always calls with temperature=0.0.
            payload["temperature"] = temperature
        if system:
            payload["system"] = system
        logger.debug(
            "POST %s model=%s (key=%s)",
            url,
            self.model,
            redact_key(self._api_key),
        )
        try:
            response = self._client_or_new().post(url, json=payload, headers=headers)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise LLMResponseError(
                f"Anthropic endpoint {self.base_url} unreachable: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            try:
                err = response.json().get("error", {})
                if isinstance(err, dict) and err.get("message"):
                    detail = str(err["message"])[:500]
            except (ValueError, AttributeError):
                pass
            raise LLMResponseError(
                f"Anthropic endpoint {self.base_url} returned HTTP "
                f"{response.status_code}: {detail}"
            )
        try:
            data = response.json()
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise TypeError("content is not a list")
            text = "".join(
                block.get("text", "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LLMResponseError(
                f"Anthropic endpoint {self.base_url} returned a malformed "
                f"messages payload: {exc}"
            ) from exc
        # Empty text is returned as-is, not raised — same contract as
        # OpenAICompatibleBackend: the pipeline's JSON-parse → repair →
        # needs-review fallback path handles it.
        return text


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

    - provider: ``--provider`` → ``OKFSMITH_PROVIDER`` → implied
      ``"anthropic"`` when ``ANTHROPIC_API_KEY`` is set and no provider or
      base URL is configured (the native Messages API needs no proxy).
    - base URL: ``--api-base`` → ``OKFSMITH_API_BASE`` → ``OKFSMITH_BASE_URL``
      (legacy alias) → ``OPENAI_BASE_URL`` (legacy) → the provider preset.
      Custom bases are normalized by :func:`_normalize_custom_base`
      (bare hosts gain ``/v1``); OpenAI-compatible backends append
      ``/chat/completions``, the Anthropic backend appends ``/v1/messages``.
    - key: ``--api-key`` → ``OKFSMITH_API_KEY`` → ``AGENTROUTER_API_KEY``
      (only when the provider is ``agentrouter``) → ``ANTHROPIC_API_KEY``
      (only when the provider is ``anthropic``) → ``OPENAI_API_KEY``
      (legacy)
    - model: ``--model`` → ``OKFSMITH_MODEL`` → built-in default
      (``claude-haiku-4-5`` for the ``anthropic`` provider, ``qwen3:8b``
      otherwise)

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
    if not provider_name and not custom_base and os.environ.get(ANTHROPIC_KEY_ENV_VAR):
        # No explicit provider or base, but an Anthropic key is configured:
        # speak the native Messages API directly (no proxy needed).
        provider_name = "anthropic"
    # The anthropic provider speaks the native Messages API: its base is
    # the API *host* and the backend appends ``/v1/messages`` itself, so
    # the OpenAI-compat bare-host ``/v1`` rule must not apply — whether the
    # provider was chosen explicitly, implied by ANTHROPIC_API_KEY, or
    # inferred from a base pointing at the Anthropic host.
    anthropic_wire = provider_name == "anthropic" or (
        not provider_name
        and bool(custom_base)
        and _preset_name_for_base(custom_base.strip().rstrip("/")) == "anthropic"  # type: ignore[union-attr]
    )
    if custom_base:
        base_url: str | None = (
            custom_base.strip().rstrip("/")
            if anthropic_wire
            else _normalize_custom_base(custom_base)
        )
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
    elif label == "anthropic" and os.environ.get(ANTHROPIC_KEY_ENV_VAR):
        # Provider-scoped, same rationale: ANTHROPIC_API_KEY is the native
        # credential for the anthropic provider only.
        key, key_source = os.environ[ANTHROPIC_KEY_ENV_VAR], ANTHROPIC_KEY_ENV_VAR
    elif os.environ.get(OPENAI_KEY_ENV_VAR):
        key, key_source = os.environ[OPENAI_KEY_ENV_VAR], OPENAI_KEY_ENV_VAR
    else:
        key, key_source = None, "none"

    default_model = (
        DEFAULT_ANTHROPIC_MODEL if label == "anthropic" else DEFAULT_MODEL
    )
    resolved_model = model or os.environ.get(MODEL_ENV_VAR) or default_model

    return LLMConfig(
        provider=label,
        base_url=base_url,
        model=resolved_model,
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

    - Explicit provider / base URL (flags or ``OKFSMITH_*`` env) → the
      matching backend: :class:`AnthropicBackend` for the ``anthropic``
      provider (native Messages API), :class:`OpenAICompatibleBackend`
      for everything else. The key comes from ``--api-key``,
      ``OKFSMITH_API_KEY``, ``ANTHROPIC_API_KEY`` (anthropic provider
      only), ``AGENTROUTER_API_KEY`` (agentrouter only), or legacy
      ``OPENAI_API_KEY``. Local endpoints may omit the key entirely.
    - ``ANTHROPIC_API_KEY`` set with no explicit provider or base URL →
      native Anthropic backend (no proxy needed).
    - Nothing configured → default Ollama at ``http://localhost:11434``
      (OpenAI-compatible API under ``/v1``).
    - Ollama unreachable and legacy ``OPENAI_API_KEY`` set → OpenAI preset
      (backwards compatible with pre-0.3 behavior).
    - Otherwise raise :class:`LLMUnavailableError` with an actionable
      message (use ``--no-llm``, start Ollama, or configure a provider).
    """
    cfg = resolve_llm_config(
        model=model, provider=provider, api_base=api_base, api_key=api_key
    )

    if cfg.provider == "anthropic":
        if not cfg.api_key:
            raise LLMError(
                "Anthropic provider selected but no API key is configured: "
                "set ANTHROPIC_API_KEY (or OKFSMITH_API_KEY, or pass "
                "--api-key)."
            )
        logger.info(
            "Using native Anthropic backend %s model=%s (key=%s)",
            cfg.base_url,
            cfg.model,
            redact_key(cfg.api_key),
        )
        return AnthropicBackend(
            base_url=cfg.base_url or ANTHROPIC_API_BASE,
            model=cfg.model,
            api_key=cfg.api_key,
            timeout=timeout,
        )

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
        "    or use Anthropic's native API directly:\n"
        "      export ANTHROPIC_API_KEY=...\n"
        "      okfsmith ingest ./kb docs/            # --provider anthropic is implied\n"
        "    (flags work too: --provider groq --api-key ... --model ...)\n"
        f"    Presets: {', '.join(sorted(PROVIDER_PRESETS))}.\n"
        "    Anything else: --api-base https://your-endpoint/v1"
    )
