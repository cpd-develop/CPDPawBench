# -*- coding: utf-8 -*-
"""Global queue: concurrency gates, ordering and the scheduling tick.

These tests run on a frozen clock.  The nightly window cannot be verified any
other way, and the ordering rules (design section 5.2) are exactly the part a
"let me just wait for midnight" test would get wrong.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest

from pawbench.cpd.acp_remote_eval.service import store as store_module
from pawbench.cpd.acp_remote_eval.service.config import ScheduleConfig
from pawbench.cpd.acp_remote_eval.service.queue import (
    JobQueue,
    QueueError,
    QueueLimits,
    STATUS_CANCELED,
    STATUS_NEW,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
)
from pawbench.cpd.acp_remote_eval.service.schedule import (
    FrozenClock,
    Window,
    resolve_window,
)
from pawbench.cpd.acp_remote_eval.service.store import Store

TZ = "Asia/Shanghai"


def shanghai(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(TZ))


MORNING = shanghai(2026, 11, 10, 9, 0)


def schedule_config(**overrides: Any) -> ScheduleConfig:
    values: dict[str, Any] = {
        "timezone": TZ,
        "tick_seconds": 5,
        "night_open": "00:00",
        "night_close": "07:00",
        "night_min_lead_seconds": 1800,
        "hard_stop": False,
        "custom_window_max_days": 7,
    }
    values.update(overrides)
    return ScheduleConfig(**values)


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    with Store(tmp_path / "state.db") as instance:
        yield instance


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(MORNING)


def queue_for(
    store: Store,
    clock: FrozenClock,
    *,
    limits: QueueLimits | None = None,
    cfg: ScheduleConfig | None = None,
) -> JobQueue:
    return JobQueue(store, cfg or schedule_config(), limits, clock)


def job_row(
    job_id: str,
    submitter: str,
    window: Window,
) -> dict:
    payload = window.to_payload()
    return {
        "id": job_id,
        "submitter": submitter,
        "token_subject": submitter,
        "acp_url": "http://127.0.0.1:9000/sse",
        "window_kind": window.kind,
        "not_before": payload["not_before"],
        "not_after": payload["not_after"],
        "status": STATUS_NEW,
        "queue_pos": 1.0,
        "created_at": store_module.utc_now_iso(),
    }


def submit(
    store: Store,
    queue: JobQueue,
    job_id: str,
    window: Window,
    *,
    submitter: str = "anderson",
    queue_pos: Optional[float] = None,
) -> float:
    """Insert the job row and hand it to the queue, as the API would."""
    store.insert_job(job_row(job_id, submitter, window))
    position = queue.admit(job_id, window)
    if queue_pos is not None:
        store.set_queue_pos(job_id, queue_pos)
    return position


def custom_window(
    clock: FrozenClock, cfg: ScheduleConfig, opens: str, closes: str
) -> Window:
    return resolve_window(
        "custom", clock.now(), cfg, not_before=opens, not_after=closes
    )


def immediate_window(clock: FrozenClock, cfg: ScheduleConfig) -> Window:
    return resolve_window("immediate", clock.now(), cfg)


# ── submission ────────────────────────────────────────────────────────────────


def test_admit_queues_an_open_window_and_defers_a_future_one(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)

    submit(store, queue, "job-now", immediate_window(clock, cfg))
    assert store.get_job("job-now")["status"] == STATUS_QUEUED

    night = resolve_window("night", clock.now(), cfg)
    submit(store, queue, "job-later", night)
    job = store.get_job("job-later")
    assert job["status"] == STATUS_SCHEDULED, "the window has not opened yet"
    assert job["not_before"] == night.to_payload()["not_before"]


def test_submissions_line_up_behind_the_tail(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)

    first = submit(store, queue, "job-a", window)
    second = submit(store, queue, "job-b", window)
    third = submit(store, queue, "job-c", window)

    assert first < second < third
    assert queue.position_in_line("job-c") == 2


# ── concurrency (requirement 4) ───────────────────────────────────────────────


def test_tick_starts_at_most_max_concurrent_jobs_across_users(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=4, max_running_per_user=4),
        cfg=cfg,
    )
    window = immediate_window(clock, cfg)
    for index in range(6):
        submit(store, queue, f"job-{index}", window, submitter=f"user{index % 3}")

    started = queue.tick().started

    assert len(started) == 4, "four is a property of the service, not of a submission"
    assert queue.running_count() == 4
    assert len(store.jobs_in_state(STATUS_QUEUED)) == 2


def test_tick_follows_queue_order_not_insertion_order(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=1, max_running_per_user=1),
        cfg=cfg,
    )
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-slow", window, submitter="li", queue_pos=50.0)
    submit(store, queue, "job-fast", window, submitter="wang", queue_pos=10.0)

    assert queue.tick().started == ["job-fast"]

    store.update_job("job-fast", status="finished")
    assert queue.tick().started == ["job-slow"]


def test_a_cancel_that_lands_mid_tick_is_not_revived(
    store: Store, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick read the queued row a moment ago; the cancel is the newer fact.

    Injected at the admission call because that is exactly the window the old
    read-then-write code left open: the queue had already decided this job was
    next, and only the ``status = 'queued'`` guard in the statement keeps the
    runner from starting a job the dashboard calls canceled.
    """
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    submit(store, queue, "job-1", immediate_window(clock, cfg))

    real_admit = store.admit_job

    def cancel_then_admit(job_id: str, **kwargs: Any) -> bool:
        subject = str(store.get_job(job_id)["submitter"])
        queue.cancel(job_id, subject)
        return real_admit(job_id, **kwargs)

    monkeypatch.setattr(store, "admit_job", cancel_then_admit)
    result = queue.tick()

    assert result.started == []
    assert store.get_job("job-1")["status"] == "canceled"


