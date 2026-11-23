# -*- coding: utf-8 -*-
"""The local submit path, end to end over HTTP.

The service's own rules are covered by :mod:`test_jobs`, :mod:`test_reports` and
:mod:`test_datasets_api`.  What only shows up here is the *client*: that the body
this tool builds is the body the submit validator accepts, that a token travels
in one header and never in a URL or an error line, that a refusal reaches the
terminal as the service's own code rather than a paraphrase, and that ``watch``
stops on its own rather than when the user notices.

Those cases run against the real app through :func:`support.cli_transport`, so
they fail if the CLI drifts from the API -- which is the one thing a stubbed
client could never catch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pawbench.cpd.acp_remote_eval import cli
from pawbench.cpd.acp_remote_eval.service import runner as runner_module
from pawbench.cpd.acp_remote_eval.service.auth import SCOPE_ADMIN, SCOPE_SUBMIT, add_subject
from pawbench.cpd.acp_remote_eval.service.config import EvalConfig
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetService
from pawbench.cpd.acp_remote_eval.service.queue import JobQueue, QueueLimits
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import (
    BASE,
    build_control_app,
    cli_transport,
    dataset_service,
    eval_config,
    job_row,
    write_task,
)

ACP_URL = "http://127.0.0.1:9412/rpc"

#: Bound here, before any fixture patches ``cli.EvalClient``: a test that swaps
#: the transport needs the real class, not another test's double.
_EVAL_CLIENT = cli.EvalClient


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    root = tmp_path / "builtin"
    write_task(root, "mail_l1", scenario="Office_Productivity/Email")
    write_task(root, "mail_l3", scenario="Office_Productivity/Email", complexity="L3")
    write_task(root, "chart_open", scenario="Data_Analytics", environment="open")
    return root


@pytest.fixture()
def config(tmp_path: Path, builtin_root: Path) -> EvalConfig:
    return eval_config(tmp_path, builtin_root=builtin_root)


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))


@pytest.fixture()
def allowlist(tmp_path: Path) -> Path:
    return tmp_path / "allowlist.yaml"


@pytest.fixture()
def tokens(allowlist: Path) -> dict[str, str]:
    return {
        "dev-1": add_subject(allowlist, "dev-1"),
        "ops": add_subject(allowlist, "ops", scopes=[SCOPE_SUBMIT, SCOPE_ADMIN]),
    }


@pytest.fixture()
def datasets(store: Store, config: EvalConfig) -> DatasetService:
    service = dataset_service(store, config)
    service.create_builtin_view(
        dataset_id="mail",
        name="Email tasks",
        owner="dev-1",
        filter_spec={"scenario": "Office_Productivity/Email"},
        categories=["email"],
    )
    return service


@pytest.fixture()
def queue(store: Store, config: EvalConfig, clock: FrozenClock) -> JobQueue:
    return JobQueue(
        store,
        config.schedule,
        QueueLimits(
            max_concurrent_jobs=config.service.max_concurrent_jobs,
            max_running_per_user=config.service.max_running_per_user,
        ),
        clock=clock,
    )


@pytest.fixture()
def client(
    store: Store,
    config: EvalConfig,
    clock: FrozenClock,
    queue: JobQueue,
    datasets: DatasetService,
    allowlist: Path,
    tmp_path: Path,
) -> TestClient:
    return TestClient(
        build_control_app(
            store=store,
            config=config,
            queue=queue,
            datasets=datasets,
            allowlist=allowlist,
            tmp_path=tmp_path,
            clock=clock,
        )
    )


@pytest.fixture()
def seen() -> list[httpx.Request]:
    return []


@pytest.fixture()
def run(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    tokens: dict[str, str],
    seen: list[httpx.Request],
) -> Any:
    """``cli.main`` against the real app, with the ambient token in place."""
    real = cli.EvalClient

    def connect(server: str, token: str, *, transport: Any = None) -> cli.EvalClient:
        return real(server, token, transport=cli_transport(client, seen))

    monkeypatch.setattr(cli, "EvalClient", connect)

    def invoke(*argv: str, subject: str | None = "dev-1") -> int:
        monkeypatch.setenv(cli.SERVER_ENV, BASE)
        monkeypatch.delenv(cli.TOKEN_ENV, raising=False)
        if subject is not None:
            monkeypatch.setenv(cli.TOKEN_ENV, tokens[subject])
        return cli.main(list(argv))

    return invoke


def submitted(run: Any, capsys: Any, *extra: str) -> str:
    """One ``submit`` through the CLI, returning the job id it printed."""
    assert run(
        "submit",
        "--acp-url",
        ACP_URL,
        "--product",
        "QwenPaw",
        "--purpose",
        "nightly gate",
        "--datasets",
        "mail",
        *extra,
    ) == cli.EXIT_OK
    return capsys.readouterr().out.split()[1]


def add_task(store: Store, job_id: str, task_id: str, **fields: Any) -> None:
    """A task row for a job the runner never reached.

    Submission stores only the snapshot; rows appear when a job starts, so a
    read-side case that wants a failed task has to write the row the runner would
    have written.
    """
    store.insert_job_tasks(
        [
            {
                "job_id": job_id,
                "task_id": task_id,
                "attempt": 1,
                "status": runner_module.STATUS_PENDING,
                "grading_type": "automated",
            }
        ]
    )
    if fields:
        store.update_job_task(job_id, task_id, 1, **fields)


# ── submit ────────────────────────────────────────────────────────────────────


def test_submit_queues_what_the_service_resolves(run: Any, store: Store, capsys: Any) -> None:
    job_id = submitted(run, capsys, "--env", "model=qwen3-max", "--env", "build=2026.11")

    job = store.get_job(job_id)
    assert job["submitter"] == "dev-1", "the token, not a flag, picks the subject"
    assert job["acp_url"] == ACP_URL
    assert job["window_kind"] == "immediate"
    assert job["env_fingerprint"] == {"model": "qwen3-max", "build": "2026.11"}
    assert list(store.list_job_datasets(job_id)[0]["resolved_task_ids"]) == [
        "mail_l1",
        "mail_l3",
    ]
    assert store.list_job_tasks(job_id) == [], "a queued job has a plan, not results"


def test_submit_offers_the_selector_the_api_takes(
    run: Any, store: Store, capsys: Any
) -> None:
    """``--categories`` is the whole-category selection, not a shorthand for one id."""
    assert run(
        "submit",
        "--acp-url",
        ACP_URL,
        "--product",
        "QwenPaw",
        "--purpose",
        "nightly gate",
        "--categories",
        "email",
    ) == cli.EXIT_OK
    job_id = capsys.readouterr().out.split()[1]

    row = store.list_job_datasets(job_id)[0]
    assert row["requested_by"] == "category:email", "the catalogue picked this one"
    assert list(row["resolved_task_ids"]) == ["mail_l1", "mail_l3"]


def test_a_full_service_queues_the_job_instead_of_bouncing_it(
    run: Any, store: Store, capsys: Any
) -> None:
    """Four running jobs is what the queue is for, and the CLI says where it is."""
    for index in range(4):
        store.insert_job(
            job_row(
                f"ahead-{index}",
                submitter="other",
                token_subject="other",
                status="running",
                queue_pos=float(index + 1),
            )
        )

    assert run(
        "submit",
        "--acp-url",
        ACP_URL,
        "--product",
        "QwenPaw",
        "--purpose",
        "nightly gate",
        "--datasets",
        "mail",
    ) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "queued" in out and "ahead=" in out


# ── reading a job back ────────────────────────────────────────────────────────


def test_status_flags_the_tasks_that_did_not_work(
    run: Any, store: Store, capsys: Any
) -> None:
    job_id = submitted(run, capsys)
    add_task(store, job_id, "mail_l1")
    add_task(store, job_id, "mail_l3")
    store.update_job_task(
        job_id,
        "mail_l1",
        1,
        status=runner_module.STATUS_FAILED,
        failure_reason="acp_unreachable",
    )
    capsys.readouterr()

    assert run("status", job_id) == cli.EXIT_OK, "a queued job is an answer, not a failure"

    out = capsys.readouterr().out
    assert "failed=1" in out and "pending=1" in out
    assert "mail_l1" in out and "acp_unreachable" in out
    assert "mail_l3" not in out, "a task with nothing wrong with it gets no line"


def test_status_can_hand_the_payload_to_a_script(
    run: Any, store: Store, tmp_path: Path, capsys: Any
) -> None:
    job_id = submitted(run, capsys)
    add_task(store, job_id, "mail_l1")
    add_task(store, job_id, "mail_l3")
    target = tmp_path / "state" / "job.json"

    assert run("status", job_id, "--json", "--out", str(target)) == cli.EXIT_OK

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["job_id"] == job_id
    assert sorted(row["task_id"] for row in payload["tasks"]) == ["mail_l1", "mail_l3"]


def test_detail_asks_for_the_view_and_writes_what_came_back(
    run: Any, tmp_path: Path, capsys: Any, seen: list[httpx.Request]
) -> None:
    job_id = submitted(run, capsys)
    target = tmp_path / "detail.json"

    assert run("detail", job_id, "--out", str(target)) == cli.EXIT_OK

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["job_id"] == job_id
    # There is no second view to choose between, so the request carries the job
    # and nothing else: the CLI cannot be the place a partial document is asked
    # for, because the service would no longer know what that meant.
    call = [request for request in seen if str(request.url).endswith("/detail")]
    assert call and "sensitivity" not in call[-1].url.params


def test_report_downloads_what_the_service_described(
    run: Any, tmp_path: Path, capsys: Any, seen: list[httpx.Request]
) -> None:
    job_id = submitted(run, capsys)
    target = tmp_path / "given" / "report.md"

    assert run("report", job_id, "--format", "md", "--out", str(target)) == cli.EXIT_OK

    body = target.read_bytes()
    assert job_id.encode() in body
    printed = capsys.readouterr().out
    assert str(target) in printed
    assert hashlib.sha256(body).hexdigest()[:16] in printed, "the fingerprint is the file's own"

    download = [request for request in seen if "/v1/reports/" in str(request.url)]
    assert len(download) == 1
    # The signature is the whole gate on that route, so the bearer is dead weight
    # -- and dead weight on a URL that will appear in an exception message.
    assert "authorization" not in download[0].headers


def test_a_broken_download_does_not_quote_the_presigned_link(
    run: Any,
    client: TestClient,
    seen: list[httpx.Request],
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
    tokens: dict[str, str],
) -> None:
    """A failed download prints where it failed, never the credential it carried.

    ``httpx`` puts the request URL -- query included -- into several of its
    exception messages, and the report route is gated by that query alone: a
    sig in a CI log is a live download link until it expires.
    """
    job_id = submitted(run, capsys)
    app = cli_transport(client, seen)
    downloads: list[httpx.Request] = []

    def leaking(request: httpx.Request) -> httpx.Response:
        if "/v1/reports/" in str(request.url):
            downloads.append(request)
            raise httpx.ConnectError(f"connection refused: {request.url}", request=request)
        return app.handle_request(request)

    monkeypatch.setattr(
        cli,
        "EvalClient",
        lambda server, token, *, transport=None: _EVAL_CLIENT(
            server, token, transport=httpx.MockTransport(leaking)
        ),
    )
    capsys.readouterr()

    assert run("report", job_id, "--format", "md") == cli.EXIT_ERROR

    err = capsys.readouterr().err
    signature = str(downloads[0].url).split("sig=", 1)[1].split("&", 1)[0]
    assert signature and signature not in err, "the link is not an error message"
    assert tokens["dev-1"] not in err
    assert "/v1/reports/" in err, "still says which call failed"


def test_a_service_that_names_a_path_for_its_file_does_not_choose_where_it_lands(
    run: Any, client: TestClient, capsys: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The filename on a report link is data from the wire, not an instruction.

    Without the guard a service (or a proxy in front of one) answers with
    ``../../escaped.md`` and the tool writes outside the directory the caller was
    standing in.  ``--out`` is a path the caller typed, so it still goes wherever
    it says -- only the name the CLI invents for itself is narrowed to a name.
    """
    job_id = submitted(run, capsys)
    app = cli_transport(client, [])
    where = tmp_path / "cwd"
    where.mkdir()

    def renamed(request: httpx.Request) -> httpx.Response:
        response = app.handle_request(request)
        if request.url.path.endswith("/report"):
            payload = response.json()
            payload["filename"] = "../../escaped.md"
            response = httpx.Response(response.status_code, json=payload)
        return response

    monkeypatch.setattr(
        cli,
        "EvalClient",
        lambda server, token, *, transport=None: _EVAL_CLIENT(
            server, token, transport=httpx.MockTransport(renamed)
        ),
    )
    monkeypatch.chdir(where)
    capsys.readouterr()

    assert run("report", job_id, "--format", "md") == cli.EXIT_OK

    assert [path.name for path in where.glob("*.md")] == ["escaped.md"]
    assert not (tmp_path / "escaped.md").exists(), "the traversal stayed in the name"


