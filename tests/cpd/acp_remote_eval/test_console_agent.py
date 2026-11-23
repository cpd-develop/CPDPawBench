# -*- coding: utf-8 -*-
"""The console lane: an evaluation attempt that the agent's own console can show.

The stdio lane cannot do this, and that is not a bug in it -- ``qwenpaw acp``
runs ephemeral, so the session-save hook returns before writing anything and the
console has neither a chat row nor a history file to offer. Posting the turn to
the console's own chat route instead is what puts the run where the person who
owns the agent is already looking.

What is proven here is the translation, and the things it can get wrong quietly:
the session id the console files the chat under has to be the one the report
quotes; a tool call has to arrive as a call *and* a result rather than as one
indistinguishable blob of text; an answer that streamed as deltas must not be
sent twice because the console's closing row carries no message id; and a turn
the console failed has to fail the attempt instead of scoring an empty answer.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from acp import RequestError

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint, connect
from pawbench.cpd.acp_remote_eval.acp.transcript import TranscriptRecorder
from pawbench.cpd.acp_remote_eval.bridge import create_console_app
from pawbench.cpd.acp_remote_eval.console_agent import (
    ConsoleAgent,
    ConsoleError,
    chat_title,
)

HOST = "127.0.0.1"
PROMPT = "数一下工作目录里有多少个文件，只回答数字。"
ANSWER = "3 个"


# ── a console, small enough to read ───────────────────────────────────────────


def _sse(rows: list[dict[str, Any]]) -> bytes:
    return "".join(f"data: {json.dumps(row, ensure_ascii=False)}\n\n" for row in rows).encode()


def _turn_rows(session_id: str = "", *, with_tool: bool = False) -> list[dict[str, Any]]:
    """One console turn, in the shape ``POST /api/console/chat`` streams it."""
    rows: list[dict[str, Any]] = [
        {"object": "response", "status": "created", "session_id": session_id, "sequence_number": 1},
        {"object": "message", "id": "msg_a", "type": "message", "role": "assistant", "status": "in_progress"},
        {"object": "content", "type": "text", "delta": True, "msg_id": "msg_a", "text": ANSWER},
        # The closing row repeats the whole text and names no message -- which
        # is exactly the shape that used to send every answer twice.
        {"object": "content", "type": "text", "delta": False, "msg_id": None, "text": ANSWER},
    ]
    if with_tool:
        rows += [
            {"object": "message", "id": "msg_call", "type": "plugin_call", "role": "assistant", "status": "in_progress"},
            {
                "object": "content",
                "type": "data",
                "delta": True,
                "msg_id": "msg_call",
                "data": {"call_id": "call-1", "name": "execute_shell_command", "arguments": ""},
                "status": "in_progress",
            },
            {
                "object": "content",
                "type": "data",
                "delta": False,
                "msg_id": None,
                "data": {
                    "call_id": "call-1",
                    "name": "execute_shell_command",
                    "arguments": json.dumps({"command": "ls | wc -l"}),
                },
                "status": "completed",
            },
            {
                "object": "message",
                "id": "msg_out",
                "type": "plugin_call_output",
                "role": "tool",
                "status": "in_progress",
            },
            {
                "object": "content",
                "type": "data",
                "delta": False,
                "msg_id": None,
                "data": {"call_id": "call-1", "name": "execute_shell_command", "output": "3", "state": "success"},
                "status": "completed",
            },
        ]
    rows += [
        {"type": "turn_usage", "session_id": session_id, "usage": {"prompt_tokens": 1200, "completion_tokens": 9}},
        {
            "object": "response",
            "status": "completed",
            "session_id": session_id,
            "output": [],
            "sequence_number": 99,
        },
    ]
    return rows


def _bare_tool_rows(session_id: str = "") -> list[dict[str, Any]]:
    """A tool call from a console that omits ``delta`` and ``status`` entirely.

    Both fields are how the console *usually* marks a finished call, and an
    earlier version of this lane required both -- so a console that left either
    out lost the call silently, leaving only its result in the transcript.
    """
    return [
        {"object": "response", "status": "created", "session_id": session_id},
        {
            "object": "content",
            "type": "data",
            "data": {"call_id": "call-9", "name": "read_file", "arguments": {"path": "a.txt"}},
        },
        {
            "object": "content",
            "type": "data",
            "data": {"call_id": "call-9", "output": "hello", "state": "success"},
        },
        {"object": "content", "type": "text", "text": "读完了"},
        {"object": "response", "status": "completed", "session_id": session_id},
    ]


class FakeConsole:
    """The console routes this lane uses, with their bodies kept for assertion."""

    def __init__(
        self,
        *,
        with_tool: bool = False,
        chat_id: str = "chat-1",
        rows: Callable[[str], list[dict[str, Any]]] | None = None,
        content_type: str = "text/event-stream",
        body: bytes | None = None,
        stall: bool = False,
        stop_payload: dict[str, Any] | None = None,
    ) -> None:
        self.with_tool = with_tool
        self.chat_id = chat_id
        self.rows = rows
        self.content_type = content_type
        self.body = body
        self.stall = stall
        self.stop_payload = {"stopped": True} if stop_payload is None else stop_payload
        self.turns: list[dict[str, Any]] = []
        self.stops: list[str] = []
        self.renames: list[dict[str, Any]] = []
        self.listed = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/console/chat"):
            body = json.loads(request.content.decode())
            self.turns.append(body)
            return self._stream(body.get("session_id", ""))
        if path.endswith("/console/chat/stop"):
            self.stops.append(request.url.params.get("chat_id", ""))
            return httpx.Response(200, json=self.stop_payload)
        if path.endswith("/chats") and request.method == "GET":
            self.listed += 1
            return httpx.Response(
                200,
                json=[
                    {"id": "other", "session_id": "1795000000000-other00", "channel": "console"},
                    {"id": self.chat_id, "session_id": self._session_of_interest, "channel": "console"},
                ],
            )
        if "/chats/" in path and request.method == "PUT":
            self.renames.append({"path": path, "body": json.loads(request.content.decode())})
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "unexpected", "path": path})

    def _stream(self, session_id: str) -> httpx.Response:
        headers = {"content-type": self.content_type}
        rows = (
            self.rows(session_id)
            if self.rows is not None
            else _turn_rows(session_id, with_tool=self.with_tool)
        )
        if self.stall:
            return httpx.Response(200, headers=headers, content=self._quiet_after(rows[:2]))
        if self.body is not None:
            return httpx.Response(200, headers=headers, content=self.body)
        return httpx.Response(200, headers=headers, content=_sse(rows))

    async def _quiet_after(self, rows: list[dict[str, Any]]) -> Any:
        """Two events, then silence -- a console whose run died holding the socket."""
        for row in rows:
            yield _sse([row])
        await asyncio.sleep(30)

    _session_of_interest = ""

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://console.test/api",
            transport=httpx.MockTransport(self.handler),
            timeout=httpx.Timeout(connect=5, read=None, write=5, pool=5),
        )


class _Sink:
    """A client connection that accepts updates and remembers them."""

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.updates: list[Any] = []

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if self.broken:
            raise RuntimeError("the client is gone")
        self.updates.append(update)


# ── the ASGI bridge, on a real port ───────────────────────────────────────────


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
def console_bridge() -> Iterator[tuple[str, FakeConsole]]:
    fake = FakeConsole()
    port = _free_port()
    app = create_console_app("http://console.test", agent="pawbench_eval", client=fake.client())
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="pawbench-console-bridge")
    thread.start()
    _wait_until_serving(port)
    try:
        yield f"http://{HOST}:{port}/acp", fake
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


def _texts(recorder: TranscriptRecorder) -> list[str]:
    return [
        block.get("text", "")
        for event in recorder.events
        for block in (event.get("message") or {}).get("content") or []
        if block.get("type") == "text"
    ]


def _turn(url: str, fake: FakeConsole, *, session_id: str = "1795156778446-y2r8j2a") -> None:
    fake._session_of_interest = session_id

    async def body(session: Any, recorder: TranscriptRecorder) -> None:
        await asyncio.wait_for(session.new_session(cwd="/tmp", preferred_id=session_id), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)

    _run(url, body)


# ── what the console files, and what reaches the client ───────────────────────


def test_an_attempt_files_itself_under_the_id_the_report_quotes(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    url, fake = console_bridge
    minted = "1795156778446-y2r8j2a"
    fake._session_of_interest = minted

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        session_id = await asyncio.wait_for(session.new_session(cwd="/tmp", preferred_id=minted), timeout=30)
        result = await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return session_id, result, recorder

    session_id, result, recorder = _run(url, body)
    assert session_id == minted
    assert result["stop_reason"] == "end_turn"
    # The console is told to file the turn under that id, for the default user,
    # on the console channel -- the three fields its chat list filters on.
    assert len(fake.turns) == 1
    body_sent = fake.turns[0]
    assert body_sent["session_id"] == minted
    assert body_sent["channel"] == "console"
    assert body_sent["user_id"] == "default"
    assert body_sent["input"][0]["content"][0]["text"] == PROMPT
    # And the words reached the client, whichever route the console took.
    assert any(ANSWER in text for text in _texts(recorder))


def test_the_answer_is_sent_once_even_when_the_closing_row_names_no_message(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """Deltas and the closing full text are one message, not two.

    ``_turn_rows`` streams ``msg_a`` and then repeats the whole answer with
    ``msg_id: null``, which is what the real console does. Keying dedup on the
    payload's string made those two different messages, so the transcript -- and
    therefore the judge -- read every answer twice.
    """
    url, fake = console_bridge
    recorder_holder: list[TranscriptRecorder] = []

    async def body(session: Any, recorder: TranscriptRecorder) -> None:
        await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        recorder_holder.append(recorder)

    _run(url, body)
    texts = _texts(recorder_holder[0])
    assert texts.count(ANSWER) == 1, texts


def test_a_tool_call_arrives_as_a_call_and_a_result(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    url, fake = console_bridge
    fake.with_tool = True
    fake._session_of_interest = "1795156778447-abc1234"

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return recorder

    recorder = _run(url, body)
    calls = [
        block
        for event in recorder.events
        for block in (event.get("message") or {}).get("content") or []
        if block.get("type") == "toolCall"
    ]
    assert calls, "the tool call never became a toolCall block"
    assert calls[0]["name"] == "execute_shell_command"
    assert calls[0]["arguments"] == {"command": "ls | wc -l"}
    results = [
        block
        for event in recorder.events
        if (event.get("message") or {}).get("role") == "toolResult"
        for block in (event.get("message") or {}).get("content") or []
    ]
    assert results and results[0]["text"] == "3"


def test_a_tool_call_survives_a_console_that_omits_delta_and_status(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """A field the console does not promise must not be able to hide a tool call."""
    url, fake = console_bridge
    fake.rows = _bare_tool_rows
    fake._session_of_interest = "1795156778451-mno7890"

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return recorder

    recorder = _run(url, body)
    calls = [
        block
        for event in recorder.events
        for block in (event.get("message") or {}).get("content") or []
        if block.get("type") == "toolCall"
    ]
    results = [
        block
        for event in recorder.events
        if (event.get("message") or {}).get("role") == "toolResult"
        for block in (event.get("message") or {}).get("content") or []
    ]
    assert calls and calls[0]["arguments"] == {"path": "a.txt"}
    assert results and results[0]["text"] == "hello"


def test_a_refusal_reaches_the_transcript_as_the_words_it_was(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """A refusal is the model's answer about the task; a ``[refusal]`` marker is not."""
    url, fake = console_bridge

    def rows(session_id: str) -> list[dict[str, Any]]:
        return [
            {"object": "response", "status": "created", "session_id": session_id},
            {"object": "message", "id": "msg_r", "type": "message", "role": "assistant"},
            {"object": "content", "type": "refusal", "msg_id": "msg_r", "text": "这个我不能做"},
            {"object": "response", "status": "completed", "session_id": session_id},
        ]

    fake.rows = rows
    fake._session_of_interest = "1795156778452-pqr1234"

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        await asyncio.wait_for(session.new_session(cwd="/tmp"), timeout=30)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return recorder

    recorder = _run(url, body)
    assert "这个我不能做" in _texts(recorder)