def test_a_cancel_between_insert_and_admit_is_not_overwritten(
    store: Store, clock: FrozenClock
) -> None:
    """The row is written before the queue places it, and that gap is real.

    An unguarded ``update_job`` here turned a job somebody had just canceled
    back into ``queued``, which the next tick would then start.
    """
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    store.insert_job(job_row("job-race", "anderson", window))
    queue.cancel("job-race", "anderson")

    with pytest.raises(QueueError) as caught:
        queue.admit("job-race", window)

    assert caught.value.code == "job_not_admissible"
    assert store.get_job("job-race")["status"] == STATUS_CANCELED


def test_a_cancel_before_the_window_opens_is_not_promoted(
    store: Store, clock: FrozenClock
) -> None:
    """Promotion is a state change too, so it goes through the same guard."""
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = custom_window(clock, cfg, "2026-11-10T22:00:00", "2026-11-11T06:00:00")
    submit(store, queue, "job-night", window)
    store.update_job("job-night", status="canceled")

    clock.set(shanghai(2026, 11, 10, 22, 0))
    result = queue.tick()

    assert result.promoted == []
    assert store.get_job("job-night")["status"] == "canceled"


def test_tick_holds_a_second_job_for_the_same_submitter(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=4, max_running_per_user=1),
        cfg=cfg,
    )
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window, submitter="li")
    submit(store, queue, "job-b", window, submitter="li")
    submit(store, queue, "job-c", window, submitter="wang")

    started = queue.tick().started

    assert set(started) == {"job-a", "job-c"}, "one person cannot spend the whole budget"
    assert store.get_job("job-b")["status"] == STATUS_QUEUED


def test_admission_reports_who_is_blocking_the_submitter(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=1, max_running_per_user=1),
        cfg=cfg,
    )
    submit(store, queue, "job-a", immediate_window(clock, cfg), submitter="li")
    queue.tick()

    ok, code, details = queue.admission("wang")
    assert (ok, code) == (False, "service_busy")
    assert details == {"running": 1, "limit": 1}

    store.update_job("job-a", status="finished")
    assert queue.admission("li") == (True, "", {})


def test_admission_refuses_a_second_running_job_for_one_submitter(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=4, max_running_per_user=1),
        cfg=cfg,
    )
    submit(store, queue, "job-a", immediate_window(clock, cfg), submitter="li")
    queue.tick()

    ok, code, details = queue.admission("li")
    assert (ok, code) == (False, "per_user_limit")
    assert details == {"running_for_subject": 1, "limit": 1}


# ── windows in the tick (design 5.1 / 5.2) ───────────────────────────────────


