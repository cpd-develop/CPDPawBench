# -*- coding: utf-8 -*-
"""``RemoteAcpAgent`` -- the harness that evaluates an agent over ACP.

It follows the lifecycle the rest of PawBench expects from a harness
(``setup / run / teardown / post_run_collect / extract_transcript``) so the
grader sees an ordinary ``execution_result`` and needs no new mode.  What is
different is only what happens in between: nothing is installed, nothing is
copied, and the files we score arrive over HTTP because the agent is somebody
else's program on somebody else's machine.

The class is instantiated directly by :mod:`.service.runner`.  It is
deliberately absent from ``pawbench/agents/factory.py`` -- see design section
2.1 -- so a community change to that registry can never half-enable a remote
run with no data plane behind it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from acp.exceptions import RequestError
from acp.schema import ResourceContentBlock
from pawbench.agents.base import BaseAgent
from pydantic import ValidationError

from .acp.client import AcpEndpoint, AcpError, connect, mint_session_id
from .acp.transcript import TranscriptRecorder
from .service.exchange import Exchange

logger = logging.getLogger(__name__)

#: What the agent is told about the protocol, next to its task text.  The
#: manifest is machine-readable; this is the part a harness written without our
#: documentation still has a chance of following.
PROTOCOL_HELP = """\
This run is graded by PawBench in bring-your-own-environment mode.

The JSON block below describes this task: the fixtures to download, and the one
URL that accepts your results.  Nothing else on this machine is shared with you,
and nothing you write to your own filesystem reaches the grader.

  - GET each entry in "assets" and save it at "dest", relative to your workspace.
  - For every result file, PUT its bytes to "upload.url" with "{path}" replaced
    by the workspace-relative path, sending the headers from "upload.headers".
  - "upload.budget" is the number of files accepted; send results, not scratch.
