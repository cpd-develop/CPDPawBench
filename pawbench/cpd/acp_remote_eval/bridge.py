# -*- coding: utf-8 -*-
"""``python -m pawbench.cpd.acp_remote_eval.bridge`` -- ACP over a port, two doors.

The service reaches subjects over streamable HTTP only (``AcpEndpoint.http``,
``runtime.http_endpoint``), and that is deliberate: a job row must not carry a
command, or one submitter could run anything on the service host.  But plenty of
agents -- QwenPaw among them -- speak ACP over stdio and nothing else, and the
machine they run on is this one.  This module is the seam for exactly that
case: it spawns the command once, serves ACP over the same streamable HTTP
transport the service already speaks, and multiplexes sessions across
connections.

    python -m pawbench.cpd.acp_remote_eval.bridge \
        --command "qwenpaw acp" --port 8472

Then submit with ``acp_url=http://127.0.0.1:8472/acp``.

``--console`` is the other door, and it exists because the first one leaves no
trace on the agent's own console: a session opened over ``qwenpaw acp`` is
ephemeral (``--runtime-provider`` asks for that), so nothing is registered or
saved on that side -- no chat row, no session file, nothing to click.  Pointed
at a running console instead, each attempt becomes a real conversation there,
under the session id the report quotes (see :mod:`.console_agent`):

    python -m pawbench.cpd.acp_remote_eval.bridge \
        --console http://127.0.0.1:8088 --agent pawbench_eval --port 8472

Two decisions worth stating, because both are the opposite of "just proxy the
bytes":

* **One backend process, many HTTP connections.**  ``qwenpaw acp`` takes seconds
  to bootstrap; spawning one per attempt would spend the task's timeout on
  startup and leave a process behind per connection.  Sessions are multiplexed
  instead, and a server-to-client message is routed by ``session_id`` to the
  connection that created it.
* **The client's capabilities are passed through, not invented.**  What the
  backend may ask for (permissions, file reads, terminals) follows from the
  ``initialize`` the real client sent; this module never claims a capability on
  the client's behalf.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shlex
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from acp.interfaces import Agent, Client

#: The path the service's own client appends to whatever base URL it is given.
DEFAULT_PATH = "/acp"

#: Calls that decide which connection receives a session's updates.  A turn is
#: delivered to the connection that asked for it; the ``session/*`` calls that
#: open one name their connection in their response instead.
_ROUTING_CALLS = frozenset({"prompt"})

_log = logging.getLogger("pawbench.bridge")


class _Backend:
    """The one child process every HTTP connection shares."""

    def __init__(
        self, command: Sequence[str], *, cwd: str | None, env: Mapping[str, str] | None
    ) -> None:
        self._command = tuple(command)
        self._cwd = cwd
        self._env = dict(env) if env else None
        self._stack: contextlib.AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._connection: Any = None
        self._sessions: dict[str, Any] = {}

    @property
    def command(self) -> tuple[str, ...]:
        return self._command

    def route(self, session_id: str, connection: Any) -> None:
        """Remember which HTTP connection owns *session_id*."""
        self._sessions[session_id] = connection
        _log.debug("session %s -> connection %s", session_id, id(connection))

    def owner(self, session_id: str) -> Any:
        return self._sessions.get(session_id)

    async def connection(self) -> Any:
        if self._connection is not None:
            return self._connection
        async with self._lock:
            if self._connection is None:
                self._connection = await self._spawn()
        return self._connection

    async def _spawn(self) -> Any:
        from acp import spawn_agent_process

        stack = contextlib.AsyncExitStack()
        _log.debug("spawning %s", " ".join(self._command))
        try:
            connection, _process = await stack.enter_async_context(
                spawn_agent_process(
                    _Router(self),
                    *self._command,
                    cwd=self._cwd,
                    env=self._env,
                    # The agent's own stderr is inherited, not piped: a piped
                    # stderr with nobody reading it deadlocks the child the
                    # moment a debug build logs a few lines, and the reason a
                    # prompt failed is usually in exactly those lines.
                    transport_kwargs={"stderr": None},
                )
            )
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        return connection

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._connection = None
        if stack is not None:
            with contextlib.suppress(Exception):
                await stack.aclose()


class _Router(Client):
    """The client half of the child connection: forwards to the owning peer.

    The backend calls these when it wants something *from the client* -- a
    permission decision, a streamed update.  Each one finds the HTTP connection
    that opened the session and asks it, so the real client's answers (and its
    capability declarations) are what the backend sees.
    """

    def __init__(self, backend: _Backend) -> None:
        self._backend = backend

    async def _peer(self, session_id: str, what: str) -> Any:
        peer = self._backend.owner(session_id)
        if peer is None:
            # Normal at the end of an attempt: the client closed the connection
            # while the backend was still finishing a turn.  Dropping the update
            # beats turning a late notification into a failed request.
            _log.debug("dropping %s for %s: no connection holds it", what, session_id)
        return peer

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        peer = await self._peer(session_id, "session_update")
        if peer is not None:
            await peer.session_update(session_id, update, **kwargs)

    async def request_permission(
        self, session_id: str, tool_call: Any, options: Any, **kwargs: Any
    ) -> Any:
        peer = await self._peer(session_id, "request_permission")
        if peer is not None:
            return await peer.request_permission(session_id, tool_call, options, **kwargs)
        return None

    async def read_text_file(self, session_id: str, path: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "read_text_file")
        return await peer.read_text_file(session_id, path, **kwargs)

    async def write_text_file(self, session_id: str, path: str, content: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "write_text_file")
        return await peer.write_text_file(session_id, path, content, **kwargs)

    async def create_terminal(self, session_id: str, command: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "create_terminal")
        return await peer.create_terminal(session_id, command, **kwargs)

    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "terminal_output")
        return await peer.terminal_output(session_id, terminal_id, **kwargs)

    async def wait_for_terminal_exit(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "wait_for_terminal_exit")
        return await peer.wait_for_terminal_exit(session_id, terminal_id, **kwargs)

    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "release_terminal")
        return await peer.release_terminal(session_id, terminal_id, **kwargs)

    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> Any:
        peer = self._require(session_id, "kill_terminal")
        return await peer.kill_terminal(session_id, terminal_id, **kwargs)

    def _require(self, session_id: str, what: str) -> Any:
        """The peer, for calls that cannot be answered without one.

        A streamed update after the client closed is normal and gets dropped;
        a file read is not, and answering it falsely would put words in the
        client's mouth.
        """
        peer = self._backend.owner(session_id)
        if peer is None:
            from acp.exceptions import RequestError

            raise RequestError.method_not_found(what)
        return peer


class _Proxy:
    """The agent the HTTP transport talks to: every call goes to the backend.

    Methods are declared one by one rather than generated, because the SDK maps
    wire methods to attributes by reading the ``Agent`` protocol
    (``build_agent_router``), and names outside that protocol are never routed.
    The four the evaluation client actually sends are implemented for real; the
    rest forward, and anything the protocol grows that the backend lacks answers
    ``method_not_found`` instead of hanging.
    """

    def __init__(self, backend: _Backend, connection: Any) -> None:
        self._backend = backend
        self._connection = connection

    def on_connect(self, connection: Any) -> None:
        self._connection = connection

    async def _call(self, name: str, **kwargs: Any) -> Any:
        # The stdio lane's backend is a *process*: reaching it is an await.
        # The console lane's backend is the console itself, which is already
        # reachable, so the same call has nothing to wait for.
        backend = self._backend
        reach = getattr(backend, "connection", None)
        if callable(reach):
            backend = await reach()
        # A turn belongs to the connection that asked for it.  Routing only on
        # ``session/new`` was enough while a session lived exactly one turn; the
        # console lane lets go of a session's connection when its turn ends (so a
        # long-lived bridge does not hold every closed ASGI connection alive), and
        # this is what re-establishes it.  Cancel is deliberately not routed: the
        # connection that drives the turn is the one that must keep receiving
        # updates, and a cancel often arrives over a second one.  Note this goes
        # to the *bridge* backend, not to the resolved one -- on the stdio lane
        # that resolves to the child process, which knows nothing of HTTP peers.
        session_id = kwargs.get("session_id")
        route = getattr(self._backend, "route", None)
        if session_id and name in _ROUTING_CALLS and callable(route):
            route(str(session_id), self._connection)
        method = getattr(backend, name, None)
        if method is None:
            from acp.exceptions import RequestError

            raise RequestError.method_not_found(name)
        _log.debug("-> %s", name)
        return await method(**kwargs)

    async def _call_and_route(self, name: str, **kwargs: Any) -> Any:
        response = await self._call(name, **kwargs)
        # ``session/new`` names the session in its response; ``session/load``
        # (and resume) are given the id and answer without it.  Reading only the
        # response leaves those sessions unrouted, and every update the agent
        # then sends is dropped as "no connection holds it" -- a run that scores
        # fine and produces an empty transcript, which reads like the agent said
        # nothing.
        session_id = getattr(response, "session_id", None) or kwargs.get("session_id")
        if session_id:
            self._backend.route(str(session_id), self._connection)
        else:
            _log.debug("%s answered %r without a session id", name, type(response).__name__)
        return response

    async def initialize(self, **kwargs: Any) -> Any:
        return await self._call("initialize", **kwargs)

    async def new_session(self, **kwargs: Any) -> Any:
        return await self._call_and_route("new_session", **kwargs)

    async def load_session(self, **kwargs: Any) -> Any:
        return await self._call_and_route("load_session", **kwargs)

    async def resume_session(self, **kwargs: Any) -> Any:
        return await self._call_and_route("resume_session", **kwargs)

    async def prompt(self, **kwargs: Any) -> Any:
        return await self._call("prompt", **kwargs)

    async def cancel(self, **kwargs: Any) -> Any:
        return await self._call("cancel", **kwargs)

    async def close_session(self, **kwargs: Any) -> Any:
        return await self._call("close_session", **kwargs)

    async def list_sessions(self, **kwargs: Any) -> Any:
        return await self._call("list_sessions", **kwargs)

    async def set_session_model(self, **kwargs: Any) -> Any:
        return await self._call("set_session_model", **kwargs)

    async def set_config_option(self, **kwargs: Any) -> Any:
        return await self._call("set_config_option", **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        async def _missing(**kwargs: Any) -> Any:
            return await self._call(name, **kwargs)

        return _missing


def _close_with_the_server(app: Any, backend: Any) -> Any:
    """Release the backend when the ASGI app shuts down.

    ``create_asgi_app`` installs its own lifespan (it closes the ACP server), and
    Starlette runs exactly one, so this composes around it rather than adding a
    second.  Without it, ``main`` returning leaves a shared ``AsyncClient`` and
    -- on the stdio lane -- a child process with nothing to stop it.
    """
    inner = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(scope: Any) -> Any:
        async with inner(scope) as state:
            try:
                yield state
            finally:
                with contextlib.suppress(Exception):
                    await backend.close()

    app.router.lifespan_context = lifespan
    return app


def create_app(command: Sequence[str], *, cwd: str | None = None, path: str = DEFAULT_PATH) -> Any:
    """The ASGI app, so a test can drive it without a port."""
    from acp.http.asgi import create_asgi_app

    backend = _Backend(command, cwd=cwd, env=None)
    app = create_asgi_app(lambda connection: _Proxy(backend, connection), path=path)
    app.state.bridge_backend = backend
    return _close_with_the_server(app, backend)


def create_console_app(
    base_url: str,
    *,
    agent: str | None = None,
    path: str = DEFAULT_PATH,
    client: Any = None,
) -> Any:
    """The same seam, with a running QwenPaw console behind it instead of a child.

    Two doors, one protocol. The stdio door is right for an agent that keeps no
    history of its own; the console door is right when the person who owns the
    agent wants to watch the run on the agent's own page, because the console is
    what registers and stores the conversation (see
    :mod:`...console_agent` for why the stdio lane cannot do that).
    """
    from acp.http.asgi import create_asgi_app

    from .console_agent import ConsoleAgent

    backend = ConsoleAgent(base_url, agent=agent, client=client)
    app = create_asgi_app(lambda connection: _Proxy(backend, connection), path=path)
    app.state.bridge_backend = backend
    return _close_with_the_server(app, backend)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pawbench.cpd.acp_remote_eval.bridge",
        description=(
            "Serve an agent over the streamable HTTP transport the service speaks: "
            "either a stdio command (--command) or a running QwenPaw console (--console)."
        ),
    )
    door = parser.add_mutually_exclusive_group(required=True)
    door.add_argument(
        "--command",
        help='the agent, as one shell-quoted line, e.g. "qwenpaw acp --agent default"',
    )
    door.add_argument(
        "--console",
        metavar="URL",
        help=(
            "a running QwenPaw console, e.g. http://127.0.0.1:8088 . Turns are posted to "
            "its /api/console/chat, so each evaluation attempt appears on that console's "
            "own chat list, with its history, under the session id the report quotes."
        ),
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="which agent the console should answer as (sent as X-Agent-Id)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default loopback only)")
    parser.add_argument("--port", type=int, default=8472, help="port to listen on")
    parser.add_argument("--path", default=DEFAULT_PATH, help="ACP path (default /acp)")
    parser.add_argument("--cwd", default=None, help="working directory for the agent")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="log every forwarded call and every session->connection binding",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.agent and args.command:
        print("error: --agent only applies to --console", file=sys.stderr)
        return 2
    command = shlex.split(args.command) if args.command else []
    if args.command and not command:
        print("error: --command is empty", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        import uvicorn
    except ImportError:
        print("error: the bridge needs uvicorn: pip install uvicorn", file=sys.stderr)
        return 1

    if args.console:
        app = create_console_app(args.console, agent=args.agent, path=args.path)
        target = f"{args.console} (console, agent={args.agent or 'active'})"
    else:
        app = create_app(command, cwd=args.cwd, path=args.path)
        target = command[0]
    print(
        f"serving {target} over ACP/HTTP on http://{args.host}:{args.port}{args.path}",
        file=sys.stderr,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


__all__ = ["Agent", "create_app", "create_console_app", "main"]


if __name__ == "__main__":
    if os.environ.get("PAWBENCH_BRIDGE_DEBUG"):
        os.environ.setdefault("PYTHONASYNCIODEBUG", "1")
    sys.exit(main())