def test_tick_promotes_a_scheduled_job_at_the_open_and_keeps_its_position(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = custom_window(
        clock, cfg, "2026-11-10T22:00:00", "2026-11-11T06:00:00"
    )
    submit(store, queue, "job-night", window, queue_pos=12.5)

    clock.set(shanghai(2026, 11, 10, 21, 59))
    assert queue.tick().promoted == []
    assert store.get_job("job-night")["status"] == STATUS_SCHEDULED

    clock.set(shanghai(2026, 11, 10, 22, 0))
    result = queue.tick()

    job = store.get_job("job-night")
    assert result.promoted == ["job-night"]
    assert job["status"] == STATUS_RUNNING
    assert float(job["queue_pos"]) == 12.5, (
        "position survives promotion, so a night run does not jump the line"
    )
    assert job["scheduled_at"] is not None


def test_a_night_job_does_not_overtake_a_daytime_submission(
    store: Store, clock: FrozenClock
) -> None:
    """The ordering reason ``scheduled`` keeps its position instead of tailing."""
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=1, max_running_per_user=1),
        cfg=cfg,
    )
    night = custom_window(
        clock, cfg, "2026-11-10T22:00:00", "2026-11-11T06:00:00"
    )
    submit(store, queue, "job-night", night, submitter="li", queue_pos=10.0)

    clock.set(shanghai(2026, 11, 10, 21, 59))
    submit(store, queue, "job-afternoon", immediate_window(clock, cfg), submitter="wang")
    assert queue.tick().started == ["job-afternoon"]

    clock.set(shanghai(2026, 11, 10, 22, 0))
    result = queue.tick()

    assert result.promoted == ["job-night"]
    assert result.started == [], "the single slot is still held by the afternoon job"
    assert queue.position_in_line("job-night") == 0

    store.update_job("job-afternoon", status="finished")
    assert queue.tick().started == [
        "job-night"
    ], "it goes next, ahead of anything submitted after it"


