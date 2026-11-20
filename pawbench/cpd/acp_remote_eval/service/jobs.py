# -*- coding: utf-8 -*-
"""Submission, and the submitter's view of the queue (design section 4).

Why this module exists instead of the routes doing the work: the dashboard, the
MCP tool and the CLI all have to run the same steps in the same order, and the
order is what carries the guarantees -- the selector is snapshotted into
``job_datasets`` before the queue can see the job, the ``jobs`` row exists
before it is admitted, and the per-user cap is answered before anything is
written at all.

Nothing here is async.  ``Store`` is one synchronous connection shared across
the thread pool (the contract in ``store.py``), so the routes reach these
methods through ``asyncio.to_thread`` and this module never touches the event
loop.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..acp.client import AcpEndpoint
from ..redact import url_without_credentials
from .auth import Principal, SCOPE_ADMIN
from .config import EvalConfig
from .datasets import DatasetService, ResolveResult
from .queue import JobQueue, STATUS_FAILED, STATUS_NEW
from .schedule import Clock, SystemClock, Window, resolve_window
from .store import Store

logger = logging.getLogger(__name__)

#: Refused before anything else is written: a ``new`` row nobody will ever run
#: is a row the dashboard shows forever, since neither the tick (which reads
#: ``queued``/``scheduled``) nor the startup reconcile (which reads ``running``)
#: has a reason to look at it.
ERROR_SUBMISSION_ABORTED = "submission_aborted"

#: Free text the submitter types, stored in a row that every ``GET /v1/jobs``
#: reads back.  Without a ceiling, a pasted log becomes part of every listing.
MAX_TEXT_FIELD_CHARS = 500

#: Same reason, one field deeper: the fingerprint is caller-shaped JSON, and it
#: is the only body field stored verbatim rather than validated.
MAX_FINGERPRINT_BYTES = 4096

#: How many jobs one listing returns when the caller does not say.  The table is
#: the team's whole evaluation history, and the dashboard polls it.
DEFAULT_LIST_LIMIT = 200

_JOB_ID_BYTES = 8


class SubmissionError(ValueError):
    """A submission this service will not accept, with a stable code."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class _Snapshot:
    """One dataset's contribution to one job, as it read at submit time.

    Lives only while the submission is being built: the rows it turns into are
    what the runner later plans from, and re-reading the dataset would be a
    different question set.
    """

    dataset_id: str
    dataset_kind: str
    requested_by: str
    task_ids: tuple[str, ...]


