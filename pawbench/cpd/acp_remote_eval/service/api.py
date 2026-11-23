# -*- coding: utf-8 -*-
"""HTTP surface of the evaluation service.

Two planes, one app, because they share the SQLite handle and the attempt
registry: the *data plane* (the presigned fixture and report links, and the
artifact PUT a remote agent crosses to do anything at all) and the *control
plane* (submit, list, cancel, reorder, preview, and every read a human looks at
-- the routes the dashboard, the MCP tools and the CLI call with a whitelist
token).  Which of the two an endpoint belongs to is decided by one question:
does the caller have a token, or only a signature?

Three invariants hold the module together:

* Every absolute URL a remote machine will visit is built by
  :class:`.exchange.Exchange` from ``service.public_base_url``.  Nothing here
  reads ``Host``: it is caller-controlled, and a presigned link assembled from
  it is a link to wherever the caller wants the signature to be replayed.
* A refusal says why, in a stable code, and writes nothing.  The data plane's
  checks live in :mod:`.exchange` so the CLI, the MCP server and this app cannot
  drift apart; the control plane's live in :mod:`.jobs`, and each module keeps
  its own code vocabulary -- this file is where those codes become statuses, in
  one table, so no caller has to guess what a 4xx means.
* Nothing on the event loop touches the database.  Both planes call their
  services through ``asyncio.to_thread``: ``Store`` is one synchronous
  connection, so a query that ran inline would stall every other request and the
  queue tick (the contract at the top of ``store.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import datasets as datasets_module
from .attempts import ATTEMPT_NOT_RUNNING, AttemptRegistry, LiveAttempt
from .auth import SCOPE_SUBMIT, AuthError, Principal, TokenVerifier
from .datasets import DatasetError, DatasetService
from .exchange import Exchange, ExchangeError
from .jobs import JobService, SubmissionError
from .queue import ALL_STATUSES, QueueError
from .reports import DEFAULT_TRANSCRIPT_PAGE, ReportError, Reports
from .schedule import WindowError

logger = logging.getLogger(__name__)

#: Data-plane routes, so the manifest and the app cannot disagree about a URL.
#: ``dest`` is a workspace-relative path, so it keeps its slashes -- ``:path``
#: is what lets Starlette match one, and :meth:`.exchange.Exchange.asset_path`
#: signs the slashes through, so the two have to stay in step.
ASSET_ROUTE = "/v1/exchange/{job_id}/{task_id}/{attempt}/assets/{dest:path}"
ARTIFACT_ROUTE = "/v1/exchange/{job_id}/{task_id}/{attempt}/artifacts"
#: A report name is one segment -- :meth:`.exchange.Exchange.report_path`
#: validates it as such -- so this route cannot be pointed outside the job's own
#: report directory by anything but a signature over the exact name.
REPORT_ROUTE = "/v1/reports/{job_id}/{filename}"

#: A refused signature, a dead run token or a path we will not write through is
#: an attack shape, not a user mistake: warn so it reaches an operator, per the
#: logging rule's levels.
_SECURITY_CODES = frozenset(
    {
        "asset_link_invalid",
        "bad_asset_link",
        "bad_report_link",
        "report_link_invalid",
        "run_token_invalid",
        "run_token_expired",
        "run_token_spent",
        "symlink_refused",
    }
)

#: The fixture was asked for correctly but our own dataset directory could not
#: serve it -- the dataset author or the deployment broke, not the caller.
_SERVER_FAULT_CODES = frozenset({"bad_asset_source"})

_ERROR_STATUS = {
    "asset_link_invalid": 403,
    # The same promise ``asset_link_invalid`` makes: the link is well-formed and
    # simply is not ours.  Left out, it would fall to the 400 default and read
    # back as "fix the URL" to someone whose URL is exactly right.
    "report_link_invalid": 403,
    "run_token_invalid": 403,
    "run_token_expired": 403,
    "run_token_spent": 403,
    "asset_not_found": 404,
    "asset_unknown_dest": 404,
    "report_not_found": 404,
    ATTEMPT_NOT_RUNNING: 404,
    "artifact_too_large": 413,
    "empty_path": 422,
    "bad_path": 422,
    "path_absolute": 422,
    "path_escape": 422,
    "path_too_deep": 422,
    "hidden_path": 422,
    "forbidden_name": 422,
    "forbidden_suffix": 422,
    "extension_not_allowed": 422,
    "prefix_not_allowed": 422,
}

#: Control-plane codes -> status.  The services raise their own vocabularies on
#: purpose (one owner per set of codes, so a rule is never stated twice), which
#: means this table is the only place that decides what a 4xx *means* to a
#: caller.  Reading it by group:
#:
#:   400 -- the body or query is not shaped the way the route says
#:   403 -- identified, but neither the object's owner nor an admin
#:   404 -- the object the path names is not there
#:   409 -- it is there, and its current state refuses this action
#:   422 -- well-formed, and describing something that cannot be run
#:   429 -- allowed, but the service has no room for this caller
#:
#: One refusal is deliberately absent: ``pilot_seed_incomplete`` is raised by
#: :func:`.pilot.seed_pilot` in the composition root, before the port is bound, so
#: it stops a boot instead of answering a request.  A fallback line is the right
#: alarm for it, and the completeness case in ``test_control_api.py`` is what
#: keeps that reasoning from rotting into an excuse.
_CONTROL_STATUS: dict[str, int] = {
    # 400: shape, not meaning.
    "acp_url_missing": 400,
    "acp_url_unsupported": 400,
    "body_not_json": 400,
    "attempt_invalid": 400,
    "cursor_invalid": 400,
    "field_type_invalid": 400,
    "field_missing": 400,
    "field_too_long": 400,
    "env_fingerprint_invalid": 400,
    "env_fingerprint_too_large": 400,
    "limit_invalid": 400,
    "queue_pos_invalid": 400,
    "reorder_field_unknown": 400,
    "reorder_needs_one_target": 400,
    "status_invalid": 400,
    "unknown_window_kind": 400,
    "bad_window_time": 400,
    "night_window_is_fixed": 400,
    "custom_window_needs_bounds": 400,
    "window_inverted": 400,
    "invalid_selector": 400,
    "invalid_dataset_id": 400,
    "invalid_category_name": 400,
    "dataset_kind_fixed": 400,
    # The filter object's own keys: which names a view may filter on is stated in
    # the route's documentation, so an unlisted key and an empty filter are both
    # "the body is not shaped right".  Left out, they reached the fallback -- a
    # 400 with the right number and an ``error``-level line that pages someone
    # whose only involvement is that they shipped the docs.
    "unknown_filter_key": 400,
    "empty_filter": 400,
    # An uploaded archive that is not a zip, or is one whose members would land
    # outside the package directory.  Both say what to fix, and neither is a
    # permission problem.
    "package_not_zip": 400,
    "package_unsafe_path": 400,
    "report_format_unsupported": 400,
    # A preview of something that is not one of the two kinds of file a job has.
    # Only reachable from code that calls ``Reports.preview`` directly, since the
    # two routes spell their kind themselves -- mapped anyway so that a
    # mislabelled call reads like the other shape refusals instead of a bug.
    "preview_kind_unsupported": 400,
    # 403: someone else's job.
    "not_job_owner": 403,
    # Creation is open to every whitelisted subject; changing and deleting are
    # not, so these two are the whole of the dataset permission model (D15).
    "not_dataset_owner": 403,
    "not_category_owner": 403,
    # 404.
    "job_not_found": 404,
    "dataset_not_found": 404,
    "category_not_found": 404,
    "task_not_found": 404,
    "artifact_not_found": 404,
    "attachment_not_found": 404,
    # 409: the row exists and is not in a state for this.
    "job_not_reorderable": 409,
    "job_already_finished": 409,
    "job_changing": 409,
    "job_not_admissible": 409,
    "dataset_exists": 409,
    # Something is still pointed at the row, and deleting it would grade the
    # next person against files that no longer exist.
    "dataset_referenced": 409,
    "category_referenced": 409,
    # 413: the request is legitimate and larger than this service's disk quota.
    "package_too_large": 413,
    # The same number for the same reason on the routes that take a document
    # instead of a package: the caller's request was fine, this service has a
    # ceiling and said so before reading past it.
    "body_too_large": 413,
    # 422: the request reads fine and describes nothing runnable.
    "selector_unknown_ids": 422,
    "empty_selection": 422,
    "empty_selector": 422,
    "too_many_tasks": 422,
    # A package that unpacked and then failed validation, item by item.
    "package_invalid": 422,
    "window_too_short": 422,
    "window_too_long": 422,
    "window_in_the_past": 422,
    # A night window shorter than its own lead time, which the schedule says
    # needs a mis-edited config to reach at all.  Mapped so that when it does, the
    # caller reads 422 like the rest of the window family and the line is a
    # refusal rather than an alarm about this table.
    "night_window_unusable": 422,
    # 429.
    "per_user_limit": 429,
    "service_busy": 429,
    # 507: the request is legitimate, the machine it arrived at is out of room.
    # Not 413, which says the package is bigger than this service will ever take
    # -- this one is a second opinion the caller cannot act on except by asking
    # someone to clear a disk, so it needs a number nobody reads as "split your
    # set" and a log line that names the free space.
    "package_disk_full": 507,
}

#: A caller bounced by a cap is a capacity signal, not a user mistake: it needs
#: to reach an operator, per the logging rule's levels.
_CAPACITY_CODES = frozenset({"per_user_limit", "service_busy"})

#: The package guards: an archive that overshoots the disk quota, or whose
#: members point outside the directory it unpacks into, is a probe of the one
#: place this service writes attacker-supplied bytes to disk.  A legitimate
#: author who packs a 300 MB set is told the same way and can check the log.
#: Running out of room joins them because the answer whoever reads the line
#: needs is in the message either way, and the upload itself is gone by then --
#: refused before it landed, or deleted on the way out.
_PACKAGE_GUARD_CODES = frozenset(
    {"package_unsafe_path", "package_too_large", "package_disk_full"}
)

#: How many task packages may land at once.  Streaming a body and unpacking it
#: are the two things this route does, and both are disk: the default thread
#: pool would let ~32 simultaneous uploads each hold a temp file of up to
#: ``MAX_PACKAGE_BYTES``, which fills the volume and then starts failing other
#: people's writes -- the reports, the transcripts, the database.  Two is the
#: smallest number that still lets an author re-cut a set while a teammate's is
#: unpacking, and it makes the worst case a number the service can state: two
#: packages, not whatever the pool allows.
MAX_CONCURRENT_PACKAGE_UPLOADS = 2

#: How much of a request body the routes that *parse* it rather than store it
#: will read.  What those bodies carry is metadata -- a selector, an endpoint URL,
#: a cancel reason -- and the largest one this service can be asked for names
#: every task in its catalog, which is identifiers and commas even for a set far
#: bigger than the builtin suite.  The ceiling exists because an uncapped
#: ``request.body()`` holds a caller's bytes twice over, once as the buffer and
#: once as the document made from it, and on a process meant to stay resident for
#: weeks that is one determined subject away from an out-of-memory.  The body this
#: service takes at real size is a task package, and that has its own route.
MAX_JSON_BODY_BYTES = 1024 * 1024

#: How much of a guard message reaches the log, as ``repr``.  The text is built
#: from the caller's own member name, so both its length and its newlines are
#: theirs -- escaped and clipped, one oversized entry name stays one record.
_GUARD_REASON_CHARS = 200

#: The whole shape of a ``PATCH /v1/jobs/{id}`` body.  ``queue_pos`` is the name
#: every listing already shows, so the request that changes it uses the same
#: word rather than inventing ``position`` for the wire.
_REORDER_FIELDS = frozenset({"before_id", "after_id", "queue_pos"})

#: Statuses ``GET /v1/jobs?status=`` will filter by.  Checked because a typo in
#: a filter answers an empty list, and an empty list on the dashboard reads as
#: "the queue is idle" -- the one wrong answer nobody goes back to check.  The
#: names come from the queue, so the filter cannot fall behind a status.
_LISTABLE_STATUSES = frozenset(ALL_STATUSES)


@dataclass(frozen=True)
class ControlPlane:
    """What the token-carrying routes need: the services, and who may ask.

    One object because the routes arrive as a set -- a service that can take a
    submission but not list it is unusable -- and because all four fields have
    to be built over the same store, queue and catalogue for their answers to
    agree with each other.  In particular ``jobs.get`` and ``reports.job_detail``
    read the same rows, so a dashboard that shows both cannot see two numbers.

    ``stop_running`` is :meth:`.runtime.EvalRuntime.stop_job`, handed over as a
    callable rather than as the runtime: cancelling a running job has two halves
    (the ``canceled`` row and the live session), and only the process that
    launched the run can do the second one.
    """

    jobs: JobService
    datasets: DatasetService
    verifier: TokenVerifier
    reports: Reports
    stop_running: Callable[[str], bool] | None = None


def create_app(
    *,
    exchange: Exchange,
    registry: AttemptRegistry | None = None,
    control: ControlPlane | None = None,
) -> FastAPI:
    """The app for one :class:`.exchange.Exchange`.

    The exchange carries the signing key, so an app instance is tied to the
    service instance that minted the links -- which is the same lifetime the
    run tokens have.

    ``control`` brings in the token-authenticated routes.  It is optional
    because the data plane stands on its own: a deployment that only ever runs
    jobs the CLI handed it still has to answer the agent's PUTs.
    """
    attempts = registry if registry is not None else AttemptRegistry()
    app = FastAPI(title="pawbench-eval", version="1", docs_url=None, redoc_url=None)
    app.state.exchange = exchange
    app.state.attempts = attempts
    app.state.control = control
    # Per app, not per process: an app is an instance of this service, and the
    # cap is about how much room one instance lets arrive at once.  On the state
    # because the control routes are registered by a function, not by this one.
    app.state.package_uploads = asyncio.Semaphore(MAX_CONCURRENT_PACKAGE_UPLOADS)

    @app.exception_handler(ExchangeError)
    async def _refuse_exchange(request: Request, exc: ExchangeError) -> JSONResponse:
        status = _ERROR_STATUS.get(exc.code, 400)
        if exc.code in _SERVER_FAULT_CODES:
            logger.error(
                "data plane could not serve its own dataset",
                extra={
                    "code": exc.code,
                    "path": request.url.path,
                    "error": exc.message,
                },
            )
        elif exc.code in _SECURITY_CODES:
            logger.warning(
                "data plane refused a request",
                extra={"code": exc.code, "status": status, "path": request.url.path},
            )
        else:
            logger.info(
                "data plane refused a request",
                extra={
                    "code": exc.code,
                    "status": status,
                    "path": request.url.path,
                    "method": request.method,
                },
            )
        return JSONResponse(status_code=status, content={"error": exc.code, "message": exc.message})

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "public_base_url": exchange.service_config.public_base_url,
            "active_attempts": len(attempts),
        }

    @app.get(ASSET_ROUTE)
    async def download_asset(job_id: str, task_id: str, attempt: int, dest: str, request: Request):
        """Serve one fixture, to whoever holds a signature for exactly it."""
        exchange.verify_asset_request(
            job_id=job_id,
            task_id=task_id,
            attempt=attempt,
            dest=dest,
            expires=request.query_params.get("expires", ""),
            signature=request.query_params.get("sig", ""),
        )
        live = attempts.lookup(job_id, task_id, attempt)
        source = exchange.fixture_for(live.task, live.dataset_root, dest)
        return FileResponse(source, media_type="application/octet-stream")

    @app.get(REPORT_ROUTE)
    async def download_report(job_id: str, filename: str, request: Request):
        """Serve a rendered report to whoever holds the link the route issued.

        Presigned like a fixture, and for the same reason: the caller here is a
        browser opening a download, not a client with a token, and the link is
        what says this job asked for this file.
        """
        checked = exchange.verify_report_request(
            job_id=job_id,
            filename=filename,
            expires=request.query_params.get("expires", ""),
            signature=request.query_params.get("sig", ""),
        )
        path = exchange.report_path(job_id, checked)
        if not path.is_file():
            raise ExchangeError(
                "report_not_found", f"no report file '{checked}' is on this service"
            )
        return FileResponse(path, media_type="application/octet-stream", filename=checked)

    @app.put(ARTIFACT_ROUTE)
    async def upload_artifact(job_id: str, task_id: str, attempt: int, request: Request):
        """Take one result file back for the workspace rebuild."""
        token = _bearer_token(request.headers.get("authorization", ""))
        if not token:
            # Asked before the registry: without this, an anonymous PUT answers
            # 404 or 403 depending on whether a run is live, which is a free way
            # to enumerate which (job, task, attempt) triples are running.
            raise ExchangeError("run_token_invalid", "the upload carried no run token")
        attempts.lookup(job_id, task_id, attempt)
        raw_path = request.query_params.get("path", "")
        limit = exchange.config.max_bytes_per_artifact
        # Before the body, not inside the thread: a PUT carrying a token this
        # service never issued is refused here rather than after we have
        # buffered max_bytes_per_artifact for it.
        exchange.check_run_token(token, job_id, task_id, attempt)
        body = await _read_body(request, limit)
        # Hashing, fsync and the SQLite write all belong to the upload, and this
        # route runs on the service event loop -- so the work goes to a thread.
        # Without it, one 64 MB artifact stalls every other request and the
        # queue tick, which is what store.py's module contract warns about.
        upload = await asyncio.to_thread(
            exchange.accept_artifact,
            job_id=job_id,
            task_id=task_id,
            attempt=attempt,
            token=token,
            raw_path=raw_path,
            data=body,
        )
        payload = upload.to_payload()
        payload["budget_left"] = upload.budget_left
        return JSONResponse(status_code=201, content=payload)

    if control is not None:
        _add_control_routes(app, control)

    return app


def _add_control_routes(app: FastAPI, control: ControlPlane) -> None:
    """Submit, list, read, reorder, cancel, preview -- the token-carrying routes.

    Every handler is the same three steps: authenticate, hand the arguments to a
    service, serialise the answer.  That is deliberate.  The rules these routes
    enforce -- who owns a job, what a window may hold, which datasets a selector
    pulled in -- belong to the services, so the MCP tools and the CLI cannot get
    a different answer from the dashboard, and the only thing the boundary adds
    is the status code.
    """

    def authenticate(request: Request, scope: str = SCOPE_SUBMIT) -> Principal:
        """The one gate the whole control plane passes through (design section 6).

        Reads ask for ``submit`` too, not for a read scope: every view is open
        to every whitelisted subject, so reading needs nothing beyond being on
        the list, and ``submit`` is the scope every entry carries.  An
        allowlist that has gone missing answers the same way -- empty list,
        every call 401 -- which is the point of keeping the file out of the
        request path.
        """
        token = _bearer_token(request.headers.get("authorization", ""))
        principal = control.verifier.verify(token, scope)
        # The refusal handler is outside the route body, so this is the only way a
        # rejected write -- a package whose member path escapes its directory, say
        # -- can say which whitelisted member attempted it.  The subject is the
        # name the allowlist already carries, never the token.
        request.state.subject = principal.subject
        return principal

    @app.exception_handler(AuthError)
    async def _refuse_caller(request: Request, exc: AuthError) -> JSONResponse:
        # Mostly a relay: the verifier has already logged the rejection with a
        # token fingerprint, and logging it twice would put the same subject in
        # the file twice.  A scope miss is the one thing it does not say.
        if exc.code == "insufficient_scope":
            logger.info(
                "token lacks a scope",
                extra={"code": exc.code, "path": request.url.path, "method": request.method},
            )
        return JSONResponse(
            status_code=exc.status, content={"error": exc.code, "message": exc.message}
        )

    async def _refuse_service(request: Request, exc: Exception) -> JSONResponse:
        """Answer a service refusal with the status its code was promised."""
        code = str(getattr(exc, "code", "") or "request_refused")
        # The two tables are disjoint, so one lookup: the artifact route hands a
        # caller's ``path`` to the data plane's own resolver, and a bad one has to
        # answer the number that resolver already promises -- otherwise the same
        # typo costs 422 on an upload and 400 on a download.
        status = _CONTROL_STATUS.get(code) or _ERROR_STATUS.get(code)
        extra = {
            "code": code,
            "path": request.url.path,
            "method": request.method,
            "subject": getattr(request.state, "subject", None),
            # An uploaded package is named in the query string, not the path, so
            # without this the guard log cannot say which dataset a member probed.
            "dataset_id": request.query_params.get("id")
            or request.path_params.get("dataset_id"),
        }
        payload: dict[str, Any] = {
            "error": code,
            "message": str(getattr(exc, "message", "") or exc),
        }
        if code in _PACKAGE_GUARD_CODES:
            # Which member tripped the guard is the one thing an operator cannot
            # reconstruct later: the upload is a temp file this route deletes on
            # the way out.  It is the caller-facing message already, so the log
            # quotes no text the response did not.
            extra["reason"] = repr(payload["message"])[:_GUARD_REASON_CHARS]
        if status is None:
            # A code this table never heard of is our gap, not the caller's:
            # say so loudly, and still answer 4xx rather than a bare 500 that
            # tells nobody which field to fix.
            logger.error("control plane raised an unmapped code", extra=extra)
            status = 400
        elif code in _CAPACITY_CODES or code in _PACKAGE_GUARD_CODES or status == 403:
            logger.warning("control plane refused a request", extra=extra)
        else:
            logger.info("control plane refused a request", extra=extra)
        details = getattr(exc, "details", None)
        if details:
            payload["details"] = dict(details)
        return JSONResponse(status_code=status, content=payload)

    for _error in (SubmissionError, QueueError, WindowError, DatasetError, ReportError):
        app.add_exception_handler(_error, _refuse_service)

    @app.post("/v1/jobs", status_code=201)
    async def submit_job(request: Request) -> JSONResponse:
        """Queue one job; see :meth:`.jobs.JobService.submit` for the order."""
        principal = authenticate(request)
        body = await _json_object(request)
        result = await asyncio.to_thread(control.jobs.submit, body, principal)
        return JSONResponse(status_code=201, content=result)

    @app.get("/v1/jobs")
    async def list_jobs(request: Request) -> JSONResponse:
        """Every job on the service, whoever submitted it (requirement 5)."""
        authenticate(request)
        query = request.query_params
        statuses = tuple(query.getlist("status"))
        unknown = sorted(set(statuses) - _LISTABLE_STATUSES)
        if unknown:
            raise SubmissionError(
                "status_invalid",
                f"no job is ever '{unknown[0]}'; the statuses are {sorted(_LISTABLE_STATUSES)}",
                statuses=list(unknown),
            )
        result = await asyncio.to_thread(
            control.jobs.list_jobs,
            statuses=statuses,
            submitter=query.get("submitter") or None,
            limit=_limit_of(query.get("limit")),
        )
        return JSONResponse(content=result)

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> JSONResponse:
        """The queue view of one job: state, score, and why a task did not move."""
        authenticate(request)
        return JSONResponse(content=await asyncio.to_thread(control.jobs.get, job_id))

    @app.patch("/v1/jobs/{job_id}")
    async def reorder_job(job_id: str, request: Request) -> JSONResponse:
        """Move a waiting job.  A running one answers 409 and says to cancel."""
        principal = authenticate(request)
        body = await _json_object(request)
        unknown = sorted(set(body) - _REORDER_FIELDS)
        if unknown:
            # Refused rather than ignored: a body that spells the field wrong
            # and answers 200 is how a dashboard ends up believing its drag was
            # saved when the row never moved.
            raise SubmissionError(
                "reorder_field_unknown",
                f"a job can be moved by before_id, after_id or queue_pos, not {unknown[0]}",
                fields=unknown,
            )
        result = await asyncio.to_thread(
            control.jobs.reorder,
            job_id,
            principal,
            before_id=body.get("before_id"),
            after_id=body.get("after_id"),
            position=_position_of(body.get("queue_pos")),
        )
        return JSONResponse(content=result)

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request) -> JSONResponse:
        """Cancel the row and, when it had started, the session behind it."""
        principal = authenticate(request)
        body = await _json_object(request)
        result = await asyncio.to_thread(
            control.jobs.cancel,
            job_id,
            principal,
            stop_running=control.stop_running,
            error=body.get("reason"),
        )
        return JSONResponse(content=result)

    @app.post("/v1/datasets/resolve")
    async def resolve_selector(request: Request) -> JSONResponse:
        """Preview a mixed multi-select before committing it to a window.

        The same call the submission makes one request later, which is the whole
        reason the route exists: without it a submitter cannot know how many
        tasks a category expanded to until the job is already queued (design
        section 4).  Unknown ids come back as data, not as an error -- telling
        the caller which names missed is more useful here than refusing.
        """
        authenticate(request)
        body = await _json_object(request)
        selector = body.get("selector")
        if not isinstance(selector, dict):
            raise SubmissionError(
                "field_type_invalid", "the body must carry a 'selector' object"
            )
        resolved = await asyncio.to_thread(control.datasets.resolve, selector)
        return JSONResponse(content=resolved.to_payload())

    @app.get("/v1/datasets")
    async def list_datasets(request: Request) -> JSONResponse:
        """The catalogue: names, owners, kinds, categories and counts.

        What the dashboard's dataset picker and the MCP catalog tool both read.
        Task bodies, rubrics and grading code are not in it (design section 4),
        so a whitelisted token can browse what exists without being able to
        quote a question back to the agent it is about to evaluate.
        """
        authenticate(request)
        return JSONResponse(content=await asyncio.to_thread(control.datasets.list_catalog))

    @app.post("/v1/datasets", status_code=201)
    async def create_dataset(request: Request) -> JSONResponse:
        """Save a slice of the builtin corpus as a named dataset.

        Creation is open to every whitelisted subject (D15); the filter resolves
        to an explicit ``task_ids`` snapshot here, which is what makes a job
        reproducible after the corpus is re-curated (design section 4).
        """
        principal = authenticate(request)
        body = await _json_object(request)
        dataset_id = _checked_name(body.get("id"), "id")
        record = await asyncio.to_thread(
            control.datasets.create_builtin_view,
            dataset_id=dataset_id,
            name=str(body.get("name") or ""),
            owner=principal.subject,
            filter_spec=_filter_of(body),
            categories=_categories_of(body),
            description=str(body.get("description") or ""),
        )
        return JSONResponse(status_code=201, content=record)

    @app.post("/v1/datasets/packages", status_code=201)
    async def upload_dataset(request: Request) -> JSONResponse:
        """Register an uploaded task package as a dataset (scenario 1).

        The zip is the body and the metadata is in the query string, because
        multipart would mean a second parse of a very large upload to reach four
        short strings -- and the limit here is the same quota the unpacker
        applies, so an oversized set is refused while it streams to a temp file
        rather than after it lands in the package directory.

        A custom set is a directory entry, not an attachment to a submission:
        once registered it participates in mixed selection exactly like a
        builtin view (D9).

        The gate covers the whole request, not just the body: unpacking is the
        other half of the disk this route spends, and a third caller waiting on
        the semaphore has a queue, not a refusal -- the package arrived, it is
        just not this service's turn to write it yet.
        """
        principal = authenticate(request)
        query = request.query_params
        # Read through the module, not a name bound at import: the quota the
        # unpacker applies has to be the same number this gate uses, and a test
        # that lowers it has to lower both.
        async with request.app.state.package_uploads:
            upload = await _stream_body_to_file(
                request,
                datasets_module.MAX_PACKAGE_BYTES,
                Path(control.datasets.config.custom_dir),
            )
            try:
                record = await asyncio.to_thread(
                    control.datasets.register_custom_archive,
                    dataset_id=_checked_name(query.get("id"), "id"),
                    name=str(query.get("name") or ""),
                    owner=principal.subject,
                    archive=upload,
                    categories=query.getlist("categories"),
                    description=str(query.get("description") or ""),
                )
            finally:
                upload.unlink(missing_ok=True)
        return JSONResponse(status_code=201, content=record)

    @app.get("/v1/datasets/{dataset_id}")
    async def describe_dataset(dataset_id: str, request: Request) -> JSONResponse:
        """One dataset, task by task -- labels and attachment names, no bodies."""
        authenticate(request)
        return JSONResponse(
            content=await asyncio.to_thread(control.datasets.describe, dataset_id)
        )

    @app.put("/v1/datasets/{dataset_id}")
    async def edit_dataset(dataset_id: str, request: Request) -> JSONResponse:
        """Re-cut a saved view: the filter, the name, the description, the filing.

        Re-resolving the filter is the point of the route -- a saved view that
        cannot be re-cut forces the author to mint a new id and leave the old one
        in everybody's selectors.  A custom dataset answers
        ``dataset_kind_fixed``: its content is the package it came in, so it is
        replaced by uploading one again.
        """
        principal = authenticate(request)
        body = await _json_object(request)
        # The kind and owner rules live inside the service, next to the ones that
        # guard creation and deletion, so an HTTP caller and a skill see one set.
        updated = await asyncio.to_thread(
            control.datasets.edit_builtin_view,
            dataset_id=dataset_id,
            principal=principal,
            filter_spec=_filter_of(body),
            name=str(body.get("name") or ""),
            categories=_categories_of(body),
            description=str(body.get("description") or ""),
        )
        return JSONResponse(content=updated)

    @app.delete("/v1/datasets/{dataset_id}")
    async def delete_dataset(dataset_id: str, request: Request) -> JSONResponse:
        """Drop a dataset, unless a job has ever been run against it."""
        principal = authenticate(request)
        await asyncio.to_thread(control.datasets.delete_dataset, dataset_id, principal)
        return Response(status_code=204)

    @app.get("/v1/dataset-categories")
    async def list_dataset_categories(request: Request) -> JSONResponse:
        authenticate(request)
        return JSONResponse(
            content={"categories": await asyncio.to_thread(control.datasets.list_categories)}
        )

    @app.post("/v1/dataset-categories", status_code=201)
    async def create_dataset_category(request: Request) -> JSONResponse:
        """Create a category, or return the one the name already normalises to.

        Open to everyone on purpose (D15), and idempotent for the same reason:
        a skill that files a dataset should not have to know whether
        ``Office Productivity`` was coined by somebody else last week.
        """
        principal = authenticate(request)
        body = await _json_object(request)
        category = await asyncio.to_thread(
            control.datasets.ensure_category,
            _checked_name(body.get("name"), "name"),
            principal.subject,
            str(body.get("description") or ""),
        )
        return JSONResponse(status_code=201, content=category)

    @app.delete("/v1/dataset-categories/{category_name}")
    async def delete_dataset_category(category_name: str, request: Request) -> JSONResponse:
        """Remove a category no dataset is filed under, by the person who made it."""
        principal = authenticate(request)
        await asyncio.to_thread(control.datasets.delete_category, category_name, principal)
        return Response(status_code=204)

    @app.get("/v1/jobs/{job_id}/detail")
    async def job_detail(job_id: str, request: Request) -> JSONResponse:
        """The evaluation view of one job.

        Distinct from ``GET /v1/jobs/{id}``, which is the *queue* view: state,
        position and why a task did not move.  This one is what a reader reads:
        config, sources, scores per slice, and per task the breakdown, the
        grading reasoning and the files.  (A task's timeline is a second
        request -- ``.../tasks/{task_id}/detail`` -- because it is paged.)
        What the document contains is decided inside
        :meth:`.reports.Reports.job_detail`, never here.
        """
        authenticate(request)
        return JSONResponse(
            content=await asyncio.to_thread(control.reports.job_detail, job_id)
        )

    @app.get("/v1/jobs/{job_id}/tasks/{task_id}/detail")
    async def task_detail(job_id: str, task_id: str, request: Request) -> JSONResponse:
        """One task, with a page of its transcript appended."""
        authenticate(request)
        query = request.query_params
        return JSONResponse(
            content=await asyncio.to_thread(
                control.reports.task_detail,
                job_id,
                task_id,
                _attempt_of(query.get("attempt")),
            )
        )

    @app.get("/v1/jobs/{job_id}/results")
    async def job_results(job_id: str, request: Request) -> JSONResponse:
        """The job in the shape ``submissions/*.json`` uses, plus its environment."""
        authenticate(request)
        return JSONResponse(content=await asyncio.to_thread(control.reports.results, job_id))

    @app.get("/v1/jobs/{job_id}/report")
    async def job_report(job_id: str, request: Request) -> JSONResponse:
        """Render a report and hand back its link -- the bytes never pass through.

        A zip is 64 MB of somebody else's files; streaming it from the request
        handler would put the whole download on the event loop's critical path,
        so this returns a presigned URL for the data plane to serve.
        """
        authenticate(request)
        query = request.query_params
        return JSONResponse(
            content=await asyncio.to_thread(
                control.reports.report,
                job_id,
                fmt=query.get("format"),
            )
        )

    @app.get("/v1/jobs/{job_id}/transcript")
    async def job_transcript(job_id: str, request: Request) -> JSONResponse:
        """One page of one task's timeline (requirement 8's paging rule)."""
        authenticate(request)
        query = request.query_params
        task_id = query.get("task_id") or ""
        if not task_id:
            raise SubmissionError(
                "field_type_invalid",
                "a transcript is per task: pass task_id",
                field="task_id",
            )
        return JSONResponse(
            content=await asyncio.to_thread(
                control.reports.transcript,
                job_id,
                task_id,
                attempt=_attempt_of(query.get("attempt")) or 1,
                cursor=_cursor_of(query.get("cursor")),
                limit=_limit_of(query.get("limit")) or DEFAULT_TRANSCRIPT_PAGE,
            )
        )

    @app.get("/v1/jobs/{job_id}/tasks/{task_id}/attempts/{attempt}/artifacts")
    async def job_artifact(
        job_id: str, task_id: str, attempt: int, request: Request
    ) -> FileResponse:
        """One result file back out, to a caller with a whitelist token.

        The download list points here rather than at a presigned link on
        purpose: an artifact is the subject's own output, and a link that
        carries its access in the URL would outlive the run it came from and
        stay valid whoever it got forwarded to.
        """
        authenticate(request)
        try:
            path = await asyncio.to_thread(
                control.reports.artifact_file,
                job_id,
                task_id,
                attempt,
                request.query_params.get("path", ""),
            )
        except ExchangeError as exc:
            # The path rules are the data plane's; re-raising them as this
            # plane's error type keeps the refusal on the handler that logs it
            # as a control-plane request while the code -- and so the status --
            # stays what an upload of the same path would have answered.
            raise ReportError(exc.code, exc.message) from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/v1/jobs/{job_id}/tasks/{task_id}/attempts/{attempt}/artifacts/preview")
    async def job_artifact_preview(
        job_id: str, task_id: str, attempt: int, request: Request
    ) -> JSONResponse:
        """What is inside one result file, trimmed to what a dialog can show."""
        authenticate(request)
        return await _preview("artifact", job_id, task_id, attempt, request)

    @app.get("/v1/jobs/{job_id}/tasks/{task_id}/attempts/{attempt}/attachments")
    async def job_attachment(
        job_id: str, task_id: str, attempt: int, request: Request
    ) -> FileResponse:
        """One of the files the task handed the agent, as it was handed over.

        Same door as an artifact and for the same reason: an attachment is part
        of the question, and a reader arguing with an answer about a spreadsheet
        has to be able to open it.  Only a path the task *declares* is
        reachable -- see :meth:`Reports.attachment_file`.
        """
        authenticate(request)
        try:
            path = await asyncio.to_thread(
                control.reports.attachment_file,
                job_id,
                task_id,
                attempt,
                request.query_params.get("path", ""),
            )
        except ExchangeError as exc:
            raise ReportError(exc.code, exc.message) from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/v1/jobs/{job_id}/tasks/{task_id}/attempts/{attempt}/attachments/preview")
    async def job_attachment_preview(
        job_id: str, task_id: str, attempt: int, request: Request
    ) -> JSONResponse:
        """What is inside one attachment."""
        authenticate(request)
        return await _preview("attachment", job_id, task_id, attempt, request)

    async def _preview(
        kind: str, job_id: str, task_id: str, attempt: int, request: Request
    ) -> JSONResponse:
        """The shared body of the two preview routes.

        One function because the answer is one shape: the dialog that renders a
        log and the dialog that renders a screenshot are the same dialog, and
        the kind of *file* is what differs, not the kind of route.
        """
        try:
            payload = await asyncio.to_thread(
                control.reports.preview,
                job_id,
                task_id,
                attempt,
                kind,
                request.query_params.get("path", ""),
            )
        except ExchangeError as exc:
            raise ReportError(exc.code, exc.message) from exc
        return JSONResponse(content=payload)


def _checked_name(value: Any, label: str) -> str:
    """A required, non-empty name off a body or a query string.

    The service checks the *shape* of an id or a category name (``_ID_RE``,
    normalisation); this only checks that the caller sent one, because a route
    that forwards ``None`` reaches a store keyed by the string "None".
    """
    text = str(value or "").strip()
    if not text:
        raise SubmissionError("field_missing", f"{label} is required", field=label)
    return text


def _filter_of(body: Mapping[str, Any]) -> dict[str, Any]:
    """The saved view's filter, which is the only reason to keep one.

    A body without it is refused rather than read as "everything": an empty
    filter resolves to the whole corpus, and a caller who meant ``scenario`` and
    typed ``scenarios`` would queue a job over several hundred tasks.
    """
    spec = body.get("filter")
    if not isinstance(spec, dict) or not spec:
        raise SubmissionError(
            "field_type_invalid", "the body must carry a non-empty 'filter' object"
        )
    return spec


def _categories_of(body: Mapping[str, Any], default: Sequence[str] = ()) -> list[str]:
    """The filing on a create or a re-cut, kept when the caller says nothing.

    Absent means "leave as stored", not "unfile it" -- a dashboard that PATCHes
    only the description must not silently drop the categories that make the
    dataset findable in somebody else's selector.
    """
    if "categories" not in body:
        return list(default)
    raw = body.get("categories")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise SubmissionError(
            "field_type_invalid", "categories must be a list of names"
        )
    return list(raw)


def _limit_of(raw: str | None) -> int | None:
    if raw in (None, ""):
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise SubmissionError("limit_invalid", f"limit must be a positive integer, got {raw!r}")
    return int(raw)


def _cursor_of(raw: str | None) -> int:
    """Where a page starts.  Unlike ``limit``, ``0`` is a value, so it returns 0."""
    if raw in (None, ""):
        return 0
    if not raw.isdigit():
        raise SubmissionError("cursor_invalid", f"cursor must be an event index, got {raw!r}")
    return int(raw)


def _attempt_of(raw: str | None) -> int | None:
    """An attempt number from a query string, or ``None`` for "the latest one".

    The callers differ on purpose: a task detail without ``attempt`` means the
    attempt a reader is most likely asking about, while a transcript is always
    about one specific run and says so in its own response.
    """
    if raw in (None, ""):
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise SubmissionError("attempt_invalid", f"attempt must be 1 or more, got {raw!r}")
    return int(raw)


def _position_of(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SubmissionError("queue_pos_invalid", f"queue_pos must be a number, got {raw!r}")
    return float(raw)


async def _json_object(request: Request) -> dict[str, Any]:
    """The body as a mapping, with ``{}`` for a body that was never sent.

    An empty POST is not a syntax error: cancelling takes an optional reason,
    and a submission that sends nothing is refused one field later as
    ``acp_url_missing``, which says more than ``body_not_json`` would.
    """
    raw = await _read_body(request, MAX_JSON_BODY_BYTES, SubmissionError, "body_too_large")
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        # ``json`` descends a document with the interpreter's stack, so a body
        # made of nothing but open brackets is well-formed syntax and a blown
        # depth at the same time.  Both are the caller's document, not our crash.
        raise SubmissionError("body_not_json", "the body was not a JSON document") from None
    if not isinstance(payload, dict):
        raise SubmissionError("field_type_invalid", "the body must be a JSON object")
    return payload


def _bearer_token(header: str) -> str:
    text = str(header or "").strip()
    scheme, _, value = text.partition(" ")
    return value.strip() if scheme.casefold() == "bearer" else ""


def _existing_parent(path: Path) -> Path:
    """The nearest directory on the way to *path* that is actually there.

    ``shutil.disk_usage`` answers about a mounted volume, so a first upload on a
    fresh install -- whose package directory has not been created yet -- can be
    measured against the directory above it.  Asking a missing path would raise,
    and a raise here would read as a broken service rather than as room to check.
    """
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return path


async def _stream_body_to_file(request: Request, limit: int, package_dir: Path) -> Path:
    """Land the request body in a temporary file and hand back its path.

    The caller owns the file and deletes it.  ``_read_body`` is right for an
    artifact -- those are hashed, so the bytes are wanted -- but a task package
    runs to the hundreds of megabytes, and the unpacker reads it from disk
    member by member: joining it into one ``bytes`` and then into a ``BytesIO``
    gave the service three copies of a file it never needed in memory at all, and
    a handful of simultaneous uploads is enough to OOM a resident process.

    As in ``_read_body``, the running total during streaming is the real check;
    ``Content-Length`` belongs to the caller.

    The free-space check is about the same header's other failure mode: a body
    that arrives in full and lands halfway.  It is asked of two volumes because
    this request spends each of them once -- the archive lands in the temp
    directory, its unpacked copy in *package_dir*, and on a box where ``/tmp`` is
    tmpfs those are two different questions.  Checking what the caller declared is
    enough for the pre-flight: a caller who lies about the size still meets the
    running total below and the write that fails, and a volume that runs out
    mid-write is refused here rather than by whatever reads the exception next.
    """
    declared = request.headers.get("content-length", "")
    if str(declared).isdigit() and int(declared) > limit:
        raise DatasetError(
            "package_too_large", f"{declared} bytes is over the {limit} byte limit"
        )
    wanted = int(declared) if str(declared).isdigit() else limit
    for volume in (_existing_parent(Path(tempfile.gettempdir())), _existing_parent(package_dir)):
        free = shutil.disk_usage(volume).free
        if free < wanted:
            raise DatasetError(
                "package_disk_full",
                f"the volume holding {volume} has {free} bytes free and this "
                f"package says it is {wanted}",
            )
    descriptor, name = tempfile.mkstemp(prefix="pawbench-package-", suffix=".zip")
    path = Path(name)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as sink:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise DatasetError(
                        "package_too_large", f"the body passed {limit} bytes before it ended"
                    )
                # One hop per chunk, and the same reason as everywhere else in
                # this file: a disk write does not belong on the loop that is
                # answering the artifact PUTs of four jobs already running.
                await asyncio.to_thread(sink.write, chunk)
    except OSError as failure:
        # The volume filled up under us after the pre-flight said otherwise --
        # somebody else's write got there first.  Same number and same fields as
        # the refusal above, because what the operator does is identical.
        path.unlink(missing_ok=True)
        raise DatasetError(
            "package_disk_full",
            f"the write stopped after {size} bytes on a volume holding "
            f"{wanted} ({type(failure).__name__})",
        ) from None
    except BaseException:
        # Including the client hanging up mid-body: a half-written upload on a
        # temp path is nobody's business and it is not size-bounded.
        path.unlink(missing_ok=True)
        raise
    return path


async def _read_body(
    request: Request,
    limit: int,
    refusal: type[Exception] = ExchangeError,
    code: str = "artifact_too_large",
) -> bytes:
    """Read the request body, stopping at *limit* rather than after it.

    The declared ``Content-Length`` is checked first so an oversized upload is
    refused without transferring it; the running total during streaming is
    what makes the refusal true, because the header belongs to the caller.

    *refusal* and *code* name the vocabulary the ceiling is quoted in.  Each
    service owns its set of codes -- see ``_CONTROL_STATUS`` -- so a control route
    that passed the default would answer a metadata POST with a message about an
    artifact nobody uploaded.
    """
    declared = request.headers.get("content-length", "")
    if str(declared).isdigit() and int(declared) > limit:
        raise refusal(code, f"{declared} bytes is over the {limit} byte limit")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise refusal(code, f"the body passed {limit} bytes before it ended")
        chunks.append(chunk)
    return b"".join(chunks)
