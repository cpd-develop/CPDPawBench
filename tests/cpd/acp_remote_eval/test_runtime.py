# -*- coding: utf-8 -*-
"""The always-on process: leases, the startup reconcile, and who writes the job row.

``test_runner.py`` covers what one run does.  This covers what the service does
*around* a run -- which process is allowed to run a job, what a restart does with
the rows the previous process left, and which status a job ends in when its tasks
are what they are.  None of that is visible from a single run, and all of it is
what an always-on service is judged on.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint
from pawbench.cpd.acp_remote_eval.service.config import ScheduleConfig
from pawbench.cpd.acp_remote_eval.service.queue import (
    JobQueue,
    QueueLimits,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from pawbench.cpd.acp_remote_eval.service.runner import (
    SKIP_DEADLINE,
    SKIP_LEASE_CONFLICT,
    SKIP_RESTART,
    SKIP_WINDOW_CLOSED,
    STATUS_MISSING,
    STATUS_SKIPPED,
)
from pawbench.cpd.acp_remote_eval.service.runtime import (
    EvalRuntime,
    ServeReport,
    default_owner_id,
    http_endpoint,
)
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import job_row

NOW = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)
LEASE_TTL = 90.0
ENDPOINT = AcpEndpoint.http("http://127.0.0.1:9000/rpc")


def schedule_config(**overrides: Any) -> ScheduleConfig:
    values: dict[str, Any] = {
        "timezone": "Asia/Shanghai",
        "tick_seconds": 5,
        "night_open": "00:00",
        "night_close": "07:00",
        "night_min_lead_seconds": 1800,
        "hard_stop": False,
        "custom_window_max_days": 7,
    }
    values.update(overrides)
    return ScheduleConfig(**values)


def _custom_window(opens_at: datetime, closes_at: datetime) -> dict[str, Any]:
    """The ``jobs`` columns for a bounded window, as the queue reads them."""
    return {
        "window_kind": "custom",
        "not_before": opens_at.isoformat(timespec="seconds"),
        "not_after": closes_at.isoformat(timespec="seconds"),
    }


def _job(
    store: Store,
    job_id: str,
    *,
    status: str = STATUS_QUEUED,
    submitter: str = "dev-1",
    window: dict[str, Any] | None = None,
    tasks: tuple[str, ...] = ("T001", "T002"),
) -> None:
    store.insert_job(job_row(job_id, status=status, submitter=submitter, **(window or {})))
    store.insert_job_tasks(
        [
            {"job_id": job_id, "task_id": task_id, "grading_type": "automated"}
            for task_id in tasks
        ]
    )


def _task(store: Store, job_id: str, task_id: str, **fields: Any) -> dict[str, Any]:
    store.update_job_task(job_id, task_id, 1, **fields)
    return store.get_job_task(job_id, task_id, 1) or {}


def _leases(store: Store, job_id: str = "job-1") -> list[dict[str, Any]]:
    return store.query(
        "SELECT owner, beat_at, ttl_seconds FROM job_leases WHERE job_id = ?", (job_id,)
    )


class _StubRunner:
    """The two things :class:`EvalRuntime` reads off a runner, without a run.

    ``run_job`` writes the task rows the real runner would have written and
    returns; ``blocks`` holds it there so cancellation has something to cancel.
    The run itself is ``test_runner.py`` and ``test_runner_e2e.py``'s business.
    """

    def __init__(
        self,
        store: Store,
        *,
        record: tuple[tuple[str, str, str], ...] = (("T001", STATUS_FINISHED, ""),),
        blocks: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.store = store
        self.record = record
        self.blocks = blocks
        self.error = error
        self.job_deadline_seconds = 7200.0
        self.calls: list[dict[str, Any]] = []

    async def run_job(
        self, job_id: str, *, endpoint: AcpEndpoint, attempt: int = 1, deadline_seconds: float | None = None
    ) -> Any:
        self.calls.append(
            {"job_id": job_id, "endpoint": endpoint, "deadline_seconds": deadline_seconds}
        )
        if self.error is not None:
            raise self.error
        for task_id, status, failure_reason in self.record:
            self.store.update_job_task(
                job_id, task_id, attempt, status=status, failure_reason=failure_reason
            )
        if self.blocks:
            await asyncio.Event().wait()
        return SimpleNamespace(job_id=job_id, tasks=[], by_status={}, artifact_count=0)


def _runtime(
    store: Store,
    runner: Any,
    *,
    owner: str = "proc-a",
    clock: FrozenClock | None = None,
    cfg: ScheduleConfig | None = None,
    lease_ttl_seconds: float = LEASE_TTL,
    tick_seconds: float = 5.0,
) -> EvalRuntime:
    shared = clock or FrozenClock(NOW)
    return EvalRuntime(
        store=store,
        queue=JobQueue(store, cfg or schedule_config(), QueueLimits(), shared),
        runner=runner,
        clock=shared,
        owner=owner,
        endpoint_for=lambda job: ENDPOINT,
        lease_ttl_seconds=lease_ttl_seconds,
        tick_seconds=tick_seconds,
    )


async def _settle(runtime: EvalRuntime, *, timeout: float = 2.0) -> None:
    """Wait until every run this process launched has written its rows."""
    until = time.monotonic() + timeout
    while runtime.running_jobs():
        assert time.monotonic() < until, f"still running: {runtime.running_jobs()}"
        await asyncio.sleep(0.01)


# ── launching, and the row a run leaves behind ────────────────────────────────


def test_a_started_job_is_run_and_closed_from_the_rows_it_left(store: Store) -> None:
    _job(store, "job-1")
    runner = _StubRunner(store)
    runtime = _runtime(store, runner)

    report = asyncio.run(_settle_after(runtime))

    assert report.launched == ["job-1"], "the queue's decision, not a hand-written row"
    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FINISHED, "")
    assert job["finished_at"]
    assert _leases(store) == [], "a finished job holds no lease"
    assert runner.calls == [
        {"job_id": "job-1", "endpoint": ENDPOINT, "deadline_seconds": 7200.0}
    ], "the configured wall clock is what the runner is asked for"


def test_a_run_that_raised_leaves_nothing_in_the_running_state(store: Store, caplog) -> None:
    """A crash mid-run must free the slot and say so on every row.

    Left ``running`` the job would hold one of the four global slots until the
    service restarted, and its tasks would read as a run still in progress.
    """
    _job(store, "job-1")
    runner = _StubRunner(store, record=(), error=RuntimeError("the transport died"))

    with caplog.at_level(logging.WARNING):
        asyncio.run(_settle_after(_runtime(store, runner)))

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, "job_failed")
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert [row["status"] for row in rows.values()] == [STATUS_SKIPPED, STATUS_SKIPPED]
    assert {row["failure_reason"] for row in rows.values()} == {"job_failed"}
    assert "job run raised" in caplog.text
    assert _leases(store) == []


def test_one_answer_is_enough_for_the_job_to_be_finished(store: Store) -> None:
    """A task timeout is a capability result; an outage is not.

    The distinction the report is read for: ``finished`` with a zero on one task
    means the agent was reached, ``failed`` means we never got an answer out of
    it and the score table must not carry it.
    """
    _job(store, "job-1")
    runner = _StubRunner(
        store,
        record=(("T001", STATUS_FINISHED, ""), ("T002", STATUS_FAILED, "timeout")),
    )

    asyncio.run(_settle_after(_runtime(store, runner)))

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FINISHED, "")


def test_a_job_of_only_missing_answers_still_counts_as_run(store: Store) -> None:
    """The agent answered and produced nothing: that is a result about it."""
    _job(store, "job-1", tasks=("T001",))
    runner = _StubRunner(store, record=(("T001", STATUS_MISSING, "no_artifacts"),))

    asyncio.run(_settle_after(_runtime(store, runner)))

    assert store.get_job("job-1")["status"] == STATUS_FINISHED


def test_a_job_where_nothing_was_exchanged_fails_with_the_first_reason(store: Store) -> None:
    _job(store, "job-1", tasks=("T001",))
    runner = _StubRunner(store, record=(("T001", STATUS_FAILED, "endpoint_unreachable"),))

    asyncio.run(_settle_after(_runtime(store, runner)))

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, "endpoint_unreachable")


async def _settle_after(runtime: EvalRuntime) -> ServeReport:
    """One pass, then wait for the runs it launched to write their rows."""
    report = await runtime.tick_once()
    await _settle(runtime)
    return report


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([(STATUS_FINISHED, "")], (STATUS_FINISHED, "")),
        ([(STATUS_MISSING, "no_artifacts")], (STATUS_FINISHED, "")),
        ([(STATUS_FAILED, "timeout"), (STATUS_FINISHED, "")], (STATUS_FINISHED, "")),
        ([(STATUS_FAILED, "endpoint_unreachable")], (STATUS_FAILED, "endpoint_unreachable")),
        ([(STATUS_SKIPPED, SKIP_DEADLINE)], (STATUS_FAILED, SKIP_DEADLINE)),
        ([], ("failed", "job_failed")),
    ],
)
def test_the_job_row_is_read_off_the_task_rows(
    rows: list[tuple[str, str]], expected: tuple[str, str]
) -> None:
    """The one rule every stop path shares, without a store or a loop."""
    tasks = [
        {"status": status, "failure_reason": reason} for status, reason in rows
    ]
    assert EvalRuntime.job_outcome(tasks) == expected


# ── restart ───────────────────────────────────────────────────────────────────


def test_startup_reconcile_settles_the_job_a_dead_process_left_running(store: Store) -> None:
    _job(store, "job-1", status=STATUS_RUNNING)
    _task(store, "job-1", "T001", status=STATUS_RUNNING)

    runtime = _runtime(store, _StubRunner(store))
    assert runtime.reconcile() == ["job-1"]

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, "recovered")
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert (rows["T001"]["status"], rows["T001"]["failure_reason"]) == (
        STATUS_FAILED,
        "recovered",
    )
    assert (rows["T002"]["status"], rows["T002"]["failure_reason"]) == (
        STATUS_SKIPPED,
        SKIP_RESTART,
    )
    assert _leases(store) == []
    assert runtime.reconcile() == [], "a settled job is not settled a second time"


def test_startup_reconcile_leaves_a_job_another_live_process_is_beating(store: Store) -> None:
    """The lease is what distinguishes a dead run from a slow one.

    Settling is not reversible -- it writes terminal rows -- so guessing here
    would fail a job that another service is running right now.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    store.acquire_lease("job-1", owner="proc-b", beat_at=NOW.isoformat(timespec="seconds"),
                        ttl_seconds=LEASE_TTL)

    assert _runtime(store, _StubRunner(store)).reconcile() == []
    assert store.get_job("job-1")["status"] == STATUS_RUNNING


