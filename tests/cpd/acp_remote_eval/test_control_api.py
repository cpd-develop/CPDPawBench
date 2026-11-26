# -*- coding: utf-8 -*-
"""The control plane as an HTTP surface: tokens in, statuses out.

``test_jobs.py`` covers the order the submission guarantees ride on.  What
belongs here is only visible at the boundary: which refusal becomes which
status, whether a token the CLI minted into the allowlist file authenticates
against the running app, that a code this service forgot to map still answers a
4xx rather than a bare 500, and that no response or log line repeats a token.

Auth runs on the real default implementation -- a YAML allowlist written by
:func:`.auth.add_subject` and re-read by :class:`.auth.StaticConfigVerifier` --
rather than a stub standing in for it, because the parts people get wrong are
the file round-trip and the revocation taking effect without a restart.
"""

from __future__ import annotations

import ast
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pawbench.cpd.acp_remote_eval.service import api
from pawbench.cpd.acp_remote_eval.service.auth import (
    SCOPE_ADMIN,
    SCOPE_SUBMIT,
    StaticConfigVerifier,
    add_subject,
    revoke_subject,
)
from pawbench.cpd.acp_remote_eval.service.config import EvalConfig
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetService
from pawbench.cpd.acp_remote_eval.service.jobs import MAX_TEXT_FIELD_CHARS
from pawbench.cpd.acp_remote_eval.service.queue import (
    JobQueue,
    QueueLimits,
    STATUS_CANCELED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import (
    build_control_app,
    dataset_service,
    eval_config,
    job_row,
    write_task,
)

MORNING = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
ACP_URL = "http://127.0.0.1:9000/rpc"


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    root = tmp_path / "builtin"
    write_task(root, "mail_l1", scenario="Office_Productivity/Email", timeout=60)
    write_task(root, "mail_l3", scenario="Office_Productivity/Email", timeout=60)
    write_task(root, "chart_open", scenario="Data_Analytics/Visualization", timeout=900)
    return root


@pytest.fixture()
def config(tmp_path: Path, builtin_root: Path) -> EvalConfig:
    return eval_config(tmp_path, builtin_root=builtin_root)


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(MORNING)


@pytest.fixture()
def allowlist(tmp_path: Path) -> Path:
    return tmp_path / "allowlist.yaml"


@pytest.fixture()
def tokens(allowlist: Path) -> dict[str, str]:
    """Three real subjects, each with a token only the allowlist's hash knows.

    ``ops`` carries ``admin`` alongside ``submit`` because that is how the CLI
    issues a queue-governance token; a subject with nothing else is a submitter.
    """
    return {
        "dev-1": add_subject(allowlist, "dev-1", display_name="Dev 1"),
        "dev-2": add_subject(allowlist, "dev-2", display_name="Dev 2"),
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
    service.create_builtin_view(
        dataset_id="charts",
        name="Charts",
        owner="dev-1",
        filter_spec={"task_ids": ["chart_open"]},
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
def stopped() -> list[str]:
    """Jobs the app forwarded a cancel to, which is the agent-facing half."""
    return []


@pytest.fixture()
def make_client(
    store: Store,
    config: EvalConfig,
    clock: FrozenClock,
    queue: JobQueue,
    datasets: DatasetService,
    allowlist: Path,
    tmp_path: Path,
    stopped: list[str],
):
    """The app every case runs against, rebuildable for the two auth shapes.

    Rebuilding is what the expired-token and empty-allowlist cases need: both
    are about the records the verifier was handed at startup, which a client
    built over a populated allowlist cannot show.
    """

    def build(**overrides: Any) -> TestClient:
        return TestClient(
            _build_app(
                store=store,
                config=config,
                clock=clock,
                queue=queue,
                datasets=datasets,
                allowlist=allowlist,
                tmp_path=tmp_path,
                stopped=stopped,
                **overrides,
            )
        )

    return build


@pytest.fixture()
def client(make_client) -> TestClient:
    return make_client()


def _build_app(
    *,
    store: Store,
    config: EvalConfig,
    clock: FrozenClock,
    queue: JobQueue,
    datasets: DatasetService,
    allowlist: Path,
    tmp_path: Path,
    stopped: list[str],
    verifier: StaticConfigVerifier | None = None,
    jobs: Any = None,
) -> Any:
    return build_control_app(
        store=store,
        config=config,
        queue=queue,
        datasets=datasets,
        allowlist=allowlist,
        tmp_path=tmp_path,
        clock=clock,
        now=MORNING,
        stopped=stopped,
        verifier=verifier,
        jobs=jobs,
    )


def auth(tokens: dict[str, str], subject: str = "dev-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens[subject]}"}


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "acp_url": ACP_URL,
        "selector": {"datasets": ["mail"]},
        "window": {"kind": "immediate"},
        "product": "qwenpaw",
        "purpose": "nightly regression",
    }
    values.update(overrides)
    return values


def jobs_of(store: Store) -> list[str]:
    return sorted(str(row["id"]) for row in store.list_jobs())


def submitted(
    client: TestClient, tokens: dict[str, str], subject: str = "dev-1", **overrides: Any
) -> dict[str, Any]:
    response = client.post("/v1/jobs", json=body(**overrides), headers=auth(tokens, subject))
    assert response.status_code == 201, response.text
    return response.json()


# ── the token gate ────────────────────────────────────────────────────────────


def test_a_token_from_the_allowlist_submits_and_gets_a_job_id(client, tokens):
    result = submitted(client, tokens)

    assert result["status"] == STATUS_QUEUED
    assert result["resolved"]["task_count"] == 2
    assert result["job_id"].startswith("job-")


def test_a_call_without_a_header_is_401_before_anything_is_read(client):
    response = client.get("/v1/jobs")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"
    assert response.json()["message"]


def test_a_token_that_is_not_on_the_allowlist_is_401(client):
    response = client.get("/v1/jobs", headers={"Authorization": "Bearer not-issued"})

    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"


def test_a_scheme_other_than_bearer_is_not_a_token(client, tokens):
    response = client.get("/v1/jobs", headers={"Authorization": f"token {tokens['dev-1']}"})

    assert response.status_code == 401


def test_no_control_route_answers_without_a_token(client):
    """Every mounted control route answers 401 without a token (D1).

    Read off ``client.app.routes`` rather than a list here, so a route added
    later that forgets ``authenticate`` fails instead of joining a set nobody
    updates.  The three data-plane paths are excluded on purpose -- a run token
    gates them, and ``test_data_plane_api.py`` covers that.
    """
    data_plane = {api.ASSET_ROUTE, api.ARTIFACT_ROUTE, api.REPORT_ROUTE}
    checked = 0
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/v1/") or path in data_plane:
            continue
        # "1" everywhere: `attempt` is declared `int`, and a placeholder that
        # fails FastAPI's own coercion is answered 422 before the handler runs,
        # which would prove nothing about auth.
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in sorted(set(route.methods) - {"HEAD", "OPTIONS"}):
            response = client.request(method, url)
            assert response.status_code == 401, f"{method} {path}"
            assert response.json()["error"] == "unauthenticated"
            checked += 1

    # 28: the catalogue drill-down added four GETs (one task, its markdown, and
    # a fixture with its preview).  Two more are the beat page and its full
    # content, both authenticated and both read on demand.
    assert checked == 30, "one call per control route; a wrong count is a typo here"


def test_revoking_in_the_file_takes_effect_without_a_restart(client, tokens, allowlist):
    revoke_subject(allowlist, "dev-1")

    response = client.post("/v1/jobs", json=body(), headers=auth(tokens))

    assert response.status_code == 401
    assert response.json()["error"] == "revoked"


def test_an_expired_token_is_401_and_is_not_echoed_back(make_client, allowlist):
    dead = add_subject(
        allowlist,
        "ghost",
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    client = make_client()

    response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {dead}"})

    assert response.status_code == 401
    assert response.json()["error"] == "expired"
    assert dead not in response.text


def test_an_empty_allowlist_is_a_closed_service_not_an_open_one(make_client, tokens):
    """A deployment that never issued a token refuses everyone, on every route.

    The routes stay mounted so the answer is a 401 naming the auth failure
    rather than a 404 that reads as a broken install, and a token handed out of
    band stops working the moment the file it came from is replaced.
    """
    client = make_client(verifier=StaticConfigVerifier([]))

    assert client.get("/v1/jobs", headers=auth(tokens)).status_code == 401
    assert client.post("/v1/jobs", json=body(), headers=auth(tokens)).status_code == 401


def test_nothing_coming_back_from_the_service_carries_the_token(client, tokens):
    job_id = submitted(client, tokens)["job_id"]
    secret = tokens["dev-1"]

    for response in (
        client.get("/v1/jobs", headers=auth(tokens)),
        client.get(f"/v1/jobs/{job_id}", headers=auth(tokens)),
        client.post(f"/v1/jobs/{job_id}/cancel", json={}, headers=auth(tokens)),
    ):
        assert response.status_code == 200, response.text
        assert secret not in response.text


def test_the_log_names_the_subject_and_never_the_token(
    client: TestClient, tokens: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    secret = tokens["dev-1"]

    with caplog.at_level(logging.INFO):
        job_id = submitted(client, tokens)["job_id"]

    submission = [r for r in caplog.records if r.getMessage() == "job submitted"]
    assert len(submission) == 1
    assert submission[0].submitter == "dev-1"
    assert submission[0].job_id == job_id
    # Asserted on the record fields, not the rendered line: this codebase puts
    # its context in ``extra``, and a token that reached a field would survive
    # whichever formatter the deployment picks.
    values = [str(value) for record in caplog.records for value in vars(record).values()]
    assert secret not in caplog.text
    assert not [value for value in values if secret in value]


# ── codes to statuses ─────────────────────────────────────────────────────────

#: Refusals the exception handler never sees, with the module that raises them.
#: ``pilot_seed_incomplete`` is raised by the composition root before the port is
#: bound, so it stops a boot rather than answering a request -- and the scan below
#: checks the exemption against the raise site, so it expires the day the code
#: starts reaching a route.
_UNROUTED_CODES = {"pilot_seed_incomplete": "pilot.py"}


def test_a_submission_without_an_acp_url_writes_no_row(client, tokens, store):
    response = client.post("/v1/jobs", json=body(acp_url=""), headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "acp_url_missing"
    assert jobs_of(store) == []


def test_a_stdio_endpoint_is_refused_as_an_unsupported_url(client, tokens):
    response = client.post("/v1/jobs", json=body(acp_url="stdio://agent"), headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "acp_url_unsupported"


def test_a_body_that_is_not_json_is_refused_rather_than_crashing(client, tokens):
    response = client.post(
        "/v1/jobs",
        content=b"acp_url=http://x",
        headers={**auth(tokens), "content-type": "text/plain"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "body_not_json"


def test_json_nested_past_the_recursion_limit_is_the_callers_error_not_ours(client, tokens):
    """``[[[[...`` is valid syntax and a blown stack at the same time.

    ``json`` scans with the C parser, which measures depth against the
    interpreter's recursion limit: the threshold was measured for the transcript
    page in ``test_reports.py`` (5,000 levels parse, tens of thousands raise).  A
    request whose body cannot be turned into a document is a fact about the
    request, so it answers like the other malformed bodies do.
    """
    response = client.post(
        "/v1/jobs",
        content=b"[" * 50_000,
        headers={**auth(tokens), "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "body_not_json"


def test_a_control_body_is_read_up_to_a_ceiling_and_not_as_far_as_the_caller_sends(
    client, tokens, monkeypatch
):
    """One subject's POST should not decide how much memory the service holds.

    The ceiling is the point rather than the number: every body these routes take
    is metadata, and the one thing on this service that is legitimately large -- a
    task package -- has its own streaming route.  Lowering the constant is how the
    case says "this route consults it" without making the suite hold a megabyte.
    """
    monkeypatch.setattr(api, "MAX_JSON_BODY_BYTES", 4096)

    response = client.post(
        "/v1/jobs",
        content=b"[" * 5000,
        headers={**auth(tokens), "content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"] == "body_too_large"


def test_an_unknown_selector_entry_comes_back_as_422_naming_the_id(client, tokens):
    response = client.post(
        "/v1/jobs", json=body(selector={"datasets": ["nope"]}), headers=auth(tokens)
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "selector_unknown_ids"
    assert payload["details"]["unknown_ids"] == ["nope"]


def test_a_window_that_cannot_hold_the_plan_is_422(client, tokens):
    window = {
        "kind": "custom",
        "not_before": MORNING.isoformat(timespec="seconds"),
        "not_after": (MORNING + timedelta(seconds=30)).isoformat(timespec="seconds"),
    }

    response = client.post("/v1/jobs", json=body(window=window), headers=auth(tokens))

    assert response.status_code == 422
    assert response.json()["error"] == "window_too_short"


def test_a_subject_at_its_running_cap_is_bounced_with_the_cap(client, tokens, store, config):
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))

    response = client.post("/v1/jobs", json=body(), headers=auth(tokens))

    assert response.status_code == 429
    payload = response.json()
    assert payload["error"] == "per_user_limit"
    assert payload["details"]["limit"] == config.service.max_running_per_user
    assert jobs_of(store) == ["job-live"]


def test_a_missing_job_is_404_for_anyone_on_the_list(client, tokens):
    response = client.get("/v1/jobs/job-never-submitted", headers=auth(tokens))

    assert response.status_code == 404
    assert response.json()["error"] == "job_not_found"


def test_a_typo_in_the_status_filter_is_refused_not_answered_empty(client, tokens):
    response = client.get("/v1/jobs?status=queuedd", headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "status_invalid"


def test_a_non_numeric_limit_is_refused(client, tokens):
    response = client.get("/v1/jobs?limit=all", headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "limit_invalid"


def test_a_code_the_status_table_never_mapped_still_answers_4xx(
    client: TestClient,
    tokens: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """The fallback, not the table, is what this case is about.

    Dropping the mapping simulates the next module adding a code nobody
    remembered here: the caller still gets a 400 naming it, and the operator
    gets an error line saying the boundary is incomplete.
    """
    monkeypatch.setattr(api, "_CONTROL_STATUS", {})

    with caplog.at_level(logging.ERROR):
        response = client.post("/v1/jobs", json=body(acp_url=""), headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "acp_url_missing"
    assert "unmapped" in caplog.text


def test_a_filter_key_nobody_spelled_right_is_not_an_alarm(
    client: TestClient, tokens: dict[str, str], caplog: pytest.LogCaptureFixture
):
    """The status did not change here; the line someone gets woken by did.

    An unlisted filter key was already a 400, because the fallback answers 400 for
    anything it does not know.  What it also did was log ``error`` about our own
    table being incomplete -- a message an on-call reader acts on, emitted once per
    mistyped body, for a deployment that has nothing wrong with it.
    """
    with caplog.at_level(logging.INFO):
        response = client.post(
            "/v1/datasets",
            json={"id": "typo", "name": "Typo", "filter": {"enviro": "open"}},
            headers=auth(tokens),
        )

    assert response.status_code == 400
    assert response.json()["error"] == "unknown_filter_key"
    told = [
        record
        for record in caplog.records
        if getattr(record, "code", "") == "unknown_filter_key"
    ]
    assert [(record.levelno, record.subject) for record in told] == [(logging.INFO, "dev-1")]
    assert "unmapped" not in caplog.text


def test_every_control_plane_code_promises_a_status() -> None:
    """A refusal with no row in the table is a status nobody chose.

    The services raise their own code vocabularies, so the only thing standing
    between a new refusal and the 400-plus-error fallback is this table.  The
    scan is over the source rather than a list copied here because a copied list
    is a second place to forget.
    """
    mapped = set(api._CONTROL_STATUS) | set(api._ERROR_STATUS)
    stray = {
        code: modules
        for code, modules in _raised_codes().items()
        if code not in mapped
    }

    assert stray == {code: {module} for code, module in _UNROUTED_CODES.items()}


def _raised_codes() -> dict[str, set[str]]:
    """Every code raised as one of the five refusals, against the module raising it.

    Keyword-string literals only: a computed code is not something the exception
    handler can have promised a status for anyway, so the scan has no reason to
    guess at it.
    """
    classes = {"SubmissionError", "QueueError", "WindowError", "DatasetError", "ReportError"}
    found: dict[str, set[str]] = {}
    for path in sorted(Path(api.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            first = node.args[0]
            if name in classes and isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, set()).add(path.name)
    return found


# ── reads ─────────────────────────────────────────────────────────────────────


def test_one_subject_sees_another_subjects_jobs(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    listed = client.get("/v1/jobs", headers=auth(tokens, "dev-2")).json()

    assert [item["job_id"] for item in listed["jobs"]] == [job_id]
    assert listed["jobs"][0]["submitter"] == "dev-1"
    assert listed["count"] == 1


def test_the_listing_filters_by_status_and_submitter(client, tokens, store):
    submitted(client, tokens)
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-2"))

    running = client.get("/v1/jobs?status=running", headers=auth(tokens)).json()
    dev2 = client.get("/v1/jobs?submitter=dev-2", headers=auth(tokens)).json()

    assert [item["job_id"] for item in running["jobs"]] == ["job-live"]
    assert [item["job_id"] for item in dev2["jobs"]] == ["job-live"]


def test_the_listing_pages_in_queue_order(client, tokens):
    first = submitted(client, tokens)["job_id"]
    second = submitted(client, tokens)["job_id"]

    page = client.get("/v1/jobs?limit=1", headers=auth(tokens)).json()
    whole = client.get("/v1/jobs", headers=auth(tokens)).json()

    # The page is a queue-order slice, so ``limit=1`` is the job at the head of
    # the queue rather than the one that happened to be submitted first.
    assert page["count"] == 1
    assert [item["job_id"] for item in page["jobs"]] == [first]
    assert [item["job_id"] for item in whole["jobs"]] == [first, second]


def test_the_detail_carries_the_queue_position_and_the_snapshot(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    detail = client.get(f"/v1/jobs/{job_id}", headers=auth(tokens)).json()

    assert detail["status"] == STATUS_QUEUED
    assert detail["queue"]["job_id"] == job_id
    assert detail["datasets"][0]["dataset_id"] == "mail"
    assert detail["tasks"] == []


# ── reorder and cancel ────────────────────────────────────────────────────────


def test_a_queued_job_moves_by_queue_pos(client, tokens):
    first = submitted(client, tokens)["job_id"]
    second = submitted(client, tokens)["job_id"]

    moved = client.patch(f"/v1/jobs/{second}", json={"queue_pos": 1.0}, headers=auth(tokens))
    listed = client.get("/v1/jobs", headers=auth(tokens)).json()["jobs"]

    assert moved.status_code == 200, moved.text
    assert moved.json()["queue_pos"] == 1.0
    assert [item["job_id"] for item in listed] == [second, first]


def test_a_reorder_needs_exactly_one_target(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    response = client.patch(f"/v1/jobs/{job_id}", json={}, headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "reorder_needs_one_target"


def test_a_misspelled_reorder_field_is_refused_instead_of_answered_200(
    client: TestClient, tokens: dict[str, str]
):
    job_id = submitted(client, tokens)["job_id"]
    before = client.get(f"/v1/jobs/{job_id}", headers=auth(tokens)).json()["queue_pos"]

    response = client.patch(f"/v1/jobs/{job_id}", json={"position": 1.0}, headers=auth(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "reorder_field_unknown"
    after = client.get(f"/v1/jobs/{job_id}", headers=auth(tokens)).json()["queue_pos"]
    assert after == before


def test_moving_someone_elses_job_is_403_and_an_admin_may(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    refused = client.patch(
        f"/v1/jobs/{job_id}", json={"queue_pos": 1.0}, headers=auth(tokens, "dev-2")
    )
    allowed = client.patch(
        f"/v1/jobs/{job_id}", json={"queue_pos": 1.0}, headers=auth(tokens, "ops")
    )

    assert refused.status_code == 403
    assert refused.json()["error"] == "not_job_owner"
    assert allowed.status_code == 200
    assert allowed.json()["queue_pos"] == 1.0


def test_a_running_job_says_to_cancel_instead_of_reordering(client, tokens, store):
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))

    response = client.patch("/v1/jobs/job-live", json={"queue_pos": 1.0}, headers=auth(tokens))

    assert response.status_code == 409
    assert response.json()["error"] == "job_not_reorderable"


def test_cancelling_a_queued_job_needs_no_reach_into_the_agent(client, tokens, stopped):
    job_id = submitted(client, tokens)["job_id"]

    outcome = client.post(f"/v1/jobs/{job_id}/cancel", json={}, headers=auth(tokens)).json()

    assert outcome["status"] == STATUS_CANCELED
    assert outcome["was_running"] is False
    assert stopped == []


def test_a_cancel_with_no_body_at_all_is_not_a_syntax_error(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    response = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth(tokens))

    # A body is optional here -- ``reason`` is the only field -- so an empty
    # POST has to read as "cancel without saying why", not as bad JSON.
    assert response.status_code == 200, response.text
    assert response.json()["status"] == STATUS_CANCELED


def test_cancelling_a_running_job_forwards_to_the_runtime(
    client: TestClient, tokens: dict[str, str], store: Store, stopped: list[str]
):
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))

    outcome = client.post("/v1/jobs/job-live/cancel", json={}, headers=auth(tokens)).json()

    assert outcome["was_running"] is True
    assert stopped == ["job-live"]


def test_a_cancel_reason_reaches_the_row_and_a_pasted_log_does_not(client, tokens):
    job_id = submitted(client, tokens)["job_id"]

    client.post(
        f"/v1/jobs/{job_id}/cancel", json={"reason": "wrong dataset"}, headers=auth(tokens)
    )

    other = submitted(client, tokens)["job_id"]
    refused = client.post(
        f"/v1/jobs/{other}/cancel",
        json={"reason": "x" * (MAX_TEXT_FIELD_CHARS + 1)},
        headers=auth(tokens),
    )

    # The reason is a column every listing reads back, so the ceiling that keeps
    # a pasted log out of ``purpose`` keeps it out here too -- and the refusal
    # leaves the second job queued rather than half-cancelled.
    reason = client.get(f"/v1/jobs/{job_id}", headers=auth(tokens)).json()["error"]
    assert reason == "wrong dataset"
    assert refused.status_code == 400
    assert refused.json()["error"] == "field_too_long"
    status = client.get(f"/v1/jobs/{other}", headers=auth(tokens)).json()["status"]
    assert status == STATUS_QUEUED


def test_cancelling_someone_elses_job_is_403(client, tokens, store):
    store.insert_job(job_row("job-2", status=STATUS_QUEUED, submitter="dev-2"))

    refused = client.post("/v1/jobs/job-2/cancel", json={}, headers=auth(tokens))
    allowed = client.post("/v1/jobs/job-2/cancel", json={}, headers=auth(tokens, "ops"))

    assert refused.status_code == 403
    assert allowed.json()["status"] == STATUS_CANCELED


# ── selector preview ──────────────────────────────────────────────────────────


def test_the_preview_resolves_a_category_the_submitter_never_typed(client, tokens):
    response = client.post(
        "/v1/datasets/resolve",
        json={"selector": {"categories": ["email"]}},
        headers=auth(tokens),
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["task_count"] == 2
    assert sorted(payload["task_ids"]) == ["mail_l1", "mail_l3"]
    assert payload["categories_expanded"] == {"email": ["mail"]}


def test_the_preview_reports_a_mixed_selection_without_editing_anything(
    client: TestClient, tokens: dict[str, str], store: Store
):
    response = client.post(
        "/v1/datasets/resolve",
        json={"selector": {"datasets": ["mail", "charts"], "categories": ["email"]}},
        headers=auth(tokens),
    )

    payload = response.json()
    assert payload["task_count"] == 3
    assert payload["duplicates_removed"] == 2
    assert jobs_of(store) == []


def test_the_preview_answers_unknown_ids_as_data_not_as_an_error(client, tokens):
    response = client.post(
        "/v1/datasets/resolve", json={"selector": {"datasets": ["nope"]}}, headers=auth(tokens)
    )

    assert response.status_code == 200
    assert response.json()["unknown_ids"] == ["nope"]


def test_a_resolve_body_without_a_selector_is_400(client, tokens):
    response = client.post(
        "/v1/datasets/resolve", json={"categories": ["email"]}, headers=auth(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "field_type_invalid"
