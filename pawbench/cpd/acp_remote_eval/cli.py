# -*- coding: utf-8 -*-
"""``python -m pawbench.cpd.acp_remote_eval.cli`` -- the local submit path.

The service has an HTTP API, so a command line has to earn its place.  It earns
it twice: the agent under evaluation runs on the submitter's own machine, and the
first submitters are agent terminals rather than a dashboard.  It also proves the
API is sufficient -- every command here is one documented request, so whatever
this tool can do ``curl`` can do, and nothing is a private door.

Because it is a client, it imports nothing from the service beyond the status
names ``watch`` has to compare against, and it validates nothing the server also
validates.  A bad ``--format`` or an empty selector is refused by
:mod:`.service.api` with its own code and message, which is the same answer the
submitter would get from any other caller; a second vocabulary here would only
be a second place for the two to disagree.

The token rides one ``Authorization`` header.  It is never printed, never placed
in a URL, and a refusal quotes the service's words, not the request that carried
the secret.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from .redact import url_without_credentials
from .service.queue import STATUS_FINISHED, TERMINAL_STATUSES

SERVER_ENV = "PAWBENCH_EVAL_SERVER"
TOKEN_ENV = "PAWBENCH_EVAL_TOKEN"

#: Task states that mean "not graded yet" rather than "went wrong".  Spelled out
#: rather than imported from :mod:`.service.runner`: borrowing two strings would
#: put the ACP protocol and the judge client on every ``--help``.
_IN_FLIGHT_STATUSES = ("pending", "running")

_DEFAULT_POLL_SECONDS = 5.0
#: A watch with no end is a hung terminal.  Six hours is longer than the pilot
#: corpus needs and short enough that a stuck job is noticed the same day.
_DEFAULT_WATCH_SECONDS = 6 * 60 * 60.0
_REQUEST_TIMEOUT_SECONDS = 120.0
#: A report is fetched through a presigned link, so one big zip is a download
#: rather than a request -- keep the read open longer than a JSON call.
_DOWNLOAD_TIMEOUT_SECONDS = 600.0

EXIT_OK = 0
#: The command never produced a result: no token, no route, a refusal.
EXIT_ERROR = 1
#: A job reached a terminal state that is not ``finished``.
EXIT_JOB_NOT_OK = 2
#: A watch ran out its own clock while the job was still moving.
EXIT_TIMED_OUT = 3


class CliError(Exception):
    """One thing the user can act on, already worded for a terminal."""


class EvalClient:
    """The handful of requests this CLI makes, over one bearer token.

    *transport* is the seam the tests use: they hand in the real ASGI app and the
    calls go through this same httpx stack, so a test that passes here cannot be
    passing against a request shape the service stopped serving.
    """

    def __init__(
        self,
        server: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._transport = transport
        self._http = httpx.Client(
            base_url=server,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EvalClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        """One call, answered with its JSON body or a :class:`CliError`."""
        response = self._http.request(method, path, params=_sent(params), json=body)
        return _unwrap(response)

    def to_file(self, url: str, target: Path) -> tuple[Path, str]:
        """Follow one presigned link to disk and return it with its sha256.

        The link is what ``GET /v1/jobs/{id}/report`` hands back -- the service
        never streams report bytes through a request handler, so a caller that
        wants the file downloads it the same way a browser would.

        Deliberately over a client with no ``Authorization`` header: ``/v1/reports``
        checks the signature and nothing else, so the bearer buys nothing here, and
        every httpx exception raised below would otherwise carry a second secret
        through the same path as the first.
        """
        digest = hashlib.sha256()
        with httpx.Client(
            transport=self._transport, timeout=_DOWNLOAD_TIMEOUT_SECONDS
        ) as anonymous:
            with anonymous.stream("GET", url) as response:
                if response.status_code >= 400:
                    response.read()
                    _unwrap(response)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        digest.update(chunk)
                        handle.write(chunk)
        return target, digest.hexdigest()


# ── commands ──────────────────────────────────────────────────────────────────


def _cmd_submit(client: EvalClient, args: argparse.Namespace) -> int:
    job = client.json("POST", "/v1/jobs", body=_submit_body(args))
    print(f"job {job['job_id']}  {job['status']}  ahead={job.get('queue_ahead', 0)}")
    warning = job.get("warning")
    if warning:
        print(f"warning: {warning.get('code')}: {warning.get('message')}", file=sys.stderr)
    if args.watch:
        return _watch(client, str(job["job_id"]), args)
    return EXIT_OK


def _cmd_status(client: EvalClient, args: argparse.Namespace) -> int:
    view = client.json("GET", f"/v1/jobs/{args.job_id}")
    if args.json:
        return _emit(view, args.out)
    return _report_job(view, quiet=False)


def _cmd_watch(client: EvalClient, args: argparse.Namespace) -> int:
    return _watch(client, args.job_id, args)


def _cmd_detail(client: EvalClient, args: argparse.Namespace) -> int:
    view = client.json(
        "GET", f"/v1/jobs/{args.job_id}/detail", params={"sensitivity": args.tier}
    )
    return _emit(view, args.out)


def _cmd_report(client: EvalClient, args: argparse.Namespace) -> int:
    link = client.json(
        "GET",
        f"/v1/jobs/{args.job_id}/report",
        params={"format": args.format, "sensitivity": args.tier},
    )
    # The service names its own report file, but the name is data from the wire:
    # a path in that field is not ours to honour, or one bad response would write
    # outside the directory the caller chose.
    filename = Path(str(link["filename"])).name or f"report-{args.job_id}.{args.format}"
    target = Path(args.out) if args.out else Path(filename)
    saved, digest = client.to_file(str(link["url"]), target)
    expected = str(link.get("sha256") or "")
    if expected and expected != digest:
        raise CliError(
            f"{saved} came back as {digest}, but the service described {expected}; "
            "the download is truncated or the file changed under us"
        )
    print(f"{saved}  {link.get('size')} bytes  sha256={digest[:16]}")
    return EXIT_OK


def _cmd_cancel(client: EvalClient, args: argparse.Namespace) -> int:
    job = client.json("POST", f"/v1/jobs/{args.job_id}/cancel")
    print(f"job {job.get('job_id', args.job_id)}  {job.get('status', 'canceled')}")
    return EXIT_OK


def _watch(client: EvalClient, job_id: str, args: argparse.Namespace) -> int:
    """Poll until the job stops moving, printing each change once."""
    deadline = time.monotonic() + args.timeout
    seen: Any = None
    while True:
        view = client.json("GET", f"/v1/jobs/{job_id}")
        marker = _progress_of(view)
        if marker != seen:
            seen = marker
            _report_job(view, quiet=True)
        status = str(view.get("status") or "")
        if status in TERMINAL_STATUSES:
            return _exit_for(status)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"job {job_id} is still '{status}' after {args.timeout:.0f}s; it keeps "
                "its place in the queue -- run 'watch' again to keep following it",
                file=sys.stderr,
            )
            return EXIT_TIMED_OUT
        time.sleep(min(args.interval, remaining))


# ── reading a job back ────────────────────────────────────────────────────────


def _report_job(view: Mapping[str, Any], *, quiet: bool) -> int:
    """One line for the job, then one per task that did not simply work.

    ``quiet`` is the watch's rule: it prints the summary and the trouble, and
    holds the per-task rows back until there is a terminal state to read them in.
    """
    tasks = list(view.get("tasks") or ())
    counts: dict[str, int] = {}
    for row in tasks:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    ahead = (view.get("queue") or {}).get("queue_ahead")
    summary = f"job {view.get('job_id')}  {view.get('status')}"
    if ahead:
        summary += f"  ahead={ahead}"
    if counts:
        summary += "  " + " ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(summary)
    if view.get("error"):
        print(f"  error: {view['error']}", file=sys.stderr)

    trouble = [
        row
        for row in tasks
        if row.get("status") not in (STATUS_FINISHED, *_IN_FLIGHT_STATUSES)
    ]
    if quiet and not trouble:
        return EXIT_OK
    for row in trouble:
        reason = row.get("failure_reason") or ""
        score = row.get("score")
        print(
            f"  {row.get('task_id')}  {row.get('status')}"
            f"  score={'' if score is None else score}  {reason}".rstrip()
        )
    return _exit_for(str(view.get("status") or ""))


def _exit_for(status: str) -> int:
    """0 for a job that finished or is still moving, 2 for one that ended badly.

    A queued job is not a failure -- ``status`` was asked a question and answered
    it.  Only a terminal state other than ``finished`` is worth branching on.
    """
    if status in TERMINAL_STATUSES and status != STATUS_FINISHED:
        return EXIT_JOB_NOT_OK
    return EXIT_OK


def _progress_of(view: Mapping[str, Any]) -> tuple[Any, ...]:
    queue = view.get("queue") or {}
    tasks = list(view.get("tasks") or ())
    return (
        view.get("status"),
        queue.get("queue_ahead"),
        len(tasks),
        sum(1 for row in tasks if row.get("status") == STATUS_FINISHED),
    )


def _emit(payload: Any, out: str | None) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(target)
    else:
        print(text)
    return EXIT_OK


# ── the request body ──────────────────────────────────────────────────────────


def _submit_body(args: argparse.Namespace) -> dict[str, Any]:
    selector: dict[str, Any] = {}
    if args.datasets:
        selector["datasets"] = list(args.datasets)
    if args.categories:
        selector["categories"] = list(args.categories)
    window: dict[str, Any] = {"kind": args.window}
    if args.not_before:
        window["not_before"] = args.not_before
    if args.not_after:
        window["not_after"] = args.not_after
    body: dict[str, Any] = {
        "acp_url": args.acp_url,
        "product": args.product,
        "purpose": args.purpose,
        "selector": selector,
        "window": window,
    }
    if args.env:
        body["env_fingerprint"] = _env_pairs(args.env)
    return body


def _env_pairs(pairs: Sequence[str]) -> dict[str, str]:
    """``--env KEY=VALUE`` repeated, into the object the job stores verbatim.

    The fingerprint is what makes a score attributable -- which model, which
    build, which machine.  It is the submitter's own vocabulary, so nothing here
    is renamed, required or filled in: an invented key would look like evidence.
    """
    fingerprint: dict[str, str] = {}
    for item in pairs:
        key, sep, value = str(item).partition("=")
        if not sep or not key.strip():
            raise CliError(f"--env wants KEY=VALUE, got '{item}'")
        fingerprint[key.strip()] = value
    return fingerprint


# ── plumbing ──────────────────────────────────────────────────────────────────


def _sent(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop the unset options, so a URL says only what the caller chose."""
    return {key: value for key, value in (params or {}).items() if value is not None}


