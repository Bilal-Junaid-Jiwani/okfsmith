"""Background job manager for the dashboard.

Jobs run in a shared :class:`ThreadPoolExecutor`; each job owns a registry
record plus an ordered SSE event log. Workers push step events through
:meth:`Job.emit`; the SSE endpoint replays the log then tails it until the
job reaches a terminal state. Steps always reflect real stage transitions
performed by the worker — this module never invents progress.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


TERMINAL_STATUSES = {"done", "error"}

#: Upper bound on retained job records. Active jobs are never evicted;
#: terminal ones are dropped oldest-first so the in-memory registry cannot
#: grow without bound over a long dashboard session.
MAX_RETAINED_JOBS = 200


@dataclass
class Job:
    """One background job: ingest, sync run, eval run, or validate run."""

    job_id: str
    kind: str  # "ingest" | "sync" | "eval" | "validate"
    bundle_id: str | None
    status: str = "queued"  # queued|running|done|error
    detail: str = ""
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(self, event: dict[str, Any]) -> None:
        """Append an SSE event and wake any streaming readers."""
        with self._lock:
            self.events.append(event)
        self._queue.put(event)

    def set_step(self, name: str, state: str, detail: str = "") -> None:
        """Record a step transition and emit it as an SSE event.

        Transitions into ``running`` stamp ``started_at``; transitions into a
        terminal step state (``done``/``error``) stamp ``finished_at`` and the
        elapsed seconds, so the pipeline UI can show real per-step timing.
        """
        now = utc_now_iso()
        for step in self.steps:
            if step["name"] == name:
                if state == "running" and not step.get("started_at"):
                    step["started_at"] = now
                if state in ("done", "error"):
                    if not step.get("started_at"):
                        step["started_at"] = now
                    step["finished_at"] = now
                    try:
                        start = datetime.fromisoformat(step["started_at"])
                        end = datetime.fromisoformat(step["finished_at"])
                        step["elapsed"] = round((end - start).total_seconds(), 2)
                    except (ValueError, TypeError):
                        pass
                step["state"] = state
                step["detail"] = detail
                break
        else:
            step = {"name": name, "state": state, "detail": detail}
            if state == "running":
                step["started_at"] = now
            if state in ("done", "error"):
                step["started_at"] = step.get("started_at", now)
                step["finished_at"] = now
            self.steps.append(step)
        self.emit({"step": name, "state": state, "detail": detail,
                   "started_at": step.get("started_at"),
                   "finished_at": step.get("finished_at"),
                   "elapsed": step.get("elapsed")})

    def finish(self, status: str, detail: str = "", error: str | None = None) -> None:
        # The terminal event and the status flip happen atomically under the
        # job lock: the SSE endpoint snapshots (events, terminal-flag) under
        # the same lock, so a fast-finishing job can never slip its closing
        # {"status": ...} frame past a reader. Status is the publication flag
        # and therefore goes last inside the critical section.
        with self._lock:
            self.detail = detail
            self.error = error
            self.finished_at = utc_now_iso()
            # Any step still pending/running is closed out honestly: the job is
            # over, so remaining steps did not happen.
            for step in self.steps:
                if step["state"] in ("pending", "running"):
                    step["state"] = "done" if status == "done" else "error"
                    if not step["detail"]:
                        step["detail"] = "not reached" if status == "done" else (error or "")
            self.events.append({"status": status})
            self.status = status
        self._queue.put({"status": status})
        self._queue.put(None)  # sentinel: wake streamers, job is terminal


class JobManager:
    """Thread-safe registry + worker pool for background jobs."""

    def __init__(self, max_workers: int = 4) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="dashboard-job"
        )

    def submit(
        self,
        kind: str,
        bundle_id: str | None,
        fn: Callable[[Job], None],
        *,
        step_names: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex[:12],
            kind=kind,
            bundle_id=bundle_id,
            steps=[
                {"name": name, "state": "pending", "detail": ""}
                for name in (step_names or [])
            ],
            extra=dict(extra or {}),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._evict_terminal_locked()
        self._pool.submit(self._run, job, fn)
        return job

    def _evict_terminal_locked(self) -> None:
        """Drop oldest terminal jobs past the cap. Caller holds ``_lock``.

        Active (queued/running) jobs are never evicted — readers may still
        be tailing their SSE streams.
        """
        if len(self._jobs) <= MAX_RETAINED_JOBS:
            return
        terminal = sorted(
            (j for j in self._jobs.values() if j.status in TERMINAL_STATUSES),
            key=lambda j: (j.finished_at or j.created_at),
        )
        for old in terminal[: len(self._jobs) - MAX_RETAINED_JOBS]:
            del self._jobs[old.job_id]

    def _run(self, job: Job, fn: Callable[[Job], None]) -> None:
        job.status = "running"
        job.started_at = utc_now_iso()
        try:
            fn(job)
        except Exception as exc:  # never leak tracebacks to API consumers
            job.finish("error", detail=str(exc)[:500], error=str(exc)[:500])
        finally:
            # Keep the registry bounded even when no further jobs are
            # submitted: trim terminal jobs right after each completion.
            with self._lock:
                self._evict_terminal_locked()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if kind is not None:
            jobs = [j for j in jobs if j.kind == kind]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def wait_for_event(self, job: Job, timeout: float) -> dict[str, Any] | None:
        """Block up to *timeout* seconds for the next SSE event (None = none)."""
        try:
            return job._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def sse_format(event: dict[str, Any]) -> str:
    """Render one event as an SSE data frame."""
    import json

    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def new_id(prefix: str = "") -> str:
    stamp = f"{time.time_ns():x}"
    return f"{prefix}{uuid.uuid4().hex[:8]}{stamp[-6:]}"
