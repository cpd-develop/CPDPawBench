# -*- coding: utf-8 -*-
"""Assembling and starting the process: which config value ends up where.

``build_service`` is the only place the whole design is wired together, so it is
where a default that was parsed and never handed on hides.  A ``max_job_seconds``
that does not reach the runner leaves the night window as the only ceiling on a
job; a bind taken from the request rather than the config is the exact failure the
``public_base_url`` rule exists to prevent.  The order ``serve`` starts things in
belongs here too: opening the port before the startup reconcile means an upload
can arrive for a job that is already dead.

No real port is bound and no agent is contacted -- ``test_runner_e2e.py`` owns
the wire.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
import yaml

from pawbench.cpd.acp_remote_eval.service import daemon as daemon_module
from pawbench.cpd.acp_remote_eval.service.daemon import (
    ContextFormatter,
    Service,
    _split_bind,
    build_service,
    main,
    serve,
)
from pawbench.cpd.acp_remote_eval.service.queue import (
    QueueLimits,
    STATUS_FAILED,
    STATUS_RUNNING,
)
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import eval_config, job_row, write_task


def write_config(workdir: Path, **service_overrides: Any) -> Path:
    """A real YAML file on disk, so the config path is exercised as a path."""
    builtin_root = workdir / "builtin"
    write_task(builtin_root, "mail_a", scenario="Office_Productivity/Email")
    raw: dict[str, Any] = {
        "service": {"public_base_url": "http://127.0.0.1:8471", **service_overrides},
        # The scratch catalogue has one text task, which is (correctly) not a
        # pilot; these cases are about the config and the process, so seeding is
        # switched off rather than faked around.
        "datasets": {"builtin_dir": str(builtin_root), "pilot_dataset_id": ""},
        "exchange": {"exchange_dir": "exchange"},
    }
    path = workdir / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@pytest.fixture()
def make_service() -> Iterator[Any]:
    """Build services through the real entry point and close them afterwards."""
    built: list[Service] = []

    def _make(workdir: Path, *, owner: str = "proc-a", **service_overrides: Any) -> Service:
        config = eval_config(
            workdir / "service",
            builtin_root=workdir / "builtin",
            service_overrides=service_overrides,
        )
        service = build_service(config, owner=owner)
        built.append(service)
        return service

    yield _make
    for service in built:
        try:
            service.store.close()
        except sqlite3.ProgrammingError:
            pass  # already closed by the exit path under test


# ── wiring ────────────────────────────────────────────────────────────────────


def test_the_defaults_reach_the_components_that_enforce_them(make_service, tmp_path: Path) -> None:
    service = make_service(tmp_path)

    assert service.runner.job_deadline_seconds == 7200.0
    assert service.queue.limits == QueueLimits(max_concurrent_jobs=4, max_running_per_user=1)
    assert (service.runtime.lease_ttl_seconds, service.runtime.tick_seconds) == (90.0, 5.0)
    assert service.runtime.owner == "proc-a", "only a pinned owner keeps the lease meaningful"


def test_an_override_is_not_read_and_then_dropped(make_service, tmp_path: Path) -> None:
    service = make_service(
        tmp_path, max_job_seconds=600, lease_ttl_seconds=40, max_concurrent_jobs=2
    )

    assert service.runner.job_deadline_seconds == 600.0
    assert service.runtime.lease_ttl_seconds == 40.0
    assert service.queue.limits.max_concurrent_jobs == 2


def test_the_data_plane_app_shares_the_exchange_and_registry_it_was_built_with(
    make_service, tmp_path: Path
) -> None:
    """One process owns both halves, so the app must not hold a second vault.

    A run token minted by the runner and looked up by a different ``Exchange``
    would refuse the agent's upload as forged -- and only show up on a real run.
    """
    service = make_service(tmp_path)

    assert service.app.state.exchange is service.exchange
    assert service.app.state.attempts is service.registry


def test_the_state_database_is_created_where_the_config_said(
    make_service, tmp_path: Path
) -> None:
    service = make_service(tmp_path)

    assert service.config.service.state_db.is_file()
    service.store.insert_job(job_row("job-wire", status=STATUS_RUNNING))
    assert str(service.store.get_job("job-wire")["status"]) == STATUS_RUNNING


# ── bind ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bind,expected",
    [("127.0.0.1:8471", ("127.0.0.1", 8471)), ("0.0.0.0:80", ("0.0.0.0", 80)),
     ("[::1]:8471", ("[::1]", 8471))],
)
def test_bind_splits_as_uvicorn_wants_it(bind: str, expected: tuple[str, int]) -> None:
    assert _split_bind(bind) == expected


@pytest.mark.parametrize("bind", ["8471", "host:port", "host:", ":8471"])
def test_a_bind_that_is_not_host_colon_port_names_the_key(bind: str) -> None:
    with pytest.raises(ValueError, match="service.bind must look like host:port"):
        _split_bind(bind)


# ── startup order ─────────────────────────────────────────────────────────────


def install_fake_uvicorn(
    monkeypatch: pytest.MonkeyPatch, store: Store, probe: dict[str, Any], events: list[str]
) -> None:
    """Replace ``uvicorn`` with two classes that keep the real call shapes."""

    class Config:
        def __init__(self, app, *, host, port, log_level):
            events.append("config")
            # Read the database at the moment the port is about to open: nothing
            # may be accepted before the leftovers are settled.
            probe["app"] = app
            probe["host"] = host
            probe["port"] = port
            probe["job"] = store.get_job("job-orphan")

    class Server:
        def __init__(self, config):
            self.config = config

        async def serve(self):
            events.append("serve")
            # A real server always yields -- it is listening on a socket.  The
            # step matters: without it the tick task never runs, and "cancelled
            # before it started" is a different ending from "died on its own".
            await asyncio.sleep(0)

    monkeypatch.setattr(daemon_module, "uvicorn", SimpleNamespace(Config=Config, Server=Server))


def test_serve_settles_the_leftovers_before_it_opens_the_port(
    make_service, monkeypatch, tmp_path: Path
) -> None:
    service = make_service(tmp_path)
    service.store.insert_job(job_row("job-orphan", status=STATUS_RUNNING))
    service.store.insert_job_tasks(
        [{"job_id": "job-orphan", "task_id": "mail_a", "grading_type": "automated"}]
    )
    probe: dict[str, Any] = {}
    events: list[str] = []
    install_fake_uvicorn(monkeypatch, service.store, probe, events)

    asyncio.run(serve(service))

    assert events == ["config", "serve"]
    assert probe["app"] is service.app
    assert (probe["host"], probe["port"]) == ("127.0.0.1", 8471)
    assert str(probe["job"]["status"]) == STATUS_FAILED
    assert str(probe["job"]["error"]) == "recovered"


def test_a_startup_reconcile_hanging_does_not_hang_the_event_loop(
    make_service, monkeypatch, tmp_path: Path
) -> None:
    """The one store call before the port opens is off the loop, and provably.

    A stalled startup is not a slow start: ``/healthz`` is served by this same
    loop, so a wedged database reads as a dead process and an orchestrator
    restarts it into another wedge.  The probe is a second coroutine, so taking
    the ``to_thread`` out fails here in two seconds instead of hanging the suite.
    """
    service = make_service(tmp_path)
    service.store.insert_job(job_row("job-orphan", status=STATUS_RUNNING))
    service.store.insert_job_tasks(
        [{"job_id": "job-orphan", "task_id": "mail_a", "grading_type": "automated"}]
    )
    at_open: dict[str, Any] = {}
    install_fake_uvicorn(monkeypatch, service.store, at_open, [])

    entered = threading.Event()
    released = threading.Event()
    loop_was_free: list[bool] = []
    real_reconcile = service.runtime.reconcile

    def blocking_reconcile() -> Any:
        entered.set()
        loop_was_free.append(released.wait(2.0))
        return real_reconcile()

    monkeypatch.setattr(service.runtime, "reconcile", blocking_reconcile)

    async def probe() -> None:
        while not entered.is_set():
            await asyncio.sleep(0.005)
        released.set()

    async def go() -> None:
        probing = asyncio.create_task(probe())
        try:
            await serve(service)
        finally:
            await probing

    asyncio.run(go())

    assert loop_was_free and all(loop_was_free), "another coroutine ran during the query"
    assert str(at_open["job"]["error"]) == "recovered", "off the loop is not skipped"


def test_the_store_is_closed_when_the_service_exits(
    make_service, monkeypatch, tmp_path: Path
) -> None:
    """An open handle after ``serve`` returns means a leaked connection.

    The process is meant to run for days and restarts are routine; the handle is
    also the thing that keeps the WAL files growing on disk.
    """
    service = make_service(tmp_path)
    install_fake_uvicorn(monkeypatch, service.store, {}, [])

    asyncio.run(serve(service))

    with pytest.raises(sqlite3.ProgrammingError):
        service.store.query("SELECT 1 FROM jobs")


def test_an_interrupted_start_still_runs_the_exit_path(
    make_service, monkeypatch, tmp_path: Path
) -> None:
    """Ctrl-C lands inside ``server.serve()``, and the finally block is the exit."""
    service = make_service(tmp_path)

    class Config:
        def __init__(self, app, *, host, port, log_level):
            self.app = app

    class Server:
        def __init__(self, config):
            pass

        async def serve(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(daemon_module, "uvicorn", SimpleNamespace(Config=Config, Server=Server))

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(serve(service))

    assert service.runtime.running_jobs() == ()
    with pytest.raises(sqlite3.ProgrammingError):
        service.store.query("SELECT 1 FROM jobs")


# ── the exit path ─────────────────────────────────────────────────────────────


def test_an_exit_step_that_raises_does_not_skip_the_others(
    make_service, monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Half an exit is a service that left a ``running`` row and a live tick loop.

    ``shutdown`` is the step that talks to a database which may be wedged; if its
    raise ended the exit, the scheduler would go on ticking against a store nobody
    closes and the jobs it holds would be settled only at the next restart.
    """
    service = make_service(tmp_path)
    install_fake_uvicorn(monkeypatch, service.store, {}, [])

    async def broken_shutdown() -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(service.runtime, "shutdown", broken_shutdown)
    with caplog.at_level(logging.ERROR):
        asyncio.run(serve(service))

    assert "exit step failed" in caplog.text
    with pytest.raises(sqlite3.ProgrammingError):
        service.store.query("SELECT 1 FROM jobs")


