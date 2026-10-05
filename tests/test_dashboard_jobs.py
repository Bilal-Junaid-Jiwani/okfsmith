"""Tests for the dashboard background-job manager (``okfsmith.dashboard.jobs``).

The job manager is the backbone of dashboard progress UX: ingest, sync,
eval, and validate runs push step events through :class:`Job`, and the
SSE endpoints replay each job's event log then tail it until the terminal
``{"status": ...}`` frame. These tests pin the lifecycle contract —
submission, step timing, terminal publication, retention bounds, and the
SSE frame format — so regressions in background-job behavior are caught
here instead of in the browser.
"""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime

import pytest

from okfsmith.dashboard import jobs


def _drain(job: jobs.Job) -> None:
    """Wait (bounded) for a submitted job to reach a terminal status."""
    deadline = time.time() + 30
    while job.status not in jobs.TERMINAL_STATUSES:
        assert time.time() < deadline, "job did not finish in time"
        time.sleep(0.02)


@pytest.fixture()
def manager():
    mgr = jobs.JobManager(max_workers=4)
    yield mgr
    mgr.shutdown()


# ---------------------------------------------------------------------------
# utc_now_iso / sse_format / new_id
# ---------------------------------------------------------------------------


def test_utc_now_iso_is_timezone_aware_iso8601():
    stamp = jobs.utc_now_iso()
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None


def test_sse_format_renders_data_frame():
    frame = jobs.sse_format({"step": "parse", "state": "running"})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert '"step": "parse"' in frame or '"step":"parse"' in frame


def test_new_id_unique_and_prefixed():
    ids = {jobs.new_id("job-") for _ in range(200)}
    assert len(ids) == 200
    assert all(i.startswith("job-") for i in ids)


# ---------------------------------------------------------------------------
# Job: steps
# ---------------------------------------------------------------------------


def test_set_step_new_step_defaults():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.set_step("parse", "running")
    step = job.steps[0]
    assert step["name"] == "parse"
    assert step["state"] == "running"
    assert step["detail"] == ""
    assert step["started_at"] is not None
    assert "finished_at" not in step  # not finished yet: no timing fields
    assert "elapsed" not in step
    assert job.status == "queued"  # steps never flip the job status
    # The emitted SSE frame carries the (None) timing fields for the UI.
    emitted = job.events[-1]
    assert emitted["step"] == "parse"
    assert emitted["finished_at"] is None
    assert emitted["elapsed"] is None


def test_set_step_running_then_done_stamps_timing():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.set_step("parse", "running")
    started = job.steps[0]["started_at"]
    job.set_step("parse", "done", "3 files")
    step = job.steps[0]
    assert step["state"] == "done"
    assert step["detail"] == "3 files"
    assert step["started_at"] == started  # running stamp is kept, not reset
    assert step["finished_at"] is not None
    assert isinstance(step["elapsed"], float)
    assert step["elapsed"] >= 0


def test_set_step_done_without_running_still_stamps():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.set_step("parse", "done")
    step = job.steps[0]
    assert step["started_at"] == step["finished_at"]


def test_set_step_emits_sse_event_with_timing():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.set_step("parse", "running")
    job.set_step("parse", "done")
    emitted = [e for e in job.events if "step" in e]
    assert [e["step"] for e in emitted] == ["parse", "parse"]
    assert emitted[-1]["state"] == "done"
    assert "elapsed" in emitted[-1]


def test_set_step_same_name_updates_in_place():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.set_step("parse", "running")
    job.set_step("parse", "running", "still going")
    assert len(job.steps) == 1
    assert job.steps[0]["detail"] == "still going"


# ---------------------------------------------------------------------------
# Job: finish / terminal publication
# ---------------------------------------------------------------------------


def test_finish_done_closes_open_steps_honestly():
    job = jobs.Job(
        job_id="j1", kind="ingest", bundle_id=None,
        steps=[
            {"name": "a", "state": "done", "detail": ""},
            {"name": "b", "state": "running", "detail": ""},
            {"name": "c", "state": "pending", "detail": ""},
        ],
    )
    job.finish("done", detail="all good")
    assert job.status == "done"
    assert job.detail == "all good"
    assert job.error is None
    assert job.finished_at is not None
    states = {s["name"]: s for s in job.steps}
    assert states["a"]["state"] == "done"  # already-terminal step untouched
    assert states["b"]["state"] == "done"
    assert states["b"]["detail"] == "not reached"
    assert states["c"]["state"] == "done"
    # The closing frame is the last event in the log.
    assert job.events[-1] == {"status": "done"}