class JobService:
    """``POST /v1/jobs`` and the read/write calls a submitter makes about them."""

    def __init__(
        self,
        *,
        store: Store,
        queue: JobQueue,
        datasets: DatasetService,
        config: EvalConfig,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.datasets = datasets
        self.config = config
        self.clock: Clock = clock or SystemClock()

    # ── submission ────────────────────────────────────────────────────────────

    def submit(self, body: Mapping[str, Any], principal: Principal) -> dict[str, Any]:
        """Turn one request body into a queued job.

        Raises :class:`SubmissionError` for what the submitter can fix, and lets
        the specialist codes of :mod:`.datasets`, :mod:`.schedule`, :mod:`.queue`
        and :mod:`.auth` come through as raised -- one vocabulary per owner, so
        the HTTP layer maps code to status in one table instead of re-deriving
        it here.
        """
        fields = _as_mapping(body, "body")
        acp_url = _checked_acp_url(fields.get("acp_url"))
        selector = _as_mapping(fields.get("selector"), "selector")
        window_body = _as_mapping(fields.get("window"), "window")
        # Read together with the other fields, and checked before a row exists:
        # a body that is going to be refused should never leave a job behind.
        purpose = _checked_text(fields.get("purpose"), "purpose")
        product = _checked_text(fields.get("product"), "product")
        fingerprint = _checked_fingerprint(fields.get("env_fingerprint"))

        resolved = self.datasets.resolve(selector)
        if resolved.unknown_ids:
            raise SubmissionError(
                "selector_unknown_ids",
                f"these selector entries do not exist: {list(resolved.unknown_ids)}",
                unknown_ids=list(resolved.unknown_ids),
            )
        if not resolved.task_ids:
            raise SubmissionError(
                "empty_selection",
                "the selector resolved to no tasks; nothing would be evaluated",
            )
        snapshots = self._snapshots(resolved, selector)

        kind = str(window_body.get("kind") or "")
        # Declared timeouts are only worth reading the task files for when a
        # window has an edge to compare them against.
        timeouts = self._task_timeouts(snapshots) if kind in ("night", "custom") else ()
        window = resolve_window(
            kind,
            self.clock.now(),
            self.config.schedule,
            not_before=window_body.get("not_before"),
            not_after=window_body.get("not_after"),
            required_seconds=max(timeouts, default=0),
        )

        self._check_per_user_limit(principal.subject)

        job_id = _new_job_id()
        self._write(
            job_id,
            acp_url=acp_url,
            principal=principal,
            window=window,
            snapshots=snapshots,
            purpose=purpose,
            product=product,
            fingerprint=fingerprint,
        )
        try:
            position = self.queue.admit(job_id, window)
        except Exception:
            # The row is written, so it has to say something better than ``new``:
            # a job the queue never took is invisible to the scheduler forever.
            self._close_unfinished(job_id, principal.subject)
            raise
        logger.info(
            "job submitted",
            extra={
                "job_id": job_id,
                "submitter": principal.subject,
                "tasks": resolved.task_count,
                "window_kind": window.kind,
                "queue_pos": position,
            },
        )
        return self._submitted(job_id, resolved, window, timeouts)

    def _check_per_user_limit(self, subject: str) -> None:
        """Refuse before writing, so a refused submission leaves no row.

        Only the per-user cap is a refusal.  ``service_busy`` is not: four jobs
        already running is what the queue exists for, and the submitter is told
        how many are ahead of it rather than bounced.
        """
        allowed, code, details = self.queue.admission(subject)
        if not allowed and code == "per_user_limit":
            raise SubmissionError(
                "per_user_limit",
                f"you already have {details.get('running_for_subject')} job(s) running; "
                f"the per-subject cap is {details.get('limit')}",
                **details,
            )

    def _write(
        self,
        job_id: str,
        *,
        acp_url: str,
        principal: Principal,
        window: Window,
        snapshots: Sequence[_Snapshot],
        purpose: str,
        product: str,
        fingerprint: Mapping[str, Any] | None,
    ) -> None:
        """Write the job row and its dataset snapshot, or close the row.

        One transaction, because the snapshot is what a job's results get
        reproduced from: a row that exists without it is a job nobody can report
        on honestly, and a half-written snapshot is worse than none.  Anything
        that fails after the row exists moves that row to ``failed`` -- guarded
        on ``new``, so a cancel that landed in between keeps its own row, which
        is the same rule :meth:`.queue.JobQueue.admit` is written for.
        """
        bounds = window.to_payload()
        try:
            self.store.insert_job_with_datasets(
                {
                    "id": job_id,
                    "submitter": principal.subject,
                    "token_subject": principal.subject,
                    "purpose": purpose,
                    "product": product,
                    "acp_url": acp_url,
                    "window_kind": window.kind,
                    "not_before": bounds["not_before"],
                    "not_after": bounds["not_after"],
                    "status": STATUS_NEW,
                    "queue_pos": 0.0,
                    "env_fingerprint": fingerprint,
                    "created_at": self.clock.now().isoformat(timespec="seconds"),
                },
                [
                    {
                        "job_id": job_id,
                        "dataset_id": snapshot.dataset_id,
                        "dataset_kind": snapshot.dataset_kind,
                        "requested_by": snapshot.requested_by,
                        "resolved_task_ids": list(snapshot.task_ids),
                    }
                    for snapshot in snapshots
                ],
            )
        except Exception as exc:
            logger.error(
                "submission write failed",
                extra={
                    "job_id": job_id,
                    "submitter": principal.subject,
                    "datasets": len(snapshots),
                    "error": repr(exc),
                },
            )
            self._close_unfinished(job_id, principal.subject)
            raise

    def _close_unfinished(self, job_id: str, submitter: str) -> None:
        """Move a row we wrote but could not queue to ``failed``.

        Guarded on ``new``, so a cancel that landed in between keeps its own
        state -- the same rule :meth:`.queue.JobQueue.admit` is written for.

        Never raises.  Both callers are on their way out of another failure, and
        a compensation that threw would replace the exception the submitter needs
        to read with one about the compensation.
        """
        try:
            moved = self.store.transition_job(
                job_id,
                from_status=STATUS_NEW,
                to_status=STATUS_FAILED,
                finished_at=self.clock.now().isoformat(timespec="seconds"),
                error=ERROR_SUBMISSION_ABORTED,
            )
        except Exception:
            logger.exception(
                "could not close an aborted job row",
                extra={"job_id": job_id, "submitter": submitter},
            )
            return
        if not moved:
            logger.error(
                "job row left open by an aborted submission",
                extra={"job_id": job_id, "submitter": submitter},
            )
            return
        logger.warning(
            "aborted submission closed its own row",
            extra={"job_id": job_id, "submitter": submitter},
        )

    # ── the submitter's reads ─────────────────────────────────────────────────

    def list_jobs(
        self,
        *,
        statuses: Sequence[str] = (),
        submitter: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Every job on the service, not only the caller's (requirement 5).

        Each row carries its task count and mean score.  That is one grouped
        query for the whole page, not one per row, and it is what lets the list
        answer "which of these is worth opening" without a detail request per
        line -- the question the dashboard polls this endpoint for.
        """
        rows = self.store.list_jobs(
            statuses=tuple(statuses),
            submitter=submitter or None,
            limit=DEFAULT_LIST_LIMIT if limit is None else max(1, int(limit)),
        )
        items = [_job_item(row) for row in rows]
        totals = self.store.job_task_totals([item["job_id"] for item in items])
        for item in items:
            item.update(
                totals.get(item["job_id"])
                or {"task_count": 0, "tasks_finished": 0, "tasks_failed": 0, "score": None}
            )
            item["score"] = item["score"] if item["task_count"] else None
        return {"jobs": items, "count": len(items)}

    def get(self, job_id: str) -> dict[str, Any]:
        """One job with the rows the runner writes: state, score, and why not.

        This is ``GET /v1/jobs/{id}``.  The richer two-tier view is
        ``reports.build_job_detail``, which every read surface shares; this
        stays the queue view -- the one place a submitter checks whether their
        job is moving.
        """
        job = self.store.get_job(job_id)
        if job is None:
            raise SubmissionError("job_not_found", f"no such job: {job_id}")
        return {
            **_job_item(job),
            "queue": self.queue.snapshot(job_id),
            "datasets": [
                {
                    "dataset_id": row["dataset_id"],
                    "dataset_kind": row["dataset_kind"],
                    "requested_by": row["requested_by"],
                    "task_count": len(row["resolved_task_ids"] or ()),
                }
                for row in self.store.list_job_datasets(job_id)
            ],
            "tasks": [_task_item(row) for row in self.store.list_job_tasks(job_id)],
        }

    def cancel(
        self,
        job_id: str,
        principal: Principal,
        *,
        stop_running: Callable[[str], bool] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Cancel, and reach the agent too when the job was already running.

        Two halves, because one write cannot stop a remote run: the queue owns
        the ``canceled`` row and :meth:`.runtime.EvalRuntime.stop_job` owns the
        in-flight attempt.  Composing them here is what keeps a caller from
        cancelling the row while the session keeps running against fixtures
        nobody is scoring any more.
        """
        outcome = self.queue.cancel(
            job_id,
            principal.subject,
            is_admin=principal.can(SCOPE_ADMIN),
            error=_checked_reason(error),
        )
        if outcome.get("was_running") and stop_running is not None:
            # Called on its own line, not inside the log's ``extra``: the row is
            # already ``canceled`` by here, so a raise while building the log line
            # would answer 5xx for a cancel that happened, and the caller's retry
            # would find a job it is told to cancel again.
            forwarded = stop_running(job_id)
            extra = {"job_id": job_id, "by": principal.subject, "local_run": forwarded}
            if forwarded:
                logger.info("running job cancel forwarded to the harness", extra=extra)
            else:
                # Nothing local was holding this session, which is the shape of a
                # run whose attempt row was lost -- the agent keeps evaluating
                # fixtures nobody is scoring, so this one is not a detail.
                logger.warning("running job cancel reached no local attempt", extra=extra)
        return outcome

    def reorder(
        self,
        job_id: str,
        principal: Principal,
        *,
        before_id: str | None = None,
        after_id: str | None = None,
        position: float | None = None,
    ) -> dict[str, Any]:
        """Move a waiting job; only its owner, or an admin, may ask (design 5.3)."""
        return self.queue.reorder(
            job_id,
            principal.subject,
            before_id=before_id,
            after_id=after_id,
            position=position,
            is_admin=principal.can(SCOPE_ADMIN),
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _snapshots(self, resolved: ResolveResult, selector: Mapping[str, Any]) -> list[_Snapshot]:
        """One row per dataset that contributed, holding only this job's tasks.

        The contributing datasets come from the per-task sources and the category
        expansion rather than ``by_dataset``, which only counts the ids the
        submitter named: a category expansion contributes datasets nobody named,
        and a snapshot that missed them would record a job whose plan the rows do
        not add up to.  The ids are then filtered by what the preview resolved
        to, so a dataset edited between the two reads cannot quietly widen the
        job.
        """
        named = _as_list(selector.get("datasets"))
        categories_by_dataset = _categories_by_dataset(resolved)
        wanted = set(resolved.task_ids)
        snapshots: list[_Snapshot] = []
        for dataset_id in _contributing_datasets(resolved):
            record = self.datasets.get(dataset_id)
            included = [task_id for task_id in record["task_ids"] if task_id in wanted]
            if not included:
                continue
            categories = categories_by_dataset.get(dataset_id, ())
            if dataset_id in named or not categories:
                requested_by = f"dataset:{dataset_id}"
            else:
                requested_by = f"category:{categories[0]}"
            snapshots.append(
                _Snapshot(
                    dataset_id=dataset_id,
                    dataset_kind=str(record["kind"]),
                    requested_by=requested_by,
                    task_ids=tuple(included),
                )
            )
        if not snapshots:
            raise SubmissionError(
                "empty_selection",
                "the selector named datasets that hold none of the resolved tasks",
            )
        return snapshots

    def _task_timeouts(self, snapshots: Sequence[_Snapshot]) -> tuple[int, ...]:
        """Declared timeouts for exactly the tasks this job will run."""
        timeouts: list[int] = []
        for snapshot in snapshots:
            wanted = set(snapshot.task_ids)
            for summary in self.datasets.task_summaries(self.datasets.get(snapshot.dataset_id)):
                if summary.task_id in wanted:
                    timeouts.append(max(0, int(summary.timeout_seconds or 0)))
        return tuple(timeouts)

    def _submitted(
        self, job_id: str, resolved: ResolveResult, window: Window, timeouts: Sequence[int]
    ) -> dict[str, Any]:
        payload = {
            **self.queue.snapshot(job_id),
            "resolved": resolved.to_payload(),
            "window": window.to_payload(),
        }
        warning = _capacity_warning(window, timeouts, self.config.service.max_concurrent_jobs)
        if warning is not None:
            payload["warning"] = warning
        return payload


def _job_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "submitter": row["submitter"],
        "status": row["status"],
        "queue_pos": float(row["queue_pos"]),
        "purpose": row["purpose"],
        "product": row["product"],
        # Every token holder reads this list, not only the owner of the row, so
        # an endpoint that carries its credential shows it to the whole service.
        "acp_url": url_without_credentials(row["acp_url"]),
        "window_kind": row["window_kind"],
        "not_before": row["not_before"],
        "not_after": row["not_after"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "env_fingerprint": row["env_fingerprint"],
    }


#: The fields ``GET /v1/jobs/{id}`` promises: state, score, why it failed, and
#: the two write-back counters that separate a real answer from a sandbox-only
#: one (design section 3).
def _task_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "attempt": int(row["attempt"] or 1),
        "status": row["status"],
        "score": row["score"],
        "grading_type": row["grading_type"],
        "failure_reason": row["failure_reason"],
        "artifact_count": int(row["artifact_count"] or 0),
        "protocol_written": int(row["protocol_written"] or 0),
        "out_of_band_count": int(row["out_of_band_count"] or 0),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_s": row["duration_s"],
        "resolved_from": list(row["resolved_from"] or ()),
    }


def _contributing_datasets(resolved: ResolveResult) -> tuple[str, ...]:
    """Every dataset the resolved task list actually came from, sorted.

    ``ResolveResult.by_dataset`` is keyed by what the *submitter named*, which is
    not the same set once a category is in the selector -- so building the
    snapshot from it would drop the datasets a category pulled in.  Neither is
    ``sources_by_task`` enough on its own: a task reached through a category
    records ``category:x`` as its source, and the datasets behind that category
    are listed once, in ``categories_expanded``.
    """
    found = {
        source.split(":", 1)[1]
        for sources in resolved.sources_by_task.values()
        for source in sources
        if source.startswith("dataset:")
    }
    for dataset_ids in resolved.categories_expanded.values():
        found.update(dataset_ids)
    return tuple(sorted(found))


def _categories_by_dataset(resolved: ResolveResult) -> dict[str, tuple[str, ...]]:
    """Which categories pulled each dataset in, so a snapshot can say why.

    ``requested_by`` would otherwise read as "the submitter chose this dataset"
    when they chose a category and the catalogue picked it -- the reason a mixed
    multi-select needs previewing before submitting in the first place.
    """
    found: dict[str, list[str]] = {}
    for category, dataset_ids in resolved.categories_expanded.items():
        for dataset_id in dataset_ids:
            names = found.setdefault(dataset_id, [])
            if category not in names:
                names.append(category)
    return {key: tuple(sorted(value)) for key, value in found.items()}


def _capacity_warning(window: Window, timeouts: Sequence[int], slots: int) -> dict[str, Any] | None:
    """Say so when the window cannot hold the plan, without refusing the job.

    An estimate built from declared timeouts is always wrong, which is why this
    is a warning on the response rather than an error (design section 5.1):
    refusing would mean nobody may try a run that finishes early.  ``slots`` is
    the service-wide concurrency, the most this job could get and probably not
    what it will -- so the estimate is optimistic by construction, and the
    number is labelled "likely".
    """
    if window.not_after is None or not timeouts:
        return None
    available = (window.not_after - window.not_before).total_seconds()
    average = sum(timeouts) / len(timeouts)
    needed = average * len(timeouts) / max(1, int(slots))
    if average <= 0 or available >= needed:
        return None
    return {
        "code": "window_too_small",
        "window_seconds": int(available),
        "avg_task_seconds": int(average),
        "tasks_planned": len(timeouts),
        "tasks_likely_completable": max(0, int(available * max(1, int(slots)) / average)),
    }


def _checked_acp_url(value: Any) -> str:
    """Validate the ACP address here, so the tick never meets a bad one.

    :func:`.runtime.http_endpoint` rebuilds the endpoint from the stored string
    on every launch, so an address this service cannot speak is a submission
    mistake rather than a runtime one -- it has to fail where the submitter sees
    it, not in someone else's log.
    """
    text = str(value or "").strip()
    if not text:
        raise SubmissionError("acp_url_missing", "the submission carried no acp_url")
    try:
        AcpEndpoint.http(text)
    except Exception as exc:
        raise SubmissionError("acp_url_unsupported", str(exc)) from exc
    return text


def _checked_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_FIELD_CHARS:
        raise SubmissionError(
            "field_too_long",
            f"{label} is {len(text)} characters; the limit is {MAX_TEXT_FIELD_CHARS}",
            field=label,
        )
    return text


def _checked_reason(value: Any) -> str | None:
    """A cancel reason, which is the same kind of text in the same kind of column.

    It goes into ``jobs.error``, and every listing reads that column back -- so
    the ceiling that keeps a pasted log out of ``purpose`` keeps it out here too.
    """
    text = _checked_text(value, "reason")
    return text or None


def _checked_fingerprint(value: Any) -> Mapping[str, Any] | None:
    if value in (None, {}, "", []):
        return None
    if not isinstance(value, Mapping):
        raise SubmissionError(
            "env_fingerprint_invalid", "env_fingerprint must be an object when present"
        )
    size = len(json.dumps(dict(value), ensure_ascii=False).encode("utf-8"))
    if size > MAX_FINGERPRINT_BYTES:
        raise SubmissionError(
            "env_fingerprint_too_large",
            f"env_fingerprint is {size} bytes; the limit is {MAX_FINGERPRINT_BYTES}",
        )
    return dict(value)


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SubmissionError("field_type_invalid", f"{label} must be an object", field=label)
    return value


def _as_list(value: Any) -> list[str]:
    if value is None or isinstance(value, str):
        return [value] if isinstance(value, str) else []
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def _new_job_id() -> str:
    """A filesystem-safe id: the data plane puts it in paths and signed URLs."""
    return f"job-{secrets.token_hex(_JOB_ID_BYTES)}"
