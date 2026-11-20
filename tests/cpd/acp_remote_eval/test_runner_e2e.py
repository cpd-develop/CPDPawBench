# -*- coding: utf-8 -*-
"""M1's exit condition, end to end: a real agent process, a real socket.

The unit tests around the data plane and the client each hold one rule; this
file is where they have to hold together.  A separate Python process talks ACP
over stdio using the official SDK, fetches its fixtures over HTTP, PUTs its
results back, and the runner records what happened -- so the pieces that only
exist at a boundary get proven at one: URL signing across a process border, the
JSON the agent parses out of the prompt, the stderr pipe that must keep draining,
and the workspace the grader will later read.

Nothing here is in-process on purpose.  An in-process double can pass while the
wire is wrong.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import uvicorn

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint
from pawbench.cpd.acp_remote_eval.service.api import create_app
from pawbench.cpd.acp_remote_eval.service.attempts import AttemptRegistry
from pawbench.cpd.acp_remote_eval.service.exchange import Exchange
from pawbench.cpd.acp_remote_eval.service.runner import JobRunner
from pawbench.cpd.acp_remote_eval.service.schedule import SystemClock
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import dataset_service, eval_config, job_row, write_task

FAKE_AGENT = Path(__file__).resolve().parent / "tools" / "fake_acp_agent.py"
HOST = "127.0.0.1"
TASK_IDS = ("mail_answer", "xlsx_with_file", "chart_csv")


@dataclass
class Env:
    """The running service, with the handles a test asserts on."""

    store: Store
    datasets: Any
    exchange: Exchange
    registry: AttemptRegistry
    base_url: str
    workdir: Path
    server: uvicorn.Server

    def runner(self, *, timeout_seconds: int | None = None) -> JobRunner:
        return JobRunner(
            store=self.store,
            datasets=self.datasets,
            exchange=self.exchange,
            registry=self.registry,
            clock=SystemClock(),
            timeout_seconds=timeout_seconds,
        )

    def submit(self, job_id: str, task_ids: tuple[str, ...] = TASK_IDS) -> str:
        """The two rows a submission will write once the API exists (M2)."""
        dataset_id = f"ds_{job_id}"
        record = self.datasets.create_builtin_view(
            dataset_id=dataset_id, name=dataset_id, owner="dev-1", filter_spec={"task_ids": list(task_ids)}
        )
        self.store.insert_job(
            job_row(
                job_id,
                # The position is the queue's business once the submit API exists
                # (M2); this test starts the run itself, so it only needs a row
                # the queue would not have rejected.
                queue_pos=float(self.store.max_queue_pos()) + 1.0,
            )
        )
        self.store.insert_job_dataset(
            {
                "job_id": job_id,
                "dataset_id": dataset_id,
                "dataset_kind": record["kind"],
                "requested_by": "dev-1",
                "resolved_task_ids": list(record["task_ids"]),
            }
        )
        return job_id


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _start_server(app: Any, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="pawbench-data-plane")
    thread.start()
    return server, thread


def _wait_until_healthy(base_url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)
    raise AssertionError(f"the data plane never came up on {base_url}")


@pytest.fixture()
def env(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Env]:
    workdir = tmp_path.resolve()
    builtin_root = workdir / "builtin"
    write_task(builtin_root, "mail_answer", scenario="Office_Productivity/Email")
    write_task(
        builtin_root,
        "xlsx_with_file",
        scenario="Office_Productivity/Spreadsheet",
        modality="multimodal",
        grading_type="hybrid",
        fixtures=("budget.xlsx",),
    )
    write_task(
        builtin_root,
        "chart_csv",
        scenario="Data_Analytics/Visualization",
        grading_type="llm_judge",
        fixtures=("series.csv",),
    )

    port = _free_port()
    base_url = f"http://{HOST}:{port}"
    config = eval_config(
        workdir / "service",
        builtin_root=builtin_root,
        public_base_url=base_url,
        exchange_overrides={"max_uploads_per_run": 8},
    )
    store = Store(config.service.state_db)
    request.addfinalizer(store.close)
    exchange = Exchange(store, config.service, config.exchange, clock=SystemClock())
    registry = AttemptRegistry()
    server, thread = _start_server(create_app(exchange=exchange, registry=registry), port)
    # Registered before the health wait, not after it: a server that never came
    # up still owns a bound socket, a live thread and the SQLite handle, and a
    # fixture that fails on the way in would leave all three behind for the
    # rest of the session.
    request.addfinalizer(_shutdown(server, thread))
    _wait_until_healthy(base_url)

    yield Env(
        store=store,
        datasets=dataset_service(store, config),
        exchange=exchange,
        registry=registry,
        base_url=base_url,
        workdir=workdir,
        server=server,
    )


def _shutdown(server: uvicorn.Server, thread: threading.Thread) -> Callable[[], None]:
    """Stop the data plane and fail the test if the thread does not come back."""

    def shutdown() -> None:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise AssertionError("the data-plane thread was still running 10s after should_exit")

    return shutdown


def _agent_endpoint(*args: str) -> AcpEndpoint:
    """The fake agent as a submission sees it: a command, over stdio."""
    return AcpEndpoint.stdio([sys.executable, str(FAKE_AGENT), *args])


def _run(
    env: Env, job_id: str, *agent_args: str, timeout_seconds: int | None = None
) -> dict[str, Any]:
    runner = env.runner(timeout_seconds=timeout_seconds)
    summary = asyncio.run(
        runner.run_job(job_id, endpoint=_agent_endpoint(*agent_args), attempt=1)
    )
    return summary.as_payload()


def _rows(env: Env, job_id: str) -> dict[str, dict[str, Any]]:
    return {row["task_id"]: row for row in env.store.list_job_tasks(job_id)}


# ── the run ───────────────────────────────────────────────────────────────────


def test_a_real_agent_runs_three_builtin_tasks(env: Env) -> None:
    """The M1 exit row: three built-in tasks, at least one with an attachment."""
    job_id = env.submit("job-artifacts")

    payload = _run(env, job_id, "--mode", "artifacts", "--model", "fake-model-1")

    assert payload["task_count"] == 3
    assert payload["by_status"] == {"finished": 3}, payload["tasks"]
    assert payload["artifacts"] == 3, "one result file per task, through the protocol"
    assert payload["subject_models_reported"] == ["fake-model-1"]
    assert len(env.registry) == 0, "every attempt closed when its task ended"


def test_the_attachment_task_shows_all_three_legs(env: Env) -> None:
    """Fixtures out, results in, workspace rebuilt -- each one visible on disk."""
    job_id = env.submit("job-roundtrip")

    _run(env, job_id, "--mode", "artifacts", "--model", "fake-model-1")

    staging = env.exchange.attempt_dir(job_id, "xlsx_with_file", 1) / "session"
    uploads = env.exchange.uploads_dir(job_id, "xlsx_with_file", 1)
    workspace = env.exchange.attempt_dir(job_id, "xlsx_with_file", 1) / "workspace"

    assert (staging / "fixtures" / "budget.xlsx").read_text() == "content of budget.xlsx"
    assert (uploads / "output" / "budget.md").read_text().startswith("# budget")
    assert (workspace / "fixtures" / "budget.xlsx").is_file()
    assert (workspace / "output" / "budget.md").is_file()

    rows = env.store.list_artifacts(job_id, task_id="xlsx_with_file", kind="output")
    assert [row["path"] for row in rows] == ["output/budget.md"]


def test_the_transcript_records_what_the_agent_said_and_did(env: Env) -> None:
    job_id = env.submit("job-transcript")

    payload = _run(env, job_id, "--mode", "artifacts", "--model", "fake-model-1")

    row = _rows(env, job_id)["chart_csv"]
    path = Path(str(row["transcript_path"]))
    assert path == env.exchange.attempt_dir(job_id, "chart_csv", 1) / "transcript.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    kinds = {str(event.get("sessionUpdate")) for event in events}
    assert "agent_message_chunk" in kinds
    assert "tool_call" in kinds, "the GET and the PUT are part of what the run did"
    task = next(item for item in payload["tasks"] if item["task_id"] == "chart_csv")
    assert task["transcript_events"] > 0, "the chat-side events reach the grader too"


def test_a_late_upload_after_the_attempt_closed_is_refused(env: Env) -> None:
    """A run token must die with its attempt, or a retry inherits a live grant."""
    job_id = env.submit("job-late")
    manifest = env.exchange.build_manifest(
        job_id=job_id,
        task=env.datasets.tasks_for_run(f"ds_{job_id}")[0],
        dataset_root=env.datasets.root_for(f"ds_{job_id}"),
    )
    _run(env, job_id, "--mode", "zero", "--model", "fake-model-1")

    request = urllib.request.Request(  # noqa: S310 - fixed localhost URL
        str(manifest["upload"]["url"]).replace("{path}", "output/late.md"),
        data=b"late",
        method="PUT",
        headers={"Authorization": str(manifest["upload"]["headers"]["Authorization"])},
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310
    assert caught.value.code == 404
    assert json.loads(caught.value.read())["error"] == "attempt_not_running"


# ── the two kinds of no-score ─────────────────────────────────────────────────


def test_an_agent_that_keeps_its_files_is_missing_not_failed(env: Env) -> None:
    """Answered, nothing to grade: dropped from the leaderboard, never a zero."""
    job_id = env.submit("job-zero")

    payload = _run(env, job_id, "--mode", "zero", "--model", "fake-model-1")

    assert payload["by_status"] == {"missing": 3}
    assert payload["tasks_missing"] == 3
    assert payload["artifacts"] == 0
    for row in payload["tasks"]:
        assert row["failure_reason"] == "no_artifacts"
        assert row["stop_reason"] == "end_turn", "the agent finished talking"
        assert row["transcript_events"] > 0, "we still know what it did"


def test_an_unreachable_agent_fails_without_eating_the_timeout(env: Env) -> None:
    """A command that does not exist costs milliseconds, not the task timeout."""
    job_id = env.submit("job-missing-agent")
    runner = env.runner()
    plan = runner.plan(env.store.get_job(job_id))
    dead_end = AcpEndpoint.stdio([str(FAKE_AGENT.parent / "no-such-agent.py")])

    row = asyncio.run(runner.run_task(job_id, plan[0], dead_end))

    assert row["status"] == "failed"
    assert row["failure_reason"] == "acp_agent_not_found"
    assert row["protocol_written"] == 0
    assert row["duration_s"] < 5


def test_a_hang_is_canceled_and_recorded_as_a_timeout(env: Env) -> None:
    """The queue slot has to come back, and it has to say why it came back."""
    job_id = env.submit("job-hang", task_ids=("mail_answer",))

    began = time.monotonic()
    payload = _run(env, job_id, "--mode", "hang", timeout_seconds=2)
    elapsed = time.monotonic() - began

    assert payload["by_status"] == {"failed": 1}
    task = payload["tasks"][0]
    assert task["failure_reason"] == "timeout"
    assert task["stop_reason"] == "timeout"
    assert elapsed < 15, "cancel plus teardown, not a second full timeout"


def test_the_stderr_of_a_chatty_agent_does_not_stall_the_run(env: Env) -> None:
    """An unread pipe fills and blocks the writer; the run must not notice."""
    job_id = env.submit("job-noise")

    payload = _run(env, job_id, "--mode", "stderr-flood", "--model", "fake-model-1")

    assert payload["by_status"] == {"finished": 3}, "the flood never reached the run"
    assert payload["artifacts"] == 3