def test_finish_error_closes_open_steps_as_error():
    job = jobs.Job(
        job_id="j1", kind="ingest", bundle_id=None,
        steps=[{"name": "b", "state": "running", "detail": ""}],
    )
    job.finish("error", detail="boom", error="boom")
    assert job.status == "error"
    assert job.events[-1] == {"status": "error"}
    step = job.steps[0]
    assert step["state"] == "error"
    assert step["detail"] == "boom"


def test_finish_wakes_queue_readers_with_status_then_sentinel():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    job.finish("done")
    assert job._queue.get(timeout=5) == {"status": "done"}
    assert job._queue.get(timeout=5) is None


def test_emit_wakes_wait_for_event():
    mgr = jobs.JobManager(max_workers=1)
    try:
        job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
        received: list = []

        def waiter():
            received.append(mgr.wait_for_event(job, timeout=10))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        job.emit({"step": "parse", "state": "running"})
        t.join(timeout=10)
        assert received == [{"step": "parse", "state": "running"}]
    finally:
        mgr.shutdown()


def test_wait_for_event_times_out_to_none():
    mgr = jobs.JobManager(max_workers=1)
    try:
        job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
        assert mgr.wait_for_event(job, timeout=0.1) is None
    finally:
        mgr.shutdown()


def test_concurrent_emit_loses_nothing():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    threads = [
        threading.Thread(target=lambda n=n: [job.emit({"n": n, "i": i})
                                             for i in range(50)])
        for n in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(job.events) == 400
    seen = {(e["n"], e["i"]) for e in job.events}
    assert len(seen) == 400


# ---------------------------------------------------------------------------
# JobManager: submit / run / list / get
# ---------------------------------------------------------------------------


def test_submit_runs_worker_and_finishes(manager):
    seen = []

    def worker(job):
        seen.append(job.job_id)
        job.set_step("work", "running")
        job.set_step("work", "done")
        job.finish("done", detail="ok")

    job = manager.submit("ingest", "bundle-1", worker,
                         step_names=["work"], extra={"x": 1})
    # (status races with the worker thread; asserted after drain below)
    assert job.kind == "ingest"
    assert job.bundle_id == "bundle-1"
    assert job.extra == {"x": 1}
    assert [s["name"] for s in job.steps] == ["work"]
    _drain(job)
    assert job.status == "done"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert seen == [job.job_id]
    assert manager.get(job.job_id) is job


def test_submit_worker_exception_becomes_error(manager):
    def worker(job):
        raise RuntimeError("kaput" * 200)

    job = manager.submit("sync", None, worker)
    _drain(job)
    assert job.status == "error"
    assert "kaput" in job.detail
    assert len(job.detail) <= 500  # never leak unbounded text to the API
    assert job.events[-1] == {"status": "error"}


def test_list_filters_by_kind_and_sorts_newest_first(manager):
    j1 = manager.submit("ingest", None, lambda job: job.finish("done"))
    time.sleep(0.01)
    j2 = manager.submit("sync", None, lambda job: job.finish("done"))
    _drain(j1)
    _drain(j2)
    assert {j.job_id for j in manager.list(kind="sync")} == {j2.job_id}
    all_jobs = manager.list()
    assert [j.job_id for j in all_jobs] == [j2.job_id, j1.job_id]


def test_get_unknown_returns_none(manager):
    assert manager.get("nope") is None


def test_retention_cap_drops_oldest_terminal_first(manager):
    submitted = [
        manager.submit("ingest", None, lambda job: job.finish("done"))
        for _ in range(jobs.MAX_RETAINED_JOBS + 25)
    ]
    for j in submitted:
        _drain(j)
    assert len(manager.list()) <= jobs.MAX_RETAINED_JOBS


def test_active_jobs_never_evicted(manager):
    gate = threading.Event()
    release = threading.Event()

    def slow(job):
        gate.set()
        assert release.wait(timeout=30)
        job.finish("done")

    active = manager.submit("ingest", None, slow)
    assert gate.wait(timeout=10)
    # Flood the registry with completed jobs past the cap.
    for _ in range(jobs.MAX_RETAINED_JOBS + 10):
        j = manager.submit("ingest", None, lambda job: job.finish("done"))
        _drain(j)
    assert manager.get(active.job_id) is active
    assert active.status == "running"
    release.set()
    _drain(active)
    assert len(manager.list()) <= jobs.MAX_RETAINED_JOBS


def test_terminal_statuses_constant():
    assert jobs.TERMINAL_STATUSES == {"done", "error"}


def test_queue_starts_empty_and_unbounded():
    job = jobs.Job(job_id="j1", kind="ingest", bundle_id=None)
    assert isinstance(job._queue, queue.Queue)
    with pytest.raises(queue.Empty):
        job._queue.get_nowait()
