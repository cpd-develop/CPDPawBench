# -*- coding: utf-8 -*-
"""Global queue: ordering, concurrency gates and the scheduling tick.

Concurrency is a property of the service, not of a submission (requirement 4):
one shared team service means ``max_concurrent_jobs: 4`` means four jobs at a
time across everyone, and ``max_running_per_user`` stops one person from
spending the whole budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from .schedule import Clock, SystemClock, Window, window_from_row
from .config import ScheduleConfig

logger = logging.getLogger(__name__)

#: A row the submit API has written but not yet placed in the queue.  It exists
#: so that :meth:`JobQueue.admit` has something to guard on: the insert and the
#: queueing are two statements, and a cancel that lands between them must not
#: be overwritten back into a live state.
STATUS_NEW = "new"
STATUS_QUEUED = "queued"
STATUS_SCHEDULED = "scheduled"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_SCHEDULED)
ORDERABLE_STATUSES = (STATUS_QUEUED, STATUS_SCHEDULED)
TERMINAL_STATUSES = (STATUS_FINISHED, STATUS_FAILED, STATUS_CANCELED)

#: Every status a row can hold.  Callers that have to enumerate them -- the
#: ``status=`` filter, the dashboard's legend -- read this rather than the
#: groupings above, because ``running`` belongs to none of them and a list
#: assembled from the groups silently drops the one state a submitter most
#: wants to ask about.
ALL_STATUSES = (
    STATUS_NEW,
    STATUS_QUEUED,
    STATUS_SCHEDULED,
    STATUS_RUNNING,
    STATUS_FINISHED,
    STATUS_FAILED,
    STATUS_CANCELED,
)

#: Positions are floats so that inserting between two neighbours is a midpoint
#: rather than a table rewrite.  Below this gap the float grid runs out and the
#: queue is renumbered.
_MIN_POSITION_GAP = 1e-6
_NORMALISED_STEP = 10.0

#: How many times :meth:`JobQueue.cancel` re-reads a row it lost a race over.
#: A job only moves through new/queued/scheduled/running, so three tries cover
#: every state it can reach while the cancel was in flight.
_CANCEL_ATTEMPTS = 4


class QueueError(ValueError):
    """A queue operation that cannot be honoured, with a stable code."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class QueueLimits:
    max_concurrent_jobs: int = 4
    max_running_per_user: int = 1


@dataclass
class TickResult:
    """What one scheduler pass changed; the loop logs this, not each job."""

    promoted: list[str] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    #: Jobs that can no longer start: still-queued jobs past ``not_after``,
    #: plus running ones when ``schedule.hard_stop`` is on.
    window_closed: list[str] = field(default_factory=list)
    waiting: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "promoted": list(self.promoted),
            "started": list(self.started),
            "window_closed": list(self.window_closed),
            "waiting": self.waiting,
        }