def test_a_second_turn_on_one_session_still_reaches_its_client(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """The lane lets go of a session's connection when a turn ends; the next turn
    has to get it back, or the second answer is streamed to nobody."""
    url, fake = console_bridge

    async def body(session: Any, recorder: TranscriptRecorder) -> Any:
        await asyncio.wait_for(
            session.new_session(cwd="/tmp", preferred_id="1795156778453-stu5678"), timeout=30
        )
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        await asyncio.wait_for(session.prompt(PROMPT), timeout=60)
        return recorder

    recorder = _run(url, body)
    assert _texts(recorder).count(ANSWER) == 2


# ── the ways a turn can end without an answer ─────────────────────────────────


def _details(exc: Exception) -> str:
    data = getattr(exc, "data", None)
    return str(data.get("details") if isinstance(data, dict) else data)


def test_a_stream_error_is_a_failed_attempt_not_an_empty_answer(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """``console.py`` reports a broken stream as ``data: {"error": ...}``."""
    url, fake = console_bridge

    def rows(session_id: str) -> list[dict[str, Any]]:
        return [
            {"object": "response", "status": "created", "session_id": session_id},
            {"error": "the model refused to answer"},
        ]

    fake.rows = rows

    with pytest.raises(RequestError) as caught:
        _turn(url, fake)
    assert "reported an error" in _details(caught.value)


def test_a_turn_that_says_nothing_is_a_failed_attempt(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    url, fake = console_bridge
    fake.rows = lambda session_id: [
        {"object": "response", "status": "created", "session_id": session_id},
        {"object": "response", "status": "completed", "session_id": session_id},
    ]

    with pytest.raises(RequestError) as caught:
        _turn(url, fake)
    assert "streamed no content" in _details(caught.value)


def test_a_200_that_is_not_an_event_stream_is_a_failed_attempt(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    """A proxy that answers JSON with a 200 used to read as a finished turn."""
    url, fake = console_bridge
    fake.content_type = "application/json"
    fake.body = b'{"detail": "not here"}'

    with pytest.raises(RequestError) as caught:
        _turn(url, fake)
    assert "event stream was required" in _details(caught.value)


def test_a_failed_run_is_not_reported_as_a_finished_turn(
    console_bridge: tuple[str, FakeConsole],
) -> None:
    url, fake = console_bridge
    fake.rows = lambda session_id: [
        {"object": "response", "status": "created", "session_id": session_id},
        {"object": "content", "type": "text", "delta": True, "msg_id": "m", "text": "半句"},
        {"object": "response", "status": "failed", "session_id": session_id},
    ]

    with pytest.raises(RequestError) as caught:
        _turn(url, fake)
    assert "as failed" in _details(caught.value)


def test_a_console_that_goes_quiet_fails_the_turn_instead_of_hanging() -> None:
    fake = FakeConsole(stall=True)
    agent = ConsoleAgent("http://console.test", client=fake.client(), idle_timeout=0.2)
    agent.route("1795156778454-vwx9012", _Sink())

    with pytest.raises(ConsoleError) as caught:
        asyncio.run(agent.prompt([{"text": PROMPT}], session_id="1795156778454-vwx9012"))
    assert caught.value.code == "console_stalled"


# ── stopping, and letting go ──────────────────────────────────────────────────


def test_a_cancelled_turn_stops_the_console_run(console_bridge: tuple[str, FakeConsole]) -> None:
    """Closing the session mid-turn has to tell the console, or the run continues."""
    url, fake = console_bridge
    session_id = "1795156778448-def5678"
    fake._session_of_interest = session_id

    async def main() -> None:
        recorder = TranscriptRecorder()
        session = await connect(AcpEndpoint.http(url), recorder)
        try:
            await session.initialize()
            await session.new_session(cwd="/tmp", preferred_id=session_id)
            await session.cancel()
        finally:
            await session.close()

    asyncio.run(main())
    # ``close`` asks again -- harmless, and the console treats a second stop as
    # a no-op -- so what matters is that the run's own chat is named every time.
    assert fake.stops and set(fake.stops) == {session_id}
    # And the stop route resolves a session id itself, so no chat listing: that
    # listing was a full unfiltered ``GET /api/chats`` on the cancel path, which
    # has a five-second budget from the harness.
    assert fake.listed == 0


def test_a_finished_turn_lets_go_of_the_client_connection() -> None:
    """A bridge outlives its attempts: holding each closed connection is a leak.

    Releasing it is only safe because the bridge routes a session to the
    connection that asks for the *next* turn; ``test_a_second_turn_on_one_session``
    is the other half of that pair.
    """
    fake = FakeConsole()
    session_id = "1795156778458-hij5678"
    sink = _Sink()
    agent = ConsoleAgent("http://console.test", client=fake.client(), rename_chats=False)
    agent.route(session_id, sink)

    asyncio.run(agent.prompt([{"text": PROMPT}], session_id=session_id))
    assert sink.updates, "the turn produced nothing to release"
    assert agent.owner(session_id) is None


def test_a_client_that_stops_reading_stops_the_console_run() -> None:
    fake = FakeConsole()
    session_id = "1795156778455-yza3456"
    agent = ConsoleAgent("http://console.test", client=fake.client(), rename_chats=False)
    agent.route(session_id, _Sink(broken=True))

    with pytest.raises(ConsoleError) as caught:
        asyncio.run(agent.prompt([{"text": PROMPT}], session_id=session_id))
    assert caught.value.code == "console_client_gone"
    assert fake.stops == [session_id]


def test_a_stop_the_console_did_not_perform_is_logged_as_such(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``stopped: false`` means the run is still going; saying "stopped" would lie."""
    import logging as _logging

    fake = FakeConsole(stop_payload={"stopped": False})
    agent = ConsoleAgent("http://console.test", client=fake.client())

    with caplog.at_level(_logging.WARNING, logger="pawbench.cpd.acp_remote_eval.console_agent"):
        asyncio.run(agent.cancel("1795156778456-bcd7890"))
    assert "no run to stop" in caplog.text


def test_the_turn_summary_is_readable_in_a_plain_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bridge logs ``%(message)s``, so a field in ``extra`` is never printed.

    Asking "which attempt, and did it die quietly" is what this line is for; the
    numbers have to be in the text or the line answers nothing.
    """
    import logging as _logging

    fake = FakeConsole()
    session_id = "1795156778459-klm6789"
    agent = ConsoleAgent("http://console.test", client=fake.client(), rename_chats=False)
    agent.route(session_id, _Sink())

    with caplog.at_level(_logging.INFO, logger="pawbench.cpd.acp_remote_eval.console_agent"):
        asyncio.run(agent.prompt([{"text": PROMPT}], session_id=session_id))
    assert f"session={session_id}" in caplog.text
    assert "updates=" in caplog.text and "tokens=1209" in caplog.text


class _StopResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, Any]:
        return {"stopped": True}


class _SlowStopClient:
    """A client whose stop request only lands when the test lets it.

    Real ones behave like this more often than not: the cancel arrives, and the
    client closes its connection before the stop has connected. The stop has to
    survive that, or the run keeps going with nobody left to ask.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stops: list[str] = []

    async def post(self, route: str, params: Any = None, timeout: Any = None) -> _StopResponse:
        target = (params or {}).get("chat_id", "")
        self.started.set()
        await self.release.wait()
        self.stops.append(target)
        return _StopResponse()


def test_a_cancel_that_loses_its_client_still_stops_the_console_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Found on a real bridge: the stop's ``connect_tcp`` came back cancelled.

    The log said nothing, the harness said "cancelled", and the console kept
    writing. The stop now runs in its own task and is shielded from the cancel
    that asked for it.
    """
    import logging as _logging

    client = _SlowStopClient()
    agent = ConsoleAgent("http://console.test", client=client)  # type: ignore[arg-type]
    session_id = "1795156778460-nop1234"

    async def main() -> None:
        task = asyncio.ensure_future(agent.cancel(session_id))
        await asyncio.wait_for(client.started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        client.release.set()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if client.stops:
                return

    with caplog.at_level(_logging.WARNING, logger="pawbench.cpd.acp_remote_eval.console_agent"):
        asyncio.run(main())
    assert client.stops == [session_id]
    assert "in flight" in caplog.text


def test_two_callers_asking_to_stop_share_one_request() -> None:
    """The harness cancels twice: the notification, and the prompt task it kills."""
    client = _SlowStopClient()
    agent = ConsoleAgent("http://console.test", client=client)  # type: ignore[arg-type]
    session_id = "1795156778461-qrs5678"

    async def main() -> None:
        first = asyncio.ensure_future(agent.cancel(session_id))
        await asyncio.wait_for(client.started.wait(), timeout=5)
        second = asyncio.ensure_future(agent.cancel(session_id))
        await asyncio.sleep(0)
        client.release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

    asyncio.run(main())
    assert client.stops == [session_id]


def test_a_closed_agent_does_not_open_another_connection() -> None:
    agent = ConsoleAgent("http://console.test")
    asyncio.run(agent.close())

    with pytest.raises(ConsoleError) as caught:
        agent.client
    assert caught.value.code == "console_closed"


def test_a_busy_session_is_told_so_instead_of_racing_itself() -> None:
    """The console answers 409 for a second turn; saying it here is clearer."""
    fake = FakeConsole()
    session_id = "1795156778457-efg1234"
    agent = ConsoleAgent("http://console.test", client=fake.client(), rename_chats=False)
    state = agent._remember(session_id, "")  # noqa: SLF001 - the flag a live turn sets
    state.running = True

    with pytest.raises(ConsoleError) as caught:
        asyncio.run(agent.prompt([{"text": PROMPT}], session_id=session_id))
    assert caught.value.code == "console_session_busy"
    assert fake.turns == []


# ── the pieces that are easier to check directly ──────────────────────────────


def test_the_chat_is_named_after_the_attempt_it_belongs_to() -> None:
    cwd = "/tmp/exchange/jobs/job-6fd8674e4c709823/T097_pinbench_eli5_model_summary/attempt-2/session"
    assert chat_title(cwd) == "T097_pinbench_eli5_model_summary · job-6fd8674e4c709823（第 2 次）"


def test_a_working_directory_that_is_not_an_attempt_is_left_alone() -> None:
    """Renaming someone's own project chat after path fragments would be rude."""
    assert chat_title("/Users/anderson/work/notes") == ""
    assert chat_title("") == ""


def test_the_prompt_carries_the_fixture_links_the_manifest_points_at() -> None:
    """A link the agent cannot see is a fixture it cannot read."""
    agent = ConsoleAgent("http://console.test", client=FakeConsole().client())

    class Block:
        def __init__(self, text: str = "", uri: str = "") -> None:
            self.text = text
            self.uri = uri

    from pawbench.cpd.acp_remote_eval.console_agent import _prompt_text

    text = _prompt_text([Block(text="做这件事"), Block(uri="http://127.0.0.1:8471/f/a.txt")])
    assert text.startswith("做这件事")
    assert "http://127.0.0.1:8471/f/a.txt" in text
    assert agent.base_url == "http://console.test/api"