def test_a_refusal_comes_through_as_the_services_words(
    run: Any, capsys: Any, tokens: dict[str, str]
) -> None:
    """A format the service does not render; the CLI quotes it and adds nothing."""
    job_id = submitted(run, capsys)
    capsys.readouterr()

    assert run("report", job_id, "--format", "pdf") == cli.EXIT_ERROR

    err = capsys.readouterr().err
    assert "400 report_format_unsupported" in err
    assert tokens["dev-1"] not in err


# ── watch ─────────────────────────────────────────────────────────────────────


def test_watch_stops_when_its_own_clock_runs_out(
    run: Any, store: Store, capsys: Any
) -> None:
    job_id = submitted(run, capsys)
    capsys.readouterr()

    assert run("watch", job_id, "--interval", "0.05", "--timeout", "0.2") == cli.EXIT_TIMED_OUT

    captured = capsys.readouterr()
    assert "queued" in captured.out
    assert "it keeps its place in the queue" in captured.err
    assert store.get_job(job_id)["status"] == "queued", "giving up is not cancelling"


def test_watch_prints_a_terminal_state_once(
    run: Any, store: Store, capsys: Any
) -> None:
    job_id = submitted(run, capsys)
    add_task(store, job_id, "mail_l1", status=runner_module.STATUS_FINISHED, score=1.0)
    add_task(store, job_id, "mail_l3", status=runner_module.STATUS_FINISHED, score=0.5)
    store.update_job(job_id, status="finished")
    capsys.readouterr()

    assert run("watch", job_id, "--interval", "0.05") == cli.EXIT_OK

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "finished=2" in lines[0]


