# -*- coding: utf-8 -*-
"""Planning a job: what the runner agrees to run, and what it refuses.

No processes here -- ``test_runner_e2e.py`` proves the run.  These cases pin the
decisions made before anything is launched, which is where a silently smaller
evaluation would hide: a dataset edited since submission, a selector that named
the same task twice, a job row with no snapshot behind it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint
from pawbench.cpd.acp_remote_eval.harness import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    MAX_TASK_TIMEOUT_SECONDS,
    RemoteAcpAgent,
    _resolve_timeout,
)
from pawbench.cpd.acp_remote_eval.service import runner as runner_module
from pawbench.cpd.acp_remote_eval.service.exchange import Exchange
from pawbench.cpd.acp_remote_eval.service.runner import (
    SKIP_DEADLINE,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    JobRunner,
    RunnerError,
)
from pawbench.cpd.acp_remote_eval.service.schedule import SystemClock
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import dataset_service, eval_config, job_row, write_task


@pytest.fixture()
def env(tmp_path: Path) -> tuple[Store, JobRunner]:
    workdir = tmp_path.resolve()
    builtin_root = workdir / "builtin"
    write_task(builtin_root, "mail_a", scenario="Office_Productivity/Email")
    write_task(builtin_root, "mail_b", scenario="Office_Productivity/Email", fixtures=("note.txt",))
    write_task(builtin_root, "chart_c", scenario="Data_Analytics/Visualization")

    config = eval_config(workdir / "service", builtin_root=builtin_root)
    store = Store(config.service.state_db)
    datasets = dataset_service(store, config)
    runner = JobRunner(
        store=store,
        datasets=datasets,
        exchange=Exchange(store, config.service, config.exchange, clock=SystemClock()),
        clock=SystemClock(),
    )
    yield store, runner
    store.close()


def make_dataset(env: tuple[Store, JobRunner], dataset_id: str, task_ids: list[str]) -> None:
    store, runner = env
    runner.datasets.create_builtin_view(
        dataset_id=dataset_id,
        name=dataset_id,
        owner="dev-1",
        filter_spec={"task_ids": task_ids},
    )


def attach(env: tuple[Store, JobRunner], job_id: str, *pairs: tuple[str, list[str]]) -> None:
    """One job row plus its dataset snapshots, in the order given."""
    store, _ = env
    store.insert_job(job_row(job_id))
    for dataset_id, task_ids in pairs:
        make_dataset(env, dataset_id, task_ids)
        store.insert_job_dataset(
            {
                "job_id": job_id,
                "dataset_id": dataset_id,
                "dataset_kind": "builtin_view",
                "requested_by": "dev-1",
                "resolved_task_ids": task_ids,
            }
        )


def test_the_plan_follows_the_snapshot_not_the_dataset_today(env) -> None:
    """Editing the dataset after submission must not change what is scored."""
    attach(env, "job-1", ("ds_mail", ["mail_a", "mail_b"]))
    store, runner = env
    make_dataset(env, "ds_mail", ["mail_a", "mail_b", "chart_c"])

    plans = runner.plan(store.get_job("job-1"))

    assert [str(plan.task.task_id) for plan in plans] == ["mail_a", "mail_b"]
    assert plans[0].resolved_from == ("dataset:ds_mail",)


def test_a_task_named_by_two_datasets_runs_once(env) -> None:
    """Mixed selectors overlap; the union is the plan, not the sum."""
    attach(env, "job-2", ("ds_charts", ["chart_c"]), ("ds_mail", ["mail_a", "mail_b", "chart_c"]))
    store, runner = env

    plans = runner.plan(store.get_job("job-2"))

    task_ids = [str(plan.task.task_id) for plan in plans]
    assert len(task_ids) == len(set(task_ids)), task_ids
    assert set(task_ids) == {"mail_a", "mail_b", "chart_c"}
    claimed = next(plan for plan in plans if str(plan.task.task_id) == "chart_c")
    assert claimed.resolved_from == ("dataset:ds_charts",), "datasets are walked in id order"


def test_the_plan_carries_where_its_fixtures_live(env) -> None:
    attach(env, "job-3", ("ds_mail", ["mail_b"]))
    store, runner = env

    plan = runner.plan(store.get_job("job-3"))[0]

    assert plan.dataset_root == runner.datasets.root_for("ds_mail")
    assert [entry["dest"] for entry in plan.task.workspace_files] == ["fixtures/note.txt"]


def test_a_job_with_no_snapshot_is_refused(env) -> None:
    store, runner = env
    store.insert_job(job_row("job-4"))

    with pytest.raises(RunnerError) as caught:
        runner.plan(store.get_job("job-4"))

    assert caught.value.code == "no_datasets"


def test_a_vanished_task_stops_the_run_instead_of_shortening_it(env) -> None:
    """Reporting on nine of ten looks like a complete result; it is not one."""
    attach(env, "job-5", ("ds_mail", ["mail_a", "gone_task"]))
    store, runner = env

    with pytest.raises(RunnerError) as caught:
        runner.plan(store.get_job("job-5"))

    assert caught.value.code == "task_unavailable"
    assert "gone_task" in caught.value.message


def test_an_empty_snapshot_is_refused(env) -> None:
    attach(env, "job-6", ("ds_mail", []))
    store, runner = env

    with pytest.raises(RunnerError) as caught:
        runner.plan(store.get_job("job-6"))

    assert caught.value.code == "empty_plan"


def test_the_plan_is_recorded_before_anything_runs(env) -> None:
    attach(env, "job-7", ("ds_mail", ["mail_a", "mail_b"]))
    store, runner = env
    plans = runner.plan(store.get_job("job-7"))

    runner.record_plan("job-7", plans)

    rows = store.list_job_tasks("job-7")
    assert [row["status"] for row in rows] == [STATUS_PENDING, STATUS_PENDING]
    assert [row["task_id"] for row in rows] == ["mail_a", "mail_b"], "snapshot order is kept"
    assert rows[1]["grading_type"] == "automated"
    assert rows[0]["resolved_from"] == ["dataset:ds_mail"]


def test_a_retry_is_a_row_of_its_own(env) -> None:
    """Attempt two must not overwrite what attempt one recorded."""
    attach(env, "job-8", ("ds_mail", ["mail_a"]))
    store, runner = env
    plans = runner.plan(store.get_job("job-8"))

    runner.record_plan("job-8", plans, attempt=1)
    runner.record_plan("job-8", plans, attempt=2)

    rows = store.list_job_tasks("job-8")
    assert [(row["task_id"], row["attempt"], row["status"]) for row in rows] == [
        ("mail_a", 1, STATUS_PENDING),
        ("mail_a", 2, STATUS_PENDING),
    ]


@pytest.mark.parametrize(
    "result, status",
    [
        ({"failure": "timeout"}, "failed"),
        ({"failure": "", "protocol_written": 2}, "finished"),
        ({"failure": "", "protocol_written": 0}, "missing"),
        ({}, "missing"),
    ],
)
def test_three_kinds_of_result_stay_three(result: dict, status: str) -> None:
    assert JobRunner.classify(result) == status


@pytest.mark.parametrize(
    "requested, declared, expected",
    [
        (2, 600, 2),
        (None, 600, 600),
        (0, 600, 600),
        (-5, 600, 600),
        ("abc", 45, 45),
        (99999, None, MAX_TASK_TIMEOUT_SECONDS),
        (None, None, DEFAULT_TASK_TIMEOUT_SECONDS),
        (0, 0, DEFAULT_TASK_TIMEOUT_SECONDS),
    ],
)
def test_the_wait_always_has_a_number_and_a_ceiling(
    requested: object, declared: object, expected: int
) -> None:
    """An unbounded wait would hold a queue slot until the service restarts.

    The caller's override, the task's front matter and a dataset someone else
    uploaded all reach the same resolver, so neither a missing number nor an
    absurd one can turn into "wait forever".
    """
    assert _resolve_timeout(requested, declared) == expected


def test_a_timeout_fallback_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert _resolve_timeout(None, 0) == DEFAULT_TASK_TIMEOUT_SECONDS
    assert "task timeout fell back" in caplog.text


# ── the two codes only run_task can produce ──────────────────────────────────


class _EarlyStopAgent:
    """An agent that stops at a chosen step, so ``run_task``'s own branches run.

    ``test_runner_e2e.py`` proves the steps that come from the wire; these
    outcomes come from the runner's exception handling, which the fake process
    has no way to reach without waiting on a real timeout.
    """

    def __init__(self, *, stops_at: str, delay: float = 0.0) -> None:
        self.stops_at = stops_at
        self.delay = delay
        self.recorder = SimpleNamespace(subject_model_reported="stub-model")
        self.torn_down = 0

    async def setup(self, environment: Any = None) -> dict:
        if self.stops_at == "setup":
            # The shape of an agent that accepts the connection and then never
            # answers the handshake: no exception, no result, just open.
            await asyncio.Event().wait()
        return {}

    async def run(self) -> dict:
        if self.stops_at == "run":
            await asyncio.Event().wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        return {
            "status": "ok",
            "failure": "",
            "protocol_written": 1,
            "stop_reason": "end_turn",
            "transcript": [],
            "subject_model_reported": "stub-model",
            "permissions": {},
            "timed_out": False,
        }

    async def post_run_collect(self) -> bool:
        if self.stops_at == "collect":
            raise TimeoutError("the collect step ran out of time")
        return True

    async def teardown(self) -> None:
        self.torn_down += 1


def _one_task_job(
    env: tuple[Store, JobRunner], monkeypatch: pytest.MonkeyPatch, job_id: str, agent: Any
):
    store, runner = env
    plans = runner.plan(store.get_job(job_id))
    runner.record_plan(job_id, plans, 1)
    monkeypatch.setattr(runner_module, "RemoteAcpAgent", lambda **kwargs: agent)
    return store, runner, plans[0]


def test_an_attempt_we_could_not_assemble_is_not_a_runner_error(env, monkeypatch) -> None:
    """The agent finished; we failed to gather it.  That is our machine to look at."""
    attach(env, "job-9", ("ds_mail", ["mail_a"]))
    agent = _EarlyStopAgent(stops_at="collect")
    store, runner, plan = _one_task_job(env, monkeypatch, "job-9", agent)

    row = asyncio.run(
        runner.run_task("job-9", plan, AcpEndpoint.stdio(["agent-bin"]), attempt=1)
    )

    assert row["status"] == "failed"
    assert row["failure_reason"] == "collect_timeout"


def test_a_cancelled_attempt_is_recorded_instead_of_staying_running(env, monkeypatch) -> None:
    """A cancelled coroutine skips the normal recording path, and the queue counts rows.

    Left in ``running`` the attempt would hold one of the global slots for the
    life of the service, so the cancellation branch has to write the row itself.
    """
    attach(env, "job-10", ("ds_mail", ["mail_a"]))
    agent = _EarlyStopAgent(stops_at="run")
    store, runner, plan = _one_task_job(env, monkeypatch, "job-10", agent)
    endpoint = AcpEndpoint.stdio(["agent-bin"])

    async def go() -> None:
        task = asyncio.create_task(runner.run_task("job-10", plan, endpoint, attempt=1))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())

    row = store.list_job_tasks("job-10")[0]
    assert row["status"] == "failed"
    assert row["failure_reason"] == "interrupted"
    assert agent.torn_down == 1


# ── the job's wall clock ──────────────────────────────────────────────────────


def _recorded_agent(
    env: tuple[Store, JobRunner],
    monkeypatch: pytest.MonkeyPatch,
    *,
    stops_at: str = "none",
    **agent_kwargs: Any,
) -> list[dict[str, Any]]:
    """Swap the agent out, keeping what the runner handed it as the attempt began."""
    built: list[dict[str, Any]] = []

    def fake_agent(**kwargs: Any) -> _EarlyStopAgent:
        built.append(kwargs)
        return _EarlyStopAgent(stops_at=stops_at, **agent_kwargs)

    monkeypatch.setattr(runner_module, "RemoteAcpAgent", fake_agent)
    return built


def test_the_wall_clock_labels_every_task_it_never_reached(env, monkeypatch) -> None:
    """No time left means no task starts, and each row says why.

    The alternative is ``pending`` rows under a job the scheduler has closed --
    a run whose denominator nobody can count, which is what the report is read
    for.
    """
    attach(env, "job-11", ("ds_mail", ["mail_a", "mail_b"]))
    store, runner = env
    built = _recorded_agent(env, monkeypatch)

    summary = asyncio.run(
        runner.run_job("job-11", endpoint=AcpEndpoint.stdio(["agent-bin"]), deadline_seconds=0)
    )

    assert built == [], "nothing was launched"
    rows = store.list_job_tasks("job-11")
    assert {row["status"] for row in rows} == {STATUS_SKIPPED}
    assert {row["failure_reason"] for row in rows} == {SKIP_DEADLINE}
    assert [row["duration_s"] for row in rows] == [0.0, 0.0]
    assert [row["status"] for row in summary.tasks] == [STATUS_SKIPPED, STATUS_SKIPPED]


def test_the_time_left_is_the_timeout_of_the_attempt_in_flight(env, monkeypatch) -> None:
    """The ceiling bites inside a task, not only between two of them.

    A task with a 300-second timeout that starts one second before the wall
    clock runs out would otherwise hold the job -- and the queue slot, and the
    next submitter -- open for five more minutes.
    """
    attach(env, "job-12", ("ds_mail", ["mail_a", "mail_b"]))
    store, runner = env
    built = _recorded_agent(env, monkeypatch, delay=0.4)

    asyncio.run(
        runner.run_job("job-12", endpoint=AcpEndpoint.stdio(["agent-bin"]), deadline_seconds=1.2)
    )

    handed = [kwargs["timeout_seconds"] for kwargs in built]
    assert handed == [1], "never zero: a zero timeout kills the attempt as it starts"
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-12")}
    assert rows["mail_a"]["status"] == STATUS_FINISHED
    assert (rows["mail_b"]["status"], rows["mail_b"]["failure_reason"]) == (
        STATUS_SKIPPED,
        SKIP_DEADLINE,
    )


def test_an_agent_that_never_finishes_the_handshake_loses_the_jobs_time(
    env, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Setup is a call into their machine, so the ceiling has to cover it too.

    The task timeout belongs to the prompt, which is why an agent that accepted
    the connection and then said nothing used to hold the attempt open past the
    wall clock -- and with it the queue slot and the lease that kept beating for
    it.  The step is named in the log because "our connection to them" and
    "their turn" are different machines to go and look at.
    """
    attach(env, "job-13", ("ds_mail", ["mail_a", "mail_b"]))
    store, runner = env
    _recorded_agent(env, monkeypatch, stops_at="setup")

    with caplog.at_level(logging.WARNING):
        started = time.monotonic()
        asyncio.run(
            runner.run_job(
                "job-13", endpoint=AcpEndpoint.stdio(["agent-bin"]), deadline_seconds=1.5
            )
        )
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"the attempt outlived the ceiling it was given: {elapsed:.1f}s"
    rows = {row["task_id"]: row for row in store.list_job_tasks("job-13")}
    assert (rows["mail_a"]["status"], rows["mail_a"]["failure_reason"]) == (
        STATUS_FAILED,
        SKIP_DEADLINE,
    ), "the in-flight attempt ran out of the job's clock, not of its own timeout"
    assert (rows["mail_b"]["status"], rows["mail_b"]["failure_reason"]) == (
        STATUS_SKIPPED,
        SKIP_DEADLINE,
    )
    assert "cut short by the job wall clock" in caplog.text
    cut_short = next(r for r in caplog.records if "cut short" in r.getMessage())
    assert cut_short.stage == "setup", "the log has to say which step the clock caught"