def test_a_scheduler_that_died_is_reported_rather_than_collected(
    make_service, monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Awaiting the tick task is what turns its traceback into a log line.

    A service with a dead scheduler still answers ``/healthz``; the only symptom
    is jobs that never start, so the exception the loop ended on has to reach the
    log rather than be dropped when the task is garbage-collected.
    """
    service = make_service(tmp_path)
    install_fake_uvicorn(monkeypatch, service.store, {}, [])

    async def dead_serve() -> None:
        raise RuntimeError("scheduler could not read the queue")

    monkeypatch.setattr(service.runtime, "serve", dead_serve)
    with caplog.at_level(logging.ERROR):
        asyncio.run(serve(service))

    stopped = next(r for r in caplog.records if "scheduler stopped on its own" in r.getMessage())
    assert "could not read the queue" in stopped.reason


def _record(message: str, **context: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        "pawbench.eval.runtime",
        logging.INFO,
        __file__,
        1,
        message,
        (),
        None,
    )
    for key, value in context.items():
        setattr(record, key, value)
    return record


def test_the_entry_point_renders_the_context_the_package_logs() -> None:
    """``extra=`` is how this package says *which* job a line is about.

    Plain ``logging`` drops record attributes the format string does not name,
    so the default entry format prints "job launched" with no job id, no owner
    and no reason -- a line nobody can locate a failure from.
    """
    formatter = ContextFormatter("%(levelname)s %(name)s: %(message)s")
    line = formatter.format(_record("job launched", job_id="job-7", owner="host:4242"))

    assert "job launched" in line
    assert "job_id='job-7'" in line and "owner='host:4242'" in line
    assert "lineno=" not in line and "msg=" not in line, "reserved keys are not context"


def test_a_line_with_no_context_reads_as_it_written() -> None:
    assert ContextFormatter("%(message)s").format(_record("scheduler starting")) == (
        "scheduler starting"
    )


def test_the_renderer_does_not_pass_a_credential_in_a_url_through() -> None:
    """An endpoint is a URL, and a library echoes the request it failed on.

    The submitter's credential can ride in the userinfo part of a URL that an
    agent's own error message repeats, and this renderer is the last place that
    still has a chance to keep it out of the log file.
    """
    text = ContextFormatter("%(message)s").format(
        _record("acp prompt failed", acp_url="http://eval:SEKRIT@127.0.0.1:9100/rpc")
    )

    assert "SEKRIT" not in text
    assert "127.0.0.1:9100/rpc" in text, "the host is the part that names the agent"


def test_main_passes_the_config_file_through_and_configures_logging(
    monkeypatch, tmp_path: Path
) -> None:
    """``--config`` is the only way to reach a deployed address, so it is tested.

    Logging is configured here and nowhere else in the package: a library that
    sets up its own handler decides the output format for the whole process.
    """
    path = write_config(tmp_path, bind="127.0.0.1:8499")
    seen: dict[str, Any] = {}

    async def fake_serve(service: Service) -> None:
        seen["bind"] = service.config.service.bind
        seen["db"] = service.config.service.state_db
        service.store.close()

    def fake_basic_config(**kwargs: Any) -> None:
        seen["logging"] = kwargs

    monkeypatch.setattr(daemon_module, "serve", fake_serve)
    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    assert main(["--config", str(path), "--log-level", "warning"]) == 0

    assert seen["bind"] == "127.0.0.1:8499"
    assert seen["db"].parent == tmp_path / "runtime"
    assert str(seen["logging"]["level"]).upper() == "WARNING"