def test_a_running_job_is_not_cut_off_when_its_window_closes(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = custom_window(
        clock, cfg, "2026-11-10T09:30:00", "2026-11-10T10:00:00"
    )
    submit(store, queue, "job-tight", window)

    clock.set(shanghai(2026, 11, 10, 9, 40))
    assert queue.tick().started == ["job-tight"]

    clock.set(shanghai(2026, 11, 10, 10, 30))
    assert queue.tick().started == []
    assert store.get_job("job-tight")["status"] == STATUS_RUNNING, (
        "crossing not_after stops starts, never finishes"
    )


def test_a_task_that_never_got_a_slot_is_reported_window_closed(
    store: Store, clock: FrozenClock
) -> None:
    """The runner can only record ``skipped(window_closed)`` if the tick says so."""
    cfg = schedule_config()
    queue = queue_for(
        store,
        clock,
        limits=QueueLimits(max_concurrent_jobs=1, max_running_per_user=1),
        cfg=cfg,
    )
    window = custom_window(
        clock, cfg, "2026-11-10T09:30:00", "2026-11-10T10:00:00"
    )
    submit(store, queue, "job-first", window, submitter="li", queue_pos=10.0)
    submit(store, queue, "job-second", window, submitter="wang", queue_pos=20.0)

    clock.set(shanghai(2026, 11, 10, 9, 31))
    assert queue.tick().started == ["job-first"]

    clock.set(shanghai(2026, 11, 10, 10, 5))
    result = queue.tick()

    assert result.window_closed == ["job-second"]
    assert store.get_job("job-second")["status"] == STATUS_QUEUED, (
        "the queue reports; only the runner writes the task outcome"
    )


def test_hard_stop_reports_a_running_job_whose_window_closed(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config(hard_stop=True)
    queue = queue_for(store, clock, cfg=cfg)
    window = custom_window(
        clock, cfg, "2026-11-10T09:30:00", "2026-11-10T10:00:00"
    )
    submit(store, queue, "job-hard", window)

    clock.set(shanghai(2026, 11, 10, 9, 40))
    assert queue.tick().started == ["job-hard"]

    clock.set(shanghai(2026, 11, 10, 10, 1))
    assert queue.tick().window_closed == ["job-hard"]


# ── reordering ────────────────────────────────────────────────────────────────


def test_reorder_before_and_after_a_neighbour(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    for job_id in ("job-a", "job-b", "job-c"):
        submit(store, queue, job_id, window)

    queue.reorder("job-c", "anderson", before_id="job-a")
    assert [job_id for job_id, _ in store.queue_positions()] == ["job-c", "job-a", "job-b"]

    queue.reorder("job-c", "anderson", after_id="job-b")
    assert [job_id for job_id, _ in store.queue_positions()] == ["job-a", "job-b", "job-c"]


def test_reorder_a_scheduled_job_moves_where_it_will_queue(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window)
    submit(store, queue, "job-night", window)
    store.update_job("job-night", status=STATUS_SCHEDULED)

    result = queue.reorder("job-night", "anderson", before_id="job-a")

    assert result["status"] == STATUS_SCHEDULED
    assert result["queue_ahead"] == 0


def test_reorder_by_absolute_position(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window)
    submit(store, queue, "job-b", window)

    result = queue.reorder("job-b", "anderson", position=0.5)

    assert result["queue_pos"] == 0.5
    assert float(store.get_job("job-b")["queue_pos"]) == 0.5


def test_reorder_renormalises_when_the_gap_runs_out(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window, queue_pos=10.0)
    submit(store, queue, "job-b", window, queue_pos=10.0 + 1e-9)
    submit(store, queue, "job-c", window, queue_pos=20.0)

    queue.reorder("job-c", "anderson", before_id="job-b")

    positions = store.queue_positions()
    assert [job_id for job_id, _ in positions] == ["job-a", "job-c", "job-b"]
    values = [pos for _, pos in positions]
    assert len(set(values)) == 3, "renumbering leaves room to insert again"


def test_reorder_allows_an_admin_on_someone_elses_job(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window, submitter="li")
    submit(store, queue, "job-b", window, submitter="li")

    result = queue.reorder("job-b", "wang", before_id="job-a", is_admin=True)

    assert result["queue_ahead"] == 0


def test_reorder_guards(store: Store, clock: FrozenClock) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window, submitter="li")
    submit(store, queue, "job-run", window, submitter="li", queue_pos=30.0)
    store.update_job("job-run", status=STATUS_RUNNING)

    with pytest.raises(QueueError) as caught:
        queue.reorder("job-a", "wang")
    assert caught.value.code == "not_job_owner"

    with pytest.raises(QueueError) as caught:
        queue.reorder("job-run", "li")
    assert caught.value.code == "job_not_reorderable"

    with pytest.raises(QueueError) as caught:
        queue.reorder("job-a", "li")
    assert caught.value.code == "reorder_needs_one_target"

    with pytest.raises(QueueError) as caught:
        queue.reorder("job-missing", "li", position=1.0)
    assert caught.value.code == "job_not_found"

    with pytest.raises(QueueError) as caught:
        queue.reorder("job-a", "li", before_id="job-missing")
    assert caught.value.code == "job_not_found"


# ── cancel ────────────────────────────────────────────────────────────────────


def test_cancel_a_waiting_job(store: Store, clock: FrozenClock) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    submit(store, queue, "job-a", immediate_window(clock, cfg), submitter="li")

    result = queue.cancel("job-a", "li")

    job = store.get_job("job-a")
    assert job["status"] == STATUS_CANCELED
    assert job["error"] == "canceled"
    assert job["finished_at"] is not None
    assert result["was_running"] is False


def test_cancel_reports_that_the_job_was_running(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    submit(store, queue, "job-a", immediate_window(clock, cfg), submitter="li")
    queue.tick()

    result = queue.cancel("job-a", "li")

    assert result["was_running"] is True, "the runner still has to release the worker"
    assert queue.running_count() == 0


def test_cancel_permissions(store: Store, clock: FrozenClock) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    submit(store, queue, "job-a", immediate_window(clock, cfg), submitter="li")

    with pytest.raises(QueueError) as caught:
        queue.cancel("job-a", "wang")
    assert caught.value.code == "not_job_owner"

    assert queue.cancel("job-a", "wang", is_admin=True)["status"] == STATUS_CANCELED

    with pytest.raises(QueueError) as caught:
        queue.cancel("job-a", "li")
    assert caught.value.code == "job_already_finished"


def test_cancel_a_scheduled_job_before_its_window_opens(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    submit(store, queue, "job-night", resolve_window("night", clock.now(), cfg))

    assert queue.cancel("job-night", "anderson")["status"] == STATUS_CANCELED
    assert queue.tick().promoted == []


# ── normalisation and snapshots ───────────────────────────────────────────────


def test_normalize_positions_preserves_order(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-a", window, queue_pos=3.14)
    submit(store, queue, "job-b", window, queue_pos=2.71)
    submit(store, queue, "job-c", window, queue_pos=1.0 + 1e-9)

    count = queue.normalize_positions()

    assert count == 3
    assert store.queue_positions() == [("job-c", 10.0), ("job-b", 20.0), ("job-a", 30.0)]


def test_line_position_counts_only_waiting_jobs(
    store: Store, clock: FrozenClock
) -> None:
    cfg = schedule_config()
    queue = queue_for(store, clock, cfg=cfg)
    window = immediate_window(clock, cfg)
    submit(store, queue, "job-wait", window, queue_pos=10.0)
    submit(store, queue, "job-ahead", window, queue_pos=5.0)
    submit(store, queue, "job-run", window, queue_pos=1.0)
    submit(store, queue, "job-done", window, queue_pos=0.5)
    store.update_job("job-run", status=STATUS_RUNNING)
    store.update_job("job-done", status="finished")

    snapshot = queue.snapshot("job-wait")

    assert snapshot["queue_ahead"] == 1, (
        "only job-ahead counts; the running and finished jobs left the line"
    )
    assert snapshot["status"] == STATUS_QUEUED
    assert snapshot["window"]["kind"] == "immediate"
    assert snapshot["window"]["not_after"] is None
    assert queue.position_in_line("job-run") == 0
    assert queue.position_in_line("job-done") == 0
