# -*- coding: utf-8 -*-
"""The bridge, end to end: a stdio agent reachable at a URL.

The service only speaks ACP over streamable HTTP, so an agent that only does
stdio -- QwenPaw among them -- needs this seam.  What is proven here is the two
things the seam can get wrong without failing loudly: the connection has to be
usable by the evaluation client's own transport, and a server-to-client message
has to find the connection that opened *that* session, not merely some
connection.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint, connect
from pawbench.cpd.acp_remote_eval.acp.transcript import TranscriptRecorder
from pawbench.cpd.acp_remote_eval.bridge import create_app

FAKE_AGENT = Path(__file__).resolve().parent / "tools" / "fake_acp_agent.py"
HOST = "127.0.0.1"
#: A manifest the fake agent understands: one task, no fixtures to fetch.
PROMPT = '```json\n{"task_id": "t1", "assets": []}\n```\n'


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _wait_until_serving(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex((HOST, port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"the bridge never came up on {HOST}:{port}")


@pytest.fixture()
def bridge() -> Iterator[str]:
    """A bridge serving the fake agent's ``zero`` mode, on a real port.

    ``zero`` returns after streaming its updates and uploads nothing, so the
    test needs no data plane and no fixtures -- only the protocol.
    """
    port = _free_port()
    app = create_app([sys.executable, str(FAKE_AGENT), "--mode", "zero"])
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="pawbench-bridge")
    thread.start()
    _wait_until_serving(port)
    try:
        yield f"http://{HOST}:{port}/acp"
    finally:
        asyncio.run(app.state.bridge_backend.close())
        server.should_exit = True
        thread.join(timeout=10)


def _run(url: str, body: Callable[[Any, TranscriptRecorder], Any]) -> Any:
    async def main() -> Any:
        recorder = TranscriptRecorder()
        session = await connect(AcpEndpoint.http(url), recorder)
        try:
            await asyncio.wait_for(session.initialize(), timeout=30)
            return await body(session, recorder)
        finally:
            await session.close()

    return asyncio.run(main())


def test_a_stdio_agent_answers_the_clients_own_transport(bridge: str) -> None:
    """The evaluation client's HTTP transport is the test: no other caller."""

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        session_id = await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        result = await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return session_id, result, recorder

    session_id, result, recorder = _run(bridge, body)
    assert session_id
    assert result["stop_reason"] == "end_turn"
    # Updates travelled agent -> bridge -> HTTP -> client, in that order.
    assert recorder.update_count >= 2
    assert recorder.counts_by_kind.get("agent_message_chunk", 0) >= 1


def test_a_session_adopted_from_the_caller_still_reaches_the_client(bridge: str) -> None:
    """``session/load`` answers without the id; the route has to come from the ask.

    An agent that honours a caller-chosen session id (QwenPaw does) is how the
    report ends up quoting an id that agent's own console recognises.  The
    bridge used to route only on ``session/new``'s response, so the updates for
    a loaded session had no connection to go to: the run scored normally and
    its transcript was empty, which reads as "the agent said nothing".
    """

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        session_id = await asyncio.wait_for(
            session.new_session(cwd="/tmp", preferred_id="1795156778446-y2r8j2a"),
            timeout=30,
        )
        result = await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return session_id, result, recorder

    session_id, result, recorder = _run(bridge, body)
    assert session_id == "1795156778446-y2r8j2a"
    assert result["stop_reason"] == "end_turn"
    assert recorder.update_count >= 2, "the adopted session's updates went nowhere"


def test_each_connection_receives_only_its_own_session_updates(bridge: str) -> None:
    """Two attempts in flight at once must not read each other's transcript.

    This is what the session->connection map exists for: the backend is one
    process, so a broadcast would look fine in a single-attempt test and leak
    one task's reasoning into another's transcript under concurrency.
    """

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        session_id = await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return session_id, recorder

    first, second = asyncio.run(_both(bridge))
    assert first[0] != second[0]
    assert first[1].update_count > 0
    assert second[1].update_count > 0


async def _both(url: str) -> list[Any]:
    """Two clients, two sessions, one backend, concurrently."""

    async def one() -> Any:
        recorder = TranscriptRecorder()
        session = await connect(AcpEndpoint.http(url), recorder)
        try:
            await session.initialize()
            session_id = await session.new_session(cwd="/tmp")
            await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
            return session_id, recorder
        finally:
            await session.close()

    return await asyncio.gather(one(), one())
