# -*- coding: utf-8 -*-
"""Which attempts this process is running right now.

Split out of :mod:`.api` because both halves of the service need it and neither
should own it: the runner registers an attempt so its fixtures can be fetched,
the data plane looks it up to answer a request, and the reader side
(:mod:`.reports`) has to reach the runner without importing the HTTP app.  Left
in ``api.py``, that last edge closed a cycle -- ``reports`` -> ``runner`` ->
``api`` -> ``reports``.

In memory, for the same reason :class:`.exchange.RunTokenVault` is: a service
that dies mid-run marks its jobs ``failed(recovered)`` instead of resuming them,
so state that outlived the process would be state nobody is scoring.  A PUT that
arrives after the attempt closed is therefore correct to refuse, not a bug to
paper over.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exchange import ExchangeError, TaskLike

#: An attempt the service is no longer running.  Not an ``ExchangeError`` code
#: from the caller's point of view -- it means "your run is over", which a
#: late PUT and a forged one both look like.
ATTEMPT_NOT_RUNNING = "attempt_not_running"


@dataclass(frozen=True)
class LiveAttempt:
    """What a running attempt needs before it can answer a fixture request."""

    task: TaskLike
    dataset_root: Path


class AttemptRegistry:
    """The attempts this process is running right now."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str, int], LiveAttempt] = {}

    def register(self, job_id: str, task_id: str, attempt: int, live: LiveAttempt) -> None:
        self._attempts[(job_id, task_id, int(attempt))] = live

    def drop(self, job_id: str, task_id: str, attempt: int) -> None:
        self._attempts.pop((job_id, task_id, int(attempt)), None)

    def lookup(self, job_id: str, task_id: str, attempt: int) -> LiveAttempt:
        live = self._attempts.get((job_id, task_id, int(attempt)))
        if live is None:
            raise ExchangeError(
                ATTEMPT_NOT_RUNNING, "this attempt is not running on this service"
            )
        return live

    def __len__(self) -> int:
        return len(self._attempts)
