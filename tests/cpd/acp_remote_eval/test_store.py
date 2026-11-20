# -*- coding: utf-8 -*-
"""Persistence layer for jobs, datasets, categories, tasks and artifacts."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pawbench.cpd.acp_remote_eval.service import store as store_module
from pawbench.cpd.acp_remote_eval.service.store import Store, UnknownColumn


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    with Store(tmp_path / "state.db") as instance:
        yield instance


def _job(job_id: str, **overrides) -> dict:
    job = {
        "id": job_id,
        "submitter": "anderson",
        "token_subject": "anderson",
        "acp_url": "http://127.0.0.1:9000/sse",
        "window_kind": "immediate",
        "status": "queued",
        "queue_pos": 1.0,
        "created_at": store_module.utc_now_iso(),
        "env_fingerprint": {"os": "darwin"},
    }
    job.update(overrides)
    return job


def test_job_round_trip_keeps_json_columns_typed(store: Store) -> None:
    store.insert_job(_job("job-1"))
    loaded = store.get_job("job-1")
    assert loaded["env_fingerprint"] == {"os": "darwin"}

    store.update_job("job-1", status="running", started_at="2026-11-10T02:00:00+00:00")
    reloaded = store.get_job("job-1")
    assert reloaded["status"] == "running"
    assert reloaded["env_fingerprint"] == {"os": "darwin"}


def test_update_job_rejects_unknown_columns(store: Store) -> None:
    store.insert_job(_job("job-1"))
    with pytest.raises(UnknownColumn):
        store.update_job("job-1", **{"status = 'x'": "y"})


def test_transition_job_only_moves_the_state_it_expected(store: Store) -> None:
    store.insert_job(_job("job-1", status="scheduled"))

    assert store.transition_job("job-1", from_status="scheduled", to_status="queued") is True
    assert store.get_job("job-1")["status"] == "queued"
    assert (
        store.transition_job(
            "job-1", from_status="scheduled", to_status="queued", started_at="2026-11-10T02:00:00+00:00"
        )
        is False
    ), "a job that already moved is not moved twice"
    assert store.get_job("job-1")["started_at"] in (None, ""), "the failed guard wrote nothing"


def test_admit_job_counts_the_running_set_inside_the_statement(store: Store) -> None:
    """The limit is the statement's, not the caller's snapshot.

    The queue reads the running set, then asks for each candidate.  Another
    writer can fill the service in between, and an admission decided from the
    earlier read is what over-books the four slots.
    """
    store.insert_job(_job("job-full", submitter="li", status="running"))
    store.insert_job(_job("job-1", submitter="anderson"))

    assert store.get_job("job-1")["status"] == "queued"
    started = store.admit_job(
        "job-1",
                started_at="2026-11-10T02:00:00+00:00",
        max_concurrent_jobs=1,
        max_running_per_user=4,
    )
    assert started is False, "the one slot is taken"
    assert store.get_job("job-1")["status"] == "queued"

    assert (
        store.admit_job(
            "job-1",
                        started_at="2026-11-10T02:00:00+00:00",
            max_concurrent_jobs=2,
            max_running_per_user=4,
        )
        is True
    )
    assert store.get_job("job-1")["status"] == "running"


def test_admit_job_holds_the_per_user_limit(store: Store) -> None:
    store.insert_job(_job("job-mine", status="running"))
    store.insert_job(_job("job-other", submitter="li"))
    store.insert_job(_job("job-second", submitter="anderson"))

    admitted = store.admit_job(
        "job-other",
                started_at="2026-11-10T02:00:00+00:00",
        max_concurrent_jobs=4,
        max_running_per_user=1,
    )
    assert admitted is True
    refused = store.admit_job(
        "job-second",
                started_at="2026-11-10T02:00:00+00:00",
        max_concurrent_jobs=4,
        max_running_per_user=1,
    )
    assert refused is False, "anderson already has one running job"
    assert store.get_job("job-second")["status"] == "queued"


def test_admit_job_never_revives_a_canceled_job(store: Store) -> None:
    """The status guard closes the other half of the race.

    A cancel that lands after the queue read must not be undone by the
    admission that was already in flight -- otherwise the dashboard says
    canceled while a runner starts the tasks.
    """
    store.insert_job(_job("job-1"))

    assert (
        store.admit_job(
            "job-1",
                        started_at="2026-11-10T02:00:00+00:00",
            max_concurrent_jobs=4,
            max_running_per_user=1,
        )
        is True
    )
    store.update_job("job-1", status="canceled")
    assert (
        store.admit_job(
            "job-1",
                        started_at="2026-11-10T03:00:00+00:00",
            max_concurrent_jobs=4,
            max_running_per_user=1,
        )
        is False
    )
    assert store.get_job("job-1")["status"] == "canceled"


def test_list_jobs_orders_by_queue_pos_and_filters(store: Store) -> None:
    store.insert_job(_job("job-a", queue_pos=3.0, submitter="li"))
    store.insert_job(_job("job-b", queue_pos=1.5, status="scheduled"))
    store.insert_job(_job("job-c", queue_pos=2.0, status="running"))

    assert [job["id"] for job in store.list_jobs()] == ["job-b", "job-c", "job-a"]
    assert [job["id"] for job in store.list_jobs(statuses=("running",))] == ["job-c"]
    assert [job["id"] for job in store.list_jobs(submitter="li")] == ["job-a"]
    assert store.max_queue_pos() == 3.0
    assert store.count_running() == 1
    assert store.count_running_for("anderson") == 1, "job-c belongs to anderson"
    assert store.count_running_for("li") == 0


def test_queue_positions_are_exposed_for_reordered(store: Store) -> None:
    store.insert_job(_job("job-a", queue_pos=1.0))
    store.insert_job(_job("job-b", queue_pos=2.0))
    store.set_queue_pos("job-a", 2.5)
    assert store.queue_positions() == [("job-b", 2.0), ("job-a", 2.5)]


def test_dataset_upsert_preserves_owner_and_created_at(store: Store) -> None:
    store.upsert_dataset(
        {
            "id": "ds-1",
            "name": "Pilot",
            "owner": "anderson",
            "kind": "builtin_view",
            "task_ids": ["T001", "T002"],
            "categories": ["office"],
            "filter_spec": {"scenario": "Office_Operations"},
        }
    )
    first = store.get_dataset("ds-1")
    assert first["task_ids"] == ["T001", "T002"]
    assert first["task_count"] == 2
    assert first["filter_spec"] == {"scenario": "Office_Operations"}

    store.upsert_dataset(
        {
            "id": "ds-1",
            "name": "Pilot v2",
            "owner": "someone-else",
            "kind": "builtin_view",
            "task_ids": ["T003"],
            "created_at": first["created_at"],
        }
    )
    second = store.get_dataset("ds-1")
    assert second["owner"] == "anderson", "upsert must not hand ownership over"
    assert second["created_at"] == first["created_at"]
    assert second["categories"] == []


def test_category_reference_count(store: Store) -> None:
    store.insert_category({"name": "office", "created_by": "anderson"})
    store.upsert_dataset(
        {"id": "ds-1", "owner": "anderson", "kind": "custom", "categories": ["office"]}
    )
    assert store.datasets_with_category("office") == 1
    assert store.datasets_with_category("missing") == 0


def test_job_task_rows_keep_attempt_and_json(store: Store) -> None:
    store.insert_job_tasks(
        [
            {"job_id": "job-1", "task_id": "T001", "grading_type": "automated", "resolved_from": ["ds-1"]},
            {"job_id": "job-1", "task_id": "T002", "grading_type": "llm_judge", "resolved_from": ["ds-1", "ds-2"]},
        ]
    )
    store.update_job_task(
        "job-1",
        "T001",
        1,
        status="done",
        score=0.75,
        judge_served_models=["model-a", "model-b"],
        subject_model_reported=["unknown"],
        protocol_written=2,
        duration_s=12.5,
    )
    store.insert_job_tasks([{"job_id": "job-1", "task_id": "T001", "attempt": 2}])

    rows = store.list_job_tasks("job-1")
    assert [(row["task_id"], row["attempt"]) for row in rows] == [("T001", 1), ("T001", 2), ("T002", 1)]

    latest = store.get_job_task("job-1", "T001")
    assert latest["attempt"] == 2, "no explicit attempt reads the newest one"
    first = store.get_job_task("job-1", "T001", 1)
    assert first["judge_served_models"] == ["model-a", "model-b"]
    assert first["resolved_from"] == ["ds-1"]
    assert first["failure_reason"] is None


def test_skipping_unrun_tasks_labels_only_what_never_started(store: Store) -> None:
    """One statement, and it cannot rewrite a row that already moved.

    This is the write that keeps a terminal job from carrying ``pending`` tasks;
    doing it per row would let a failure halfway through leave the job closed
    over a set that is neither whole nor explainable.  A row already ``running``
    belongs to an attempt in flight, and a finished one is a measurement --
    relabelling either would turn "we did not reach these" into a lie.
    """
    store.insert_job_tasks(
        [
            {"job_id": "job-1", "task_id": "T001", "attempt": 1},
            {"job_id": "job-1", "task_id": "T002", "attempt": 1},
            {"job_id": "job-1", "task_id": "T003", "attempt": 1},
        ]
    )
    store.update_job_task("job-1", "T001", 1, status="running", started_at=_beat(0))
    store.update_job_task(
        "job-1", "T003", 1, status="finished", protocol_written=2, score=1.0
    )

    assert store.skip_unrun_tasks("job-1", reason="deadline", now_iso=_beat(10)) == 1

    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert (rows["T002"]["status"], rows["T002"]["failure_reason"]) == (
        "skipped",
        "deadline",
    )
    assert rows["T002"]["duration_s"] == 0.0, "an attempt that never ran took no time"
    assert rows["T001"]["status"] == "running", "the run in flight is not ours to close"
    assert rows["T003"]["score"] == 1.0, "a measurement is not relabelled"


def test_skipping_is_scoped_to_the_attempt_it_was_asked_for(store: Store) -> None:
    """A retry writes its own rows, and the ceiling applies to that attempt only.

    Without the filter the second attempt's pending rows would be closed by a
    decision made about the first one, and the retry would report tasks that were
    never even offered to the agent.
    """
    store.insert_job_tasks(
        [
            {"job_id": "job-1", "task_id": "T001", "attempt": 1},
            {"job_id": "job-1", "task_id": "T001", "attempt": 2},
        ]
    )

    assert store.skip_unrun_tasks("job-1", reason="deadline", now_iso=_beat(10), attempt=2) == 1

    rows = {row["attempt"]: row for row in store.list_job_tasks("job-1")}
    assert rows[2]["status"] == "skipped"
    assert rows[1]["status"] == "pending", "the earlier attempt is a different question"


def test_artifacts_are_keyed_per_job_and_task(store: Store) -> None:
    store.record_artifact(
        {"job_id": "job-1", "task_id": "T001", "path": "output/a.csv", "sha256": "aa", "size": 10}
    )
    store.record_artifact(
        {
            "job_id": "job-1",
            "task_id": "T001",
            "path": "fixtures/in.pdf",
            "sha256": "bb",
            "size": 20,
            "kind": "fixture",
        }
    )
    assert [row["path"] for row in store.list_artifacts("job-1")] == [
        "fixtures/in.pdf",
        "output/a.csv",
    ]
    assert [row["path"] for row in store.list_artifacts("job-1", kind="fixture")] == [
        "fixtures/in.pdf"
    ]
    assert store.list_artifacts("job-1", "T002") == []

    store.record_artifact(
        {"job_id": "job-1", "task_id": "T001", "path": "output/a.csv", "sha256": "cc", "size": 11}
    )
    reuploaded = store.list_artifacts("job-1", "T001", kind="output")
    assert [row["sha256"] for row in reuploaded] == ["cc"], "same path overwrites, no duplicate row"


def test_dataset_job_references_are_tracked(store: Store) -> None:
    store.insert_job_dataset(
        {"job_id": "job-1", "dataset_id": "ds-1", "dataset_kind": "builtin_view", "resolved_task_ids": ["T001"]}
    )
    store.insert_job_dataset({"job_id": "job-2", "dataset_id": "ds-1", "dataset_kind": "custom"})
    assert store.dataset_job_refs("ds-1") == ["job-1", "job-2"]
    assert store.list_job_datasets("job-1")[0]["resolved_task_ids"] == ["T001"]


# ── leases: which live process is running a ``running`` row ──────────────────

LEASE_TTL = 90.0
_ANCHOR = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)


def _beat(seconds: float) -> str:
    """A lease beat ``seconds`` away from the anchor, as the table stores it."""
    return (_ANCHOR + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _lease_owners(store: Store, job_id: str = "job-1") -> list[dict]:
    return store.query(
        "SELECT owner, beat_at, ttl_seconds FROM job_leases WHERE job_id = ?", (job_id,)
    )


def test_a_lease_is_refreshed_by_its_owner_and_refused_while_it_is_fresh(store: Store) -> None:
    """Two services on one database must not run the same job twice.

    The beat the owner writes moves the row forward; a different owner asking
    inside the TTL gets nothing, and the row keeps the first owner's beat.
    """
    store.insert_job(_job("job-1", status="running"))

    assert store.acquire_lease("job-1", owner="proc-a", beat_at=_beat(0), ttl_seconds=LEASE_TTL)
    assert store.acquire_lease("job-1", owner="proc-a", beat_at=_beat(30), ttl_seconds=LEASE_TTL)
    assert not store.acquire_lease("job-1", owner="proc-b", beat_at=_beat(60), ttl_seconds=LEASE_TTL)

    assert _lease_owners(store) == [{"owner": "proc-a", "beat_at": _beat(30), "ttl_seconds": LEASE_TTL}]


def test_a_lease_is_up_for_grabs_only_once_its_beat_is_older_than_the_ttl(store: Store) -> None:
    """The stale boundary is exclusive, and it is what tells late from dead.

    A beat exactly one TTL old is still believed: the TTL is set to outlast a
    couple of scheduler ticks, so taking the job over at that instant would run
    it twice.
    """
    store.insert_job(_job("job-1", status="running"))
    store.acquire_lease("job-1", owner="proc-a", beat_at=_beat(0), ttl_seconds=LEASE_TTL)

    assert not store.acquire_lease("job-1", owner="proc-b", beat_at=_beat(LEASE_TTL), ttl_seconds=LEASE_TTL)
    assert store.acquire_lease("job-1", owner="proc-b", beat_at=_beat(LEASE_TTL + 1), ttl_seconds=LEASE_TTL)

    assert _lease_owners(store) == [{"owner": "proc-b", "beat_at": _beat(LEASE_TTL + 1), "ttl_seconds": LEASE_TTL}]


def test_beating_or_releasing_a_lease_never_touches_another_owners_row(store: Store) -> None:
    """A process that lost its lease has to find out, and stop.

    Silent failure here is the split-brain case: both services would keep
    running the job and both would write task rows over each other.
    """
    store.insert_job(_job("job-1", status="running"))
    store.acquire_lease("job-1", owner="proc-a", beat_at=_beat(0), ttl_seconds=LEASE_TTL)

    assert not store.beat_lease("job-1", owner="proc-b", beat_at=_beat(30))
    assert store.beat_lease("job-1", owner="proc-a", beat_at=_beat(30))
    assert not store.release_lease("job-1", owner="proc-b")
    assert len(_lease_owners(store)) == 1, "a refused release must not delete the row"

    assert store.release_lease("job-1", owner="proc-a")
    assert _lease_owners(store) == []


def test_the_lease_owner_is_named_for_the_process_that_lost_the_race(store: Store) -> None:
    """A refusal has to say who to go and talk to.

    Two services on one database is a deployment fault, and "not mine" without
    the name leaves the operator with two machines and no way to tell which one
    is holding the job.
    """
    store.insert_job(_job("job-1", status="running"))
    store.acquire_lease("job-1", owner="proc-a", beat_at=_beat(0), ttl_seconds=LEASE_TTL)

    assert store.lease_owner("job-1") == "proc-a"

    store.release_lease("job-1", owner="proc-a")
    assert store.lease_owner("job-1") is None, "a job nobody holds answers as nobody"


def test_a_running_job_is_an_orphan_only_when_its_lease_is_gone_or_stale(store: Store) -> None:
    """The question reconcile asks, answered in one statement.

    ``jobs.status = 'running'`` alone cannot tell a live run from what a dead
    process left behind, and guessing from timestamps would settle a job that is
    merely between two beats.
    """
    store.insert_job(_job("job-none", status="running", queue_pos=1.0))
    store.insert_job(_job("job-live", status="running", queue_pos=2.0))
    store.insert_job(_job("job-dead", status="running", queue_pos=3.0))
    store.insert_job(_job("job-queued", status="queued", queue_pos=4.0))
    store.acquire_lease("job-live", owner="proc-a", beat_at=_beat(0), ttl_seconds=LEASE_TTL)
    store.acquire_lease("job-dead", owner="proc-x", beat_at=_beat(-3600), ttl_seconds=LEASE_TTL)

    assert store.orphan_running_jobs(_beat(0)) == ["job-none", "job-dead"]


def test_settling_an_orphan_closes_every_row_it_leaves_behind(store: Store) -> None:
    """The job and its tasks move together, in one transaction.

    A failed job whose task row still says ``running`` holds a concurrency slot
    -- the limits are counted from rows -- and a report with tasks still
    ``pending`` under a terminal job reads as a run that was cut short.
    """
    store.insert_job(_job("job-1", status="running"))
    store.insert_job_tasks(
        [
            {"job_id": "job-1", "task_id": "T001", "status": "running"},
            {"job_id": "job-1", "task_id": "T002", "status": "pending"},
        ]
    )
    store.acquire_lease("job-1", owner="proc-dead", beat_at=_beat(-3600), ttl_seconds=LEASE_TTL)

    outcome = store.settle_orphan_job(
        "job-1", now_iso=_beat(0), failure_reason="recovered", not_run_reason="service_restarted"
    )

    assert outcome == {
        "job_id": "job-1",
        "settled": True,
        "tasks_failed": 1,
        "tasks_skipped": 1,
    }
    job = store.get_job("job-1")
    assert (job["status"], job["error"], job["finished_at"]) == ("failed", "recovered", _beat(0))
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-1")}
    assert (rows["T001"]["status"], rows["T001"]["failure_reason"]) == ("failed", "recovered")
    assert (rows["T002"]["status"], rows["T002"]["failure_reason"]) == ("skipped", "service_restarted")
    assert store.orphan_running_jobs(_beat(0)) == [], "the lease row goes with the job"


def test_a_job_and_its_snapshot_arrive_together_or_not_at_all(store: Store) -> None:
    """One transaction, because a job without its snapshot cannot be explained.

    ``new`` is the state nothing else in the service reads -- not the queue tick,
    not the startup reconcile, which only settles ``running`` -- so a row written
    on its own is a job that no code path can finish, and a snapshot that names
    two of three datasets reproduces a result that was never submitted.
    """
    snapshot = {
        "job_id": "job-1",
        "dataset_id": "mail",
        "dataset_kind": "builtin_view",
        "requested_by": "category:email",
        "resolved_task_ids": ["mail_l1"],
    }

    with pytest.raises(sqlite3.Error):
        store.insert_job_with_datasets(
            _job("job-1"), [dict(snapshot, requested_by={"not": "a string"})]
        )

    assert store.get_job("job-1") is None
    assert store.list_job_datasets("job-1") == []

    store.insert_job_with_datasets(_job("job-1"), [snapshot])

    assert store.get_job("job-1")["status"] == "queued"
    assert store.list_job_datasets("job-1")[0]["resolved_task_ids"] == ["mail_l1"]


def test_settling_is_a_one_shot_write(store: Store) -> None:
    """The guard is the job's own status, so a second pass changes nothing.

    Two services starting against one database both reconcile; whichever lands
    second must not re-date the failure it did not cause.
    """
    store.insert_job(_job("job-1", status="running"))
    store.update_job("job-1", error="first")

    assert store.settle_orphan_job(
        "job-1", now_iso=_beat(0), failure_reason="recovered", not_run_reason="service_restarted"
    )["settled"] is True
    second = store.settle_orphan_job(
        "job-1", now_iso=_beat(60), failure_reason="recovered", not_run_reason="service_restarted"
    )

    assert second["settled"] is False
    job = store.get_job("job-1")
    assert (job["error"], job["finished_at"]) == ("recovered", _beat(0))
