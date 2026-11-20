# -*- coding: utf-8 -*-
"""The always-on half: what the service does when nobody is asking.

The queue decides when a job may run and the runner decides what one run does;
neither owns the process.  This does the three things they cannot: it drives the
tick, it keeps a lease so that a ``running`` row means "some live process is
running this", and it writes the *job* row when a run is over -- ``runner.py``
deliberately never touches it.

Without the lease, "did this job die with the previous process, or is it still
being run?" has no answer in the database, and a restart leaves rows in
``running`` holding concurrency slots forever, because the queue counts rows.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..acp.client import AcpEndpoint
from .queue import (
    JobQueue,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    TickResult,
)
from .runner import (
    SKIP_LEASE_CONFLICT,
    SKIP_RESTART,
    SKIP_WINDOW_CLOSED,
    STATUS_MISSING,
    JobRunner,
)
from .schedule import Clock, SystemClock
from .store import Store

logger = logging.getLogger(__name__)

#: How long a lease stays believed after its last beat.  The beat interval is
#: derived from it, so the number has to survive one tick that found the
#: database busy -- while a dead process still gets noticed in minutes, not days.
DEFAULT_LEASE_TTL_SECONDS = 90.0

#: Beats per TTL: three means one missed beat is survivable and two are not.
LEASE_BEATS_PER_TTL = 3.0

#: A task status that means "the exchange happened", whatever the score says.
#: ``missing`` belongs here: the agent answered and produced nothing, which is a
#: result about the agent; a job made only of them still ran.
EXCHANGED_STATUSES = (STATUS_FINISHED, STATUS_MISSING)

#: Written when a run ended with nothing on any row to explain itself.
UNKNOWN_JOB_FAILURE = "job_failed"


def default_owner_id() -> str:
    """Which process this is, for the lease table.

    Host and pid, because the failure the lease exists for is "a second service
    was pointed at the same database": two processes on one host differ by pid,
    two services on two hosts differ by host.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


def http_endpoint(job: dict[str, Any]) -> AcpEndpoint:
    """The endpoint a submitted job asked for.

    Only ``acp_url`` is stored, so a tick can only reach an HTTP-shaped agent.
    A stdio agent has to be submitted by something already on this machine,
    which is the CLI path rather than the service.
    """
    return AcpEndpoint.http(str(job["acp_url"]))


@dataclass
class ServeReport:
    """What one tick pass changed, including what this process launched."""

    tick: TickResult = field(default_factory=TickResult)
    launched: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick.as_dict(),
            "launched": list(self.launched),
            "closed": list(self.closed),
            "stopped": list(self.stopped),
        }