def test_a_collect_that_outlives_its_own_bound_is_still_our_fault(
    env, monkeypatch
) -> None:
    """The same TimeoutError, read two ways, and the stage says which.

    The job clock firing during the collect step and the collect step running
    past its own deadline look identical to the ``except`` clause.  Only the
    second is "the agent answered and we could not assemble it", which is the
    difference between a capability score and a service incident.
    """
    attach(env, "job-14", ("ds_mail", ["mail_a"]))
    store, runner = env
    _recorded_agent(env, monkeypatch, stops_at="collect")
    plan = runner.plan(store.get_job("job-14"))[0]

    row = asyncio.run(
        runner.run_task(
            "job-14", plan, AcpEndpoint.stdio(["agent-bin"]), attempt=1, timeout_cap=30.0
        )
    )

    assert (row["status"], row["failure_reason"]) == (STATUS_FAILED, "collect_timeout")


@pytest.mark.parametrize(
    "requested, cap, expected",
    [
        (None, None, None),
        (600, math.inf, 600),
        (None, math.inf, None),
        (600, 30.9, 30),
        (None, 30.9, 30),
        (2, 0.2, 1),
        (None, 0.0, 1),
    ],
)
def test_the_cap_never_hands_the_agent_a_timeout_of_zero(
    requested: int | None, cap: float | None, expected: int | None
) -> None:
    """One number for both halves of the ceiling: the submitter's override and
    whatever the job's wall clock has left."""
    assert runner_module._capped_timeout(requested, cap) == expected


def test_an_agent_that_refuses_the_prompt_is_not_a_lost_connection() -> None:
    """A JSON-RPC error is an answer, not a dropped link.

    An agent whose own model is misconfigured replies ``Internal error`` -- the
    wire worked, the agent did not.  Filing that under ``acp_connection_lost``
    sends the reader to the bridge's logs, which are clean, instead of to the
    agent's, which hold the reason.
    """
    from acp.exceptions import RequestError

    async def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RequestError.internal_error()

    agent = object.__new__(RemoteAcpAgent)
    agent.session = SimpleNamespace(prompt=refuse, stderr_tail=lambda _lines: "")
    agent.timeout_seconds = 5.0
    agent.job_id = "job-1"
    agent.task_id = "task-1"
    agent._timed_out = False
    agent._failure = ""
    agent.prompt_text = lambda text: text
    agent._resource_links = lambda: ()
    agent.execution_result = lambda result, _elapsed: {
        "status": "error" if agent._failure else "success",
        "failure": agent._failure,
        "error": result.get("error"),
    }

    outcome = asyncio.run(agent.run("do the thing"))

    assert outcome["failure"] == "acp_agent_error"
    assert outcome["error"] == "Internal error"
