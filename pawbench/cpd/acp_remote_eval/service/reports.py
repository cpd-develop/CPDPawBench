# -*- coding: utf-8 -*-
"""Everything a reader is shown about a job: the detail, results, report files.

The queue answers "is my job moving".  This answers "what did the subject do, and
how did it score".  That is one view with one field list, which is why the module
keeps it as one place rather than as fields picked by each route: five routes
read it, and a field a route forgot to include is a question the reader cannot
answer.

There is no second, trimmed copy of that view.  An earlier design had one --
``shared`` was what a submitter forwarded and ``full`` added the rubric text, the
judge's reasoning and the files -- and it was dropped: two shapes of the same
document meant every route decided twice what a reader may see, and the answer
that was actually wanted was always the complete one.  The allowlist is the
boundary now; a caller with a token sees the run.

The one thing that stays out is ``automated_checks``: the grading code is the
answer key, and it is not rendered by anything, for anyone.

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
from .exchange import Exchange, ExchangeError
from .preview import preview_of as _preview_of
from .runner import STATUS_FAILED, STATUS_MISSING, STATUS_PENDING, STATUS_SKIPPED
from .schedule import Clock, SystemClock
from .store import Store

logger = logging.getLogger(__name__)

FORMAT_JSON = "json"
FORMAT_MD = "md"
FORMAT_HTML = "html"
FORMAT_ZIP = "zip"
REPORT_FORMATS = (FORMAT_JSON, FORMAT_MD, FORMAT_HTML, FORMAT_ZIP)

#: What each format is written as, and the extension a report file carries.
_FORMAT_SUFFIX = {FORMAT_JSON: "json", FORMAT_MD: "md", FORMAT_HTML: "html", FORMAT_ZIP: "zip"}

#: A transcript page small enough that the dashboard can render it inline; the
#: ceiling is what keeps ``?limit=`` from turning one read into the whole file.
DEFAULT_TRANSCRIPT_PAGE = 200
MAX_TRANSCRIPT_PAGE = 1000

#: The dashboard pages *beats*, not raw notifications: twenty streamed chunks
#: are one sentence, and a reader turning a page wants the next sentence.  The
#: raw line cursor stays inside the service -- it is how a beat finds its lines
#: again when the reader asks to expand one -- and is never shown in the UI.
DEFAULT_BEAT_PAGE = 10
BEAT_PAGE_SIZES = (10, 20, 50)
BEAT_VOICES = ("all", "talk", "tool", "thought", "plan")

#: Expanding is an explicit act, so it returns everything the beat carried.  A
#: ceiling this high is a guard against one pathological tool argument, not a
#: preview: it is a few hundred screens of text, and ``truncated`` says so if a
#: beat ever reaches it.
_FULL_CONTENT_CHARS = 200_000

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

#: How much of a task's prompt the markdown report inlines.  Long enough for
#: the instructions a reader needs to judge the answer, short enough that a
#: 200-task report stays a document rather than an archive.
_REPORT_PROMPT_CHARS = 1200

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
    """Reads one job, and renders what it did as a document."""

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

    # ── the detail, and one task of it ────────────────────────────────────────

    def job_detail(self, job_id: str) -> dict[str, Any]:
        """One job as a reader sees it: config, sources, progress, scores, tasks.

        Called by ``GET /v1/jobs/{id}/detail``, by the report renderer, and by
        the MCP tool that answers "how did that run go" -- three readers, one
        field list, so the shape cannot drift between them.
        """
        job = self._job(job_id)
        rows = self.store.list_job_tasks(job_id)
        bodies = self._bodies(job_id)
        roots = self._fixture_roots(job_id)
        artifacts = _artifacts_by_task(self.store, job_id)
        progress = _progress(rows)
        return {
            "job_id": job_id,
            "generated_at": self.clock.now().isoformat(timespec="seconds"),
            "status": job["status"],
            "error": job["error"],
            "submitter": job["submitter"],
            "product": job["product"],
            "purpose": job["purpose"],
            # The address the runner dials, not the one a report forwards: an
            # endpoint that takes its key as userinfo or ``?key=`` is common,
            # and a report is still a document somebody hands to a colleague.
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
                self._task_entry(
                    job_id,
                    row,
                    bodies,
                    roots,
                    artifacts.get(str(row["task_id"]), []),
                )
                for row in rows
            ],
        }

    def task_detail(
        self, job_id: str, task_id: str, attempt: int | None = None
    ) -> dict[str, Any]:
        """One task: the breakdown, the judge's reasoning, the files, a timeline."""
        self._job(job_id)
        row = self._task_row(job_id, task_id, attempt)
        entry = self._task_entry(
            job_id,
            row,
            self._bodies(job_id),
            self._fixture_roots(job_id),
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
        detail: bool = False,
    ) -> dict[str, Any]:
        """A page of the run's timeline.

        Paged and summarised on purpose: the JSONL is the full stream, and a
        detail route that returned it whole would put every tool argument -- the
        subject's own files included -- into a response the dashboard renders.

        ``detail`` is the dashboard's own request and nobody else's.  Off, a row
        is a size ("340 chars") and a tool's identity; on, it carries a *window*
        into what was said or returned -- a few hundred characters per event,
        still not the body -- because a timeline that only counts characters
        cannot be read, and the person reading it is deciding whether a score is
        fair.  The judge prompt and the MCP tools never pass it: their copies of
        a transcript are the capped event list, and a wider page would only cost
        them tokens.
        """
        # The row is looked up before the file, so a mistyped task answers
        # ``task_not_found`` instead of a well-formed page of nothing -- an empty
        # transcript is also what a task that never started legitimately has.
        self._job(job_id)
        self._task_row(job_id, task_id, int(attempt))
        page = max(1, min(int(limit), MAX_TRANSCRIPT_PAGE))
        start = max(0, int(cursor))
        path = self.exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
        # A page can begin in the middle of a tool call, and the line that named
        # the tool is then on the page before: without this the update draws as
        # an anonymous "工具调用" with a result and no arguments.  The label map is
        # filled during the walk that counts the file, and only for a detail page.
        labels: dict[str, tuple[str, str]] | None = {} if detail else None
        window, total, state = _read_window(path, start, page, labels=labels)
        events, damaged = _timeline_events(window, detail=detail, labels=labels)
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

    def trace(
        self,
        job_id: str,
        task_id: str,
        *,
        attempt: int = 1,
        page: int = 1,
        size: int = DEFAULT_BEAT_PAGE,
        voice: str = "all",
    ) -> dict[str, Any]:
        """One page of a run's *beats*: the things a person would name.

        :meth:`transcript` pages raw JSONL lines because the judge and the MCP
        tools consume them one by one.  A reader does not: twenty thought chunks
        are one thought, and a tool call and its update are one action.  Folding
        has to happen before paging, or "next page" advances the reader by
        twenty fragments of a sentence instead of by one sentence.

        The fold is done here on the server (the same rules the dashboard used
        to apply in the browser) so a page can be as small as ten beats without
        downloading the whole transcript to learn where beat eleven begins.
        Every beat keeps the raw line span it came from; that is the *internal*
        handle :meth:`trace_content` uses when a reader expands one.  It is not
        presented as a cursor in the UI.
        """
        self._job(job_id)
        self._task_row(job_id, task_id, int(attempt))
        width = size if size in BEAT_PAGE_SIZES else DEFAULT_BEAT_PAGE
        index = max(1, int(page))
        selected = voice if voice in BEAT_VOICES else "all"

        path = self.exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
        lines, total, state = _read_all(path)
        if state != TRANSCRIPT_OK:
            logger.warning(
                "trace page found the file and could not read it",
                extra={
                    "job_id": job_id,
                    "task_id": task_id,
                    "attempt": int(attempt),
                    "transcript_state": state,
                },
            )
        events, damaged = _timeline_events(lines, detail=True)
        all_beats = _fold_beats(events)
        counts = _voice_counts(all_beats)
        matches = [beat for beat in all_beats if _passes(beat, selected)]

        start = (index - 1) * width
        window = matches[start : start + width]
        # Give every beat a stable index in its *filtered* list, so the expand
        # route can name one without the reader ever seeing a line number.
        for offset, beat in enumerate(window):
            beat["index"] = start + offset

        return {
            "task_id": task_id,
            "attempt": int(attempt),
            "page": index,
            "size": width,
            "voice": selected,
            "total_beats": len(matches),
            "next_page": index + 1 if start + width < len(matches) else None,
            "beats": window,
            "counts": counts,
            "transcript_state": state,
            "damaged_events": damaged,
            "total_events": total,
        }

    def trace_content(
        self,
        job_id: str,
        task_id: str,
        *,
        attempt: int = 1,
        index: int = 0,
        voice: str = "all",
    ) -> dict[str, Any]:
        """The complete words of one beat, read only when a reader expands it.

        The list page stays bounded: it carries previews, because it renders
        hundreds of beats at once and a tool's argument may be a whole file.
        Opening a beat is a deliberate act, so this walks the same fold again
        and returns that beat's full text, arguments and result.  Nothing is
        clipped at the preview ceilings here; ``truncated`` is set only if the
        beat exceeds the much larger safety ceiling.
        """
        self._job(job_id)
        self._task_row(job_id, task_id, int(attempt))
        selected = voice if voice in BEAT_VOICES else "all"
        path = self.exchange.attempt_dir(job_id, task_id, attempt) / "transcript.jsonl"
        lines, _total, state = _read_all(path)
        events, _damaged = _timeline_events(lines, detail=True)
        matches = [beat for beat in _fold_beats(events) if _passes(beat, selected)]
        wanted = max(0, int(index))
        if state != TRANSCRIPT_OK or wanted >= len(matches):
            return {
                "task_id": task_id,
                "attempt": int(attempt),
                "index": wanted,
                "voice": selected,
                "text": "",
                "args": {},
                "output": "",
                "text_truncated": False,
                "output_truncated": False,
                "transcript_state": state,
                "found": False,
            }

        beat = matches[wanted]
        first, last = int(beat["from"]), int(beat["to"])
        # Re-read just this beat's lines at full length.  Parsing the whole file
        # again would be simple but would also copy every other tool's arguments
        # into a response for one card.
        portion = lines[first : last + 1]
        full_events, _ = _timeline_events(portion, full=True)
        full_beat = _fold_beats(full_events)[0]
        return {
            "task_id": task_id,
            "attempt": int(attempt),
            "index": wanted,
            "voice": selected,
            "kind": beat["voice"],
            "text": full_beat.get("text", ""),
            "args": full_beat.get("args", {}),
            "output": full_beat.get("output", ""),
            "text_truncated": bool(full_beat.get("text_truncated")),
            "output_truncated": bool(full_beat.get("output_truncated")),
            "transcript_state": state,
            "found": True,
        }

    # ── report files ──────────────────────────────────────────────────────────

    def report(self, job_id: str, *, fmt: str = FORMAT_JSON) -> dict[str, Any]:
        """Render a report and hand back a link, never the bytes.

        The file is cached under the fingerprint of the rows it was built from,
        which is what makes the design's staleness rule need no bookkeeping: a
        job that finishes another task gets a different fingerprint, so the old
        file is simply not what a fresh request asks for.
        """
        format_ = check_format(fmt)
        rows = self.store.list_job_tasks(job_id)
        fingerprint = _fingerprint(job_id, rows)
        filename = f"report-{fingerprint[:16]}.{_FORMAT_SUFFIX[format_]}"
        path = self.exchange.report_path(job_id, filename)
        digest, size = self._ensure_report_file(path, job_id, format_, rows)
        return {
            "job_id": job_id,
            "format": format_,
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
        payload = self.job_detail(job_id)
        data = self._render(fmt, payload, job_id, rows)
        with self._report_lock:
            if path.is_file():
                return _digest_and_size(path)
            _write(path, data)
            logger.info(
                "report rendered",
                extra={"job_id": job_id, "format": fmt, "bytes": len(data)},
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

    # ── the question's own files, and what is inside either kind ──────────────

    def attachment_file(
        self, job_id: str, task_id: str, attempt: int, raw_path: str
    ) -> Path:
        """One attachment of a task, for the route that hands the bytes over.

        Only a file the task *declares* can be asked for.  The session directory
        beside an attempt also holds whatever the agent wrote there, and a route
        that served any path under it would be a file browser over somebody
        else's working directory.
        """
        if not str(raw_path or "").strip():
            raise ReportError("empty_path", "an attachment needs a path", path=raw_path)
        summary, root = self._task_fixtures(job_id, task_id)
        declared = {str(item.get("dest", "")) for item in summary.workspace_files}
        if str(raw_path) not in declared:
            raise ReportError(
                "attachment_not_found",
                f"task {task_id} declares no attachment '{raw_path}'",
                path=raw_path,
            )
        path, _ = self._locate_fixture(job_id, task_id, attempt, summary, root, str(raw_path))
        return path

    def preview(
        self, job_id: str, task_id: str, attempt: int, kind: str, raw_path: str
    ) -> dict[str, Any]:
        """What is inside one file, as much of it as a dialog can show.

        Both kinds come through the same two lookups the downloads use, so a
        path refused there is refused here -- there is no second, looser way to
        reach a file.  The answer says what the file *is* (``text``, ``image``,
        ``binary``) rather than only what it says: a reader looking at a
        spreadsheet needs to be told to download it, not shown mojibake.
        """
        if kind == "artifact":
            target = self.artifact_file(job_id, task_id, attempt, raw_path)
        elif kind == "attachment":
            target = self.attachment_file(job_id, task_id, attempt, raw_path)
        else:
            raise ReportError(
                "preview_kind_unsupported",
                f"{kind!r} is not previewable; artifacts and attachments are",
                allowed=["artifact", "attachment"],
            )
        return _preview_of(target, raw_path)

    def _attachment_row(
        self,
        job_id: str,
        summary: TaskSummary,
        root: Path | None,
        attempt: int,
        item: Mapping[str, str],
    ) -> dict[str, Any]:
        """One line of the attachment list: what it is, how big, which copy."""
        dest = str(item.get("dest", ""))
        try:
            path, copy_from = self._locate_fixture(
                job_id, summary.task_id, attempt, summary, root, dest
            )
        except (ReportError, ExchangeError):
            # Declared but unreadable: not on disk, or a dest the exchange layer
            # refuses (a dot path, say).  Listed anyway -- the manifest says the
            # agent was given it, and hiding the row would hide that fact.  The
            # exchange error counts here too: it is raised per attachment by
            # `session_file`, and letting one bad dest escape would turn "this
            # file is odd" into a report that will not open.
            return {"path": dest, "size": None, "copy": None}
        return {"path": dest, "size": path.stat().st_size, "copy": copy_from}

    def _locate_fixture(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
        summary: TaskSummary,
        root: Path | None,
        dest: str,
    ) -> tuple[Path, str]:
        """The dataset's own file, else the copy this attempt laid down.

        The dataset first, because that is the question as it was written.  The
        per-attempt copy second, because it is what the agent actually had in
        front of it -- and the only survivor when a package has been pruned or a
        fixture edited away since the run.
        """
        if root is not None:
            try:
                source = self.exchange.fixture_for(summary, root, dest)
            except ExchangeError:
                source = None
            if source is not None and source.is_file():
                return source, "dataset"
        laid_down = self.exchange.session_file(job_id, task_id, attempt, dest)
        if laid_down.is_file():
            return laid_down, "attempt"
        raise ReportError(
            "attachment_not_found",
            f"task {task_id} attempt {attempt} has no attachment '{dest}'",
            path=dest,
        )

    def _task_fixtures(self, job_id: str, task_id: str) -> tuple[TaskSummary, Path | None]:
        """The summary that declares this task's attachments, and its dataset root."""
        for row in self.store.list_job_datasets(job_id):
            dataset_id = str(row["dataset_id"])
            try:
                record = self.datasets.get(dataset_id)
                for summary in self.datasets.task_summaries(record):
                    if summary.task_id == task_id:
                        return summary, self.datasets.root_for(dataset_id)
            except Exception as exc:  # same tolerance as _bodies, same reason
                logger.warning(
                    "attachment lookup skipped a dataset",
                    extra={"job_id": job_id, "dataset_id": dataset_id, "error": repr(exc)},
                )
                continue
        raise ReportError(
            "attachment_not_found",
            f"no dataset this job ran with still declares '{task_id}'",
            task_id=task_id,
        )

    def _fixture_roots(self, job_id: str) -> dict[str, Path]:
        """Task id -> the dataset root its ``workspace_files`` are relative to.

        Built once per detail view: the alternative is a dataset scan per task
        per attachment, and a 200-task report would do that two hundred times.
        """
        roots: dict[str, Path] = {}
        for row in self.store.list_job_datasets(job_id):
            dataset_id = str(row["dataset_id"])
            try:
                record = self.datasets.get(dataset_id)
                root = self.datasets.root_for(dataset_id)
                for summary in self.datasets.task_summaries(record):
                    roots.setdefault(summary.task_id, root)
            except Exception as exc:
                logger.warning(
                    "fixture roots incomplete",
                    extra={"job_id": job_id, "dataset_id": dataset_id, "error": repr(exc)},
                )
                continue
        return roots

    def _render(
        self,
        fmt: str,
        payload: Mapping[str, Any],
        job_id: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> bytes:
        if fmt == FORMAT_JSON:
            return (json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n").encode()
        if fmt in (FORMAT_MD, FORMAT_HTML):
            text = _markdown(payload, self.results(job_id))
            if fmt == FORMAT_MD:
                return text.encode("utf-8")
            return _html(payload["job_id"], text).encode("utf-8")
        return _zip(self.exchange, job_id, payload, rows)

    # ── one task's fields, assembled here and nowhere else ────────────────────

    def _task_entry(
        self,
        job_id: str,
        row: Mapping[str, Any],
        bodies: Mapping[str, tuple[TaskSummary, Any]],
        roots: Mapping[str, Path],
        recorded: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        task_id = str(row["task_id"])
        attempt = int(row["attempt"] or 1)
        summary, task = bodies.get(task_id, (None, None))
        # *recorded* is this task's slice of one query the caller already made,
        # used twice: as the list of files the agent wrote, and as the entries a
        # download link is built from.
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
            # What the attempt can be looked up by afterwards.  Both are absent
            # for attempts that never opened a session (skipped, cancelled
            # before dispatch), which is why they are read defensively: a
            # report must render for a row an older database wrote.
            "trace_id": _optional(row, "trace_id"),
            "session_id": _optional(row, "session_id"),
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
            # The question's own files: what was handed to the agent is part of
            # what was asked, and a reader who cannot see the attachment cannot
            # judge an answer about it.
            entry["attachments"] = [
                self._attachment_row(job_id, summary, roots.get(task_id), attempt, item)
                for item in summary.workspace_files
            ]
        if task is not None:
            entry["prompt"] = task.prompt
        # How the score was reached, and where the rest of it lives.  ``None`` is
        # an answer for each of these -- a task graded by rules has no rubric --
        # so they are present on every entry rather than conditionally absent.
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


def check_format(value: Any) -> str:
    """The report format, checked against the four that exist.

    Checked rather than defaulted, so a typo in a forwarder's script is a
    sentence about the typo instead of a silent Markdown download.
    """
    text = str(value or FORMAT_JSON).strip().casefold()
    if text not in REPORT_FORMATS:
        raise ReportError(
            "report_format_unsupported",
            f"no report format '{value}'; the formats are {list(REPORT_FORMATS)}",
            allowed=list(REPORT_FORMATS),
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


def _fingerprint(job_id: str, rows: Sequence[Mapping[str, Any]]) -> str:
    """What the report was built from, so a newer job cannot reuse its file.

    Only the columns a reader can see in the numbers: a task that finished, or
    was re-run, changes it, while a label edited in the dataset does not -- the
    report would otherwise churn on every catalogue write.
    """
    seed = [job_id]
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


def _optional(row: Mapping[str, Any], key: str) -> str | None:
    """A column that a row written before it existed does not have."""
    try:
        value = row[key]
    except (KeyError, IndexError):
        return None
    text = str(value or "").strip()
    return text or None


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


def _read_window(
    path: Path,
    start: int,
    page: int,
    *,
    labels: dict[str, tuple[str, str]] | None = None,
) -> tuple[list[str], int, str]:
    """Lines ``[start, start + page)`` of a transcript, its length and its state.

    Streamed, not read whole: the file is the raw notification stream, a long run
    makes it tens of megabytes, and a page is 200 lines.  The walk still goes to
    the end because ``total_events`` is what a reader uses to know the run is
    longer than what it was handed.

    ``errors="replace"`` because a stream the harness wrote byte by byte can pick
    up one undecodable byte without losing its other 200 lines: a
    ``UnicodeDecodeError`` here would answer 500 for the whole page, on a run that
    is readable apart from one character.

    ``labels``, when given, is filled with the ``toolCallId -> (title, name)`` seen
    *before* the window: a page that starts inside a tool call would otherwise
    draw that call's updates as an unnamed "工具调用".  They are collected on this
    walk rather than in a second pass over the prefix -- the file is already being
    streamed to the end for the count, and a dashboard asking for page 9 of a long
    run should not pay for the first eight pages twice.
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
                elif labels is not None and total < start:
                    _remember_label(line, labels)
                total += 1
    except OSError:
        # The same answer as a file that would not open at all.  A read that dies
        # halfway -- a volume unmounted under the process, an I/O error on a
        # network disk -- leaves a page that is neither this run's transcript nor
        # a run that wrote nothing, and the reader has no way to tell which.
        return [], 0, TRANSCRIPT_UNREADABLE
    return window, total, TRANSCRIPT_OK


def _read_all(path: Path) -> tuple[list[str], int, str]:
    """Every non-blank line of a transcript, its count and its state.

    Unlike :func:`_read_window` this keeps the lines, because folding a run into
    beats needs them all: the last chunk of a sentence may be the last line of
    the file.  The dashboard asks for a page of ten beats, not ten lines, and a
    line cursor would land in the middle of a thought.  The lines stay in the
    service -- only the folded beats cross the wire.
    """
    lines: list[str] = []
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return lines, 0, TRANSCRIPT_ABSENT
    except OSError:
        return lines, 0, TRANSCRIPT_UNREADABLE
    try:
        with handle:
            for line in handle:
                if line.strip():
                    lines.append(line.rstrip("\n"))
    except OSError:
        return [], 0, TRANSCRIPT_UNREADABLE
    return lines, len(lines), TRANSCRIPT_OK


#: ACP's notification name to the voice a reader hears.  Everything else is UI
#: chatter (usage, mode, available commands) and folds into one system beat.
_VOICE_OF = {
    "user_message_chunk": "user",
    "agent_message_chunk": "assistant",
    "agent_thought_chunk": "thought",
    "tool_call": "tool",
    "tool_call_update": "tool",
    "plan": "plan",
    "plan_update": "plan",
}

_VOICE_LABEL = {
    "user": "你",
    "assistant": "助手",
    "thought": "思考",
    "tool": "工具",
    "plan": "计划",
    "system": "系统",
}


def _passes(beat: Mapping[str, Any], voice: str) -> bool:
    if voice == "all":
        return True
    if voice == "talk":
        return beat.get("voice") in ("user", "assistant")
    return beat.get("voice") == voice


def _voice_counts(beats: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "all": len(beats),
        "talk": sum(1 for beat in beats if _passes(beat, "talk")),
        "tool": sum(1 for beat in beats if _passes(beat, "tool")),
        "thought": sum(1 for beat in beats if _passes(beat, "thought")),
        "plan": sum(1 for beat in beats if _passes(beat, "plan")),
    }


def _fold_beats(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold notifications into the beats a person would name.

    The rules are the ones the dashboard used to apply in the browser: adjacent
    chunks of one voice become one utterance; a tool's updates join the call
    that opened them, by call id when there is one and by adjacency when there
    is not; a plan's last update replaces the one before it.  Only *adjacent*
    chunks join, so a thought between two sentences stays between them.

    ``from`` and ``to`` are line numbers in the transcript.  They travel with
    the beat as its private handle for the full-content read; the UI never
    prints them as a cursor.
    """
    out: list[dict[str, Any]] = []
    for line, event in enumerate(events):
        kind = str(event.get("kind") or "other")
        voice = _VOICE_OF.get(kind, "system")
        call_id = str(event.get("tool_call_id") or "")
        previous = out[-1] if out else None
        starts_tool = kind == "tool_call"
        extends_tool = (
            voice == "tool"
            and previous is not None
            and previous["voice"] == "tool"
            and not starts_tool
            and (
                previous["key"] == f"tool:{call_id}"
                if call_id
                else True
            )
        )
        joins = previous is not None and (
            extends_tool
            or (voice != "tool" and previous["voice"] == voice and not call_id)
        )

        if joins:
            beat = previous
            beat["to"] = line
            beat["events"] += 1
            beat["kinds"].append(kind)
            text = str(event.get("text") or "")
            if voice != "plan":
                beat["text"] = (beat["text"] + text) if text else beat["text"]
            elif text:
                beat["text"] = text
            beat["text_truncated"] = beat["text_truncated"] or bool(event.get("text_truncated"))
            beat["chars"] += int(event.get("chars") or 0)
            beat["tool"] = beat["tool"] or str(event.get("tool") or "")
            beat["name"] = beat["name"] or str(event.get("name") or "")
            beat["status"] = str(event.get("status") or "") or beat["status"]
            if event.get("args"):
                beat["args"] = dict(event["args"])
            beat["result_chars"] = max(beat["result_chars"], int(event.get("result_chars") or 0))
            beat["output"] = str(event.get("output") or "") or beat["output"]
            beat["output_truncated"] = bool(event.get("output_truncated"))
            beat["steps"] = int(event.get("steps") or 0) or beat["steps"]
            continue

        key = f"tool:{call_id}" if voice == "tool" and call_id else f"{voice}:{line}"
        out.append(
            {
                "key": key,
                "voice": voice,
                "label": _VOICE_LABEL[voice],
                "at": str(event.get("at") or ""),
                "from": line,
                "to": line,
                "events": 1,
                "text": str(event.get("text") or ""),
                "text_truncated": bool(event.get("text_truncated")),
                "chars": int(event.get("chars") or 0),
                "tool": str(event.get("tool") or ""),
                "name": str(event.get("name") or ""),
                "status": str(event.get("status") or ""),
                "args": dict(event.get("args") or {}),
                "result_chars": int(event.get("result_chars") or 0),
                "output": str(event.get("output") or ""),
                "output_truncated": bool(event.get("output_truncated")),
                "steps": int(event.get("steps") or 0),
                "kinds": [kind],
            }
        )
    return out


def _timeline_events(
    lines: Sequence[str],
    *,
    detail: bool = False,
    full: bool = False,
    labels: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
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
    known: dict[str, tuple[str, str]] = dict(labels or {})
    for text in lines:
        try:
            row = json.loads(text)
        except (ValueError, RecursionError):
            row = None
        if not isinstance(row, dict):
            damaged += 1
            continue
        events.append(_timeline_event(row, detail=detail, full=full, labels=known))
        # In-page calls teach the rest of the page, so an update whose own row
        # names nothing is still readable when the call happens to precede it in
        # the same window.
        _remember_label(text, known)
    return events, damaged


def _remember_label(line: str, labels: dict[str, tuple[str, str]]) -> None:
    """Record a ``tool_call`` row's title and tool name under its call id.

    Damage is not counted here -- ``_timeline_events`` owns that count -- so an
    unparsable line is simply not a label.
    """
    try:
        row = json.loads(line)
    except (ValueError, RecursionError):
        return
    if not isinstance(row, Mapping) or row.get("sessionUpdate") != "tool_call":
        return
    call_id = str(row.get("toolCallId") or "")
    title = str(row.get("title") or row.get("name") or "")
    if call_id and title:
        labels[call_id] = (title, str(row.get("name") or ""))


#: A tool's arguments are summarised, never copied.  The values are the
#: subject's own inputs and one of them may be the contents of a file it read,
#: while what a reader of the timeline is comparing is which tool ran with which
#: fields and how it ended (design section 4.1).
_ARG_PREVIEW_CHARS = 40
_ARG_KEYS_SHOWN = 12

#: How much of one event a ``detail`` page shows.  Two different jobs, two
#: different ceilings: a message chunk is a sentence or half of one (the dashboard
#: stitches a run of chunks back together), while a result is often a table or a
#: stack trace and the first screenful is what a reader scans before asking for
#: the artifact.  Neither is the body; the report zip is.
_DETAIL_TEXT_CHARS = 500
_DETAIL_OUTPUT_CHARS = 700
_DETAIL_ARG_CHARS = 200


def _timeline_event(
    row: Mapping[str, Any],
    *,
    detail: bool = False,
    full: bool = False,
    labels: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """One JSONL row down to the timeline the dashboard is made of.

    The file holds the raw ``session/update`` stream, not the message events the
    judge is given, so this reads the wire names (``sessionUpdate``, ``rawInput``)
    -- a summariser written against the judge shape would find nothing in it.

    ``detail`` widens a row from "how much" to "what": the chunk's opening words,
    the tool's call id (so the dashboard can pair a call with its updates), the
    arguments at a readable length, and the result's first screenful.  The keys it
    adds are absent -- never empty -- when there is nothing to say, so a caller
    that ignores them reads the same page it read before.

    ``full`` is the opposite of a preview: it is asked for one beat, after a
    reader has opened it, so arguments keep every field and every character and
    results are not cut at a screenful.  A single generous ceiling still guards
    against a pathological row, and says so when it bites.
    """
    kind = str(row.get("sessionUpdate") or "other")
    entry: dict[str, Any] = {"kind": kind, "at": row.get("at")}
    if kind in ("tool_call", "tool_call_update"):
        call_id = str(row.get("toolCallId") or "")
        # The update carries the id only; the row that named the call is on an
        # earlier page.  A reader comparing outcomes needs to know which tool
        # these are the outcome of.
        known = (labels or {}).get(call_id, ("", "")) if call_id else ("", "")
        entry["tool"] = str(row.get("title") or row.get("name") or "") or known[0]
        entry["status"] = str(row.get("status") or "")
        if full:
            entry["args"] = _full_args(row.get("rawInput"))
        else:
            entry["args"] = _args_summary(
                row.get("rawInput"), chars=_DETAIL_ARG_CHARS if detail else _ARG_PREVIEW_CHARS
            )
        entry["result_chars"] = _result_length(row)
        if detail or full:
            entry["name"] = str(row.get("name") or "") or known[1]
            entry["tool_call_id"] = call_id
            if full:
                output, truncated = _clip(_flatten_result(row), _FULL_CONTENT_CHARS)
            else:
                output, truncated = _output_preview(row)
            if output:
                entry["output"] = output
                entry["output_truncated"] = truncated
        return entry
    if kind in ("plan", "plan_update"):
        entries = row.get("entries") or row.get("plan") or []
        entry["steps"] = len(entries) if isinstance(entries, list) else 0
        if detail or full:
            text, truncated = _clip(
                _plan_lines(entries), _FULL_CONTENT_CHARS if full else _DETAIL_TEXT_CHARS
            )
            if text:
                entry["text"] = text
                entry["text_truncated"] = truncated
        return entry
    if detail or full:
        text, truncated = _clip(
            "".join(str(_block_text(block)) for block in _blocks(row.get("content"))),
            _FULL_CONTENT_CHARS if full else _DETAIL_TEXT_CHARS,
        )
        if text:
            entry["text"] = text
            entry["text_truncated"] = truncated
    entry["chars"] = _text_length(row.get("content"))
    return entry


def _args_summary(raw_input: Any, *, chars: int = _ARG_PREVIEW_CHARS) -> dict[str, str]:
    source = raw_input if isinstance(raw_input, Mapping) else {}
    summary: dict[str, str] = {}
    names = sorted(str(name) for name in source)
    for name in names[:_ARG_KEYS_SHOWN]:
        summary[name] = _preview(str(source[name]), chars)
    if len(names) > _ARG_KEYS_SHOWN:
        summary["…"] = f"{len(names) - _ARG_KEYS_SHOWN} more field(s)"
    return summary


def _preview(text: str, chars: int = _ARG_PREVIEW_CHARS) -> str:
    if len(text) <= chars:
        return text
    return f"{text[:chars]}… +{len(text) - chars} chars"


def _clip(text: str, chars: int) -> tuple[str, bool]:
    """``text`` cut to ``chars``, and whether anything was cut.

    No marker is appended: the caller stitches several of these back together
    (a streamed message is one sentence per chunk), and a "+3400 chars" notice in
    the middle of a paragraph is noise where the surrounding text is the point.
    The panel says "已截断" once, at the level of the whole entry.
    """
    if len(text) <= chars:
        return text, False
    return text[:chars], True


def _text_preview(content: Any) -> tuple[str, bool]:
    """The opening words of a chunk, from the block shape a chunk carries."""
    return _clip("".join(str(_block_text(block)) for block in _blocks(content)), _DETAIL_TEXT_CHARS)


def _output_preview(row: Mapping[str, Any]) -> tuple[str, bool]:
    """A tool's result as text, the first screenful of it.

    ``rawOutput`` first, then the content blocks -- the same order
    :func:`.acp.transcript._tool_output_blocks` reads them in.  A structured
    result is flattened to JSON for the same reason the judge gets it that way:
    it is the only honest rendering of a value that has no text.
    """
    raw = row.get("rawOutput")
    if raw not in (None, "", {}, []):
        return _clip(_flatten(raw), _DETAIL_OUTPUT_CHARS)
    parts = []
    for block in _blocks(row.get("content")):
        parts.append(str(_block_text(block)))
    return _clip("".join(parts), _DETAIL_OUTPUT_CHARS)


def _plan_lines(entries: Any) -> str:
    """A plan as the checklist the agent wrote, one line per entry."""
    lines = []
    for entry in entries if isinstance(entries, list) else []:
        item = entry if isinstance(entry, Mapping) else {}
        content = str(item.get("content") or "").strip()
        if content:
            status = str(item.get("status") or "pending")
            lines.append(f"[{status}] {content}")
    return "\n".join(lines)


def _plan_preview(entries: Any) -> tuple[str, bool]:
    return _clip(_plan_lines(entries), _DETAIL_TEXT_CHARS)


def _full_args(raw_input: Any) -> dict[str, str]:
    """Every argument, in full, for a card the reader opened.

    The list page summarises values at 200 characters because it renders many
    cards at once and one argument may be a whole file.  Here the reader asked
    for this one card, so every key and every character comes back -- the only
    ceiling is the same generous one as text, and it is reported when hit.
    """
    source = raw_input if isinstance(raw_input, Mapping) else {}
    full: dict[str, str] = {}
    for name in sorted(str(key) for key in source):
        value, _ = _clip(_flatten(source[name]), _FULL_CONTENT_CHARS)
        full[name] = value
    return full


def _flatten_result(row: Mapping[str, Any]) -> str:
    """A tool's complete result, from whichever place the agent put it."""
    raw = row.get("rawOutput")
    if raw not in (None, "", {}, []):
        return _flatten(raw)
    return "".join(str(_block_text(block)) for block in _blocks(row.get("content")))


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _block_text(block: Any) -> str:
    """The text a content block carries, whether or not it wraps another block.

    A tool-call block wraps its content one level deeper than a message chunk
    does (``{"type": "content", "content": {...}}``), so reading only the outer
    mapping would find no ``text`` key and count every tool result as zero.
    """
    if not isinstance(block, Mapping):
        return ""
    inner = block.get("content")
    text = inner if isinstance(inner, Mapping) else block
    return str(text.get("text") or "")


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
    return len(_block_text(block))


def _artifact_link(job_id: str, task_id: str, attempt: int, path: str) -> dict[str, Any]:
    """How a task's download entry says to fetch one result file.

    A route plus a query, not a presigned link: these files are read back with
    the caller's own whitelist token, which is the whole guarantee -- a URL that
    carried its access in itself would outlive the run it came from and stay
    valid for whoever it got forwarded to.
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
) -> bytes:
    """The detail document plus every file the run actually collected."""
    buffer = io.BytesIO()
    by_task = _artifacts_by_task(exchange.store, job_id)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "detail.json", json.dumps(payload, indent=2, ensure_ascii=False, default=str)
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
            f"### {task.get('name') or task['task_id']}",
            "",
            f"`{task['task_id']}` · attempt {task.get('attempt') or 1}",
            "",
            f"- status: {task['status']}, score: {task['score']}",
            f"- duration: {task['duration_s']}s, artifacts: {len(task['artifacts'])}",
        ]
        if task.get("failure_reason"):
            lines.append(f"- failure: {task['failure_reason']}")
        if task.get("judge_notes"):
            lines.append(f"- judge: {_judge_line(task['judge_notes'])}")
        if task.get("trace_id") or task.get("session_id"):
            # The two ids a reader needs to find this attempt in a log file.
            lines.append(
                f"- trace: `{task.get('trace_id') or '—'}` · "
                f"session: `{task.get('session_id') or '—'}`"
            )
        prompt = str(task.get("prompt") or "").strip()
        if prompt:
            # The task itself, not a summary of it: a report whose scores cannot
            # be argued with without opening another system is a report someone
            # forwards and nobody reads twice.
            lines += ["", "**Task**", "", "> " + prompt[:_REPORT_PROMPT_CHARS].replace("\n", "\n> "), ""]
        if task.get("artifacts"):
            lines.append("- artifacts: " + ", ".join(
                f"`{item['path']}` ({item['size']}B)" for item in task["artifacts"]
            ))
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