class JobQueue:
    """Ordering and admission control over the ``jobs`` table."""

    def __init__(
        self,
        store: Any,
        schedule_config: ScheduleConfig,
        limits: QueueLimits | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.schedule_config = schedule_config
        self.limits = limits or QueueLimits()
        self.clock: Clock = clock or SystemClock()

    # ── positions ─────────────────────────────────────────────────────────────

    def tail_position(self) -> float:
        return self.store.max_queue_pos() + _NORMALISED_STEP

    @staticmethod
    def midpoint(before: float | None, after: float | None) -> float:
        """Position that sits between two neighbours, or at the tail."""
        if before is None and after is None:
            return _NORMALISED_STEP
        if before is None:
            return float(after) - _NORMALISED_STEP
        if after is None:
            return float(before) + _NORMALISED_STEP / 2
        return (float(before) + float(after)) / 2

    def normalize_positions(self) -> int:
        """Rewrite the whole queue as integers ``10, 20, 30...`` preserving order."""
        positions = self.store.queue_positions()
        for index, (job_id, _) in enumerate(positions, start=1):
            self.store.set_queue_pos(job_id, index * _NORMALISED_STEP)
        logger.info("queue positions normalised", extra={"jobs": len(positions)})
        return len(positions)

    # ── submission ────────────────────────────────────────────────────────────

    def admit(self, job_id: str, window: Window, *, from_status: str = STATUS_NEW) -> float:
        """Put a freshly created job at the tail and pick its first status.

        Guarded on ``from_status`` rather than written blind: the row exists
        before it is queued, so an unguarded update would happily turn a job
        that was canceled a moment ago back into ``queued``.
        """
        position = self.tail_position()
        status = STATUS_QUEUED if window.seconds_until_open(self.clock.now()) <= 0 else STATUS_SCHEDULED
        if not self.store.transition_job(
            job_id, from_status=from_status, to_status=status, queue_pos=position
        ):
            raise QueueError(
                "job_not_admissible",
                f"job {job_id} left state {from_status} before it could be queued",
            )
        return position

    def reorder(
        self,
        job_id: str,
        principal_subject: str,
        *,
        before_id: str | None = None,
        after_id: str | None = None,
        position: float | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Move a waiting job, by neighbour or by absolute position."""
        job = self._require_job(job_id)
        if job["status"] not in ORDERABLE_STATUSES:
            raise QueueError(
                "job_not_reorderable",
                f"a {job['status']} job cannot be reordered; running jobs can only be canceled",
                status=job["status"],
            )
        if job["submitter"] != principal_subject and not is_admin:
            raise QueueError("not_job_owner", "only the submitter or an admin can reorder this job")

        target = self._resolve_target(before_id, after_id, position)
        self.store.set_queue_pos(job_id, target)
        result = self.snapshot(job_id)
        logger.info(
            "job reordered",
            extra={"job_id": job_id, "by": principal_subject, "queue_pos": target},
        )
        return result

    def cancel(
        self, job_id: str, principal_subject: str, *, is_admin: bool = False, error: str | None = None
    ) -> dict[str, Any]:
        job = self._require_job(job_id)
        if job["submitter"] != principal_subject and not is_admin:
            raise QueueError("not_job_owner", "only the submitter or an admin can cancel this job")
        if job["status"] in TERMINAL_STATUSES:
            raise QueueError("job_already_finished", f"job is already {job['status']}")

        was_running = False
        # The read above and the write below are two statements, and a tick can
        # admit this job in between.  Writing ``canceled`` blind would stamp a
        # row the runner has already started, and the caller's ``was_running``
        # would say it never ran -- so the guard is the status that was read,
        # and a lost race means re-reading and trying against the truth.
        for _ in range(_CANCEL_ATTEMPTS):
            was_running = job["status"] == STATUS_RUNNING
            moved = self.store.transition_job(
                job_id,
                from_status=job["status"],
                to_status=STATUS_CANCELED,
                finished_at=self.clock.now().isoformat(timespec="seconds"),
                error=error or "canceled",
            )
            if moved:
                break
            job = self._require_job(job_id)
            if job["status"] in TERMINAL_STATUSES:
                raise QueueError("job_already_finished", f"job is already {job['status']}")
        else:
            raise QueueError(
                "job_changing",
                f"job {job_id} kept changing state while it was being canceled",
            )
        return {**self.snapshot(job_id), "was_running": was_running}

    # ── tick ──────────────────────────────────────────────────────────────────

    def tick(self) -> TickResult:
        """One pass of the loop in design section 5.2.

        Returns the transitions it applied.  It never touches a running job's
        tasks -- the runner owns those -- it only decides who may start.
        """
        now = self.clock.now()
        result = TickResult()
        self._promote_scheduled(now, result)
        self._start_queued(now, result)
        result.waiting = len(self.store.jobs_in_state(STATUS_QUEUED, STATUS_SCHEDULED))
        if result.promoted or result.started:
            logger.info("scheduler tick", extra=result.as_dict())
        return result

    def _promote_scheduled(self, now: datetime, result: TickResult) -> None:
        for job in self.store.jobs_in_state(STATUS_SCHEDULED):
            window = self.window_of(job)
            if window.seconds_until_open(now) > 0:
                continue
            moved = self.store.transition_job(
                job["id"],
                from_status=STATUS_SCHEDULED,
                to_status=STATUS_QUEUED,
                scheduled_at=now.isoformat(timespec="seconds"),
            )
            if not moved:
                continue
            result.promoted.append(job["id"])
            logger.info(
                "scheduled job became queued",
                extra={"job_id": job["id"], "window_open": window.not_before.isoformat()},
            )

    def _start_queued(self, now: datetime, result: TickResult) -> None:
        running = self.store.jobs_in_state(STATUS_RUNNING)
        free_slots = max(0, self.limits.max_concurrent_jobs - len(running))
        running_by_submitter: dict[str, int] = {}
        for job in running:
            running_by_submitter[job["submitter"]] = running_by_submitter.get(job["submitter"], 0) + 1

        for job in sorted(self.store.jobs_in_state(STATUS_QUEUED), key=_queue_order):
            window = self.window_of(job)
            if window.blocks_starts_at(now):
                # Checked before the slot guard: a job that lost its chance
                # because the service was busy still has to be reported, or the
                # runner would leave it queued forever instead of recording
                # skipped(window_closed).
                result.window_closed.append(job["id"])
                continue
            if window.seconds_until_open(now) > 0:
                continue
            if free_slots <= 0 or running_by_submitter.get(job["submitter"], 0) >= (
                self.limits.max_running_per_user
            ):
                # These two counters are a fast path, not the decision.  Without
                # them a saturated service would run one write statement per
                # queued job on every tick; with them the same skip happens
                # before the statement.  ``admit_job`` re-counts both limits in
                # SQL, so a stale counter can delay a job by one tick but can
                # never over-book the service or start a canceled job.
                continue
            if not self.store.admit_job(
                job["id"],
                started_at=now.isoformat(timespec="seconds"),
                max_concurrent_jobs=self.limits.max_concurrent_jobs,
                max_running_per_user=self.limits.max_running_per_user,
            ):
                continue
            running_by_submitter[job["submitter"]] = running_by_submitter.get(job["submitter"], 0) + 1
            free_slots -= 1
            result.started.append(job["id"])

        result.window_closed.extend(self._closed_running_jobs(now, running))

    def snapshot(self, job_id: str) -> dict[str, Any]:
        job = self._require_job(job_id)
        return {
            "job_id": job["id"],
            "status": job["status"],
            "queue_pos": float(job["queue_pos"]),
            "queue_ahead": self.position_in_line(job_id),
            "window": self.window_of(job).to_payload(),
        }

    def position_in_line(self, job_id: str) -> int:
        """How many waiting jobs are ahead of this one.

        Always 0 for a job that is not waiting: once it is running (or done)
        the line no longer applies to it, and the dashboard shows progress
        instead of a queue depth.
        """
        job = self._require_job(job_id)
        if job["status"] not in ACTIVE_STATUSES:
            return 0
        ahead = [
            row["id"]
            for row in sorted(
                self.store.jobs_in_state(*ACTIVE_STATUSES),
                key=lambda row: (float(row["queue_pos"]), row["id"]),
            )
            if row["id"] != job_id and float(row["queue_pos"]) < float(job["queue_pos"])
        ]
        return len(ahead)

    def window_of(self, job: dict[str, Any]) -> Window:
        return window_from_row(job, self.schedule_config)

    def running_count(self) -> int:
        return len(self.store.jobs_in_state(STATUS_RUNNING))

    def admission(self, submitter: str) -> tuple[bool, str, dict[str, Any]]:
        """Whether a new submission may enter the queue, and what to tell the caller.

        ``service_busy`` is not an error the submitter caused -- the service is
        full -- so it comes back with the queue depth instead of a bare refusal.
        """
        running = self.store.jobs_in_state(STATUS_RUNNING)
        if len(running) >= self.limits.max_concurrent_jobs:
            return False, "service_busy", {"running": len(running), "limit": self.limits.max_concurrent_jobs}
        mine = [job for job in running if job["submitter"] == submitter]
        if len(mine) >= self.limits.max_running_per_user:
            return (
                False,
                "per_user_limit",
                {"running_for_subject": len(mine), "limit": self.limits.max_running_per_user},
            )
        return True, "", {}

    # ── internals ─────────────────────────────────────────────────────────────

    def _closed_running_jobs(self, now: datetime, running: Sequence[dict[str, Any]]) -> list[str]:
        if not self.schedule_config.hard_stop:
            return []
        closed = []
        for job in running:
            window = self.window_of(job)
            if window.blocks_starts_at(now):
                closed.append(job["id"])
        return closed

    def _require_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise QueueError("job_not_found", f"no such job: {job_id}")
        return job

    def _resolve_target(
        self, before_id: str | None, after_id: str | None, position: float | None
    ) -> float:
        given = [item for item in (before_id, after_id, position) if item is not None]
        if len(given) != 1:
            raise QueueError(
                "reorder_needs_one_target",
                "give exactly one of before_id, after_id or position",
            )
        if position is not None:
            return float(position)
        if before_id is not None:
            return self._position_before(before_id)
        return self._position_after(str(after_id))

    def _position_before(self, neighbour_id: str) -> float:
        """Slot immediately ahead of ``neighbour_id``."""
        neighbour = float(self._require_job(neighbour_id)["queue_pos"])
        before = self._previous_position(neighbour)
        if before is not None and not _gap_is_wide_enough(before, neighbour):
            self.normalize_positions()
            neighbour = float(self._require_job(neighbour_id)["queue_pos"])
            before = self._previous_position(neighbour)
        return self.midpoint(before, neighbour)

    def _position_after(self, neighbour_id: str) -> float:
        """Slot immediately behind ``neighbour_id``."""
        neighbour = float(self._require_job(neighbour_id)["queue_pos"])
        after = self._next_position(neighbour)
        if after is not None and not _gap_is_wide_enough(neighbour, after):
            self.normalize_positions()
            neighbour = float(self._require_job(neighbour_id)["queue_pos"])
            after = self._next_position(neighbour)
        return self.midpoint(neighbour, after)

    def _previous_position(self, position: float) -> float | None:
        lower = [pos for _, pos in self.store.queue_positions() if pos < position]
        return max(lower) if lower else None

    def _next_position(self, position: float) -> float | None:
        higher = [pos for _, pos in self.store.queue_positions() if pos > position]
        return min(higher) if higher else None


def _queue_order(row: dict[str, Any]) -> tuple[float, str]:
    """Queue order: position first, id to break ties deterministically."""
    return (float(row["queue_pos"]), str(row["id"]))


def _gap_is_wide_enough(before: float | None, after: float | None) -> bool:
    if before is None or after is None:
        return True
    midpoint = (before + after) / 2
    return min(abs(midpoint - before), abs(after - midpoint)) >= _MIN_POSITION_GAP
