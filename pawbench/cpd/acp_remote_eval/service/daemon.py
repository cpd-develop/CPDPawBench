# -*- coding: utf-8 -*-
"""The process: config in, one always-on service out.

One event loop carries both halves of the design -- the HTTP data plane a remote
agent PUTs its answers to, and the scheduler tick that decides when to run a job
against a remote agent.  They share the SQLite handle and the attempt registry,
which is the reason they are one process and not two: a job the queue has
started must be able to hand its run token to the same process that will answer
the upload.

Nothing here reads a task or talks ACP; it wires components and starts them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import uvicorn

from .api import ControlPlane, create_app
from .attempts import AttemptRegistry
from .auth import StaticConfigVerifier, TokenVerifier
from .config import EvalConfig, load_config
from .datasets import BuiltinCatalog, DatasetError, DatasetService
from .exchange import Exchange
from .grading import LlmJudge, Scorer
from .jobs import JobService
from .pilot import seed_pilot
from .queue import JobQueue, QueueLimits
from .reports import Reports
from .runner import JobRunner
from .runtime import EvalRuntime
from .schedule import SystemClock
from .store import Store

logger = logging.getLogger(__name__)

#: Attributes every :class:`logging.LogRecord` has, worked out from a sample
#: rather than listed: a hardcoded set rots when the stdlib adds one, and the
#: fallback would be printing ``module=daemon.py lineno=116`` on every line.
_RESERVED_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}

#: The userinfo part of a URL.  An endpoint is a URL, and an SDK that echoes the
#: request back in the exception it raises puts whatever the submitter carried in
#: it -- often a token -- into the text we then render.  The host stays: it is
#: the part that identifies which agent was being reached.
_URL_CREDENTIALS = re.compile(r"(\w+)://[^\s/@]+@")


class ContextFormatter(logging.Formatter):
    """Append the ``extra=`` fields, which is where this package puts its context.

    ``logging`` silently drops record attributes the format string does not
    name, so the default entry-point format would print ``job launched`` with
    no job id, no owner and no reason attached -- and a line that cannot say
    *which* object it is about is a line nobody can act on.

    Every line also goes through the URL credential scrub, because this renderer
    is the one place that turns a library's exception text into our log file.
    """

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        context = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_")
        }
        if context:
            joined = " ".join(f"{key}={context[key]!r}" for key in sorted(context))
            text = f"{text} [{joined}]"
        return _URL_CREDENTIALS.sub(r"\1://***@", text)


@dataclass
class Service:
    """Everything the running service owns, for the tests and for ``main``."""

    config: EvalConfig
    store: Store
    exchange: Exchange
    registry: AttemptRegistry
    datasets: DatasetService
    queue: JobQueue
    jobs: JobService
    reports: Reports
    runner: JobRunner
    runtime: EvalRuntime
    app: Any


def build_verifier(config: EvalConfig) -> TokenVerifier:
    """The token check this deployment will actually run.

    An unset ``service.allowlist_file`` is an empty allowlist, not an open
    service: the routes stay up and every call answers 401.  The alternative --
    no control plane until someone adds a file -- would let a half-configured
    box start, look healthy and refuse nothing, which is the failure that ends
    with an evaluation service on a team network that anyone can submit to.
    """
    if config.allowlist_path is None:
        logger.warning("no allowlist configured; every control call will be refused")
        return StaticConfigVerifier([])
    return StaticConfigVerifier.from_file(config.allowlist_path)


def build_service(
    config: EvalConfig, *, owner: str | None = None, log_level: str = "INFO"
) -> Service:
    """Construct the components in dependency order, without starting anything.

    ``owner`` is pinned only by tests: in production it is this process's host
    and pid, which is what makes the lease mean something to a second service
    pointed at the same database file.
    """
    clock = SystemClock()
    store = Store(config.service.state_db)
    exchange = Exchange(store, config.service, config.exchange, clock=clock)
    registry = AttemptRegistry()
    datasets = DatasetService(store, config.datasets, BuiltinCatalog(config.datasets.builtin_dir))
    queue = JobQueue(
        store,
        config.schedule,
        limits=QueueLimits(
            max_concurrent_jobs=config.service.max_concurrent_jobs,
            max_running_per_user=config.service.max_running_per_user,
        ),
        clock=clock,
    )
    jobs = JobService(
        store=store, queue=queue, datasets=datasets, config=config, clock=clock
    )
    reports = Reports(store, exchange, datasets, clock=clock)
    runner = JobRunner(
        store=store,
        datasets=datasets,
        exchange=exchange,
        registry=registry,
        clock=clock,
        scorer=Scorer(LlmJudge(config.judge)),
        job_deadline_seconds=float(config.service.max_job_seconds),
    )
    runtime = EvalRuntime(
        store=store,
        queue=queue,
        runner=runner,
        clock=clock,
        owner=owner,
        lease_ttl_seconds=config.service.lease_ttl_seconds,
        tick_seconds=config.schedule.tick_seconds,
    )
    control = ControlPlane(
        jobs=jobs,
        datasets=datasets,
        verifier=build_verifier(config),
        reports=reports,
        # The runtime's own method: a cancel only reaches the agent in the
        # process holding the run, which is exactly the process this app is.
        stop_running=runtime.stop_job,
    )
    app = create_app(exchange=exchange, registry=registry, control=control)
    from ..mcp.server import mount_mcp

    mount_mcp(app, control, config.service.public_base_url, log_level)
    return Service(
        config=config,
        store=store,
        exchange=exchange,
        registry=registry,
        datasets=datasets,
        queue=queue,
        jobs=jobs,
        reports=reports,
        runner=runner,
        runtime=runtime,
        app=app,
    )


def _split_bind(bind: str) -> tuple[str, int]:
    """``host:port`` as uvicorn wants it, with the failure named."""
    host, _, port_text = bind.rpartition(":")
    if not host or not port_text.isdigit():
        raise ValueError(f"service.bind must look like host:port (got {bind!r})")
    return host, int(port_text)


async def serve(service: Service) -> None:
    """Run the data plane and the scheduler until one of them stops."""
    host, port = _split_bind(service.config.service.bind)
    settled = await asyncio.to_thread(service.runtime.reconcile)
    logger.info(
        "evaluation service starting",
        extra={
            "bind": service.config.service.bind,
            "public_base_url": service.config.service.public_base_url,
            "max_concurrent_jobs": service.config.service.max_concurrent_jobs,
            "settled_jobs": len(settled),
            "owner": service.runtime.owner,
        },
    )
    server = uvicorn.Server(
        uvicorn.Config(service.app, host=host, port=port, log_level="info")
    )
    scheduler = asyncio.create_task(service.runtime.serve(), name="eval-scheduler")
    try:
        await server.serve()
    finally:
        # In this order: jobs still running would otherwise be cancelled while
        # their rows say ``running``, which is the state the lease is meant to
        # clean up rather than this being a normal exit.
        #
        # Each step guarded on its own.  Together they are the only path that
        # writes the terminal rows and closes the database, so one raising must
        # not skip the rest -- the jobs it left behind would then be settled by
        # the next restart instead of by this exit.
        try:
            await service.runtime.shutdown()
        except Exception:
            logger.exception("exit step failed", extra={"step": "running jobs"})
        try:
            await _stop_scheduler(scheduler)
        except Exception:
            logger.exception("exit step failed", extra={"step": "scheduler"})
        try:
            await asyncio.to_thread(service.store.close)
        except Exception:
            logger.exception("exit step failed", extra={"step": "store"})


async def _stop_scheduler(scheduler: asyncio.Task) -> None:
    """Cancel the tick loop and report how it ended.

    The wait is the point: a task nobody awaits can raise on its way out and be
    collected without anyone reading the traceback, which is how a service with a
    dead scheduler keeps answering ``/healthz``.  ``asyncio.wait`` is used instead
    of ``await`` because our own cancellation of it is the expected ending, while
    its own exception is the one that has to reach a log.
    """
    scheduler.cancel()
    await asyncio.wait({scheduler})
    if scheduler.cancelled():
        logger.info("scheduler stopped", extra={"scheduler": scheduler.get_name()})
        return
    logger.error(
        "scheduler stopped on its own",
        extra={"scheduler": scheduler.get_name(), "reason": repr(scheduler.exception())},
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m pawbench.cpd.acp_remote_eval --config service.yaml``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="path to the service config")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    handler = logging.StreamHandler()
    handler.setFormatter(
        ContextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=args.log_level.upper(), handlers=[handler])
    config = load_config(args.config)
    service = build_service(config, log_level=args.log_level.upper())
    try:
        seed_pilot(service.datasets, config.datasets)
    except DatasetError as exc:
        # Refuse readiness rather than start anyway: a pilot that quietly lost its
        # fixture tasks scores exactly as convincingly as one that exercises the
        # data plane, and the gap list is the only thing that tells them apart.
        logger.error(
            "service refused to start",
            extra={"code": exc.code, "error": exc.message, "gaps": exc.details.get("gaps")},
        )
        service.store.close()
        return 2
    asyncio.run(serve(service))
    return 0
