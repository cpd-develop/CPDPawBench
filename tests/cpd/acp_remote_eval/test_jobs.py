# -*- coding: utf-8 -*-
"""``POST /v1/jobs`` and the submitter's reads, one layer below HTTP.

The routes in ``test_control_api.py`` will cover statuses and bearer tokens.
What belongs here is the *order*, because that is what the guarantees ride on:
nothing is written for a body that is going to be refused, the dataset snapshot
is written before the queue can see the job, and a failure in the middle leaves
a closed row rather than a ``new`` one nobody will ever run.

Everything runs on a frozen clock, so the nightly and custom-window cases are
arithmetic rather than a wait for midnight.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from pawbench.cpd.acp_remote_eval.acp.client import AcpError
from pawbench.cpd.acp_remote_eval.service.auth import SCOPE_ADMIN, SCOPE_SUBMIT, Principal
from pawbench.cpd.acp_remote_eval.service.config import EvalConfig
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetError
from pawbench.cpd.acp_remote_eval.service.jobs import (
    JobService,
    MAX_TEXT_FIELD_CHARS,
    SubmissionError,
)
from pawbench.cpd.acp_remote_eval.service.queue import (
    JobQueue,
    QueueError,
    QueueLimits,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
)
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock, WindowError
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import dataset_service, eval_config, job_row, write_task

ACP_URL = "http://127.0.0.1:9000/rpc"
MORNING = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

SUBMITTER = Principal("dev-1", "Dev 1", frozenset({SCOPE_SUBMIT}))
OTHER = Principal("dev-2", "Dev 2", frozenset({SCOPE_SUBMIT}))
ADMIN = Principal("ops", "Ops", frozenset({SCOPE_SUBMIT, SCOPE_ADMIN}))


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    """Two email tasks at a minute each, one long chart task, ten bulk tasks.

    The timeouts differ on purpose: the window floor is defined over the tasks a
    submission actually selected, and that is only testable if the corpus has
    tasks the selector could have picked and did not.
    """
    root = tmp_path / "builtin"
    write_task(root, "mail_l1", scenario="Office_Productivity/Email", timeout=60)
    write_task(root, "mail_l3", scenario="Office_Productivity/Email", timeout=60)
    write_task(root, "chart_open", scenario="Data_Analytics/Visualization", timeout=900)
    for index in range(10):
        write_task(root, f"bulk_{index}", scenario="Bulk/Many", timeout=60)
    return root


@pytest.fixture()
def config(tmp_path: Path, builtin_root: Path) -> EvalConfig:
    return eval_config(tmp_path, builtin_root=builtin_root)


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(MORNING)


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
def catalog(store: Store, config: EvalConfig):
    """The catalogue, with three views and one category filed under 'email'."""
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
    service.create_builtin_view(
        dataset_id="bulk",
        name="Bulk",
        owner="dev-1",
        filter_spec={"scenario": "Bulk/Many"},
    )
    return service


@pytest.fixture()
def service(
    store: Store, config: EvalConfig, queue: JobQueue, catalog, clock: FrozenClock
) -> JobService:
    return JobService(store=store, queue=queue, datasets=catalog, config=config, clock=clock)


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


def custom_window(seconds: int) -> dict[str, str]:
    """A bounded window of ``seconds`` starting now, as the dashboard writes it."""
    return {
        "kind": "custom",
        "not_before": MORNING.isoformat(timespec="seconds"),
        "not_after": (MORNING + timedelta(seconds=seconds)).isoformat(timespec="seconds"),
    }


def jobs_of(store: Store) -> list[str]:
    return sorted(str(row["id"]) for row in store.list_jobs())


# ── what one submission writes ────────────────────────────────────────────────


def test_a_submission_queues_the_job_and_records_who_asked(service: JobService, store: Store):
    result = service.submit(body(purpose="compare the vision model"), SUBMITTER)

    assert result["status"] == STATUS_QUEUED
    assert result["job_id"] == store.list_jobs()[0]["id"]
    row = store.get_job(result["job_id"])
    assert row["acp_url"] == ACP_URL
    assert row["submitter"] == "dev-1"
    assert row["token_subject"] == "dev-1"
    assert row["purpose"] == "compare the vision model"
    assert row["window_kind"] == "immediate"


def test_the_queue_views_drop_the_endpoints_credential(
    service: JobService, store: Store
):
    """``GET /v1/jobs`` is everyone's list, so it cannot carry one person's key.

    The row keeps the URL exactly as submitted -- the runner has to be able to
    reconnect with it -- and only the two read surfaces narrow it to host+path.
    """
    secret = "hunter2-key"
    result = service.submit(
        body(acp_url=f"http://agent:{secret}@eval.example.com/rpc?key={secret}&v=2"),
        SUBMITTER,
    )

    assert store.get_job(result["job_id"])["acp_url"].count(secret) == 2
    for view in (service.get(result["job_id"]), service.list_jobs()["jobs"][0]):
        assert view["acp_url"] == "http://eval.example.com/rpc"
        assert secret not in json.dumps(view)


def test_the_response_carries_the_resolved_plan_and_the_window(service: JobService):
    result = service.submit(body(selector={"datasets": ["mail", "charts"]}), SUBMITTER)

    resolved = result["resolved"]
    assert resolved["task_count"] == 3
    assert resolved["by_dataset"] == {"mail": 2, "charts": 1}
    assert resolved["duplicates_removed"] == 0
    assert resolved["task_ids_digest"]
    assert result["window"]["kind"] == "immediate"
    assert result["window"]["tz"] == "Asia/Shanghai"


def test_one_snapshot_row_per_dataset_holds_the_tasks_that_job_ran(
    service: JobService, store: Store
):
    result = service.submit(body(selector={"datasets": ["charts", "mail"]}), SUBMITTER)

    rows = store.list_job_datasets(result["job_id"])
    assert [row["dataset_id"] for row in rows] == ["charts", "mail"]
    assert [row["dataset_kind"] for row in rows] == ["builtin_view", "builtin_view"]
    assert rows[1]["resolved_task_ids"] == ["mail_l1", "mail_l3"]


def test_a_dataset_widened_after_the_preview_does_not_widen_the_job(
    service: JobService, store: Store
):
    """The snapshot is the preview's task list, not a later read of the dataset.

    ``datasets.resolve`` and the snapshot are two reads of the same table, and a
    dataset is edited in place -- so without the intersection a submission could
    end up scoring questions the submitter never saw in the preview.
    """
    real_get_dataset = store.get_dataset
    reads = {"n": 0}

    def get_dataset(dataset_id: str) -> Mapping[str, Any] | None:
        reads["n"] += 1
        record = real_get_dataset(dataset_id)
        if reads["n"] > 1 and record is not None:
            return {**record, "task_ids": [*record["task_ids"], "chart_open"]}
        return record

    store.get_dataset = get_dataset  # type: ignore[method-assign]
    result = service.submit(body(), SUBMITTER)

    assert reads["n"] > 1, "the test needs the snapshot read to disagree with the preview"
    assert store.list_job_datasets(result["job_id"])[0]["resolved_task_ids"] == [
        "mail_l1",
        "mail_l3",
    ]


def test_a_category_pulls_in_datasets_the_submitter_never_named(
    service: JobService, store: Store
):
    """The snapshot must cover a category's datasets, which ``by_dataset`` omits.

    ``ResolveResult.by_dataset`` counts what the submitter named; a category-only
    selector names none, so building the snapshot off it refuses the submission
    as an empty selection.
    """
    result = service.submit(body(selector={"categories": ["email"]}), SUBMITTER)

    assert result["resolved"]["task_count"] == 2
    row = store.list_job_datasets(result["job_id"])[0]
    assert row["dataset_id"] == "mail"
    assert row["requested_by"] == "category:email"


def test_a_task_two_datasets_share_is_recorded_under_both_and_counted_once(
    service: JobService, store: Store
):
    result = service.submit(body(selector={"datasets": ["mail", "charts"]}), SUBMITTER)

    assert result["resolved"]["task_count"] == 3
    rows = store.list_job_datasets(result["job_id"])
    assert {row["dataset_id"] for row in rows} == {"charts", "mail"}


# ── refusals that must leave nothing behind ───────────────────────────────────


def test_a_selector_naming_a_missing_dataset_writes_no_row(service: JobService, store: Store):
    with pytest.raises(SubmissionError) as refused:
        service.submit(body(selector={"datasets": ["nope"]}), SUBMITTER)

    assert refused.value.code == "selector_unknown_ids"
    assert jobs_of(store) == []


def test_a_selector_resolving_to_nothing_writes_no_row(service: JobService, store: Store):
    """The catalogue owns this code, so it comes back as a ``DatasetError``.

    Not every refusal is a ``SubmissionError``: re-raising another module's code
    here would put the same rule in two places and let them drift.
    """
    with pytest.raises(DatasetError) as refused:
        service.submit(body(selector={}), SUBMITTER)

    assert refused.value.code == "empty_selector"
    assert jobs_of(store) == []


def test_a_stdio_acp_url_is_refused_at_submission(service: JobService, store: Store):
    """Only an HTTP-shaped agent can be reached from a tick.

    ``runtime.http_endpoint`` rebuilds the endpoint from this string on every
    launch, so an address the service cannot speak has to fail where the
    submitter sees it rather than in somebody else's log.
    """
    with pytest.raises(SubmissionError) as refused:
        service.submit(body(acp_url="stdio:///tmp/agent"), SUBMITTER)

    assert refused.value.code == "acp_url_unsupported"
    assert jobs_of(store) == []


def test_a_missing_acp_url_is_refused_at_submission(service: JobService, store: Store):
    with pytest.raises(SubmissionError) as refused:
        service.submit(body(acp_url="   "), SUBMITTER)

    assert refused.value.code == "acp_url_missing"
    assert jobs_of(store) == []


def test_an_oversized_purpose_is_refused_before_the_row_exists(
    service: JobService, store: Store
):
    with pytest.raises(SubmissionError) as refused:
        service.submit(body(purpose="x" * (MAX_TEXT_FIELD_CHARS + 1)), SUBMITTER)

    assert refused.value.code == "field_too_long"
    assert jobs_of(store) == []


def test_an_oversized_env_fingerprint_is_refused(service: JobService, store: Store):
    with pytest.raises(SubmissionError) as refused:
        service.submit(body(env_fingerprint={"blob": "x" * 5000}), SUBMITTER)

    assert refused.value.code == "env_fingerprint_too_large"
    assert jobs_of(store) == []


def test_a_fingerprint_is_stored_as_written(service: JobService, store: Store):
    result = service.submit(body(env_fingerprint={"os": "linux", "gpu": "none"}), SUBMITTER)

    assert store.get_job(result["job_id"])["env_fingerprint"] == {"os": "linux", "gpu": "none"}


def test_the_per_user_cap_is_answered_before_anything_is_written(
    service: JobService, store: Store
):
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))

    with pytest.raises(SubmissionError) as refused:
        service.submit(body(), SUBMITTER)

    assert refused.value.code == "per_user_limit"
    assert refused.value.details["limit"] == 1
    assert jobs_of(store) == ["job-live"]


def test_a_full_service_queues_the_submission_instead_of_bouncing_it(
    service: JobService, store: Store
):
    """Four running jobs is what the queue is for, not a reason to refuse.

    Design section 5.3 makes only the per-subject cap a refusal; conflating the
    two would turn a busy service into a 429 for everyone.
    """
    for index in range(4):
        store.insert_job(
            job_row(f"job-live-{index}", status=STATUS_RUNNING, submitter=f"other-{index}")
        )

    result = service.submit(body(), SUBMITTER)

    assert result["status"] == STATUS_QUEUED
    assert store.get_job(result["job_id"])["status"] == STATUS_QUEUED


# ── a failure in the middle ───────────────────────────────────────────────────


def test_a_submission_that_cannot_write_leaves_no_row_to_close(
    service: JobService, store: Store
):
    """The job row and its snapshot are one transaction, so they arrive together.

    Before that, a crash between the two commits left a ``new`` row with a
    missing or half-written snapshot.  ``new`` is invisible both to the tick and
    to the startup reconcile (which only settles ``running``), so the row sat in
    a status no scheduler had any reason to look at while the dashboard showed a
    job that could never start.
    """
    def refuse(job: dict[str, Any], datasets: list[dict[str, Any]]) -> None:
        raise sqlite3.OperationalError("database is locked")

    store.insert_job_with_datasets = refuse  # type: ignore[method-assign]

    with pytest.raises(sqlite3.OperationalError):
        service.submit(body(), SUBMITTER)

    assert jobs_of(store) == []


def test_a_cancel_landing_midway_is_not_written_back_to_queued(
    service: JobService, store: Store, queue: JobQueue
):
    """The submitter can cancel before the response even arrives.

    ``admit`` is guarded on the status it read for the same reason
    ``test_queue.py`` pins it: the write and the queueing are two statements, and
    the window between them belongs to whoever cancels.
    """
    real_write = store.insert_job_with_datasets

    def write_then_cancel(job: dict[str, Any], datasets: list[dict[str, Any]]) -> None:
        real_write(job, datasets)
        queue.cancel(str(job["id"]), "dev-1")

    store.insert_job_with_datasets = write_then_cancel  # type: ignore[method-assign]

    with pytest.raises(QueueError) as refused:
        service.submit(body(), SUBMITTER)

    assert refused.value.code == "job_not_admissible"
    assert store.get_job(jobs_of(store)[0])["status"] == STATUS_CANCELED


def test_a_failing_closing_write_does_not_replace_the_real_error(
    service: JobService, store: Store
):
    """The compensation is best-effort, so the submitter reads the real failure.

    Closing the row is a second write, and it can fail on the same locked
    database that broke the first one.  Letting that throw would report an error
    about the error -- and the message the submitter can act on would be gone.
    """

    def refuse_write(job: dict[str, Any], datasets: list[dict[str, Any]]) -> None:
        raise sqlite3.OperationalError("snapshot write refused")

    def refuse_close(*args: Any, **fields: Any) -> None:
        raise sqlite3.OperationalError("database is locked")

    store.insert_job_with_datasets = refuse_write  # type: ignore[method-assign]
    store.transition_job = refuse_close  # type: ignore[method-assign]

    with pytest.raises(sqlite3.OperationalError) as raised:
        service.submit(body(), SUBMITTER)

    assert "snapshot write refused" in str(raised.value)
    assert jobs_of(store) == []


# ── windows ───────────────────────────────────────────────────────────────────


def test_a_night_submission_in_the_morning_is_scheduled_not_queued(
    service: JobService, store: Store
):
    result = service.submit(body(window={"kind": "night"}), SUBMITTER)

    assert result["status"] == STATUS_SCHEDULED
    assert result["window"]["kind"] == "night"
    assert store.get_job(result["job_id"])["not_after"]


def test_a_custom_window_shorter_than_the_longest_selected_task_is_refused(
    service: JobService, store: Store
):
    with pytest.raises(WindowError) as refused:
        service.submit(body(window=custom_window(30)), SUBMITTER)

    assert refused.value.code == "window_too_short"
    assert jobs_of(store) == []


def test_the_window_floor_uses_the_selected_tasks_not_the_whole_corpus(
    service: JobService, store: Store
):
    """``chart_open`` needs 900 s and is in the catalogue; it is not in this job.

    Taking the floor from the corpus would refuse a two-minute window that every
    task in the submission fits.
    """
    result = service.submit(body(window=custom_window(180)), SUBMITTER)

    assert result["status"] == STATUS_QUEUED


def test_a_window_that_cannot_hold_the_plan_warns_without_refusing(
    service: JobService, store: Store
):
    result = service.submit(
        body(selector={"datasets": ["bulk"]}, window=custom_window(120)), SUBMITTER
    )

    assert result["status"] == STATUS_QUEUED
    warning = result["warning"]
    assert warning["code"] == "window_too_small"
    assert warning["tasks_planned"] == 10
    assert warning["tasks_likely_completable"] < 10


def test_a_window_big_enough_for_the_plan_carries_no_warning(service: JobService):
    result = service.submit(
        body(selector={"datasets": ["bulk"]}, window=custom_window(3600)), SUBMITTER
    )

    assert "warning" not in result


# ── reads ─────────────────────────────────────────────────────────────────────


def test_listing_returns_every_subjects_jobs(service: JobService, store: Store):
    mine = service.submit(body(), SUBMITTER)["job_id"]
    theirs = service.submit(body(), OTHER)["job_id"]

    listing = service.list_jobs()
    assert sorted(item["job_id"] for item in listing["jobs"]) == sorted([mine, theirs])
    only_theirs = service.list_jobs(submitter="dev-2")
    assert [item["job_id"] for item in only_theirs["jobs"]] == [theirs]


def test_listing_can_be_filtered_and_paginated(service: JobService, store: Store):
    first = service.submit(body(), SUBMITTER)["job_id"]
    second = service.submit(body(), OTHER)["job_id"]
    store.insert_job(job_row("job-done", status=STATUS_FAILED, submitter="dev-1"))

    assert service.list_jobs(statuses=["failed"])["jobs"][0]["job_id"] == "job-done"
    # The page is a queue-order slice, not an insertion-order one: ``job-done``
    # was written last but sits at queue_pos 1.0, so it heads both the filtered
    # read and the first page. A dashboard that paginates the wrong way shows
    # the back of the line as what is about to run.
    assert [item["job_id"] for item in service.list_jobs(limit=1)["jobs"]] == ["job-done"]
    assert [item["job_id"] for item in service.list_jobs()["jobs"]] == [
        "job-done",
        first,
        second,
    ]


def test_listing_carries_no_task_rows(service: JobService, store: Store):
    service.submit(body(), SUBMITTER)

    assert "tasks" not in service.list_jobs()["jobs"][0]


def test_get_reports_the_score_and_the_two_write_back_counters(
    service: JobService, store: Store
):
    job_id = service.submit(body(), SUBMITTER)["job_id"]
    store.insert_job_tasks(
        [
            {
                "job_id": job_id,
                "task_id": "mail_l1",
                "status": STATUS_FAILED,
                "grading_type": "llm_judge",
            }
        ]
    )
    store.update_job_task(
        job_id,
        "mail_l1",
        1,
        score=0.8,
        failure_reason="missing_artifact",
        protocol_written=0,
        out_of_band_count=2,
    )

    task = service.get(job_id)["tasks"][0]
    assert task["status"] == STATUS_FAILED
    assert task["score"] == 0.8
    assert task["failure_reason"] == "missing_artifact"
    # The pair that separates a real answer from one written in a sandbox nobody
    # crossed back from (design section 3).
    assert (task["protocol_written"], task["out_of_band_count"]) == (0, 2)


def test_get_names_the_queue_position_and_the_window(service: JobService, store: Store):
    job_id = service.submit(body(), SUBMITTER)["job_id"]

    detail = service.get(job_id)
    assert detail["queue"]["status"] == STATUS_QUEUED
    assert detail["queue"]["queue_ahead"] == 0
    assert detail["datasets"][0]["task_count"] == 2


def test_get_refuses_a_job_that_is_not_there(service: JobService):
    with pytest.raises(SubmissionError) as refused:
        service.get("job-nope")

    assert refused.value.code == "job_not_found"


# ── cancel and reorder ────────────────────────────────────────────────────────


def stop(stopped: list[str], forwarded: bool) -> Any:
    """A harness stub that answers the way :meth:`.EvalRuntime.stop_job` does.

    The real one returns whether it found an attempt, and the caller logs the
    difference -- a stub returning ``None`` would say "nothing local" for every
    cancel and train the reader to ignore that line.
    """

    def forward(job_id: str) -> bool:
        stopped.append(job_id)
        return forwarded

    return forward


def test_canceling_a_running_job_also_stops_the_local_run(store: Store, service: JobService):
    """The row and the remote session are two different stops.

    Cancelling only the row would leave the ACP session running against fixtures
    nobody is scoring, holding a concurrency slot the queue has already freed.
    """
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))
    stopped: list[str] = []

    outcome = service.cancel("job-live", SUBMITTER, stop_running=stop(stopped, True))

    assert stopped == ["job-live"]
    assert outcome["status"] == STATUS_CANCELED


def test_the_cancel_logs_which_half_of_it_actually_happened(
    store: Store, service: JobService, caplog: pytest.LogCaptureFixture
) -> None:
    """Reached the harness is ``info``; reached nothing is a warning.

    The row reads ``canceled`` either way, so this record is the only place that
    says whether the remote session was told too.  A cancel whose forward found no
    local attempt means an agent still running against fixtures nobody will score,
    holding a slot the queue has already given away -- not a detail to bury at the
    same level as the working case.
    """
    store.insert_job(job_row("job-kept", status=STATUS_RUNNING, submitter="dev-1"))
    store.insert_job(job_row("job-lost", status=STATUS_RUNNING, submitter="dev-1"))

    with caplog.at_level(logging.INFO):
        for job_id, forwarded in (("job-kept", True), ("job-lost", False)):
            service.cancel(job_id, SUBMITTER, stop_running=stop([], forwarded))

    told = [record for record in caplog.records if hasattr(record, "local_run")]
    assert {record.job_id: record.levelno for record in told} == {
        "job-kept": logging.INFO,
        "job-lost": logging.WARNING,
    }
    warned = [record for record in told if record.levelno == logging.WARNING]
    assert len(warned) == 1
    assert (warned[0].job_id, warned[0].by, warned[0].local_run) == ("job-lost", "dev-1", False)


def test_a_cancel_that_reached_nothing_is_loud_enough_to_be_seen(
    store: Store, service: JobService, caplog: pytest.LogCaptureFixture
) -> None:
    """``warning`` because a deployment running above ``info`` still has to see it.

    The row reads ``canceled`` either way, so when the forward found no local
    attempt this record is the only trace of an agent still evaluating fixtures
    nobody is scoring.  Logged at the same level as the working case it is
    indistinguishable from a clean cancel in exactly the installations that set
    a threshold.  The trailing ``stopped`` assertion is a guard for the next
    refactor, not a claim about the old code: a side effect that belongs to the
    job must not move behind an ``isEnabledFor`` check that belongs to the log.
    """
    store.insert_job(job_row("job-lost", status=STATUS_RUNNING, submitter="dev-1"))
    stopped: list[str] = []

    with caplog.at_level(logging.WARNING):
        outcome = service.cancel("job-lost", SUBMITTER, stop_running=stop(stopped, False))

    told = [record for record in caplog.records if hasattr(record, "local_run")]
    assert [(r.job_id, r.levelno, r.local_run) for r in told] == [
        ("job-lost", logging.WARNING, False)
    ]
    assert stopped == ["job-lost"]
    assert outcome["status"] == STATUS_CANCELED


def test_canceling_a_queued_job_does_not_reach_the_harness(store: Store, service: JobService):
    stopped: list[str] = []
    job_id = service.submit(body(), SUBMITTER)["job_id"]

    service.cancel(job_id, SUBMITTER, stop_running=stopped.append)

    assert stopped == []
    assert store.get_job(job_id)["status"] == STATUS_CANCELED


def test_only_the_owner_or_an_admin_may_cancel(store: Store, service: JobService):
    store.insert_job(job_row("job-live", status=STATUS_QUEUED, submitter="dev-1"))

    with pytest.raises(QueueError) as refused:
        service.cancel("job-live", OTHER)
    assert refused.value.code == "not_job_owner"

    assert service.cancel("job-live", ADMIN)["status"] == STATUS_CANCELED


def test_an_admin_may_move_someone_elses_waiting_job(store: Store, service: JobService):
    first = service.submit(body(), SUBMITTER)["job_id"]
    second = service.submit(body(), OTHER)["job_id"]

    moved = service.reorder(second, ADMIN, before_id=first)

    assert moved["queue_ahead"] == 0
    with pytest.raises(QueueError) as refused:
        service.reorder(first, OTHER, before_id=second)
    assert refused.value.code == "not_job_owner"


def test_a_running_job_is_not_reorderable(store: Store, service: JobService):
    store.insert_job(job_row("job-live", status=STATUS_RUNNING, submitter="dev-1"))

    with pytest.raises(QueueError) as refused:
        service.reorder("job-live", SUBMITTER, position=1.0)

    assert refused.value.code == "job_not_reorderable"


# ── the endpoint type the submit API promises ─────────────────────────────────


def test_an_acp_url_the_runner_cannot_rebuild_is_refused(service: JobService, store: Store):
    """What ``submit`` accepts must be what ``runtime.http_endpoint`` accepts.

    The two parse the same string at different times; a URL that passes here and
    raises there is a job that fails in somebody else's log.
    """
    from pawbench.cpd.acp_remote_eval.service.runtime import http_endpoint

    job_id = service.submit(body(), SUBMITTER)["job_id"]
    endpoint = http_endpoint(store.get_job(job_id))

    assert endpoint.transport == "http"
    with pytest.raises(AcpError):
        http_endpoint({"acp_url": "ws://127.0.0.1:9000"})