def _unwrap(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        detail = _as_object(response)
        code = str(detail.get("error") or f"http_{response.status_code}")
        message = str(detail.get("message") or response.text.strip()[:200] or "no message")
        raise CliError(f"{response.status_code} {code}: {message}")
    return response.json()


def _as_object(response: httpx.Response) -> Mapping[str, Any]:
    """The error body, when there is one -- a proxy or a 404 has no JSON to read."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _transport_failure(exc: Exception) -> str:
    """A transport error, worded so the URL cannot smuggle out a signature.

    Several httpx exceptions put the request URL -- query string included -- in
    their message, and a report link's query *is* a credential.  So the class
    name says what broke, the path says where, and the message stays out.
    """
    request = getattr(exc, "request", None)
    where = f" while calling {url_without_credentials(request.url)}" if request else ""
    return f"cannot reach the service: {type(exc).__name__}{where}"


def _client(args: argparse.Namespace) -> EvalClient:
    server = str(args.server or os.environ.get(SERVER_ENV) or "").strip()
    if not server:
        raise CliError(f"no service URL: pass --server or set ${SERVER_ENV}")
    token = str(args.token or os.environ.get(TOKEN_ENV) or "").strip()
    if not token:
        raise CliError(f"no token: pass --token or set ${TOKEN_ENV}")
    return EvalClient(server, token)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pawbench.cpd.acp_remote_eval.cli",
        description="Submit and read remote ACP evaluations over the service API.",
        epilog=f"--server and --token fall back to ${SERVER_ENV} and ${TOKEN_ENV}.",
    )
    parser.add_argument("--server", default=None, help="service base URL")
    parser.add_argument("--token", default=None, help="bearer token (never printed)")
    commands = parser.add_subparsers(dest="command", required=True)

    submit = commands.add_parser("submit", help="queue a job against a running agent")
    submit.add_argument("--acp-url", required=True, help="the agent's ACP endpoint")
    submit.add_argument("--product", required=True, help="what is being evaluated")
    submit.add_argument("--purpose", required=True, help="why this run exists")
    submit.add_argument("--datasets", nargs="+", default=[], help="dataset ids")
    submit.add_argument("--categories", nargs="+", default=[], help="whole categories")
    submit.add_argument("--window", default="immediate", help="immediate, night or custom")
    submit.add_argument("--not-before", default=None, help="ISO instant a custom window opens")
    submit.add_argument("--not-after", default=None, help="ISO instant a custom window closes")
    submit.add_argument(
        "--env", action="append", default=[], metavar="KEY=VALUE", help="fingerprint field"
    )
    submit.add_argument("--watch", action="store_true", help="follow it to a terminal state")
    _add_watch_flags(submit)
    submit.set_defaults(handler=_cmd_submit)

    status = commands.add_parser("status", help="the queue view of one job")
    _job_id(status)
    status.add_argument("--json", action="store_true", help="print the payload as returned")
    _out_flag(status)
    status.set_defaults(handler=_cmd_status)

    watch = commands.add_parser("watch", help="follow one job until it stops moving")
    _job_id(watch)
    _add_watch_flags(watch)
    watch.set_defaults(handler=_cmd_watch)

    detail = commands.add_parser("detail", help="the evaluation view, at one tier")
    _job_id(detail)
    _tier_flag(detail)
    _out_flag(detail)
    detail.set_defaults(handler=_cmd_detail)

    report = commands.add_parser("report", help="render a report and download it")
    _job_id(report)
    report.add_argument("--format", default="md", help="json, md, html or zip")
    _tier_flag(report)
    _out_flag(report)
    report.set_defaults(handler=_cmd_report)

    cancel = commands.add_parser("cancel", help="stop a job, including a running one")
    _job_id(cancel)
    cancel.set_defaults(handler=_cmd_cancel)
    return parser


def _job_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("job_id", help="the id 'submit' printed")


def _tier_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tier", default=None, help="shared (default) or full")


def _out_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default=None, help="write here instead of the terminal")


def _add_watch_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_POLL_SECONDS,
        help="seconds between polls while watching",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_WATCH_SECONDS,
        help="give up watching after this many seconds (the job keeps running)",
    )


def main(argv: list[str] | None = None) -> int:
    """Parse argv, make one call, turn a refusal into an exit code."""
    args = _parser().parse_args(argv)
    try:
        client = _client(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        with client:
            return int(args.handler(client, args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except httpx.HTTPError as exc:
        print(f"error: {_transport_failure(exc)}", file=sys.stderr)
        return EXIT_ERROR


__all__ = ["CliError", "EvalClient", "main"]

if __name__ == "__main__":
    sys.exit(main())