def test_watch_reports_a_canceled_job_as_not_ok(run: Any, capsys: Any) -> None:
    job_id = submitted(run, capsys)
    assert run("cancel", job_id) == cli.EXIT_OK
    capsys.readouterr()

    assert run("watch", job_id, "--interval", "0.05") == cli.EXIT_JOB_NOT_OK
    assert "canceled" in capsys.readouterr().out


# ── the token ─────────────────────────────────────────────────────────────────


def test_the_token_rides_one_header_and_never_a_url(
    run: Any, tokens: dict[str, str], capsys: Any, seen: list[httpx.Request]
) -> None:
    submitted(run, capsys)

    assert seen, "the call went out over httpx"
    assert all(tokens["dev-1"] not in str(request.url) for request in seen)
    assert all(request.headers["authorization"] == f"Bearer {tokens['dev-1']}" for request in seen)


def test_a_missing_token_is_refused_before_the_network(
    run: Any, capsys: Any, seen: list[httpx.Request]
) -> None:
    assert run("status", "job-1", subject=None) == cli.EXIT_ERROR

    assert seen == []
    assert cli.TOKEN_ENV in capsys.readouterr().err


def test_a_token_not_on_the_list_quotes_the_services_code(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[httpx.Request] = []
    real = cli.EvalClient
    monkeypatch.setattr(
        cli,
        "EvalClient",
        lambda server, token, *, transport=None: real(
            server, token, transport=cli_transport(client, seen)
        ),
    )
    monkeypatch.setenv(cli.SERVER_ENV, BASE)
    monkeypatch.setenv(cli.TOKEN_ENV, "not-on-the-list")

    assert cli.main(["status", "job-1"]) == cli.EXIT_ERROR

    err = capsys.readouterr().err
    assert "401 unauthenticated" in err
    assert "not-on-the-list" not in err


def test_a_service_that_is_not_listening_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    real = cli.EvalClient
    monkeypatch.setattr(
        cli,
        "EvalClient",
        lambda server, token, *, transport=None: real(
            server, token, transport=httpx.MockTransport(refuse)
        ),
    )
    monkeypatch.setenv(cli.SERVER_ENV, BASE)
    monkeypatch.setenv(cli.TOKEN_ENV, "anything")

    assert cli.main(["status", "job-1"]) == cli.EXIT_ERROR
    assert "cannot reach the service" in capsys.readouterr().err


def test_a_malformed_fingerprint_pair_is_refused_locally(
    run: Any, capsys: Any, seen: list[httpx.Request]
) -> None:
    assert (
        run(
            "submit",
            "--acp-url",
            ACP_URL,
            "--product",
            "QwenPaw",
            "--purpose",
            "gate",
            "--datasets",
            "mail",
            "--env",
            "model",
        )
        == cli.EXIT_ERROR
    )

    assert seen == []
    assert "KEY=VALUE" in capsys.readouterr().err


def test_an_empty_selector_is_refused_by_the_service_not_here(
    run: Any, capsys: Any, seen: list[httpx.Request]
) -> None:
    """The CLI does not re-implement the selector rule; it forwards and quotes."""
    assert (
        run(
            "submit",
            "--acp-url",
            ACP_URL,
            "--product",
            "QwenPaw",
            "--purpose",
            "gate",
        )
        == cli.EXIT_ERROR
    )

    assert len(seen) == 1
    assert "empty_selector" in capsys.readouterr().err
