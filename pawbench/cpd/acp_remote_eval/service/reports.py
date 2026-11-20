# -*- coding: utf-8 -*-
"""Everything a reader is shown about a job: detail tiers, results, report files.

The queue answers "is my job moving".  This answers "what did the subject do, how
did it score, and what may I send to the people who own the agent".  That second
question is why the module exists as one place rather than as fields picked by
each route: the two sensitivity tiers differ *by content*, and the design rule
(design section 4.1) is that the trimming happens inside the aggregation -- a
route that forgot to trim is a leak, and there are five routes here.

The line between the tiers is not "who is asking": both are readable by everyone
on the allowlist.  It is "could this leave the allowlist", because the shared
tier is the one a submitter forwards to the team being evaluated.  So ``shared``
carries the prompt, the labels, the score, the breakdown, the timeline and the
artifact list, while the rubric text, the judge's per-item reasoning and the
files themselves stay in ``full``.  The grading code -- ``automated_checks`` --
is in neither: it is the answer key, and no tier is a licence to publish it.

Nothing here writes.  It reads the rows the runner and the exchange already
own, renders report files on demand, and hands links to
:class:`.exchange.Exchange` so every absolute URL still comes from one place.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import secrets
import threading
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..redact import url_without_credentials
from .datasets import DatasetService, TaskSummary
from .exchange import Exchange
from .runner import STATUS_FAILED, STATUS_MISSING, STATUS_PENDING, STATUS_SKIPPED
from .schedule import Clock, SystemClock
from .store import Store

logger = logging.getLogger(__name__)

SENSITIVITY_SHARED = "shared"
SENSITIVITY_FULL = "full"
SENSITIVITIES = (SENSITIVITY_SHARED, SENSITIVITY_FULL)

FORMAT_JSON = "json"
FORMAT_MD = "md"
FORMAT_HTML = "html"
FORMAT_ZIP = "zip"
REPORT_FORMATS = (FORMAT_JSON, FORMAT_MD, FORMAT_HTML, FORMAT_ZIP)

#: What each format is written as, and the extension a report file carries.
_FORMAT_SUFFIX = {FORMAT_JSON: "json", FORMAT_MD: "md", FORMAT_HTML: "html", FORMAT_ZIP: "zip"}

#: ``zip`` is the only format that carries another party's files, so it exists
#: only at the tier that is not forwarded.  Refused as a mismatch, not as a
#: permission error -- both tiers are open to every whitelisted caller, so a 403
#: here would send the reader off to ask for a scope that does not exist.
_FORMAT_TIER_LIMIT = {FORMAT_ZIP: SENSITIVITY_FULL}

#: A transcript page small enough that the dashboard can render it inline; the
#: ceiling is what keeps ``?limit=`` from turning one read into the whole file.
DEFAULT_TRANSCRIPT_PAGE = 200
MAX_TRANSCRIPT_PAGE = 1000

#: The three answers a transcript page can come back with, and the only two that
#: are not "the file read fine" are spelled out because a page of nothing is
#: otherwise three different situations wearing one shape: a task that never
#: started, and a file this process cannot open, are not the same fact.
TRANSCRIPT_OK = "ok"
TRANSCRIPT_ABSENT = "absent"
TRANSCRIPT_UNREADABLE = "unreadable"

#: A rubric excerpt, not a rubric: capped so a full report cannot be paged
#: through to read a task's grading text out of the service.
_RUBRIC_EXCERPT_CHARS = 600

#: The dimensions the catalogue can label a task with, in the order the report
#: prints them.  ``values_for`` is the single place that knows how each one is
#: spelled in the front matter, so the slices are built from it rather than from
#: a second copy of that knowledge.
_SLICE_KEYS = ("scenario", "capability", "complexity", "environment", "modality", "source")


class ReportError(ValueError):
    """A detail view that cannot be built, with the code the boundary maps."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class Reports:
    """Reads one job and renders it at a chosen sensitivity."""

    def __init__(
        self,
        store: Store,
        exchange: Exchange,
        datasets: DatasetService,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.exchange = exchange
        self.datasets = datasets
        self.clock: Clock = clock or SystemClock()
        # Guards only the step that decides whether this fingerprint still has no
        # file, so it is held for a write and a hash, never for a render.
        self._report_lock = threading.Lock()

    # ── the two detail views ──────────────────────────────────────────────────

    def job_detail(self, job_id: str, sensitivity: str = SENSITIVITY_SHARED) -> dict[str, Any]:
        """One job as a reader sees it: config, sources, progress, scores, tasks.

        Called by ``GET /v1/jobs/{id}/detail``, by the report renderer, and by
        the MCP tool that answers "how did that run go" -- three readers, one
        field list, so the tier cannot drift between them.
        """
        tier = check_sensitivity(sensitivity)
        job = self._job(job_id)
        rows = self.store.list_job_tasks(job_id)
        bodies = self._bodies(job_id)
        artifacts = _artifacts_by_task(self.store, job_id)
        progress = _progress(rows)
        return {
            "job_id": job_id,
            "sensitivity": tier,
            "generated_at": self.clock.now().isoformat(timespec="seconds"),
            "status": job["status"],
            "error": job["error"],
            "submitter": job["submitter"],
            "product": job["product"],
            "purpose": job["purpose"],
            # The address the runner dials, not the one a report forwards: an
            # endpoint that takes its key as userinfo or ``?key=`` is common, and
            # the shared tier is meant to leave this service.
            "acp_url": url_without_credentials(job["acp_url"]),
            "window": _window(job),
            "env_fingerprint": job["env_fingerprint"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "sources": self.sources(job_id),
            "progress": progress,
            "score": _score(rows),
            "slices": _slices(rows, bodies),
            "tasks": [
                self._task_entry(job_id, row, tier, bodies, artifacts.get(str(row["task_id"]), []))
                for row in rows
            ],
            "full_only": tier == SENSITIVITY_FULL,
        }

    def task_detail(
        self,
        job_id: str,
        task_id: str,
        sensitivity: str = SENSITIVITY_SHARED,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        """One task: the breakdown, the judge's reasoning at full tier, the files."""
        tier = check_sensitivity(sensitivity)
        self._job(job_id)
        row = self._task_row(job_id, task_id, attempt)
        entry = self._task_entry(
            job_id,
            row,
            tier,
            self._bodies(job_id),
            self.store.list_artifacts(job_id, task_id=task_id),
        )
        entry["transcript"] = self.transcript(job_id, task_id, attempt=int(row["attempt"]))
        return entry

    def results(self, job_id: str) -> dict[str, Any]:
        """The job in the shape ``submissions/*.json`` already uses.

        Same keys, so a remote run lands on the same leaderboard as a local one,
        plus the ``environment`` block -- the submission's fingerprint and
        endpoint -- because for a remote subject the environment *is* the result's
        provenance.
        """
        job = self._job(job_id)
        rows = self.store.list_job_tasks(job_id)
        bodies = self._bodies(job_id)
        scored = _scored(rows)
        return {
            "run": job_id,
            "model": _models(rows),
            "harness": job["product"] or "",
            "overall": _mean(row["score"] for row in scored),
            "automated": _mean(
                row["score"] for row in scored if row["grading_type"] == "automated"
            ),
            "judge": _mean(row["score"] for row in scored if row["grading_type"] == "llm_judge"),
            "tasks": len(scored),
            "tasks_total": len(rows),
            "tasks_errored": _count(rows, STATUS_FAILED),
            "tasks_missing": _count(rows, STATUS_MISSING),
            "missing_metadata": _count(rows, STATUS_SKIPPED) + _count(rows, STATUS_PENDING),
            "updated": job["finished_at"] or job["created_at"],
            "by_complexity": _slice_map(rows, bodies, "complexity"),
            "by_environment": _slice_map(rows, bodies, "environment"),
            "by_scenario": _slice_map(rows, bodies, "scenario"),
            "by_scenario_top": _slice_map(rows, bodies, "scenario", top=True),
            "by_modality": _slice_map(rows, bodies, "modality"),
            "by_channel": _slice_map(rows, bodies, "modality", channel=True),
            "by_capability": _slice_map(rows, bodies, "capability"),
            "by_source": _slice_map(rows, bodies, "source"),
            "by_category": _slice_map(rows, bodies, "category"),
            "by_subcategory": _slice_map(rows, bodies, "subcategory"),
            "by_grading": _slice_map(rows, bodies, "grading"),
            "environment": {
                "fingerprint": job["env_fingerprint"],
                "acp_url": url_without_credentials(job["acp_url"]),
                "product": job["product"],
            },
            "task_scores": [
                {
                    "task_id": row["task_id"],
                    "attempt": int(row["attempt"] or 1),
                    "status": row["status"],
                    "score": row["score"],
                    "grading_type": row["grading_type"],
                }
                for row in rows
            ],
        }

    def sources(self, job_id: str) -> list[dict[str, Any]]:
        """What the submitter asked for, dataset by dataset.

        The snapshot rows rather than a fresh resolve: a dataset edited after
        the job ran must not rewrite what the job actually covered.
        """
        return [
            {
                "dataset_id": row["dataset_id"],
                "dataset_kind": row["dataset_kind"],
                "requested_by": row["requested_by"],
                "task_count": len(row["resolved_task_ids"] or ()),
                "task_ids": list(row["resolved_task_ids"] or ()),
            }
            for row in self.store.list_job_datasets(job_id)
        ]

    def transcript(
        self,
        job_id: str,
        task_id: str,
        *,
        attempt: int = 1,
        cursor: int = 0,
        limit: int = DEFAULT_TRANSCRIPT_PAGE,
    ) -> dict[str, Any]:
        """A page of the run's timeline, in the shape the shared tier allows.

        Paged and summarised on purpose: the JSONL is the full stream, and a
        detail route that returned it whole would put every tool argument -- the
        subject's own files included -- into a response the dashboard renders.
        """
        # The row is looked up before the file, so a mistyped task answers
        # ``task_not_found`` instead of a well-formed page of nothing -- an empty
        # transcript is also what a task that never started legitimately has.
        self._job(job_id)
        self._task_row(job_id, task_id, int(attempt))
        page = max(1, min(int(limit), MAX_TRANSCRIPT_PAGE))
        start = max(0, int(cursor))
        path = self.exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
        window, total, state = _read_window(path, start, page)
        events, damaged = _timeline_events(window)
        if state == TRANSCRIPT_UNREADABLE:
            logger.warning(
                "transcript page found the file and could not read it",
                extra={
                    "job_id": job_id,
                    "task_id": task_id,
                    "attempt": int(attempt),
                    "transcript_state": state,
                },
            )
        # The cursor counts the lines read, not the events made: a damaged line
        # still has to be stepped over, or the next page re-reads it forever.
        ahead = start + len(window)
        return {
            "task_id": task_id,
            "attempt": int(attempt),
            "cursor": start,
            "limit": page,
            "total_events": total,
            "next_cursor": ahead if ahead < total else None,
            "events": events,
            "transcript_state": state,
            "damaged_events": damaged,
        }

    # ── report files ──────────────────────────────────────────────────────────

    def report(
        self,
        job_id: str,
        *,
        fmt: str = FORMAT_JSON,
        sensitivity: str = SENSITIVITY_SHARED,
    ) -> dict[str, Any]:
        """Render a report and hand back a link, never the bytes.

        The file is cached under the fingerprint of the rows it was built from,
        which is what makes the design's staleness rule need no bookkeeping: a
        job that finishes another task gets a different fingerprint, so the old
        file is simply not what a fresh request asks for.
        """
        tier = check_sensitivity(sensitivity)
        format_ = check_format(fmt, tier)
        rows = self.store.list_job_tasks(job_id)
        fingerprint = _fingerprint(job_id, tier, rows)
        filename = f"report-{fingerprint[:16]}-{tier}.{_FORMAT_SUFFIX[format_]}"
        path = self.exchange.report_path(job_id, filename)
        digest, size = self._ensure_report_file(path, job_id, tier, format_, rows)
        return {
            "job_id": job_id,
            "format": format_,
            "sensitivity": tier,
            "filename": filename,
            "sha256": digest,
            "size": size,
            "url": self.exchange.report_link(job_id, filename),
            "expires_at": self.exchange.report_expires_at().isoformat(timespec="seconds"),
            "stale_before": fingerprint,
        }

    def _ensure_report_file(
        self,
        path: Path,
        job_id: str,
        tier: str,
        fmt: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> tuple[str, int]:
        """Make this fingerprint's report file exist, then describe the landed bytes.

        The name already records which state of the job the file holds, so a
        request that finds it present renders nothing.  Two that arrive together
        both do the work -- the render stays outside the lock, because a 64 MB zip
        is the slow part and two different jobs have no reason to queue -- and the
        lock picks which of them writes.  The two renders are not interchangeable:
        ``generated_at`` is in the payload and not in the fingerprint, so they
        differ by at least a second of clock.  Whoever loses therefore reports the
        winner's numbers: the ``sha256`` returned here is what a submitter forwards
        to the team that owns the agent, and a checksum of bytes that never reached
        the disk fails on their side with no way to tell who to blame.
        """
        if path.is_file():
            return _digest_and_size(path)
        payload = self.job_detail(job_id, tier)
        data = self._render(fmt, payload, job_id, rows, tier)
        with self._report_lock:
            if path.is_file():
                return _digest_and_size(path)
            _write(path, data)
            logger.info(
                "report rendered",
                extra={"job_id": job_id, "format": fmt, "sensitivity": tier, "bytes": len(data)},
            )
        return hashlib.sha256(data).hexdigest(), len(data)

    def artifact_file(self, job_id: str, task_id: str, attempt: int, raw_path: str) -> Path:
        """One result file back out, for the route the download list points at.

        The path is resolved by :meth:`.exchange.Exchange.upload_path` -- the
        same call that decided where the agent's PUT would land -- so a download
        cannot reach a location the upload rules would have refused, and a bad
        path arrives here as the data plane's own ``ExchangeError``, with the
        status its code already has.
        """
        if not str(raw_path or "").strip():
            # The upload door calls a blank path ``empty_path``; a download that
            # answered ``path_escape`` instead would make the same mistake cost
            # two different sentences depending on which side you were on.
            raise ReportError(
                "empty_path", "an artifact download needs a path", path=raw_path
            )
        path = self.exchange.upload_path(job_id, task_id, attempt, raw_path, create=False)
        if not path.is_file():
            raise ReportError(
                "artifact_not_found",
                f"job {job_id} task {task_id} attempt {attempt} has no '{raw_path}'",
                path=raw_path,
            )
        return path

    def _render(
        self,
        fmt: str,
        payload: Mapping[str, Any],
        job_id: str,
        rows: Sequence[Mapping[str, Any]],
        tier: str,
    ) -> bytes:
        if fmt == FORMAT_JSON:
            return (json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n").encode()
        if fmt in (FORMAT_MD, FORMAT_HTML):
            text = _markdown(payload, self.results(job_id))
            if fmt == FORMAT_MD:
                return text.encode("utf-8")
            return _html(payload["job_id"], text).encode("utf-8")
        return _zip(self.exchange, job_id, payload, rows, tier)

    # ── one task's fields, trimmed here and nowhere else ──────────────────────

    def _task_entry(
        self,
        job_id: str,
        row: Mapping[str, Any],
        tier: str,
        bodies: Mapping[str, tuple[TaskSummary, Any]],
        recorded: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        task_id = str(row["task_id"])
        attempt = int(row["attempt"] or 1)
        summary, task = bodies.get(task_id, (None, None))
        # *recorded* is this task's slice of one query the caller already made,
        # shaped twice: the list every tier shows, and the download entries only
        # the full tier gets.
        entry: dict[str, Any] = {
            "task_id": task_id,
            "attempt": attempt,
            "status": row["status"],
            "score": row["score"],
            "grading_type": row["grading_type"] or (task.grading_type if task else None),
            "failure_reason": row["failure_reason"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_s": row["duration_s"],
            "protocol_written": int(row["protocol_written"] or 0),
            "out_of_band_count": int(row["out_of_band_count"] or 0),
            "subject_model_reported": row["subject_model_reported"],
            "resolved_from": list(row["resolved_from"] or ()),
            "automated_breakdown": row["automated_breakdown"],
            "artifacts": [
                {
                    "path": str(item["path"]),
                    "size": int(item["size"] or 0),
                    "sha256": str(item["sha256"]),
                    "kind": str(item["kind"]),
                }
                for item in recorded
            ],
        }
        if summary is not None:
            entry["name"] = summary.name
            entry["labels"] = dict(summary.labels)
            entry["has_attachments"] = summary.has_attachments
        if task is not None:
            entry["prompt"] = task.prompt
        if tier == SENSITIVITY_FULL:
            entry["judge_notes"] = row["judge_notes"]
            entry["judge_served_models"] = row["judge_served_models"]
            entry["workspace_path"] = row["workspace_path"]
            entry["transcript_path"] = row["transcript_path"]
            entry["expected_behavior"] = task.expected_behavior if task else None
            entry["rubric_excerpt"] = _excerpt(task.llm_judge_rubric if task else None)
            entry["downloads"] = [
                _artifact_link(job_id, task_id, attempt, str(item["path"]))
                for item in recorded
            ]
        return entry

    # ── reads that every method above shares ──────────────────────────────────

    def _job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise ReportError("job_not_found", f"no such job: {job_id}")
        return job

    def _task_row(self, job_id: str, task_id: str, attempt: int | None) -> dict[str, Any]:
        """One task's row: the attempt asked for, or the latest one recorded."""
        wanted = str(task_id or "")
        if attempt is None:
            rows = [row for row in self.store.list_job_tasks(job_id) if row["task_id"] == wanted]
            if not rows:
                raise ReportError("task_not_found", f"job {job_id} never ran '{wanted}'")
            return max(rows, key=lambda row: int(row["attempt"] or 1))
        row = self.store.get_job_task(job_id, wanted, int(attempt))
        if row is None:
            raise ReportError(
                "task_not_found", f"job {job_id} has no attempt {attempt} for '{wanted}'"
            )
        return row

    def _bodies(self, job_id: str) -> dict[str, tuple[TaskSummary, Any]]:
        """Catalogue summary and task body per task id, from this job's snapshots.

        Read through the datasets the job *ran* with, so a task that a dataset
        lost since the run still renders the version that was scored.  A task
        id the catalogue no longer knows keeps its rows and simply has no
        labels -- a deleted fixture must not blank a finished job's report.
        """
        found: dict[str, tuple[TaskSummary, Any]] = {}
        for row in self.store.list_job_datasets(job_id):
            dataset_id = str(row["dataset_id"])
            try:
                record = self.datasets.get(dataset_id)
                summaries = {s.task_id: s for s in self.datasets.task_summaries(record)}
                tasks = {t.task_id: t for t in self.datasets.tasks_for_run(dataset_id)}
            except Exception as exc:  # a dataset edited away is a gap, not an error
                logger.warning(
                    "report sources incomplete",
                    extra={"job_id": job_id, "dataset_id": dataset_id, "error": repr(exc)},
                )
                continue
            for task_id, summary in summaries.items():
                entry = found.get(task_id)
                if entry is None or entry[1] is None:
                    found[task_id] = (summary, tasks.get(task_id))
        return found


def check_sensitivity(value: Any) -> str:
    """The tier, or a refusal naming the two that exist.

    Checked rather than defaulted: a dashboard that misspells ``full`` and is
    quietly served the shared tier believes it just sent the judge's reasoning
    to the subject.
    """
    text = str(value or SENSITIVITY_SHARED).strip().casefold()
    if text not in SENSITIVITIES:
        raise ReportError(
            "sensitivity_unknown",
            f"sensitivity is 'shared' or 'full', not '{value}'",
            allowed=list(SENSITIVITIES),
        )
    return text


def check_format(value: Any, tier: str) -> str:
    """The report format, refusing the pairs that cannot exist together."""
    text = str(value or FORMAT_JSON).strip().casefold()
    if text not in REPORT_FORMATS:
        raise ReportError(
            "report_format_unsupported",
            f"no report format '{value}'; the formats are {list(REPORT_FORMATS)}",
            allowed=list(REPORT_FORMATS),
        )
    required = _FORMAT_TIER_LIMIT.get(text)
    if required is not None and tier != required:
        raise ReportError(
            "sensitivity_format_mismatch",
            f"'{text}' bundles result files, so it is only rendered at "
            f"'{required}' sensitivity; ask for ?sensitivity={required} or use "
            f"'{FORMAT_JSON}'",
            format=text,
            sensitivity=tier,
            required=required,
        )
    return text


# ── aggregation helpers ───────────────────────────────────────────────────────


def _progress(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(rows), "by_status": counts, "scored": len(_scored(rows))}


def _scored(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The tasks that count: the ones a grader actually gave a number to.

    Judged by the score rather than by ``status == finished`` because the
    denominator has to survive a grader that broke on a finished task -- and
    because ``skipped`` and ``pending`` must stay out of it: a task the service
    never started says nothing about the subject, and counting it as a zero is
    how an outage becomes a capability result.
    """
    return [row for row in rows if row["score"] is not None]


def _score(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["score"]) for row in _scored(rows)]
    return {
        "mean": _mean(values),
        "count": len(values),
        "best": max(values) if values else None,
        "worst": min(values) if values else None,
    }


def _slices(
    rows: Sequence[Mapping[str, Any]], bodies: Mapping[str, Any]
) -> dict[str, dict[str, float]]:
    """Mean score per label value, for the comparison the detail view shows.

    A task with three capabilities lands in all three buckets: the point of the
    slice is "where is this subject weak", and picking one bucket per task would
    hide that.
    """
    out: dict[str, dict[str, float]] = {}
    for key in _SLICE_KEYS:
        out[key] = _slice_map(rows, bodies, key, top=key == "scenario")
    out["grading"] = _slice_map(rows, bodies, "grading")
    return out


def _slice_map(
    rows: Sequence[Mapping[str, Any]],
    bodies: Mapping[str, Any],
    key: str,
    *,
    top: bool = False,
    channel: bool = False,
) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if row["score"] is None:
            continue
        for name in _labels_for(row["task_id"], bodies.get(row["task_id"]), key, top, channel):
            buckets.setdefault(name, []).append(float(row["score"]))
    return {name: round(sum(values) / len(values), 4) for name, values in sorted(buckets.items())}


def _labels_for(
    task_id: Any,
    entry: Any,
    key: str,
    top: bool,
    channel: bool,
) -> list[str]:
    """The values a task carries on one slice dimension, empty when it has none."""
    if entry is None:
        return []
    summary, task = entry
    if key == "grading":
        return [str(task.grading_type)] if task is not None else []
    if key == "category":
        return [str(task.category)] if task is not None else []
    if key == "subcategory":
        # A top-level front matter field, not a label: the catalogue never filters
        # on it, but ``submissions/*.json`` buckets by it, so the leaderboard
        # column has to be filled from the same place the local scorer read it.
        if task is None:
            return []
        value = task.frontmatter.get("subcategory")
        return [str(value)] if value else []
    if channel:
        modality = summary.labels.get("modality")
        if isinstance(modality, Mapping):
            return sorted(_as_set(modality.get("channels")))
        return []
    if key == "modality":
        # ``by_modality`` holds the type and ``by_channel`` the channels, which
        # is why this does not fall through to ``values_for``: that union is
        # right for a catalogue filter -- match a task on either -- and wrong
        # for a slice, where it would score one channel as a modality.
        modality = summary.labels.get("modality")
        value = modality.get("type") if isinstance(modality, Mapping) else modality
        return [str(value)] if value else []
    try:
        values = sorted(summary.values_for(key))
    except KeyError:
        return []
    if top and key == "scenario":
        return sorted({value.split("/", 1)[0] for value in values if value})
    return [value for value in values if value]


def _count(rows: Sequence[Mapping[str, Any]], *statuses: str) -> int:
    return sum(1 for row in rows if str(row["status"]) in statuses)


def _models(rows: Sequence[Mapping[str, Any]]) -> str:
    """What the subjects said they ran, joined -- ``unknown`` stays visible."""
    found: set[str] = set()
    for row in rows:
        value = row["subject_model_reported"]
        if isinstance(value, (list, tuple, set)):
            found.update(str(item) for item in value)
        elif value:
            found.add(str(value))
    return ", ".join(sorted(found)) if found else "unknown"


def _mean(values: Iterable[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


def _fingerprint(
    job_id: str, tier: str, rows: Sequence[Mapping[str, Any]]
) -> str:
    """What the report was built from, so a newer job cannot reuse its file.

    Only the columns a reader can see in the numbers: a task that finished, or
    was re-run, changes it, while a label edited in the dataset does not -- the
    report would otherwise churn on every catalogue write.
    """
    seed = [tier]
    for row in sorted(rows, key=lambda item: (str(item["task_id"]), int(item["attempt"] or 1))):
        seed.append(
            f"{row['task_id']}#{row['attempt']}:{row['status']}:{row['score']}:"
            f"{row['finished_at']}:{row['artifact_count']}"
        )
    return hashlib.sha256("|".join(seed).encode("utf-8")).hexdigest()


def _window(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": job["window_kind"],
        "not_before": job["not_before"],
        "not_after": job["not_after"],
    }


def _excerpt(text: Any) -> str | None:
    if not text:
        return None
    return str(text)[:_RUBRIC_EXCERPT_CHARS]


def _as_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, Iterable):
        return {str(item) for item in value if item}
    return set()


def _read_window(path: Path, start: int, page: int) -> tuple[list[str], int, str]:
    """Lines ``[start, start + page)`` of a transcript, its length and its state.

    Streamed, not read whole: the file is the raw notification stream, a long run
    makes it tens of megabytes, and a page is 200 lines.  The walk still goes to
    the end because ``total_events`` is what a reader uses to know the run is
    longer than what it was handed.

    ``errors="replace"`` because a stream the harness wrote byte by byte can pick
    up one undecodable byte without losing its other 200 lines: a
    ``UnicodeDecodeError`` here would answer 500 for the whole page, on a run that
    is readable apart from one character.
    """
    window: list[str] = []
    total = 0
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return window, 0, TRANSCRIPT_ABSENT
    except OSError:
        # A directory where the file should be, a symlink chain, a mode this user
        # cannot read -- one state for all of them, because what a reader acts on
        # is "this run's transcript is not there for me", and the job, task and
        # attempt in the caller's log line say exactly which file to go and look
        # at.
        return window, 0, TRANSCRIPT_UNREADABLE
    try:
        with handle:
            for line in handle:
                if not line.strip():
                    continue
                if start <= total < start + page:
                    window.append(line.rstrip("\n"))
                total += 1
    except OSError:
        # The same answer as a file that would not open at all.  A read that dies
        # halfway -- a volume unmounted under the process, an I/O error on a
        # network disk -- leaves a page that is neither this run's transcript nor
        # a run that wrote nothing, and the reader has no way to tell which.
        return [], 0, TRANSCRIPT_UNREADABLE
    return window, total, TRANSCRIPT_OK


def _timeline_events(lines: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
    """One timeline entry per line, and how many lines gave no entry.

    The count travels with the page because a transcript that was truncated
    mid-write, or edited by something outside the harness, would otherwise look
    exactly like a run that stopped early -- and the reader cannot tell those
    apart from the browser.

    Only the line's own shape is treated as untrusted, so a damaged file costs a
    count and nothing else.  A failure raised while summarising a line that *is*
    a JSON object is a bug in this module and has to stay a 500, not join the
    count of bad input.

    ``RecursionError`` belongs with ``ValueError`` rather than with the bugs: the
    parser raises it on a line nested deeper than the interpreter's limit, which
    is a fact about a stream the subject's own tool calls helped write -- and
    ``json`` is documented to raise it, not to convert it.
    """
    events: list[dict[str, Any]] = []
    damaged = 0
    for text in lines:
        try:
            row = json.loads(text)
        except (ValueError, RecursionError):
            row = None
        if not isinstance(row, dict):
            damaged += 1
            continue
        events.append(_timeline_event(row))
    return events, damaged


#: A tool's arguments are summarised, never copied.  The values are the
#: subject's own inputs and one of them may be the contents of a file it read,
#: while what a reader of the timeline is comparing is which tool ran with which
#: fields and how it ended (design section 4.1).
_ARG_PREVIEW_CHARS = 40
_ARG_KEYS_SHOWN = 12


def _timeline_event(row: Mapping[str, Any]) -> dict[str, Any]:
    """One JSONL row down to the timeline the shared tier is made of.

    The file holds the raw ``session/update`` stream, not the message events the
    judge is given, so this reads the wire names (``sessionUpdate``, ``rawInput``)
    -- a summariser written against the judge shape would find nothing in it.
    """
    kind = str(row.get("sessionUpdate") or "other")
    entry: dict[str, Any] = {"kind": kind, "at": row.get("at")}
    if kind in ("tool_call", "tool_call_update"):
        entry["tool"] = str(row.get("title") or row.get("name") or "")
        entry["status"] = str(row.get("status") or "")
        entry["args"] = _args_summary(row.get("rawInput"))
        entry["result_chars"] = _result_length(row)
        return entry
    if kind in ("plan", "plan_update"):
        entries = row.get("entries") or row.get("plan") or []
        entry["steps"] = len(entries) if isinstance(entries, list) else 0
        return entry
    entry["chars"] = _text_length(row.get("content"))
    return entry


def _args_summary(raw_input: Any) -> dict[str, str]:
    source = raw_input if isinstance(raw_input, Mapping) else {}
    summary: dict[str, str] = {}
    names = sorted(str(name) for name in source)
    for name in names[:_ARG_KEYS_SHOWN]:
        summary[name] = _preview(str(source[name]))
    if len(names) > _ARG_KEYS_SHOWN:
        summary["…"] = f"{len(names) - _ARG_KEYS_SHOWN} more field(s)"
    return summary


def _preview(text: str) -> str:
    if len(text) <= _ARG_PREVIEW_CHARS:
        return text
    return f"{text[:_ARG_PREVIEW_CHARS]}… +{len(text) - _ARG_PREVIEW_CHARS} chars"


def _text_length(content: Any) -> int:
    """How many characters of text a notification carried, without keeping them."""
    return sum(_block_length(block) for block in _blocks(content))


def _result_length(row: Mapping[str, Any]) -> int:
    """How big a tool's result was, from the two places a result can be put.

    ``rawOutput`` first, then the content blocks -- the same order
    :func:`.acp.transcript._tool_output_blocks` reads them in, because an agent
    that returns a structured result uses the first and one that returns text
    uses the second.  Looking in only one would report real results as empty.
    """
    raw = row.get("rawOutput")
    if raw in (None, "", {}, []):
        return _text_length(row.get("content"))
    if isinstance(raw, str):
        return len(raw)
    return len(json.dumps(raw, ensure_ascii=False, default=str))


def _blocks(content: Any) -> list[Any]:
    if isinstance(content, Mapping):
        return [content]
    if isinstance(content, list):
        return list(content)
    return []


def _block_length(block: Any) -> int:
    if not isinstance(block, Mapping):
        return 0
    # A tool-call block wraps its content one level deeper than a message chunk
    # does (``{"type": "content", "content": {...}}``), so reading only the outer
    # mapping would find no ``text`` key and count every tool result as zero.
    inner = block.get("content")
    text = inner if isinstance(inner, Mapping) else block
    return len(str(text.get("text") or ""))


def _artifact_link(job_id: str, task_id: str, attempt: int, path: str) -> dict[str, Any]:
    """How the full tier's download list says to fetch one result file.

    A route plus a query, not a presigned link: these files are read back with
    the caller's own whitelist token, which is the tier's whole guarantee -- a
    URL that carried its access in itself would outlive the run it came from and
    stay valid for whoever it got forwarded to.
    """
    return {
        "path": path,
        "href": f"/v1/jobs/{job_id}/tasks/{task_id}/attempts/{attempt}/artifacts",
        "query": {"path": path},
    }


def _digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), path.stat().st_size


def _write(path: Path, data: bytes) -> None:
    """Write the report through a temporary name, then move it into place.

    The link a caller receives is the final name, so a reader that arrives while
    a 64 MB zip is still being built must see either nothing or a whole file --
    never the half that ``open(path, "wb")`` would leave behind.

    The temporary name carries a random suffix, the same way ``exchange._stage``
    names a quarantined upload, because one fixed name is not one file per
    writer: two renderers that reach the same name at the same moment write into
    each other's bytes and ``replace`` the loser's half.  What landed then looked
    like a cached report and stayed there.  The ``finally`` is what pays for the
    suffix -- a name nobody else owns is a file nobody else will clean up.
    """
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifacts_by_task(store: Store, job_id: str) -> dict[str, list[Mapping[str, Any]]]:
    """Every artifact row of one job, bucketed by task id, from a single query.

    Both readers that walk a job's tasks need them -- the detail view shapes
    each row's ``artifacts`` and ``downloads``, the zip writes their files -- and
    asking ``list_artifacts(job_id, task_id=...)`` inside those loops means one
    query per task on the route the dashboard polls.
    """
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    for item in store.list_artifacts(job_id):
        by_task.setdefault(str(item["task_id"]), []).append(item)
    return by_task


def _zip(
    exchange: Exchange,
    job_id: str,
    payload: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    tier: str,
) -> bytes:
    """The detail document plus every file the run actually collected."""
    buffer = io.BytesIO()
    by_task = _artifacts_by_task(exchange.store, job_id)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"detail-{tier}.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )
        for row in rows:
            task_id = str(row["task_id"])
            attempt = int(row["attempt"] or 1)
            transcript = exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
            if transcript.is_file():
                archive.write(transcript, f"transcripts/{task_id}-{attempt}.jsonl")
            for item in by_task.get(task_id, ()):
                relative = str(item["path"])
                path = exchange.upload_path(job_id, task_id, attempt, relative, create=False)
                if path.is_file():
                    archive.write(path, f"artifacts/{task_id}-{attempt}/{relative}")
    return buffer.getvalue()


def _markdown(payload: Mapping[str, Any], results: Mapping[str, Any]) -> str:
    """The human-readable report: the scores, then one block per task."""
    lines = [
        f"# Job {payload['job_id']}",
        "",
        f"- status: {payload['status']}",
        f"- sensitivity: {payload['sensitivity']}",
        f"- subject: {payload['product']} at {payload['acp_url']}",
        f"- mean score: {results['overall']} over {results['tasks']} scored task(s)",
        f"- by status: {results['tasks_errored']} failed, {results['tasks_missing']} missing, "
        f"{results['missing_metadata']} never started",
        "",
        "## Slices",
        "",
    ]
    for key, values in results.items():
        if key.startswith("by_") and isinstance(values, dict):
            rendered = ", ".join(f"{name}={value}" for name, value in values.items()) or "-"
            lines.append(f"- {key[3:]}: {rendered}")
    lines += ["", "## Tasks", ""]
    for task in payload["tasks"]:
        lines += [
            f"### {task['task_id']}",
            "",
            f"- status: {task['status']}, score: {task['score']}",
            f"- duration: {task['duration_s']}s, artifacts: {len(task['artifacts'])}",
        ]
        if task.get("failure_reason"):
            lines.append(f"- failure: {task['failure_reason']}")
        if task.get("judge_notes"):
            lines.append(f"- judge: {_judge_line(task['judge_notes'])}")
        lines.append("")
    return "\n".join(lines)


def _judge_line(notes: Any) -> str:
    """One judge row of the markdown report: its prose, then its numbers.

    :mod:`.grading` writes ``judge_notes`` as ``{"scores": ..., "notes": ...}``.
    Rendering the mapping itself would put Python syntax into the one report
    format people paste into chat, and the criterion numbers are the part a
    reader actually compares.
    """
    if not isinstance(notes, Mapping):
        return str(notes)
    scores = notes.get("scores") or {}
    rendered = ", ".join(f"{name}={value}" for name, value in scores.items())
    text = str(notes.get("notes") or "").strip()
    if not rendered:
        return text
    return f"{text} (scores: {rendered})" if text else f"scores: {rendered}"


def _html(job_id: str, body: str) -> str:
    """The markdown report inside one readable page.

    Deliberately unstyled: the artifact is a file people forward, and a report
    that depends on the dashboard's assets is a report that renders blank for
    whoever received it.
    """
    return (
        "<!doctype html>\n<meta charset=\"utf-8\">\n"
        f"<title>PawBench job {job_id}</title>\n"
        "<style>body{max-width:60rem;margin:3rem auto;"
        "font:16px/1.5 system-ui}pre{white-space:pre-wrap}</style>\n"
        f"<pre>{_escape(body)}</pre>\n"
    )


def _escape(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
