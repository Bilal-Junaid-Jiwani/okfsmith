"""Thread-safe dashboard settings store.

The ``PUT /api/v1/settings`` endpoint used to write provider config and
secrets directly into :data:`os.environ`. That is process-global mutable
state: a settings change made while a background job (ingest / sync /
eval) was running could flip the job's LLM endpoint or key mid-flight,
and mutating ``os.environ`` from request threads races with C-level
``getenv`` calls in worker threads.

This module replaces that with a :class:`DashboardSettings` object kept on
``app.state``. All mutations hold a :class:`threading.Lock`; readers take
an immutable snapshot. Background jobs capture a snapshot at submit time
(see :func:`okfsmith.extract.llm.job_env_overlay`), so a later settings
change can never affect an in-flight job.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping


class DashboardSettings:
    """Lock-protected key/value overrides for LLM provider settings.

    Keys are environment-variable names (``OKFSMITH_PROVIDER``,
    ``OKFSMITH_API_KEY``, ...). Values are strings; a ``None`` value
    removes an override. Reads via :meth:`snapshot` return a plain dict
    copy that the caller may keep without holding the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[str, str] = {}

    def update(self, values: Mapping[str, str | None]) -> None:
        """Apply overrides; ``None`` values delete the override."""
        with self._lock:
            for key, value in values.items():
                if value is None:
                    self._overrides.pop(str(key), None)
                else:
                    self._overrides[str(key)] = str(value)

    def get(self, name: str) -> str | None:
        """Return the override for *name*, or ``None`` if unset."""
        with self._lock:
            return self._overrides.get(name)

    def snapshot(self) -> dict[str, str]:
        """Return an immutable-feeling copy of current overrides."""
        with self._lock:
            return dict(self._overrides)

    def clear(self) -> None:
        """Remove all overrides (used by tests)."""
        with self._lock:
            self._overrides.clear()
