# -*- coding: utf-8 -*-
"""The client half of an ACP connection, sized for unattended evaluation.

Three things distinguish an evaluation client from an editor one: nobody is
there to approve tool permissions, the file and terminal delegations are
deliberately not offered (the subject agent works in its own environment --
that is the whole point of BYO), and a hang has to be turned into a
diagnosis rather than a stalled queue slot.

The protocol itself comes from ``agent-client-protocol``; re-implementing the
JSON-RPC layer would give us a private schema to keep in sync with whoever is
on the other end.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent, spawn_agent_process
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    Implementation,
    PermissionOption,
    RequestPermissionResponse,
    TextContentBlock,
)

from ..redact import url_without_credentials
from .transcript import TranscriptRecorder

logger = logging.getLogger(__name__)

#: Tried in this order; see :func:`_allow_option`.
_ALLOW_KINDS = ("allow_always", "allow_once")

#: Bounded because the subject is third-party code: an agent that spams stderr
#: must not be able to grow our memory, and nobody reads those lines except in
#: a failure report.
_STDERR_TAIL_LINES = 200

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"
_SUPPORTED_URL_SCHEMES = ("http://", "https://")

#: Alphabet for the random half of a minted session id: lowercase alnum, which
#: is what the consoles we mirror use.
_SESSION_ID_ALPHABET = string.ascii_lowercase + string.digits
_SESSION_ID_SUFFIX = 7


def mint_session_id(now: float | None = None) -> str:
    """A session handle shaped like the ones agents show their own users.

    ``1795156778446-y2r8j2a``: epoch milliseconds, a dash, seven random
    characters.  We mint it rather than accept the agent's opaque handle for
    one reason -- the report is read by whoever owns the agent, and they search
    *their* console, not our protocol trace.  An id the console recognises is
    the difference between "this run" and "a run somewhere, sometime".
    """
    millis = int((time.time() if now is None else now) * 1000)
    suffix = "".join(secrets.choice(_SESSION_ID_ALPHABET) for _ in range(_SESSION_ID_SUFFIX))
    return f"{millis}-{suffix}"


#: argv tokens matching one of these words have their value replaced.  A name
#: list rather than a pattern, because the submissions we launch are ordinary
#: CLIs whose secret is a flag value, not an embedded credential.
_SECRET_WORDS = ("key", "token", "secret", "password", "credential")

#: How long a session waits for a polite ``session/cancel`` on close before it
#: moves on; the same reason the harness caps it during a timeout.
CANCEL_CLOSE_GRACE_SECONDS = 5.0

#: The two handshake calls are the only ones with no deadline of their own,
#: and a process that starts and then says nothing would hold a queue slot, a
#: run token and a session forever.  ``prompt`` is bounded by the task timeout.
HANDSHAKE_TIMEOUT_SECONDS = 30.0


async def _bounded(awaitable: Any, step: str) -> Any:
    """One handshake call, with a deadline and a name for the failure.

    A plain ``wait_for`` timeout would reach the runner as ``runner_error``;
    naming the step is what tells the next reader which call the agent never
    answered.
    """
    try:
        return await asyncio.wait_for(awaitable, HANDSHAKE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise AcpError(
            "acp_handshake_timeout",
            f"{step} did not answer within {HANDSHAKE_TIMEOUT_SECONDS} seconds",
        ) from exc


def _redact_argv(argv: Sequence[str]) -> list[str]:
    """The command line with any credential value replaced by its length."""
    shown: list[str] = []
    secret_next = False
    for part in [str(item) for item in argv]:
        name = part.split("=", 1)[0].casefold()
        is_secret_flag = any(word in name for word in _SECRET_WORDS)
        if secret_next and not part.startswith("-"):
            shown.append(f"<{len(part)} chars>")
            secret_next = False
            continue
        secret_next = is_secret_flag and "=" not in part
        if is_secret_flag and "=" in part:
            shown.append(f"{name}=<{len(part.split('=', 1)[1])} chars>")
            continue
        shown.append(part)
    return shown


class AcpError(ValueError):
    """A connection or protocol step that cannot be honoured."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AcpEndpoint:
    """Where the subject agent is, and how to reach it.

    ``env`` only ever *adds* to the small allowlist the SDK inherits
    (``acp.transports.default_environment``): the subject agent is someone
    else's code running on our machine, so it must not see ``JUDGE_API_KEY``.
    """

    transport: str
    command: tuple[str, ...] = ()
    url: str = ""
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    #: Directories named in ``session/new`` besides the working directory --
    #: where the agent may put files it wants us to look at.  Declaring them is
    #: the agent-side contract; checking what comes back is the collection
    #: layer's job (design section 8).
    additional_directories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.transport not in (TRANSPORT_STDIO, TRANSPORT_HTTP):
            raise AcpError(
                "acp_transport_unsupported",
                f"unknown ACP transport {self.transport!r}; use stdio or http",
            )

    @classmethod
    def stdio(
        cls,
        command: Any,
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        additional_directories: Sequence[str] = (),
    ) -> "AcpEndpoint":
        """An agent we launch ourselves over stdio."""
        argv = tuple(str(part) for part in list(command))
        if not argv or not argv[0].strip():
            raise AcpError("acp_command_empty", "a stdio endpoint needs at least a program name")
        return cls(
            TRANSPORT_STDIO,
            command=argv,
            cwd=cwd,
            env=env,
            additional_directories=tuple(str(path) for path in additional_directories),
        )

    @classmethod
    def http(
        cls,
        url: str,
        *,
        cwd: str | None = None,
        additional_directories: Sequence[str] = (),
    ) -> "AcpEndpoint":
        """An agent someone else is running, reached over streamable HTTP."""
        text = str(url or "").strip()
        if not text.startswith(_SUPPORTED_URL_SCHEMES):
            raise AcpError(
                "acp_url_unsupported",
                f"only http:// and https:// ACP addresses are supported, got {text!r}",
            )
        return cls(
            TRANSPORT_HTTP,
            url=text,
            cwd=cwd,
            additional_directories=tuple(str(path) for path in additional_directories),
        )

    def describe(self) -> str:
        """A log-safe identity: nothing that can carry a credential.

        The http form drops the query string, the stdio form drops the values of
        flags that read like a key.  Both strings end up in the job row, in
        failure messages and in the log, and a submission writes the command.
        """
        if self.transport == TRANSPORT_STDIO:
            return f"stdio:{' '.join(_redact_argv(self.command))}"
        return f"{self.transport}:{url_without_credentials(self.url)}"


