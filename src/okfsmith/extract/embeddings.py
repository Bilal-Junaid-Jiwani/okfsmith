"""okfsmith.extract.embeddings — hosted text embedders for duplicate detection.

The ingest pipeline resolves duplicates in precedence order: exact
normalized title, same-resource gating, then stemmed-token title
similarity (:func:`okfsmith.extract.pipeline.title_similarity`) — the
dependency-free, deterministic, offline-safe default. An optional
embedding layer sits *after* those cheap checks and catches the
paraphrases token overlap misses: "How to sync your vault" vs "Vault
synchronization guide" share almost no stemmed tokens but are
near-identical in embedding space.

:class:`OpenAIEmbedder` speaks any OpenAI-compatible ``/embeddings``
endpoint (OpenAI, OpenRouter, Together, self-hosted vLLM, …):
``--embeddings openai`` (or another provider preset, or
``OKFSMITH_EMBEDDINGS``). It honors the same security rules as the
chat backends: an API key is never sent over cleartext ``http://`` to
a non-loopback host, the legacy ``OPENAI_API_KEY`` is only honored
for the ``openai`` provider, and ``__repr__`` never includes
credentials.
"""

from __future__ import annotations

import logging
import math
import time
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

import httpx

from .llm import (
    OPENAI_KEY_ENV_VAR,
    PROVIDER_PRESETS,
    _env_get,
    _is_local_url,
    _owned_clients,
    redact_key,
)

logger = logging.getLogger(__name__)

#: Default hosted embedding model for :class:`OpenAIEmbedder`.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

#: Timeout (seconds) for ``/embeddings`` calls.
EMBED_TIMEOUT = 60.0

#: Env var selecting the embedder: an OpenAI-compatible provider preset
#: (see :func:`resolve_embedder`).
EMBEDDINGS_ENV_VAR = "OKFSMITH_EMBEDDINGS"

#: Env var overriding the hosted embedding model.
EMBEDDING_MODEL_ENV_VAR = "OKFSMITH_EMBEDDING_MODEL"

#: Per-text character budget before embedding: bounds request size and
#: hosted cost. Titles are always kept whole; bodies are truncated.
_MAX_EMBED_CHARS = 4000


class EmbeddingError(Exception):
    """Base class for all embedding errors."""


class EmbeddingUnavailableError(EmbeddingError):
    """No usable embeddings endpoint: no key configured and no local base.

    Raised *before* any extraction work starts, with an actionable
    message — mirroring :class:`LLMUnavailableError` semantics.
    """


class EmbeddingResponseError(EmbeddingError):
    """The endpoint answered, but the response was unusable."""


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (0.0–1.0 for normalized inputs).

    Pure function. A zero vector (e.g. embedded empty text) scores 0.0
    against everything — it can never trigger a merge. The result is
    clamped to [-1.0, 1.0] against float drift.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def embed_text(title: str, body: str) -> str:
    """Build the text an embedder sees for a concept: title + body.

    The title is always kept whole (it carries the most signal for
    duplicate detection); the body is truncated to
    :data:`_MAX_EMBED_CHARS` to bound request size and hosted cost.
    """
    text = f"{(title or '').strip()}\n{(body or '').strip()}".strip()
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    return text