def test_a_run_that_loses_its_lease_stops_rather_than_double_writes(store: Store) -> None:
    """A beat that no longer lands means somebody else believes it owns the job.

    Two processes writing one job's task rows is the failure the lease exists
    to prevent, so the half that lost the lease has to stop -- and must not take
    the new owner's row with it.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    runner = _StubRunner(store, record=(), blocks=True)
    runtime = _runtime(store, runner, lease_ttl_seconds=0.05)
    store.acquire_lease("job-1", owner="proc-a", beat_at=NOW.isoformat(timespec="seconds"),
                        ttl_seconds=0.05)

    async def go() -> None:
        assert await runtime._launch("job-1") is True
        store.execute("UPDATE job_leases SET owner = 'proc-b' WHERE job_id = 'job-1'")
        await _settle(runtime)

    asyncio.run(go())

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, SKIP_LEASE_CONFLICT)
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert {row["failure_reason"] for row in rows.values()} == {SKIP_LEASE_CONFLICT}
    assert [row["owner"] for row in _leases(store)] == ["proc-b"], "we do not reclaim it"


# ── windows ───────────────────────────────────────────────────────────────────


def test_a_job_leased_by_a_live_foreign_process_is_not_run_twice(store: Store, caplog) -> None:
    """Refusing a job somebody else holds closes it, and leaves their lease.

    Not reachable through the queue today -- ``admit_job`` moves the row from
    ``queued`` and only one service can win that statement -- so this calls the
    launch directly.  It becomes reachable with the retry path, which requeues a
    job whose lease a still-live process has not given up, and the answer has to
    be "not mine": running it twice would score one workspace from two runs.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    store.acquire_lease("job-1", owner="proc-b", beat_at=NOW.isoformat(timespec="seconds"),
                        ttl_seconds=LEASE_TTL)
    runner = _StubRunner(store)
    runtime = _runtime(store, runner)

    with caplog.at_level(logging.ERROR):
        launched = asyncio.run(runtime._launch("job-1"))

    assert launched is False
    assert runner.calls == []
    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, SKIP_LEASE_CONFLICT)
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert {row["status"] for row in rows.values()} == {STATUS_SKIPPED}
    assert {row["failure_reason"] for row in rows.values()} == {SKIP_LEASE_CONFLICT}
    assert [row["owner"] for row in _leases(store)] == ["proc-b"]
    assert "leased by another process" in caplog.text
    refused = next(r for r in caplog.records if "leased by another" in r.getMessage())
    assert refused.held_by == "proc-b", "the refusal has to say who to go and talk to"
    assert refused.owner == "proc-a", "and which of the two is being refused"


