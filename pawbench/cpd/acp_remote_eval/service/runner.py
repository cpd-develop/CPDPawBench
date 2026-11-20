# -*- coding: utf-8 -*-
"""Runs a job's tasks against a remote agent and records what happened.

The queue decides *when* a job runs; this decides what one run does.  It owns
the per-task rows because that is where the difference between three kinds of
"no score" has to survive: the agent never answered (``failed``), it answered
but nothing came back through the data plane (``missing``), and it finished and
will be scored (``finished``).  Collapsing those into a zero is how a benchmark
starts reporting an infrastructure outage as a capability result.

It never changes the *job* row -- the scheduler owns job status, because a job
that lost its run window and a job whose tasks all failed are different
transitions made by different loops.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ..acp.client import AcpEndpoint, AcpError
from ..harness import RemoteAcpAgent
from .attempts import AttemptRegistry, LiveAttempt
from .datasets import DatasetService
from .exchange import Exchange, ExchangeError
from .grading import Scorer
from .schedule import Clock, SystemClock
from .store import Store

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_MISSING = "missing"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
#: Never started, so there is nothing to score and nothing to blame the agent
#: for (design section 7: it stays out of the denominator, unlike ``missing``).
STATUS_SKIPPED = "skipped"

#: Why a task row was written without a run.  ``window_closed`` is a job that
#: lost its chance to start, ``deadline`` a job that ran out of its wall clock,
#: ``service_restarted`` the tasks of a job whose process died,
#: ``lease_conflict`` a job another process got to first -- all four are facts
#: about the service, and the report has to say which one.
SKIP_WINDOW_CLOSED = "window_closed"
SKIP_DEADLINE = "deadline"
SKIP_RESTART = "service_restarted"
SKIP_LEASE_CONFLICT = "lease_conflict"

#: A task with less than this left of the job's wall clock does not start: it
#: would be killed by the deadline in the middle of a prompt, which reads as an
#: agent problem in the transcript and as a service problem here.
MIN_TASK_BUDGET_SECONDS = 1.0

#: Ran, but there is nothing to score.  The leaderboard drops these instead of
#: counting them (design section 7).
MISSING_REASONS = ("no_artifacts",)


class RunnerError(ValueError):
    """A job the runner refuses to start, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TaskPlan:
    """One task of one job, with the dataset it came from and where its files are."""

    task: Any
    dataset_root: Path
    resolved_from: tuple[str, ...] = ()


@dataclass
class JobSummary:
    """The run's tally, in the shape the job view and the CLI both print."""

    job_id: str
    tasks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.tasks:
            status = str(row["status"])
            counts[status] = counts.get(status, 0) + 1
        return counts

    @property
    def artifact_count(self) -> int:
        return sum(int(row.get("protocol_written") or 0) for row in self.tasks)

    @property
    def models_reported(self) -> list[str]:
        found = {str(row.get("subject_model_reported") or "unknown") for row in self.tasks}
        return sorted(found)

    def as_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_count": len(self.tasks),
            "by_status": self.by_status,
            "artifacts": self.artifact_count,
            "tasks_missing": self.by_status.get(STATUS_MISSING, 0),
            "subject_models_reported": self.models_reported,
            "tasks": list(self.tasks),
        }


def _capped_timeout(
    requested: int | None, cap: float | None
) -> int | None:
    """The task timeout to hand the agent: the submitter's, or what is left."""
    if cap is None or not math.isfinite(cap):
        return requested
    remaining = max(int(cap), 1)
    if requested is None:
        return remaining
    return min(int(requested), remaining)


def _attempt_deadline(cap: float | None) -> float | None:
    """The deadline for a whole attempt, or ``None`` for "no ceiling".

    ``asyncio.timeout`` reads None as unbounded, so an infinite budget becomes it
    here instead of a timer that can never fire.  The cap is the job's remaining
    wall clock, and the attempt needs it as one window over setup, the prompt and
    the collect step: each of those has its own bound, and three bounds in a row
    can still add up to more time than the job was given.
    """
    return cap if cap is not None and math.isfinite(cap) else None