class Embedder(ABC):
    """Abstract text embedder. Subclass and implement :meth:`embed`."""

    #: Display name (``"openai"``, …).
    name = "base"

    #: Cosine similarity at/above which a candidate counts as a
    #: duplicate of the incoming concept.
    merge_threshold = 0.87

    def __init__(self) -> None:
        self._owned_client: httpx.Client | None = None

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts*, returning one vector per text, in order."""

    def close(self) -> None:
        """Close the lazily-created client, if any. Safe to repeat."""
        client, self._owned_client = self._owned_client, None
        if client is not None:
            _owned_clients.discard(client)
            client.close()

    def __enter__(self) -> Embedder:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class OpenAIEmbedder(Embedder):
    """Embeddings from any OpenAI-compatible ``/embeddings`` endpoint.

    ``base_url`` is the full API base (e.g.
    ``https://api.openai.com/v1`` — the embedder appends only
    ``/embeddings``). ``api_key`` may be ``None``/empty for local
    endpoints that need no auth. A prebuilt :class:`httpx.Client` can
    be injected (tests use a mock transport); otherwise one is created
    lazily and reused across calls.

    Security mirrors :class:`OpenAICompatibleBackend`: a key is never
    sent over cleartext ``http://`` to a non-loopback host.
    """

    name = "openai"
    merge_threshold = 0.87

    def __init__(
        self,
        base_url: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        api_key: str | None = None,
        timeout: float = EMBED_TIMEOUT,
        client: httpx.Client | None = None,
        provider: str = "openai",
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        if self._api_key and not _is_local_url(self.base_url):
            if urlsplit(self.base_url).scheme.lower() == "http":
                raise EmbeddingError(
                    "Refusing to send an API key over cleartext http:// to "
                    f"{urlsplit(self.base_url).hostname!r}. Use https://, "
                    "a localhost endpoint, or omit the key."
                )
        self._client = client  # injected: owned by the caller, never closed here
        self._timeout = timeout
        self.provider = provider

    @property
    def has_key(self) -> bool:
        """Whether an API key is configured (never exposes the value)."""
        return bool(self._api_key)

    def _embeddings_url(self) -> str:
        return self.base_url.rstrip("/") + "/embeddings"

    def _client_or_new(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.Client(timeout=self._timeout)
            _owned_clients.add(self._owned_client)
        return self._owned_client

    def _post_once(self, texts: list[str]) -> list[list[float]]:
        url = self._embeddings_url()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"model": self.model, "input": texts}
        logger.debug(
            "POST %s model=%s n=%d (key=%s)",
            url,
            self.model,
            len(texts),
            redact_key(self._api_key),
        )
        try:
            response = self._client_or_new().post(url, json=payload, headers=headers)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise EmbeddingResponseError(
                f"Embeddings endpoint {self.base_url} unreachable: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code >= 400:
            body = response.text[:500]
            raise EmbeddingResponseError(
                f"Embeddings endpoint {self.base_url} returned HTTP "
                f"{response.status_code}: {body}"
            )
        try:
            data = response.json()
            items = data["data"]
            ordered = sorted(items, key=lambda d: d["index"])
            vectors = [item["embedding"] for item in ordered]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise EmbeddingResponseError(
                f"Embeddings endpoint {self.base_url} returned a malformed "
                f"embeddings payload: {exc}"
            ) from exc
        if len(vectors) != len(texts) or not all(
            isinstance(v, list)
            and v
            and all(isinstance(x, (int, float)) for x in v)
            for v in vectors
        ):
            raise EmbeddingResponseError(
                f"Embeddings endpoint {self.base_url} returned "
                f"{len(vectors)} embedding(s) for {len(texts)} input(s), "
                "or a non-numeric vector."
            )
        return [[float(x) for x in v] for v in vectors]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* via ``POST {base}/embeddings``, one vector each.

        Transient failures (HTTP 5xx, timeouts, malformed payloads) are
        retried with exponential backoff; configuration errors
        (:class:`EmbeddingUnavailableError`) fail fast.
        """
        if not texts:
            return []
        last_error: EmbeddingError | None = None
        for attempt in range(1, 4):
            try:
                return self._post_once(texts)
            except EmbeddingUnavailableError:
                raise
            except EmbeddingError as exc:
                last_error = exc
                if attempt == 3:
                    break
                delay = min(30.0, 1.0 * 2 ** (attempt - 1))
                logger.warning(
                    "Embeddings attempt %d/3 failed (%s: %s); retrying in %.2fs",
                    attempt,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def __repr__(self) -> str:  # never includes credentials
        return (
            f"OpenAIEmbedder(base_url={self.base_url!r}, "
            f"model={self.model!r}, provider={self.provider!r}, "
            f"key={redact_key(self._api_key)})"
        )


def resolve_embedder(
    spec: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> Embedder | None:
    """Pick the embedder for duplicate detection. Single source of truth.

    - ``spec`` (or the ``OKFSMITH_EMBEDDINGS`` env var): an
      OpenAI-compatible provider preset (``"openai"``,
      ``"openrouter"``, ``"together"``, …) for hosted embeddings.
    - ``None``/empty → ``None``: the pipeline keeps its current
      title-similarity behavior, fully offline.
    - The key comes from ``api_key``, then ``OKFSMITH_API_KEY``, then
      legacy ``OPENAI_API_KEY`` — the legacy key only when the provider
      is ``openai`` (same provider-scoping rule as the chat backends).
    - A preset without a usable key on a non-local base raises
      :class:`EmbeddingUnavailableError` with an actionable message.
    """
    raw = spec if spec is not None else _env_get(EMBEDDINGS_ENV_VAR)
    name = (raw or "").strip().lower()
    if not name:
        return None
    if name == "anthropic":
        raise EmbeddingError(
            "The 'anthropic' provider has no embeddings endpoint: use an "
            "OpenAI-compatible provider preset "
            f"({', '.join(sorted(p for p in PROVIDER_PRESETS if p != 'anthropic'))})."
        )
    if name not in PROVIDER_PRESETS:
        raise EmbeddingError(
            f"Unknown embeddings spec {raw!r}: use one of "
            f"{', '.join(sorted(PROVIDER_PRESETS))} "
            f"(or {EMBEDDINGS_ENV_VAR})."
        )
    base_url = PROVIDER_PRESETS[name]
    key: str | None
    key_source: str
    if api_key is not None:
        key, key_source = api_key, "explicit api_key"
    elif _env_get("OKFSMITH_API_KEY"):
        key, key_source = _env_get("OKFSMITH_API_KEY"), "OKFSMITH_API_KEY"
    elif name == "openai" and _env_get(OPENAI_KEY_ENV_VAR):
        # Legacy key, provider-scoped like the chat backends: it must
        # never leak into another provider's requests.
        key, key_source = _env_get(OPENAI_KEY_ENV_VAR), OPENAI_KEY_ENV_VAR
    else:
        key, key_source = None, "none"
    if not key and not _is_local_url(base_url):
        raise EmbeddingUnavailableError(
            f"No API key for embeddings provider {name!r}: set "
            "OKFSMITH_API_KEY (or pass an explicit key), or use a local "
            "embeddings endpoint."
        )
    resolved_model = model or _env_get(EMBEDDING_MODEL_ENV_VAR) or DEFAULT_EMBEDDING_MODEL
    logger.info(
        "Using %s embeddings %s model=%s (key: %s)",
        name,
        base_url,
        resolved_model,
        key_source,
    )
    return OpenAIEmbedder(
        base_url=base_url,
        model=resolved_model,
        api_key=key,
        provider=name,
    )