def test_a_canceled_job_is_not_relabelled_when_its_window_closes(store: Store) -> None:
    """The cancel and the tick are racing, and the submitter's answer wins.

    ``queue.tick`` decided from a row that was still queued; a cancel landed in
    between and wrote ``canceled``.  Closing the job as ``window_closed`` here
    would overwrite a status somebody asked for, and their dashboard row would
    say the night ended before their run started.
    """
    _job(store, "job-1", status=STATUS_CANCELED)
    store.update_job("job-1", error="canceled")

    closed = asyncio.run(_runtime(store, _StubRunner(store))._window_closed("job-1"))

    assert closed is False, "nothing was closed by this pass"
    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_CANCELED, "canceled")


def test_the_beat_loop_is_stopped_before_the_lease_is_released(store: Store) -> None:
    """A beat that lands after the release is a false alarm about a finished job.

    Cancelling the heartbeat without awaiting it lets one more beat go out under
    a lease this process has already handed back; its failure is logged as
    "lease lost while running" for a job whose rows are already closed.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    runner = _StubRunner(store, record=(), blocks=True)
    runtime = _runtime(store, runner)
    events: list[str] = []

    async def beating(job_id: str) -> None:
        events.append("beat-start")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("beat-stop")

    real_release = store.release_lease

    def release_lease(*args: Any, **kwargs: Any) -> bool:
        events.append("release")
        return real_release(*args, **kwargs)

    runtime._beat_loop = beating  # type: ignore[method-assign]
    store.release_lease = release_lease  # type: ignore[method-assign]

    async def go() -> None:
        assert await runtime._launch("job-1") is True
        await asyncio.sleep(0.02)
        await runtime.shutdown()

    asyncio.run(go())

    assert events == ["beat-start", "beat-stop", "release"]


def test_a_lease_release_that_fails_still_closes_the_job_row(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    """Two writes share the ``finally``, and the later one is the one that matters.

    A SQLite error handed back by the release skips out of the block, and with it
    the only statement that moves the job off ``running`` -- which is the damage
    that lasts, because a running row is one of the four global slots spent until
    somebody restarts the service.  The lease it failed to drop expires on its
    own and the next process takes the job.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    done = (("T001", STATUS_FINISHED, ""), ("T002", STATUS_FINISHED, ""))
    runtime = _runtime(store, _StubRunner(store, record=done))

    def release_lease(*args: Any, **kwargs: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    store.release_lease = release_lease  # type: ignore[method-assign]

    with caplog.at_level(logging.ERROR):
        asyncio.run(runtime._run_job(store.get_job("job-1")))

    assert store.get_job("job-1")["status"] == STATUS_FINISHED
    assert "lease release failed" in caplog.text, "a swallowed write has to leave a trace"


def test_a_job_whose_window_passed_is_closed_once_not_reported_every_tick(store: Store) -> None:
    """The list of jobs still waiting has to end somewhere.

    A queued job past ``not_after`` can never start, and returning it on every
    pass would be an unbounded "still waiting" -- a log line per job per tick
    and a status the submitter never gets.
    """
    _job(store, "job-1", window=_custom_window(NOW - timedelta(hours=2), NOW - timedelta(minutes=30)))
    runtime = _runtime(store, _StubRunner(store))

    report = asyncio.run(runtime.tick_once())

    assert report.closed == ["job-1"] and report.launched == []
    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, SKIP_WINDOW_CLOSED)
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert {row["status"] for row in rows.values()} == {STATUS_SKIPPED}
    assert {row["failure_reason"] for row in rows.values()} == {SKIP_WINDOW_CLOSED}

    again = asyncio.run(runtime.tick_once())
    assert again.closed == [] and again.launched == [], "closed means it left the queue"