"""

#: Stamped on the prompt so a report can name the instructions the agent saw.
PROTOCOL_VERSION_TAG = "pawbench-exchange/1"

#: A task with no usable ``timeout_seconds`` -- the field is missing, or it is
#: not a number -- still has to end.  ``datasets`` coerces the missing case to
#: ``0``, and ``0`` fed to ``asyncio.wait_for`` means *forever*: an unbounded
#: hold on someone else's process, which also pins the queue slot.
DEFAULT_TASK_TIMEOUT_SECONDS = 1800

#: The ceiling on that resolution, so one mistyped front matter cannot ask for
#: a week while the queue believes it has four slots.
MAX_TASK_TIMEOUT_SECONDS = 4 * 3600

#: How long the post-run rebuild gets before the attempt is called failed.  It
#: is disk work in a thread, so cancelling the coroutine would not stop it; the
#: deadline is what keeps one wedged volume from holding a queue slot.
COLLECT_TIMEOUT_SECONDS = 300.0

#: How long a canceled agent gets to notice before we stop waiting.  The
#: connection is torn down regardless; this only bounds the courtesy.
CANCEL_GRACE_SECONDS = 5.0


class RemoteAcpAgent(BaseAgent):
    """One ACP session for one task attempt.

    Short-lived by construction: the run token, the session and the staging
    directory all belong to a single attempt, so a retry cannot inherit a
    half-written workspace.
    """

    def __init__(
        self,
        *,
        endpoint: AcpEndpoint,
        exchange: Exchange,
        job_id: str,
        task: Any,
        dataset_root: Path,
        attempt: int = 1,
        timeout_seconds: int | None = None,
        client_name: str = "pawbench-eval",
    ) -> None:
        super().__init__(name="acp-remote")
        self.endpoint = endpoint
        self.exchange = exchange
        self.job_id = job_id
        self.task = task
        self.task_id = str(task.task_id)
        self.dataset_root = Path(dataset_root)
        self.attempt = int(attempt)
        self.timeout_seconds = _resolve_timeout(timeout_seconds, task.timeout_seconds)
        self.client_name = client_name

        self.attempt_dir = exchange.attempt_dir(job_id, self.task_id, self.attempt)
        self.staging_dir = self.attempt_dir / "session"
        self.workspace_dir = self.attempt_dir / "workspace"
        self.recorder = TranscriptRecorder(self.attempt_dir / "transcript.jsonl")
        # Two handles, two readers.  ``trace_id`` appears in *our* log lines, so
        # a report row and the stderr that explains it join without guessing
        # timestamps.  ``session_id`` is the agent's own handle for this
        # conversation -- we ask for a recognisable one in ``setup`` -- and is
        # for whoever reads that agent's console.  Neither substitutes for the
        # other: our log has no idea what the agent called the conversation,
        # and the agent's log has never heard of our attempt.
        self.trace_id = uuid.uuid4().hex[:16]
        self.session_id = ""
        self.manifest: dict[str, Any] = {}
        self.handshake: dict[str, Any] = {}
        self.session: Any = None
        self._failure = ""
        self._timed_out = False

    # ── BaseAgent contract ────────────────────────────────────────────────────

    @property
    def version(self) -> str:
        return str((self.handshake.get("agent_info") or {}).get("version") or "1")

    @property
    def capabilities(self) -> dict[str, Any]:
        return dict(self.handshake.get("capabilities") or {})

    async def setup(self, environment: Any = None) -> dict[str, Any]:
        """Open the connection and one session, after minting the run manifest.

        The manifest comes first because the prompt has to carry it: issuing the
        token and building the links must not fail halfway and leave a session
        open with nothing to ask.
        """
        self.attempt_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        # Every fixture is read and hashed to build this, so it goes to a
        # thread: the service loop also carries the data plane and the tick.
        self.manifest = await asyncio.to_thread(
            self.exchange.build_manifest,
            job_id=self.job_id,
            task=self.task,
            dataset_root=self.dataset_root,
            attempt=self.attempt,
        )
        self.session = await connect(self._endpoint_for_attempt(), self.recorder)
        self.handshake = await self.session.initialize(client_name=self.client_name)
        # Ask the agent to file this conversation under an id its own console
        # recognises (``1795156778446-y2r8j2a``), not the opaque handle
        # ``session/new`` would mint.  The report is read by whoever owns the
        # agent; an id they can paste into their session list is what turns
        # "a run happened" into "this run, on this machine".
        self.session_id = await self.session.new_session(
            str(self.staging_dir),
            self._declared_directories(),
            preferred_id=mint_session_id(),
        )
        logger.info(
            "remote agent ready",
            extra={
                "job_id": self.job_id,
                "task_id": self.task_id,
                "trace_id": self.trace_id,
                "session_id": self.session_id,
                "endpoint": self.session.describe,
                "load_session": self.handshake.get("supports_load_session"),
            },
        )
        return self.handshake

    async def run(self, instruction: str = "", environment: Any = None) -> dict[str, Any]:
        """Send the task and wait for the agent, up to the deadline.

        A timeout is a result rather than an exception: the fixtures were
        served, the transcript exists, and whatever arrived is still scored.
        What the run failed to prove is recorded in ``failure``, which is where
        the queue view and the report both look.
        """
        text = str(instruction or self.manifest.get("prompt") or self.task.prompt)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.session.prompt(self.prompt_text(text), self._resource_links()),
                self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._timed_out = True
            self._failure = "timeout"
            await self._cancel_after_timeout()
            result = {"stop_reason": "timeout", "usage": {}}
        except AcpError as exc:
            self._failure = exc.code
            result = {"stop_reason": "error", "usage": {}, "error": exc.message}
        except ValidationError as exc:
            # Our prompt did not serialise: the agent never saw it, so saying
            # "connection lost" would send the next reader to the wrong machine.
            self._failure = "acp_prompt_rejected"
            result = {"stop_reason": "error", "usage": {}, "error": str(exc)}
            logger.error(
                "prompt rejected before it was sent",
                extra={"job_id": self.job_id, "task_id": self.task_id, "error": str(exc)[:300]},
            )
        except RequestError as exc:
            # The agent answered -- it answered with a JSON-RPC error, which is
            # a task failure and not a lost link.  An agent whose own model is
            # misconfigured replies ``Internal error`` here, and calling that
            # "connection lost" sends the reader to the bridge's logs instead of
            # to the agent's, which is where the reason actually is.
            self._failure = "acp_agent_error"
            result = {"stop_reason": "error", "usage": {}, "error": str(exc)}
            logger.warning(
                "acp prompt refused by the agent",
                extra={
                    "job_id": self.job_id,
                    "task_id": self.task_id,
                    "code": getattr(exc, "code", None),
                    "error": str(exc)[:200],
                    "stderr_tail": self.session.stderr_tail(5) if self.session else "",
                },
            )
        except Exception as exc:  # the SDK raises its own transport errors here
            self._failure = "acp_connection_lost"
            result = {"stop_reason": "error", "usage": {}, "error": str(exc)}
            logger.warning(
                "acp prompt failed",
                extra={
                    "job_id": self.job_id,
                    "task_id": self.task_id,
                    "error": str(exc)[:200],
                    "stderr_tail": self.session.stderr_tail(5) if self.session else "",
                },
            )
        return await asyncio.to_thread(self.execution_result, result, time.monotonic() - started)

    async def post_run_collect(self, environment: Any = None) -> dict[str, Any]:
        """Rebuild the graded workspace from our fixtures plus their uploads."""
        # A tree copy of a whole dataset directory, on the service loop: the
        # thread is the only reason a rebuild does not stall the other attempts.
        # The deadline exists because the thread cannot be cancelled -- past it
        # the attempt is failed and the queue slot moves on, which is what a
        # wedged disk call must not be able to prevent.
        rebuild = await asyncio.wait_for(
            asyncio.to_thread(
                self.exchange.rebuild_workspace,
                job_id=self.job_id,
                task=self.task,
                dataset_root=self.dataset_root,
                target=self.workspace_dir,
                attempt=self.attempt,
            ),
            COLLECT_TIMEOUT_SECONDS,
        )
        logger.info(
            "workspace rebuilt",
            extra={
                "job_id": self.job_id,
                "task_id": self.task_id,
                "fixtures_laid": rebuild.fixtures_laid,
                "artifacts_laid": rebuild.artifacts_laid,
            },
        )
        return rebuild.to_payload()

    async def teardown(self, environment: Any = None) -> None:
        """Close the session, revoke the token and stop writing the transcript."""
        try:
            if self.session is not None:
                await self.session.close()
        finally:
            self.session = None
            self.exchange.tokens.revoke(self.job_id, self.task_id)
            self.recorder.close()

    def extract_transcript(self, local_workspace: Any = None, stdout: str = "") -> list[dict]:
        """The recorded events, in the shape ``grader._summarize_transcript`` reads."""
        return list(self.recorder.events)

    # ── the result ────────────────────────────────────────────────────────────

    def execution_result(self, prompt_result: Mapping[str, Any], elapsed: float) -> dict[str, Any]:
        """An ``execution_result`` for the existing grading code to consume.

        ``status`` is about the exchange, not the score: an agent that said "I
        cannot do this" and handed a file back still ran successfully.  Whether
        the run measured anything at all is ``protocol_written``, and a zero
        there is ``no_artifacts`` -- dropped from the leaderboard rather than
        counted as zero, because zero means "did it wrong".
        """
        uploads = self.exchange.store.list_artifacts(
            self.job_id, task_id=self.task_id, kind="output"
        )
        return {
            "agent_id": self.name,
            "harness_kind": "acp_remote",
            "environment": "byo",
            "task_id": self.task_id,
            "attempt": self.attempt,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "status": "error" if self._failure else "success",
            "failure": self._failure,
            "stop_reason": str(prompt_result.get("stop_reason") or ""),
            "transcript": self.extract_transcript(),
            "transcript_stats": self.recorder.stats(),
            "subject_model_reported": self.recorder.subject_model_reported,
            "usage": dict(prompt_result.get("usage") or {}),
            "workspace": str(self.workspace_dir),
            "exit_code": 0 if not self._failure else 1,
            "timed_out": self._timed_out,
            "execution_time": elapsed,
            "stdout": "",
            "stderr": self.session.stderr_tail() if self.session is not None else "",
            "log_text": "",
            "protocol_written": len(uploads),
            "permissions": self.session.permission_stats() if self.session is not None else {},
            "agent_capabilities": self.capabilities,
            "agent_info": self.handshake.get("agent_info") or {},
            "error": str(prompt_result.get("error") or ""),
        }

    def prompt_text(self, instruction: str) -> str:
        """The task in its own words, then the manifest in a JSON fence.

        The fence is the contract on the agent side -- it is what a harness
        written without our documentation greps for -- so the manifest travels
        inside the prompt rather than behind a URL that would itself need
        authenticating before the first authenticated link could be handed out.
        """
        body = json.dumps(self.manifest, ensure_ascii=False, indent=2, sort_keys=True)
        return f"{instruction.strip()}\n\n---\n\n{PROTOCOL_HELP}\n```json\n{body}\n```\n"

    # ── prompt blocks ─────────────────────────────────────────────────────────

    def _resource_links(self) -> list[ResourceContentBlock]:
        """One link per fixture, so a multimodal agent sees what it is for.

        The ``uri`` is the same presigned URL the manifest carries: an agent
        that resolves links fetches the fixture that way, one that ignores them
        still has the JSON, and both end up calling the same route.  The SDK's
        prompt union accepts the ``resource_link`` variant, not the bare
        ``ResourceLink`` base it is built from.
        """
        links = []
        for asset in self.manifest.get("assets") or []:
            links.append(
                ResourceContentBlock(
                    name=str(asset.get("dest", "")),
                    uri=str(asset.get("url", "")),
                    mime_type="application/octet-stream",
                    size=int(asset.get("size") or 0),
                )
            )
        return links

    def _endpoint_for_attempt(self) -> AcpEndpoint:
        """The submitted endpoint, pointed at this attempt's staging directory.

        ``cwd`` belongs to the attempt, not to the submission: two tasks of one
        job must not share a working directory, or the second reads the first's
        leftovers and both scores mean nothing.
        """
        return dataclasses.replace(self.endpoint, cwd=str(self.staging_dir))

    def _declared_directories(self) -> Sequence[str]:
        return tuple(self.endpoint.additional_directories)

    async def _cancel_after_timeout(self) -> None:
        if self.session is None:
            return
        try:
            await asyncio.wait_for(self.session.cancel(), timeout=CANCEL_GRACE_SECONDS)
        except Exception as exc:  # a hung agent is the case this exists for
            logger.warning(
                "cancel did not stop the agent",
                extra={
                    "job_id": self.job_id,
                    "task_id": self.task_id,
                    "error": str(exc)[:200],
                },
            )


def endpoint_from_submission(
    *,
    acp_url: str = "",
    command: Sequence[str] | str = (),
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    additional_directories: Sequence[str] = (),
) -> AcpEndpoint:
    """Build the endpoint a submission asked for, without guessing in between.

    A submission gives exactly one of a command or an address.  Deciding that
    here keeps the precedence in one place -- if it grew, every caller would
    need the same rule and only one of them would be tested.
    """
    url = str(acp_url or "").strip()
    argv = [str(part) for part in ([command] if isinstance(command, str) else list(command))]
    if url and argv:
        raise AcpError("acp_endpoint_ambiguous", "give either an ACP address or a command, not both")
    if url:
        return AcpEndpoint.http(url, cwd=cwd, additional_directories=additional_directories)
    if argv:
        return AcpEndpoint.stdio(argv, cwd=cwd, env=env, additional_directories=additional_directories)
    raise AcpError("acp_endpoint_missing", "the submission gave neither an ACP address nor a command")


def _resolve_timeout(requested: Any, declared: Any) -> int:
    """Seconds to wait for one prompt, always a number.

    Order is the runner's override, then the task's own front matter.  Anything
    missing, zero, negative or unparseable becomes
    :data:`DEFAULT_TASK_TIMEOUT_SECONDS`, and a value over
    :data:`MAX_TASK_TIMEOUT_SECONDS` is pulled back to it: the wait has a ceiling
    whether the number came from us or from a dataset someone else uploaded.
    """
    for candidate in (requested, declared):
        try:
            seconds = int(str(candidate).strip())
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return min(seconds, MAX_TASK_TIMEOUT_SECONDS)
    logger.warning(
        "task timeout fell back to the service default",
        extra={"requested": requested, "declared": declared, "default": DEFAULT_TASK_TIMEOUT_SECONDS},
    )
    return DEFAULT_TASK_TIMEOUT_SECONDS


__all__ = ["RemoteAcpAgent", "endpoint_from_submission"]
