"""Tests for the lock-protected dashboard settings store.

The ``PUT /api/v1/settings`` endpoint used to write provider config and
secrets directly into :data:`os.environ` (process-global mutable state —
a settings change could flip a running job's LLM endpoint mid-flight and
raced C-level ``getenv`` in worker threads). The 0.7.13 fix keeps
overrides in :class:`DashboardSettings` on ``app.state`` instead.

These tests pin the replacement's contract: reads never see a half-write,
``snapshot()`` hands out an isolated copy, ``None`` deletes an override,
and — the security invariant — ``os.environ`` is never mutated.
"""

from __future__ import annotations

import os
import threading

from okfsmith.dashboard.settings import DashboardSettings


def test_update_get_roundtrip():
    store = DashboardSettings()
    assert store.get("OKFSMITH_PROVIDER") is None
    store.update({"OKFSMITH_PROVIDER": "openai"})
    assert store.get("OKFSMITH_PROVIDER") == "openai"


def test_none_value_deletes_override():
    store = DashboardSettings()
    store.update({"OKFSMITH_API_KEY": "sk-secret"})
    store.update({"OKFSMITH_API_KEY": None})
    assert store.get("OKFSMITH_API_KEY") is None
    assert store.snapshot() == {}


def test_clear_removes_all_overrides():
    store = DashboardSettings()
    store.update({"A": "1", "B": "2"})
    store.clear()
    assert store.snapshot() == {}
    assert store.get("A") is None


def test_snapshot_returns_isolated_copy():
    store = DashboardSettings()
    store.update({"OKFSMITH_PROVIDER": "gemini"})
    snap = store.snapshot()
    snap["OKFSMITH_PROVIDER"] = "tampered"
    snap["EVIL"] = "1"
    # The store itself is unaffected by mutating the snapshot.
    assert store.get("OKFSMITH_PROVIDER") == "gemini"
    assert store.get("EVIL") is None


def test_update_never_mutates_process_environment(monkeypatch):
    """The 0.7.13 security invariant: settings overrides stay in the store."""
    key = "OKFSMITH_TEST_SECRET_DO_NOT_READ"
    monkeypatch.delenv(key, raising=False)
    before = dict(os.environ)
    store = DashboardSettings()
    store.update({key: "sk-secret-value"})
    assert os.environ == before
    assert key not in os.environ
    # ...but the value is retrievable from the store itself.
    assert store.get(key) == "sk-secret-value"


def test_concurrent_updates_do_not_lose_or_raise():
    store = DashboardSettings()
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(200):
                store.update({f"KEY-{n}": str(i)})
                store.get(f"KEY-{n}")
                store.snapshot()
        except BaseException as exc:  # noqa: BLE001 - collected, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # Every worker's last write (i=199) must be visible.
    assert store.snapshot() == {f"KEY-{n}": "199" for n in range(8)}