def test_a_hard_stop_window_stops_the_run_and_labels_what_never_ran(store: Store) -> None:
    """``schedule.hard_stop`` is the one case a running job is cut off.

    The tasks that had not started are ``skipped(window_closed)``: they stay out
    of the denominator, which is the difference between a short night and an
    agent that looks like it failed.
    """
    _job(store, "job-1", window=_custom_window(NOW - timedelta(hours=1), NOW + timedelta(minutes=30)))
    clock = FrozenClock(NOW)
    runner = _StubRunner(store, record=(), blocks=True)
    runtime = _runtime(store, runner, clock=clock, cfg=schedule_config(hard_stop=True))

    launched = asyncio.run(_stop_when_the_window_closes(runtime, clock))

    assert launched.stopped == ["job-1"]
    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_FAILED, SKIP_WINDOW_CLOSED)
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert {row["failure_reason"] for row in rows.values()} == {SKIP_WINDOW_CLOSED}
    assert _leases(store) == []


async def _stop_when_the_window_closes(runtime: EvalRuntime, clock: FrozenClock) -> ServeReport:
    report = await runtime.tick_once()
    await asyncio.sleep(0.02)
    clock.advance(minutes=31)
    closing = await runtime.tick_once()
    await _settle(runtime)
    assert report.launched == ["job-1"]
    return closing