class EvalAcpClient(Client):
    """Callbacks the agent calls into us, with an evaluation's defaults.

    Built by :func:`spawn_command` / :func:`spawn_url`; the harness never
    touches it, which is why the transcript lands on ``_recorder`` rather than
    being threaded through every caller.
    """

    def __init__(self, recorder: TranscriptRecorder | None = None) -> None:
        super().__init__()
        self.recorder = recorder if recorder is not None else TranscriptRecorder()
        self.permission_requests = 0
        self.permissions_allowed = 0
        self.permissions_denied = 0

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        self.recorder.record(update, session_id=session_id)

    async def request_permission(
        self,
        session_id: str,
        tool_call: Any,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        """Answer a tool-permission request without a human.

        Auto-approval is what makes an unattended run possible, and every one of
        them is recorded -- each is a place where the subject's harness wants a
        person, which is a capability difference worth reporting even when the
        task scores well.
        """
        self.permission_requests += 1
        title = str(getattr(tool_call, "title", "") or getattr(tool_call, "name", "") or "")
        choice = _allow_option(options)
        if choice is None:
            self.permissions_denied += 1
            self.recorder.note(f"[evaluation] no allow option offered for {title!r}")
            logger.warning(
                "permission request offered no allow option",
                extra={"session_id": session_id, "tool": title[:120]},
            )
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        self.permissions_allowed += 1
        logger.debug(
            "permission auto-approved",
            extra={"session_id": session_id, "tool": title[:120], "kind": choice.kind},
        )
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=str(choice.option_id))
        )

    # ── delegations we never offered ──────────────────────────────────────────

    async def read_text_file(self, session_id: str, path: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("fs/read_text_file")

    async def write_text_file(self, session_id: str, path: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("fs/write_text_file")

    async def create_terminal(self, session_id: str, command: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/output")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> Any:
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/release")

    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        raise RequestError.method_not_found("terminal/kill")


class AcpSession:
    """One live connection: initialize, one session, one prompt at a time.

    Transport-agnostic on purpose -- :func:`spawn_command` builds one over a
    stdio subprocess, :func:`spawn_url` over HTTP, and a test around an
    in-process agent.  Everything the protocol steps need is handed in here, so
    the only difference between those three is how the agent object was made.
    """

    def __init__(
        self,
        agent: Any,
        client: EvalAcpClient,
        *,
        describe: str = "in-process",
        stderr_lines: list[str] | None = None,
        teardown: Any = None,
        process: Any = None,
    ) -> None:
        self.agent = agent
        self.client = client
        self.recorder = client.recorder
        self.describe = describe
        self.session_id = ""
        self.agent_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self.supports_load_session = False
        self.stop_reason = ""
        self.usage: dict[str, Any] = {}
        self._stderr = stderr_lines if stderr_lines is not None else []
        self._teardown = teardown
        self._process = process

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "AcpSession":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Tear the connection down; safe to call twice, never raises.

        Every step logs instead of swallowing: this is the only place the
        subprocess is reaped, so a silent failure here is an orphan that
        outlives the job and the queue slot it was holding.  The kill sits in a
        ``finally`` rather than in the sequence because a cancelled run lands
        here as ``CancelledError``, which is not an ``Exception`` -- an
        unhandled one would abandon the reap along with the transport close.
        """
        try:
            if self.session_id and not self.stop_reason:
                try:
                    await asyncio.wait_for(self.cancel(), CANCEL_CLOSE_GRACE_SECONDS)
                except (Exception, asyncio.CancelledError) as exc:
                    logger.warning(
                        "session/cancel did not finish on close",
                        extra={
                            "endpoint": self.describe,
                            "session_id": self.session_id,
                            "reason": repr(exc),
                        },
                    )
            teardown, self._teardown = self._teardown, None
            if teardown is not None:
                await teardown()
        except (Exception, asyncio.CancelledError) as exc:
            logger.warning(
                "endpoint teardown failed",
                extra={
                    "endpoint": self.describe,
                    "session_id": self.session_id,
                    "reason": repr(exc),
                },
            )
        finally:
            self._kill_process()
            self.agent = None

    def _kill_process(self) -> None:
        """Kill the child if the transport's own shutdown left it running.

        Synchronous, and no exit is waited for: the child watcher reaps the
        process whether or not this coroutine gets to keep running, and a
        cancelled caller cannot afford the wait.
        """
        process, self._process = self._process, None
        if process is None or getattr(process, "returncode", None) is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            # It exited between the returncode check and the signal, which is
            # the outcome this was asking for.
            return
        logger.warning(
            "agent process left running; killed",
            extra={"endpoint": self.describe, "session_id": self.session_id},
        )

    # ── protocol steps ────────────────────────────────────────────────────────

    async def initialize(self, *, client_name: str = "pawbench-eval") -> dict[str, Any]:
        """Handshake once per connection; returns the capability record."""
        response = await _bounded(
            self.agent.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(name=client_name, version="1"),
            ),
            "initialize",
        )
        payload = _dump(response)
        caps = _as_mapping(payload.get("agentCapabilities"))
        self.agent_info = _as_mapping(payload.get("agentInfo"))
        self.capabilities = caps
        self.supports_load_session = bool(caps.get("loadSession"))
        return {
            "protocol_version": payload.get("protocolVersion"),
            "agent_info": self.agent_info,
            "capabilities": caps,
            "supports_load_session": self.supports_load_session,
            "auth_methods": payload.get("authMethods") or [],
        }

    async def new_session(
        self,
        cwd: str,
        additional_directories: Sequence[str] = (),
        *,
        preferred_id: str = "",
    ) -> str:
        """Open a session rooted at *cwd* (the agent's own choice what that means).

        The extra directories exist for the stdio lane, where the agent shares
        this machine: they are the only places we will later agree to look for
        files it produced, so naming them up front is what makes "I wrote the
        answer somewhere" a question with an answer.  For an agent on another
        machine they are our paths, not theirs, and the submission declares them
        only if it means to.

        *preferred_id* asks the agent to file this conversation under a handle
        we chose (see :func:`mint_session_id`).  ``session/new`` has no field
        for it, so the ask goes through ``session/load``: an agent that
        supports loading adopts the id and writes its own history under it,
        which is what makes the report's ``session_id`` searchable in that
        agent's console.  Everything else is unchanged -- if the agent does not
        declare ``loadSession``, or refuses the id, we fall back to whatever
        ``session/new`` hands back rather than failing the attempt.
        """
        directories = [str(path) for path in additional_directories]
        if preferred_id and await self._adopt_session(preferred_id, cwd, directories):
            return self.session_id
        response = await _bounded(
            self.agent.new_session(
                cwd=cwd, additional_directories=directories, mcp_servers=[]
            ),
            "session/new",
        )
        self.session_id = str(_dump(response).get("sessionId") or "")
        if not self.session_id:
            raise AcpError("acp_session_missing", "the agent opened no session")
        logger.info(
            "acp session open",
            extra={
                "endpoint": self.describe,
                "session_id": self.session_id,
                "additional_directories": len(directories),
            },
        )
        return self.session_id

    async def _adopt_session(self, session_id: str, cwd: str, directories: list[str]) -> bool:
        """Try to make *session_id* the agent's own handle for this conversation.

        Returns whether it took.  A refusal is routine, not an error: the id is
        a convenience for whoever reads the report, and losing it must not cost
        a task attempt.
        """
        if not self.supports_load_session:
            logger.info(
                "agent cannot adopt a session id; using the one it mints",
                extra={"endpoint": self.describe, "preferred_id": session_id},
            )
            return False
        try:
            await _bounded(
                self.agent.load_session(
                    cwd=cwd,
                    session_id=session_id,
                    mcp_servers=[],
                    additional_directories=directories,
                ),
                "session/load",
            )
        except Exception as exc:  # noqa: BLE001 - a refusal must never fail the attempt
            # Any failure here is the agent declining a courtesy.  Swallowing
            # broadly is the point: a transport hiccup would otherwise surface
            # as "could not open a session", which sends the next reader to the
            # wrong layer.
            logger.warning(
                "agent refused the requested session id; opening a fresh one",
                extra={
                    "endpoint": self.describe,
                    "preferred_id": session_id,
                    "reason": repr(exc),
                },
            )
            return False
        self.session_id = session_id
        logger.info(
            "acp session adopted the caller's id",
            extra={
                "endpoint": self.describe,
                "session_id": session_id,
                "additional_directories": len(directories),
            },
        )
        return True

    async def prompt(self, text: str, blocks: Sequence[Any] = ()) -> dict[str, Any]:
        """Send one prompt and wait for the agent to say it is done.

        *blocks* carries the resource links the run declared; text-only agents
        ignore them and a multimodal one reads the fixture it was pointed at.
        """
        if not self.session_id:
            raise AcpError("acp_session_missing", "open a session before prompting")
        response = await self.agent.prompt(
            session_id=self.session_id,
            prompt=[TextContentBlock(text=text), *list(blocks)],
        )
        payload = _dump(response)
        self.stop_reason = str(payload.get("stopReason") or "")
        self.usage = _as_mapping(payload.get("usage"))
        return {"stop_reason": self.stop_reason, "usage": self.usage}

    async def cancel(self) -> None:
        """Tell the agent to stop; the runner calls this on deadline."""
        if self.agent is None or not self.session_id:
            return
        await self.agent.cancel(self.session_id)
        logger.info(
            "acp session canceled",
            extra={"session_id": self.session_id, "endpoint": self.describe},
        )

    def permission_stats(self) -> dict[str, int]:
        return {
            "requests": self.client.permission_requests,
            "allowed": self.client.permissions_allowed,
            "denied": self.client.permissions_denied,
        }

    def stderr_tail(self, limit: int = 20) -> str:
        """The agent's own last words, when it has any.

        Kept off the transcript on purpose: stderr is the harness complaining,
        not the answer, and the judge prompt must not read it as either.
        """
        return "\n".join(self._stderr[-limit:])


class StderrLogDrain:
    """Reads a subprocess stderr into a bounded tail.

    An unread pipe fills at the OS buffer size and the agent blocks on its next
    log line, which is indistinguishable from a slow model in the queue view.
    The task is created only once the pipe exists, or it dies reading a
    ``None`` and the buffer is unread again.
    """

    def __init__(self, process: Any) -> None:
        self.lines: list[str] = []
        self._task = (
            asyncio.create_task(self._drain(process.stderr))
            if getattr(process, "stderr", None) is not None
            else None
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None

    async def _drain(self, stream: Any) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            self.lines.append(line.decode("utf-8", "replace").rstrip())
            del self.lines[:-_STDERR_TAIL_LINES]


async def spawn_command(
    endpoint: AcpEndpoint, recorder: TranscriptRecorder
) -> tuple[AcpSession, Any]:
    """Launch the agent and hand back a session that reaps it.

    The process is kept on the session, not only returned: :meth:`AcpSession.close`
    is what guarantees the child is gone even when the transport's shutdown
    raised.  Telling a crashed agent apart from a thinking one -- so a crash
    costs seconds instead of the task timeout -- is not done here yet; the
    harness waits on the prompt alone.
    """
    client = EvalAcpClient(recorder)
    stack = contextlib.AsyncExitStack()
    try:
        agent, process = await stack.enter_async_context(
            spawn_agent_process(
                client,
                *endpoint.command,
                cwd=endpoint.cwd,
                env=endpoint.env,
            )
        )
    except FileNotFoundError as exc:
        raise AcpError("acp_agent_not_found", f"cannot launch {endpoint.describe()}: {exc}")
    except OSError as exc:
        raise AcpError("acp_unreachable", f"cannot launch {endpoint.describe()}: {exc}")
    drain = StderrLogDrain(process)
    session = AcpSession(
        agent,
        client,
        describe=endpoint.describe(),
        stderr_lines=drain.lines,
        teardown=lambda: _close_both(stack, drain),
        process=process,
    )
    return session, process


def spawn_url(endpoint: AcpEndpoint, recorder: TranscriptRecorder) -> AcpSession:
    """Connect to an agent someone else is running, over streamable HTTP.

    The SDK keeps that transport behind its ``http`` extra, so a deployment
    that only evaluates stdio agents never installs it -- and a submission that
    needs it gets named in the failure instead of an ImportError from a library.
    """
    try:
        from acp.http import create_http_stream
    except ImportError as exc:
        raise AcpError(
            "acp_transport_unavailable",
            f"{endpoint.describe()} needs the streamable HTTP transport: "
            "pip install 'agent-client-protocol[http]'",
        ) from exc
    client = EvalAcpClient(recorder)
    transport = create_http_stream(endpoint.url)
    return AcpSession(
        connect_to_agent(client, transport),
        client,
        describe=endpoint.describe(),
        teardown=transport.close,
    )


async def connect(endpoint: AcpEndpoint, recorder: TranscriptRecorder) -> AcpSession:
    """Open the session for *endpoint*, whatever transports it uses.

    The harness calls this instead of picking a transport, so a submission that
    gave a command and one that gave a address follow the same code path from
    here on.
    """
    if endpoint.transport == TRANSPORT_STDIO:
        session, _process = await spawn_command(endpoint, recorder)
        return session
    return spawn_url(endpoint, recorder)


async def _close_both(stack: contextlib.AsyncExitStack, drain: StderrLogDrain) -> None:
    await drain.stop()
    await stack.aclose()


def _allow_option(options: Sequence[Any]) -> Any:
    """The option that unblocks the run for good, or ``None`` if none allows.

    ``allow_always`` before ``allow_once``: an agent that has to ask again for
    every step spends its timeout on the asking, and the score then measures
    our own chattiness instead of its ability.  The request count keeps both
    visible either way.
    """
    listed = [option for option in list(options or []) if getattr(option, "option_id", None)]
    by_kind = {str(getattr(option, "kind", "")): option for option in reversed(listed)}
    for kind in _ALLOW_KINDS:
        if kind in by_kind:
            return by_kind[kind]
    return next(
        (option for option in listed if str(option.kind).startswith("allow")),
        None,
    )


def _dump(model: Any) -> dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dict(dump(by_alias=True, exclude_none=True, mode="json"))
    return dict(model) if isinstance(model, Mapping) else {}


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