class JobRunner:
    """Executes the tasks of one job, dataset by dataset.

    The order is the snapshot's rather than the submitter's: one dataset's tasks
    in the order their ids were resolved, datasets themselves in id order.  A
    dependency on when the rows were written would be invisible until someone
    re-submitted a job -- and re-submitting rewrites the rows.
    """

    def __init__(
        self,
        *,
        store: Store,
        datasets: DatasetService,
        exchange: Exchange,
        registry: AttemptRegistry | None = None,
        clock: Clock | None = None,
        scorer: Scorer | None = None,
        timeout_seconds: int | None = None,
        job_deadline_seconds: float | None = None,
    ) -> None:
        self.store = store
        self.datasets = datasets
        self.exchange = exchange
        self.registry = registry if registry is not None else AttemptRegistry()
        self.clock: Clock = clock or SystemClock()
        #: Grades the attempts that finished.  Without one the runner records the
        #: run and leaves ``score`` NULL, which reads as "not graded" -- a zero
        #: there would be a claim about the subject that nobody measured.
        self.scorer = scorer
        #: Overrides every task's own timeout; what the submitter asked for.
        self.timeout_seconds = timeout_seconds
        #: Ceiling on the whole job.  Without it a 15-task submission may run for
        #: fifteen task timeouts, which is longer than the night window it was
        #: queued into; the queue's slots are counted per job, so the over-run
        #: also prices itself in other people's waiting time.  ``None`` means
        #: "no ceiling" and is what the unit tests use.
        self.job_deadline_seconds = job_deadline_seconds

    # ── planning ──────────────────────────────────────────────────────────────

    def plan(self, job: dict[str, Any]) -> list[TaskPlan]:
        """Expand the job's dataset snapshots into tasks, refusing a partial plan.

        The ids come from ``job_datasets.resolved_task_ids`` -- what the dataset
        held when the job was submitted -- so a dataset edited in between cannot
        silently change which questions this result scored.  An id that no
        longer resolves is the one case where continuing would be worse than
        stopping: the report would look complete.
        """
        rows = self.store.list_job_datasets(str(job["id"]))
        if not rows:
            raise RunnerError("no_datasets", "the job records no dataset snapshot")

        plans: list[TaskPlan] = []
        seen: set[str] = set()
        missing: list[str] = []
        for row in rows:
            dataset_id = str(row["dataset_id"])
            wanted = [str(task_id) for task_id in (row.get("resolved_task_ids") or [])]
            by_id = {str(task.task_id): task for task in self.datasets.tasks_for_run(dataset_id)}
            root = self.datasets.root_for(dataset_id)
            for task_id in wanted:
                task = by_id.get(task_id)
                if task is None:
                    missing.append(f"{dataset_id}/{task_id}")
                    continue
                if task_id in seen:
                    continue
                seen.add(task_id)
                plans.append(
                    TaskPlan(
                        task=task,
                        dataset_root=root,
                        resolved_from=(f"dataset:{dataset_id}",),
                    )
                )
        if missing:
            raise RunnerError(
                "task_unavailable",
                f"these submitted task ids no longer resolve in their dataset: {missing[:10]}",
            )
        if not plans:
            raise RunnerError("empty_plan", "the job's datasets resolved to no tasks")
        return plans

    def record_plan(self, job_id: str, plans: Sequence[TaskPlan], attempt: int = 1) -> None:
        """Write the pending rows before anything runs, so the queue view is whole."""
        self.store.insert_job_tasks(
            [
                {
                    "job_id": job_id,
                    "task_id": str(plan.task.task_id),
                    "attempt": attempt,
                    "status": STATUS_PENDING,
                    "grading_type": str(getattr(plan.task, "grading_type", "") or ""),
                    "resolved_from": list(plan.resolved_from),
                }
                for plan in plans
            ]
        )

    # ── running ───────────────────────────────────────────────────────────────

    async def run_job(
        self,
        job_id: str,
        *,
        endpoint: AcpEndpoint,
        attempt: int = 1,
        deadline_seconds: float | None = None,
    ) -> JobSummary:
        """Run every task of one job against one endpoint.

        Called by the scheduler loop once the job has a slot.  Tasks run in plan
        order under one wall clock: ``deadline_seconds`` (defaulting to
        ``self.job_deadline_seconds``) bounds the whole job, and whatever has not
        started when it runs out is written as ``skipped(deadline)`` rather than
        left pending.
        """
        # The store is synchronous and the dataset plan reads every task file,
        # so all of it goes to a thread: this coroutine shares the service's
        # event loop with the data plane (store.py's module contract).
        job = await asyncio.to_thread(self.store.get_job, job_id)
        if job is None:
            raise RunnerError("job_not_found", f"no such job: {job_id}")
        plans = await asyncio.to_thread(self.plan, job)
        await asyncio.to_thread(self.record_plan, job_id, plans, attempt)
        summary = JobSummary(job_id=job_id)
        budget = (
            deadline_seconds if deadline_seconds is not None else self.job_deadline_seconds
        )
        began = time.monotonic()
        for index, plan in enumerate(plans):
            left = math.inf if budget is None else budget - (time.monotonic() - began)
            if left < MIN_TASK_BUDGET_SECONDS:
                summary.tasks.extend(
                    await asyncio.to_thread(
                        self.skip_tasks, job_id, plans[index:], attempt, SKIP_DEADLINE
                    )
                )
                logger.warning(
                    "job wall clock reached",
                    extra={
                        "job_id": job_id,
                        "budget_seconds": budget,
                        "skipped": len(plans) - index,
                    },
                )
                break
            summary.tasks.append(
                await self.run_task(
                    job_id, plan, endpoint, attempt=attempt, timeout_cap=left
                )
            )
        logger.info(
            "job run complete",
            extra={"job_id": job_id, "by_status": summary.by_status, "artifacts": summary.artifact_count},
        )
        return summary

    async def run_task(
        self,
        job_id: str,
        plan: TaskPlan,
        endpoint: AcpEndpoint,
        *,
        attempt: int = 1,
        timeout_cap: float | None = None,
    ) -> dict[str, Any]:
        """One attempt of one task, recorded whichever way it went.

        ``timeout_cap`` is what the job's wall clock has left.  It bounds the
        attempt as a whole -- setup, the prompt and the collect step inside one
        window -- so a remote agent that never answers the handshake cannot hold
        a slot past the job's own deadline, and the agent's per-request timeout
        is capped to the same figure.
        """
        task_id = str(plan.task.task_id)
        agent = RemoteAcpAgent(
            endpoint=endpoint,
            exchange=self.exchange,
            job_id=job_id,
            task=plan.task,
            dataset_root=plan.dataset_root,
            attempt=attempt,
            timeout_seconds=_capped_timeout(self.timeout_seconds, timeout_cap),
        )
        self.registry.register(job_id, task_id, attempt, LiveAttempt(plan.task, plan.dataset_root))
        started_at = self.clock.now()
        try:
            await asyncio.to_thread(
                self.store.update_job_task,
                job_id,
                task_id,
                attempt,
                status=STATUS_RUNNING,
                started_at=started_at.isoformat(),
            )
        except BaseException:
            self.registry.drop(job_id, task_id, attempt)
            raise
        began = time.monotonic()
        #: Which step of the attempt the clock ran out during.  Only read when a
        #: TimeoutError arrives, and read because the two answers are different
        #: faults on different machines.
        stage = "setup"
        result: dict[str, Any]
        try:
            async with asyncio.timeout(_attempt_deadline(timeout_cap)):
                await agent.setup()
                stage = "run"
                result = await agent.run()
                stage = "collect"
                result["workspace_rebuilt"] = await agent.post_run_collect()
        except (AcpError, ExchangeError) as exc:
            result = self._blank_result(agent, failure=exc.code, error=exc.message)
            logger.warning(
                "task attempt failed before it could be scored",
                extra={
                    "job_id": job_id,
                    "task_id": task_id,
                    "code": exc.code,
                    "reason": exc.message,
                },
            )
        except TimeoutError as exc:
            if stage == "collect":
                # "The agent answered but we could not assemble the workspace"
                # is our fault, and reading it as a plain timeout would hide
                # which of the two machines to look at.
                result = self._blank_result(agent, failure="collect_timeout", error=str(exc))
                logger.error(
                    "post-run collection timed out",
                    extra={"job_id": job_id, "task_id": task_id, "reason": repr(exc)},
                )
            else:
                # The job's own ceiling, and the step it fired in says the
                # agent never got as far as answering: setup is our connection
                # to them, run is their turn.  Both are the submitter's problem
                # to read as ``deadline``, not as a harness fault.
                result = self._blank_result(
                    agent, failure=SKIP_DEADLINE, error=f"{stage} ran out of the job's time"
                )
                logger.warning(
                    "task attempt cut short by the job wall clock",
                    extra={"job_id": job_id, "task_id": task_id, "stage": stage},
                )
        except Exception as exc:  # a harness bug must not take the queue down
            result = self._blank_result(agent, failure="runner_error", error=str(exc))
            logger.exception(
                "task attempt raised", extra={"job_id": job_id, "task_id": task_id}
            )
        except BaseException as exc:
            # Reached when the run is stopped from outside -- the task holding
            # it is cancelled, not raising.  A cancelled coroutine that skips
            # ``_record`` leaves the row in the status it started with, and the
            # queue counts rows, so that attempt holds one of the four global
            # slots for the life of the process.
            await asyncio.shield(
                asyncio.to_thread(
                    self._record,
                    job_id,
                    task_id,
                    attempt,
                    plan,
                    self._blank_result(agent, failure="interrupted", error=repr(exc)),
                    time.monotonic() - began,
                    started_at,
                )
            )
            raise
        finally:
            try:
                await agent.teardown()
            except Exception:
                # A teardown failure must not leave the attempt registered.
                logger.exception(
                    "teardown failed", extra={"job_id": job_id, "task_id": task_id}
                )
            finally:
                self.registry.drop(job_id, task_id, attempt)

        row = await asyncio.to_thread(
            self._record,
            job_id,
            task_id,
            attempt,
            plan,
            result,
            time.monotonic() - began,
            started_at,
        )
        if row["status"] == STATUS_FINISHED:
            # Grading is outside the attempt's timeout, so it is handed what the
            # job's wall clock has left rather than a budget of its own.
            grading_budget = (
                None if timeout_cap is None else timeout_cap - (time.monotonic() - began)
            )
            row = await self._score(
                job_id, task_id, attempt, plan, result, row, grading_budget
            )
        return row

    # ── recording ─────────────────────────────────────────────────────────────

    def skip_tasks(
        self, job_id: str, plans: Sequence[TaskPlan], attempt: int, reason: str
    ) -> list[dict[str, Any]]:
        """Write rows for tasks that will never run, so the job can be finished.

        A task nobody started has to read as "the service did not reach it" and
        stay out of the denominator (design section 7); leaving the row
        ``pending`` inside a terminal job instead asks the next reader to explain
        why a finished job has tasks that never happened.
        """
        finished_at = self.clock.now()
        self.store.skip_unrun_tasks(
            job_id,
            reason=reason,
            now_iso=finished_at.isoformat(timespec="seconds"),
            attempt=attempt,
        )
        rows: list[dict[str, Any]] = []
        for plan in plans:
            task_id = str(plan.task.task_id)
            rows.append(
                {
                    "task_id": task_id,
                    "attempt": attempt,
                    "status": STATUS_SKIPPED,
                    "failure_reason": reason,
                    "stop_reason": "",
                    "protocol_written": 0,
                    "subject_model_reported": "unknown",
                    "permissions": {},
                    "duration_s": 0.0,
                    "started_at": "",
                    "workspace": "",
                    "transcript_events": 0,
                }
            )
        logger.info(
            "tasks skipped before they could run",
            extra={"job_id": job_id, "reason": reason, "count": len(rows)},
        )
        return rows

    @staticmethod
    def _blank_result(agent: RemoteAcpAgent, *, failure: str, error: str) -> dict[str, Any]:
        """A result for an attempt that never produced one.

        The three ways an attempt stops early -- the agent refused, the
        harness raised, the run was cancelled -- differ only in ``failure``, and
        the row they write has to look like every other row or the report has
        blank cells where "we measured nothing, for this reason" belongs.
        """
        return {
            "status": "error",
            "failure": failure,
            "error": error,
            "protocol_written": 0,
            "stop_reason": "",
            "transcript": [],
            "subject_model_reported": agent.recorder.subject_model_reported,
            "trace_id": getattr(agent, "trace_id", ""),
            "session_id": getattr(agent, "session_id", ""),
            "permissions": {},
            "timed_out": False,
        }

    def _record(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
        plan: TaskPlan,
        result: dict[str, Any],
        elapsed: float,
        started_at: datetime,
    ) -> dict[str, Any]:
        status = self.classify(result)
        failure = str(result.get("failure") or "")
        if status == STATUS_MISSING:
            # The attempt itself succeeded, so there is no error code to carry:
            # naming the reason is what keeps "we measured nothing" readable as
            # itself in the report instead of looking like an unrecorded 0.
            failure = MISSING_REASONS[0]
        written = int(result.get("protocol_written") or 0)
        self.store.update_job_task(
            job_id,
            task_id,
            attempt,
            status=status,
            failure_reason=failure,
            artifact_count=written,
            protocol_written=written,
            out_of_band_count=0,
            workspace_path=str(result.get("workspace") or ""),
            transcript_path=str(
                self.exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
            ),
            duration_s=round(elapsed, 3),
            finished_at=self.clock.now().isoformat(),
            subject_model_reported=[str(result.get("subject_model_reported") or "unknown")],
            session_id=str(result.get("session_id") or "") or None,
            trace_id=str(result.get("trace_id") or "") or None,
        )
        return {
            "task_id": task_id,
            "attempt": attempt,
            "status": status,
            "failure_reason": failure,
            "stop_reason": str(result.get("stop_reason") or ""),
            "protocol_written": written,
            "subject_model_reported": str(result.get("subject_model_reported") or "unknown"),
            "permissions": result.get("permissions") or {},
            "duration_s": round(elapsed, 3),
            "started_at": started_at.isoformat(),
            "workspace": str(result.get("workspace") or ""),
            "transcript_events": len(result.get("transcript") or []),
        }

    async def _score(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
        plan: TaskPlan,
        result: dict[str, Any],
        row: dict[str, Any],
        budget_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Grade the attempt that just ran and write whatever it came up with.

        Only ``finished`` rows reach this.  A grading failure is not a low score
        either: when the judge was rate limited the row becomes ``failed`` with
        ``judge_unavailable``, so the report counts it as an error and the mean
        keeps measuring the subject rather than the judge's capacity.
        """
        if self.scorer is None:
            return row
        outcome = await self.scorer.score(
            plan.task, result, budget_seconds=budget_seconds
        )
        fields = outcome.row_fields()
        if outcome.failure_reason:
            fields["status"] = STATUS_FAILED
        await asyncio.to_thread(
            self.store.update_job_task, job_id, task_id, attempt, **fields
        )
        row["score"] = outcome.score
        row["failure_reason"] = outcome.failure_reason
        if outcome.failure_reason:
            row["status"] = STATUS_FAILED
        return row

    @staticmethod
    def classify(result: dict[str, Any]) -> str:
        """Which of the three kinds of "no score" this is.

        ``no_artifacts`` is a finished exchange with nothing in it, so it gets
        its own status rather than being folded into ``failed``: an agent that
        answered in chat and a service that could not reach it have to stay
        distinguishable in the aggregate, or the first is counted as the second.
        """
        if str(result.get("failure") or ""):
            return STATUS_FAILED
        return STATUS_FINISHED if int(result.get("protocol_written") or 0) else STATUS_MISSING