def test_finalizing_does_not_revive_a_job_the_submitter_canceled(store: Store) -> None:
    """The cancel landed while the run was in flight; its row is the truth.

    ``_finalize`` writes over whatever the run recorded, so without the guard a
    cancel would be talked back into a status nobody asked for -- and the
    dashboard would show a job running that the submitter had already closed.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    store.transition_job("job-1", from_status=STATUS_RUNNING, to_status=STATUS_CANCELED,
                         error="canceled")

    asyncio.run(_runtime(store, _StubRunner(store))._finalize("job-1"))

    job = store.get_job("job-1")
    assert (job["status"], job["error"]) == (STATUS_CANCELED, "canceled")
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert {row["status"] for row in rows.values()} == {STATUS_SKIPPED}
    assert {row["failure_reason"] for row in rows.values()} == {"canceled"}, \
        "the reason the job row carries is the reason its tasks get"


# ── the loop and the process ──────────────────────────────────────────────────


def test_shutdown_cancels_every_run_and_leaves_nothing_running(store: Store) -> None:
    """A clean exit must not need the startup reconcile.

    Cancelling without awaiting would leave task rows ``running`` and leases in
    the table -- the state that is only supposed to appear after a crash, so a
    restart would report it as one.
    """
    _job(store, "job-1", submitter="dev-1")
    _job(store, "job-2", submitter="dev-2")
    runner = _StubRunner(store, record=(), blocks=True)
    runtime = _runtime(store, runner)

    async def go() -> None:
        report = await runtime.tick_once()
        assert sorted(report.launched) == ["job-1", "job-2"]
        # Let each run reach its await first.  A task cancelled before it ever
        # started has no run to finalize, and that case belongs to the lease and
        # the startup reconcile, not to a clean exit.
        await asyncio.sleep(0.05)
        await runtime.shutdown()

    asyncio.run(go())

    assert runtime.running_jobs() == ()
    for job_id in ("job-1", "job-2"):
        assert store.get_job(job_id)["status"] == STATUS_FAILED
        rows = {row["task_id"]: row for row in store.list_job_tasks(job_id)}
        assert {row["failure_reason"] for row in rows.values()} == {SKIP_RESTART}
    assert store.query("SELECT job_id FROM job_leases") == []


def test_a_failing_tick_does_not_end_the_loop(store: Store, caplog) -> None:
    """One bad pass cannot take the service down.

    The tick's IO is the database and the queue's rows; both can fail once.  A
    loop that exited on it would stop scheduling for everybody, and the
    dashboard would keep reporting a service that is up.
    """
    runtime = _runtime(store, _StubRunner(store), tick_seconds=0.01)
    passes: list[int] = []
    second_pass = asyncio.Event()

    async def flaky() -> ServeReport:
        passes.append(1)
        if len(passes) == 1:
            raise RuntimeError("database is locked")
        second_pass.set()
        return ServeReport()

    runtime.tick_once = flaky  # type: ignore[method-assign]

    async def go() -> None:
        loop = asyncio.create_task(runtime.serve())
        try:
            await asyncio.wait_for(second_pass.wait(), timeout=2.0)
        finally:
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)

    with caplog.at_level(logging.ERROR):
        asyncio.run(go())

    assert len(passes) >= 2
    assert "scheduler tick failed" in caplog.text


def test_a_store_query_hanging_does_not_hang_the_event_loop(store: Store) -> None:
    """L16: the awaits around ``store`` must yield the loop, not just the call stack.

    ``Store`` is one synchronous sqlite connection, so a query issued straight
    from a coroutine stops every other coroutine in the process -- including the
    report route answering whoever else is waiting on this service.  No
    single-threaded assertion can see that, so this test makes the blocked query
    wait for *another coroutine* to release it: take the ``to_thread`` out of
    :meth:`EvalRuntime._finalize` and the release never happens, because the loop
    does not get back to the probe.

    The 2 s is the verdict, not a retry.  The honest path releases in
    milliseconds; only a loop that was blocked spends it.
    """
    _job(store, "job-1", status=STATUS_RUNNING)
    entered = threading.Event()
    released = threading.Event()
    released_in_time: list[bool] = []
    real_get_job = store.get_job

    def blocking_get_job(job_id: str) -> Any:
        entered.set()
        released_in_time.append(released.wait(2.0))
        return real_get_job(job_id)

    store.get_job = blocking_get_job  # type: ignore[method-assign]

    async def probe() -> None:
        while not entered.is_set():
            await asyncio.sleep(0.005)
        released.set()

    async def go() -> None:
        runtime = _runtime(store, _StubRunner(store))
        probing = asyncio.create_task(probe())
        try:
            await runtime._finalize("job-1")
        finally:
            await probing

    asyncio.run(go())

    assert released_in_time and all(released_in_time), (
        "another coroutine ran while the query was in flight"
    )
    rows = store.list_job_tasks("job-1")
    assert {row["status"] for row in rows} == {STATUS_SKIPPED}, (
        "the awaited call still wrote the rows it is there to write"
    )
    assert real_get_job("job-1")["status"] in (STATUS_FAILED, STATUS_FINISHED)


def test_the_lease_owner_names_the_process_and_the_job_url_names_the_agent() -> None:
    """The two identifiers the lease and the run are built from."""
    owner = default_owner_id()
    assert owner == f"{socket.gethostname()}:{os.getpid()}"
    endpoint = http_endpoint({"acp_url": "http://127.0.0.1:9100/rpc"})
    assert endpoint.transport == "http"
    assert endpoint.url == "http://127.0.0.1:9100/rpc"