class EvalRuntime:
    """Lease-keeping driver for one service process.

    Safe to call from the service event loop: the store is synchronous, so every
    statement goes through :func:`asyncio.to_thread`, as ``store.py``'s module
    contract requires.
    """

    def __init__(
        self,
        *,
        store: Store,
        queue: JobQueue,
        runner: JobRunner,
        clock: Clock | None = None,
        owner: str | None = None,
        endpoint_for: Callable[[dict[str, Any]], AcpEndpoint] | None = None,
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        tick_seconds: float = 5.0,
    ) -> None:
        self.store = store
        self.queue = queue
        self.runner = runner
        self.clock: Clock = clock or SystemClock()
        self.owner = owner or default_owner_id()
        self.endpoint_for = endpoint_for or http_endpoint
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.tick_seconds = float(tick_seconds)
        self._runs: dict[str, asyncio.Task] = {}
        #: Why each run in ``_runs`` was stopped, kept for the task rows that
        #: never got started.  Cleared when the run is forgotten.
        self._stops: dict[str, str] = {}

    # ── restart ───────────────────────────────────────────────────────────────

    def reconcile(self) -> list[str]:
        """Settle the ``running`` rows no live process is beating a lease for.

        Called once, before the first tick.  Design section 5 fixes what happens
        to them: ``failed(recovered)``, and no automatic retry.  A retry is the
        friendly choice and the wrong one -- the dead attempt's workspace is
        still on disk, so a second run would inherit half-written files and have
        them scored as its own output.
        """
        now = self.clock.now().isoformat(timespec="seconds")
        settled: list[str] = []
        for job_id in self.store.orphan_running_jobs(now):
            outcome = self.store.settle_orphan_job(
                job_id,
                now_iso=now,
                failure_reason="recovered",
                not_run_reason=SKIP_RESTART,
            )
            if not outcome["settled"]:
                continue
            settled.append(job_id)
            logger.error(
                "job left running by a dead process was settled",
                extra={
                    "job_id": job_id,
                    "tasks_failed": outcome["tasks_failed"],
                    "tasks_skipped": outcome["tasks_skipped"],
                },
            )
        if settled:
            logger.warning(
                "startup reconcile settled jobs",
                extra={"jobs": len(settled), "owner": self.owner},
            )
        return settled

    # ── the loop ──────────────────────────────────────────────────────────────

    async def serve(self) -> None:
        """Tick until cancelled.  One failed pass does not end the loop."""
        while True:
            try:
                await self.tick_once()
                # Inside the guard: a sleep left outside would let one raise
                # between ticks end the loop, and a scheduler that is not
                # ticking is not visibly dead -- the jobs just never start.
                await asyncio.sleep(self.tick_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")

    async def tick_once(self) -> ServeReport:
        """One pass: run the queue, close what lost its window, launch the rest."""
        report = ServeReport(tick=await asyncio.to_thread(self.queue.tick))
        for job_id in report.tick.window_closed:
            if await self._window_closed(job_id):
                (
                    report.stopped
                    if job_id in self._runs
                    else report.closed
                ).append(job_id)
        for job_id in report.tick.started:
            if await self._launch(job_id):
                report.launched.append(job_id)
        return report

    # ── one job's run ─────────────────────────────────────────────────────────

    async def _launch(self, job_id: str) -> bool:
        """Start a job this process now owns, unless another process holds it."""
        job = await asyncio.to_thread(self.store.get_job, job_id)
        if job is None or job["status"] != STATUS_RUNNING:
            return False
        held = await asyncio.to_thread(
            self.store.acquire_lease,
            job_id,
            owner=self.owner,
            beat_at=self.clock.now().isoformat(timespec="seconds"),
            ttl_seconds=self.lease_ttl_seconds,
        )
        if not held:
            # The queue counted rows and found a free slot; the lease says the
            # slot is already being spent by another service on the same
            # database.  That is a deployment fault, and "not mine" is the only
            # reading that cannot run the same job twice.
            logger.error(
                "job is leased by another process",
                extra={
                    "job_id": job_id,
                    "owner": self.owner,
                    "held_by": await asyncio.to_thread(self.store.lease_owner, job_id),
                },
            )
            await asyncio.to_thread(self._skip_pending, job_id, SKIP_LEASE_CONFLICT)
            await asyncio.to_thread(
                self.store.transition_job,
                job_id,
                from_status=STATUS_RUNNING,
                to_status=STATUS_FAILED,
                finished_at=self.clock.now().isoformat(timespec="seconds"),
                error=SKIP_LEASE_CONFLICT,
            )
            return False
        task = asyncio.create_task(self._run_job(job), name=f"eval-job-{job_id}")
        self._runs[job_id] = task
        task.add_done_callback(lambda finished, key=job_id: self._forget(key, finished))
        logger.info(
            "job launched",
            extra={"job_id": job_id, "owner": self.owner, "submitter": job["submitter"]},
        )
        return True

    async def _run_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        beating: asyncio.Task | None = None
        try:
            beating = asyncio.create_task(self._beat_loop(job_id))
            await self.runner.run_job(
                job_id,
                endpoint=self.endpoint_for(job),
                deadline_seconds=self.runner.job_deadline_seconds,
            )
        except asyncio.CancelledError:
            try:
                await self._finalize(job_id)
            except Exception:
                # The row is still ``running`` and the lease went with the
                # finally block, so nothing live is left to write it -- the next
                # startup's reconcile will settle it, which is the slow answer.
                # This log is the loud one, and a cancelled run has no other.
                logger.exception(
                    "job finalize failed after a cancel", extra={"job_id": job_id}
                )
            raise
        except Exception:
            # A run that raised before recording anything still has to leave the
            # running state, or the slot it holds is gone for good.
            logger.exception("job run raised", extra={"job_id": job_id})
            await self._finalize(job_id, not_run_reason=UNKNOWN_JOB_FAILURE)
            return
        finally:
            if beating is not None:
                # Awaited, not merely cancelled: a beat that lands after
                # ``release_lease`` would renew a lease another process has
                # taken by then, and the row would read as ours.
                beating.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beating
            try:
                await asyncio.to_thread(self.store.release_lease, job_id, owner=self.owner)
            except Exception:
                # Swallowed on purpose, and loudly: a lease left behind expires
                # on its own, whereas the job row is moved by the statement after
                # this one and nothing else will ever move it.
                logger.exception("lease release failed", extra={"job_id": job_id})
        await self._finalize(job_id)

    async def _beat_loop(self, job_id: str) -> None:
        """Keep the lease ours for as long as this process is on the job."""
        interval = max(self.lease_ttl_seconds / LEASE_BEATS_PER_TTL, 0.05)
        while True:
            await asyncio.sleep(interval)
            kept = await asyncio.to_thread(
                self.store.beat_lease,
                job_id,
                owner=self.owner,
                beat_at=self.clock.now().isoformat(timespec="seconds"),
            )
            if kept:
                continue
            logger.error(
                "lease lost while running",
                extra={"job_id": job_id, "owner": self.owner},
            )
            self.stop_job(job_id, reason=SKIP_LEASE_CONFLICT)
            return

    async def _finalize(self, job_id: str, *, not_run_reason: str = "") -> None:
        """Write the job row from the task rows the run left behind.

        Two writes, in this order: tasks the run never reached are labelled
        first, so the job row closes over rows that already explain themselves.
        A terminal job with ``pending`` tasks under it reads as a run the agent
        was cut short in, and it is the same leftover the startup reconcile had
        to be written for.

        The job row itself is guarded on ``running``: a cancel that landed
        during the run has already written ``canceled``, and this must not talk
        it back into a status the submitter never asked for.
        """
        reason = not_run_reason or await asyncio.to_thread(self._cut_short_reason, job_id)
        skipped = await asyncio.to_thread(self._skip_pending, job_id, reason)
        rows = await asyncio.to_thread(self.store.list_job_tasks, job_id)
        status, error = self.job_outcome(rows)
        moved = await asyncio.to_thread(
            self.store.transition_job,
            job_id,
            from_status=STATUS_RUNNING,
            to_status=status,
            finished_at=self.clock.now().isoformat(timespec="seconds"),
            error=error,
        )
        logger.info(
            "job finalized",
            extra={
                "job_id": job_id,
                "status": status,
                "error": error,
                "tasks": len(rows),
                "tasks_skipped": skipped,
                "written": moved,
            },
        )

    def _cut_short_reason(self, job_id: str) -> str:
        """Why the tasks this run never started will never start.

        Only read on a run that stopped before its plan.  What this process
        asked for wins over the job row: on a hard stop the row still says
        ``running``, and "the window closed" is the part a reader needs.
        """
        reason = self._stops.get(job_id)
        if reason:
            return reason
        job = self.store.get_job(job_id)
        if job is not None and str(job["status"]) in TERMINAL_STATUSES:
            # The submitter's cancel: the queue wrote this row a moment ago and
            # the reason is already in it.
            return str(job["error"] or STATUS_CANCELED)
        return SKIP_RESTART

    @staticmethod
    def job_outcome(rows: Sequence[dict[str, Any]]) -> tuple[str, str]:
        """``(status, error)`` for a job whose task rows are these.

        A job is ``failed`` only when nothing was exchanged at all.  One task
        timing out while the others answered is a capability result and the job
        is done; a job whose every task failed for a service reason is an
        outage, and calling that ``finished`` would put an unreachable agent in
        the score table as a zero.
        """
        if any(str(row["status"]) in EXCHANGED_STATUSES for row in rows):
            return STATUS_FINISHED, ""
        for row in rows:
            reason = str(row.get("failure_reason") or "")
            if reason:
                return STATUS_FAILED, reason
        return STATUS_FAILED, UNKNOWN_JOB_FAILURE

    def _skip_pending(self, job_id: str, reason: str) -> int:
        """Write the tasks that will never run, so the job can be closed.

        One statement, bounded by the job's task count: leaving rows
        ``pending`` under a terminal job is what makes the next reader explain
        why a finished job has tasks that never happened.
        """
        skipped = self.store.skip_unrun_tasks(
            job_id, reason=reason, now_iso=self.clock.now().isoformat(timespec="seconds")
        )
        if skipped:
            logger.info(
                "tasks skipped before they could run",
                extra={"job_id": job_id, "reason": reason, "count": skipped},
            )
        return skipped

    async def _window_closed(self, job_id: str) -> bool:
        """Close a job whose run window passed, instead of reporting it forever.

        Without this the queue returns the same still-queued job on every tick --
        an unbounded list of "still waiting" that is not a status, and a log line
        per pass per job.
        """
        job = await asyncio.to_thread(self.store.get_job, job_id)
        if job is None:
            return False
        if job["status"] == STATUS_RUNNING:
            # ``schedule.hard_stop`` only: stop the run and let
            # :meth:`_finalize` write the rows the cancellation left.
            return self.stop_job(job_id, reason=SKIP_WINDOW_CLOSED)
        if str(job["status"]) in TERMINAL_STATUSES:
            # A cancel or a failure landed between the tick that named this job
            # and here.  Its row already says why it stopped; relabelling it
            # ``window_closed`` would overwrite an answer somebody asked for.
            return False
        await asyncio.to_thread(self._skip_pending, job_id, SKIP_WINDOW_CLOSED)
        moved = await asyncio.to_thread(
            self.store.transition_job,
            job_id,
            from_status=str(job["status"]),
            to_status=STATUS_FAILED,
            finished_at=self.clock.now().isoformat(timespec="seconds"),
            error=SKIP_WINDOW_CLOSED,
        )
        if not moved:
            # Same race, one tick later: the guarded write lost, so the row is
            # somebody else's answer and this pass did not close anything.
            logger.warning(
                "job was closed by something else first",
                extra={"job_id": job_id, "was": job["status"]},
            )
            return False
        logger.info(
            "job closed with its window",
            extra={"job_id": job_id, "was": job["status"]},
        )
        return True

    # ── cancellation ──────────────────────────────────────────────────────────

    def stop_job(self, job_id: str, *, reason: str = SKIP_WINDOW_CLOSED) -> bool:
        """Cancel the run this process holds, and remember why.

        The queue owns the ``canceled`` row: :meth:`JobQueue.cancel` already
        wrote it and reported that a stop was needed.  This is the half that
        reaches the agent, and it is only effective in the process that launched
        the job -- another service's run keeps going until its lease goes stale.

        A cancel the submitter asked for needs no ``reason`` from here: the job
        row already carries it, and :meth:`_cut_short_reason` reads that first.
        """
        task = self._runs.get(job_id)
        if task is None:
            return False
        self._stops[job_id] = reason
        task.cancel()
        return True

    def running_jobs(self) -> tuple[str, ...]:
        return tuple(self._runs)

    async def shutdown(self) -> None:
        """Stop every run and wait for the rows to be written.

        Cancelling without awaiting would exit with task rows still ``running``,
        which is the state the lease exists to clean up after an unclean death --
        and a clean exit should not need that.
        """
        tasks = list(self._runs.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runs.clear()
        self._stops.clear()

    def _forget(self, job_id: str, finished: asyncio.Task) -> None:
        self._runs.pop(job_id, None)
        self._stops.pop(job_id, None)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None:
            logger.error(
                "job run task ended unexpectedly",
                extra={"job_id": job_id, "reason": repr(error)},
            )
