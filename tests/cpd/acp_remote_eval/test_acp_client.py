# -*- coding: utf-8 -*-
"""The ACP client half: what we accept, what we refuse, and what we hand back.

These are the behaviours an evaluation depends on and an editor never had to
think about -- nobody is there to answer a permission prompt, the subject's
stderr must not become our memory, and a program that does not exist must cost
milliseconds rather than the task timeout.  Everything here runs against a stub
agent object; the wire itself is proven by ``test_runner_e2e.py``, which spawns
the fake agent as a real process.
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any

import pytest
from acp import RequestError
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
)

from pawbench.cpd.acp_remote_eval.acp import client
from pawbench.cpd.acp_remote_eval.acp.client import (
    AcpEndpoint,
    AcpError,
    AcpSession,
    EvalAcpClient,
    StderrLogDrain,
    _STDERR_TAIL_LINES,
    _allow_option,
    connect,
    mint_session_id,
    spawn_command,
    spawn_url,
)
from pawbench.cpd.acp_remote_eval.acp.transcript import TranscriptRecorder


class StubAgent:
    """The agent side of the four calls :class:`AcpSession` makes."""

    def __init__(
        self,
        *,
        session_id: str = "sess-1",
        new_session_response: Any = None,
        stop_reason: str = "end_turn",
        can_load: bool = True,
        load_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.session_id = session_id
        self.new_session_response = new_session_response
        self.stop_reason = stop_reason
        self.can_load = can_load
        self.load_error = load_error
        self.canceled = ""

    async def initialize(self, **kwargs: Any) -> InitializeResponse:
        self.calls.append(("initialize", kwargs))
        return InitializeResponse(
            protocol_version=kwargs.get("protocol_version", 1),
            agent_capabilities={"loadSession": self.can_load},
            agent_info={"name": "stub", "version": "9"},
        )

    async def load_session(self, **kwargs: Any) -> Any:
        self.calls.append(("load_session", kwargs))
        if self.load_error is not None:
            raise self.load_error
        return {}

    async def new_session(self, **kwargs: Any) -> Any:
        self.calls.append(("new_session", kwargs))
        if self.new_session_response is not None:
            return self.new_session_response
        return NewSessionResponse(session_id=self.session_id)

    async def prompt(self, **kwargs: Any) -> PromptResponse:
        self.calls.append(("prompt", kwargs))
        return PromptResponse(stop_reason=self.stop_reason)

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self.canceled = session_id


def _session(agent: Any = None, **kwargs: Any) -> AcpSession:
    return AcpSession(
        agent if agent is not None else StubAgent(), EvalAcpClient(TranscriptRecorder()), **kwargs
    )


def _options(*kinds: str) -> list[PermissionOption]:
    return [
        PermissionOption(option_id=f"opt-{index}", name=kind, kind=kind)
        for index, kind in enumerate(kinds)
    ]


# ── endpoint validation ───────────────────────────────────────────────────────


def test_a_stdio_endpoint_needs_a_program() -> None:
    for command in ([], [""], ["   "]):
        with pytest.raises(AcpError) as caught:
            AcpEndpoint.stdio(command)
        assert caught.value.code == "acp_command_empty"


def test_an_http_endpoint_only_takes_http() -> None:
    for url in ("", "ftp://host/agent", "/agents/1", "stdio:python"):
        with pytest.raises(AcpError) as caught:
            AcpEndpoint.http(url)
        assert caught.value.code == "acp_url_unsupported"


def test_an_unknown_transport_is_refused_where_it_is_named() -> None:
    with pytest.raises(AcpError) as caught:
        AcpEndpoint(transport="grpc", url="host:1234")
    assert caught.value.code == "acp_transport_unsupported"


def test_describe_drops_a_query_string() -> None:
    """The query can carry a credential; ``describe`` goes into logs."""
    endpoint = AcpEndpoint.http("https://host/agent?token=secret")

    assert endpoint.describe() == "http:https://host/agent"


def test_connect_routes_by_transport(monkeypatch) -> None:
    """A command and an address reach the same steps; only the branch differs."""
    seen: list[str] = []

    async def fake_spawn_command(endpoint, recorder):
        seen.append(f"stdio:{endpoint.describe()}")
        return _session(), None

    def fake_spawn_url(endpoint, recorder):
        seen.append(f"http:{endpoint.describe()}")
        return _session()

    monkeypatch.setattr(client, "spawn_command", fake_spawn_command)
    monkeypatch.setattr(client, "spawn_url", fake_spawn_url)

    asyncio.run(connect(AcpEndpoint.stdio(["agent-bin"]), TranscriptRecorder()))
    asyncio.run(connect(AcpEndpoint.http("https://host/agent"), TranscriptRecorder()))

    assert seen == ["stdio:stdio:agent-bin", "http:http:https://host/agent"]


# ── permission policy ─────────────────────────────────────────────────────────


def test_allow_always_beats_allow_once() -> None:
    chosen = _allow_option(_options("allow_once", "allow_always", "reject_once"))

    assert str(chosen.kind) == "allow_always"


def test_an_option_that_only_rejects_is_not_chosen() -> None:
    assert _allow_option(_options("reject_once", "reject_always")) is None
    assert _allow_option([]) is None


def test_a_permission_request_is_answered_and_counted() -> None:
    session = _session()

    async def ask() -> dict[str, Any]:
        response = await session.client.request_permission(
            "sess-1", object(), _options("allow_once", "reject_once")
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    payload = asyncio.run(ask())

    assert payload["outcome"] == {"outcome": "selected", "optionId": "opt-0"}
    assert session.permission_stats() == {"requests": 1, "allowed": 1, "denied": 0}


def test_a_request_with_no_way_to_say_yes_is_denied_not_hung() -> None:
    """Denying is the only answer that lets the run continue to a diagnosis."""
    session = _session()

    async def ask() -> dict[str, Any]:
        response = await session.client.request_permission(
            "sess-1", _NamedTool(), _options("reject_once")
        )
        return response.model_dump(by_alias=True, exclude_none=True)

    payload = asyncio.run(ask())

    assert payload["outcome"] == {"outcome": "cancelled"}
    assert session.permission_stats() == {"requests": 1, "allowed": 0, "denied": 1}
    assert "[evaluation]" in str(session.recorder.events[-1])


class _NamedTool:
    title = "run shell command"


@pytest.mark.parametrize("method", ["read_text_file", "write_text_file"])
def test_filesystem_delegations_are_not_offered(method: str) -> None:
    """The subject works in its own environment; we never agreed to lend ours."""
    client = EvalAcpClient(TranscriptRecorder())

    with pytest.raises(RequestError):
        asyncio.run(getattr(client, method)("sess-1", "/etc/passwd"))


@pytest.mark.parametrize(
    "method",
    [
        "create_terminal",
        "terminal_output",
        "wait_for_terminal_exit",
        "release_terminal",
        "kill_terminal",
    ],
)
def test_terminal_delegations_are_not_offered(method: str) -> None:
    client = EvalAcpClient(TranscriptRecorder())

    with pytest.raises(RequestError):
        asyncio.run(getattr(client, method)("sess-1", "term-1"))


# ── session steps ─────────────────────────────────────────────────────────────


def test_initialize_returns_the_capability_record() -> None:
    session = _session()

    handshake = asyncio.run(session.initialize(client_name="pawbench-eval"))

    assert handshake["agent_info"] == {"name": "stub", "version": "9"}
    # The SDK fills in every capability the agent left out, so read the one
    # this stub opted into rather than comparing the whole record.
    assert handshake["capabilities"]["loadSession"] is True
    assert handshake["supports_load_session"] is True
    assert handshake["auth_methods"] == []


def test_new_session_declares_the_directories_it_was_given() -> None:
    agent = StubAgent()
    session = _session(agent)

    session_id = asyncio.run(session.new_session("/tmp/staging", ["/tmp/out"]))

    assert session_id == "sess-1"
    _, kwargs = agent.calls[-1]
    assert kwargs == {"cwd": "/tmp/staging", "additional_directories": ["/tmp/out"], "mcp_servers": []}


# ── the session id a report quotes ───────────────────────────────────────────
#
# ``session_id`` is the agent's own handle for the conversation, and the person
# reading a report searches *that* agent's console with it.  So we ask for an
# id shaped the way those consoles print them, and treat the ask as a courtesy:
# an agent that cannot or will not take it still has to run.


def test_a_minted_session_id_looks_like_the_ones_agents_show() -> None:
    session_id = mint_session_id(now=1795156778.446)

    assert re.fullmatch(r"\d{13}-[a-z0-9]{7}", session_id), session_id
    assert session_id.startswith("1795156778446-")


def test_the_minted_ids_do_not_repeat() -> None:
    assert len({mint_session_id() for _ in range(50)}) == 50


def test_an_agent_that_can_load_files_the_run_under_the_id_we_asked_for() -> None:
    agent = StubAgent()
    session = _session(agent)
    asyncio.run(session.initialize(client_name="pawbench-eval"))

    session_id = asyncio.run(session.new_session("/tmp/staging", ["/tmp/out"], preferred_id="42-a"))

    assert session_id == "42-a"
    assert session.session_id == "42-a"
    # The id arrives through session/load: session/new has no field for it.
    assert [name for name, _ in agent.calls].count("load_session") == 1
    assert [name for name, _ in agent.calls].count("new_session") == 0
    _, kwargs = agent.calls[-1]
    assert kwargs["session_id"] == "42-a"
    assert kwargs["cwd"] == "/tmp/staging"


def test_an_agent_that_cannot_load_keeps_the_id_it_mints() -> None:
    agent = StubAgent(can_load=False)
    session = _session(agent)
    asyncio.run(session.initialize(client_name="pawbench-eval"))

    session_id = asyncio.run(session.new_session("/tmp/staging", preferred_id="42-a"))

    assert session_id == "sess-1"
    assert "load_session" not in [name for name, _ in agent.calls]


def test_an_agent_that_refuses_the_id_still_runs() -> None:
    """A refused courtesy is not a failed attempt: fall back to its own id."""
    agent = StubAgent(load_error=RequestError(-32602, "no such session"))
    session = _session(agent)
    asyncio.run(session.initialize(client_name="pawbench-eval"))

    session_id = asyncio.run(session.new_session("/tmp/staging", preferred_id="42-a"))

    assert session_id == "sess-1"
    assert [name for name, _ in agent.calls][-1] == "new_session"


def test_an_agent_that_opens_no_session_fails_the_step() -> None:
    session = _session(StubAgent(new_session_response={}))

    with pytest.raises(AcpError) as caught:
        asyncio.run(session.new_session("/tmp/staging"))
    assert caught.value.code == "acp_session_missing"


def test_an_agent_that_never_takes_the_handshake_does_not_hold_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process that spawns and says nothing must cost seconds, not the task timeout.

    Without a deadline the runner waits inside ``initialize`` for the whole
    attempt, which pins one of the global queue slots, the run token and the
    registry entry until someone restarts the service.
    """

    class SilentAgent(StubAgent):
        async def initialize(self, **kwargs: Any) -> Any:
            await asyncio.Event().wait()
            raise AssertionError("the handshake was never answered")

    monkeypatch.setattr(client, "HANDSHAKE_TIMEOUT_SECONDS", 0.05)
    session = _session(SilentAgent())

    with pytest.raises(AcpError) as caught:
        asyncio.run(session.initialize(client_name="pawbench-eval"))

    assert caught.value.code == "acp_handshake_timeout"
    assert "did not answer within" in caught.value.message


def test_prompting_before_a_session_is_open_is_a_programming_error() -> None:
    session = _session()

    with pytest.raises(AcpError) as caught:
        asyncio.run(session.prompt("do the task"))
    assert caught.value.code == "acp_session_missing"


def test_prompt_sends_the_text_and_the_links_and_keeps_the_stop_reason() -> None:
    agent = StubAgent(stop_reason="max_tokens")
    session = _session(agent)
    links = ["resource-link"]

    async def run() -> dict[str, Any]:
        await session.new_session("/tmp/staging")
        return await session.prompt("manifest here", links)

    result = asyncio.run(run())

    _, kwargs = agent.calls[-1]
    assert kwargs["prompt"][0].text == "manifest here"
    assert kwargs["prompt"][1] == "resource-link"
    assert result["stop_reason"] == "max_tokens" == session.stop_reason


def test_closing_an_unfinished_session_cancels_it() -> None:
    """Otherwise a harness that walks away leaves the agent burning its timeout."""
    agent = StubAgent()
    session = _session(agent)
    asyncio.run(session.new_session("/tmp/staging"))

    asyncio.run(session.close())

    assert agent.canceled == "sess-1"


def test_closing_a_finished_session_does_not_cancel() -> None:
    agent = StubAgent()
    session = _session(agent)
    asyncio.run(session.new_session("/tmp/staging"))
    asyncio.run(session.prompt("done"))

    asyncio.run(session.close())

    assert agent.canceled == ""


def test_close_is_safe_twice_and_after_the_agent_is_gone() -> None:
    session = _session()
    asyncio.run(session.new_session("/tmp/staging"))

    asyncio.run(session.close())
    asyncio.run(session.close())

    assert session.agent is None


def test_a_teardown_runs_once_even_if_close_is_called_twice() -> None:
    calls: list[str] = []

    async def teardown() -> None:
        calls.append("closed")

    session = _session(teardown=teardown)

    asyncio.run(session.close())
    asyncio.run(session.close())

    assert calls == ["closed"]


def test_stderr_tail_returns_only_the_last_lines() -> None:
    session = _session(stderr_lines=[f"line {index}" for index in range(500)])

    assert session.stderr_tail(3) == "line 497\nline 498\nline 499"
    assert session.stderr_tail(1) == "line 499"


# ── stderr drain ──────────────────────────────────────────────────────────────


class _FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeProcess:
    def __init__(self, stderr: Any) -> None:
        self.stderr = stderr


def test_a_flooded_stderr_keeps_only_a_bounded_tail() -> None:
    """An unread pipe fills and blocks the agent; an unbounded tail fills us."""
    noisy = _FakeStream([b"noise %d\n" % index for index in range(_STDERR_TAIL_LINES * 3)])
    drain = _FakeProcess(noisy)

    async def run() -> list[str]:
        stderr_drain = StderrLogDrain(drain)
        await asyncio.sleep(0.05)
        await stderr_drain.stop()
        return stderr_drain.lines

    lines = asyncio.run(run())

    assert len(lines) == _STDERR_TAIL_LINES
    assert lines[-1] == f"noise {_STDERR_TAIL_LINES * 3 - 1}"


def test_a_process_with_no_stderr_pipe_is_not_a_problem() -> None:
    async def run() -> None:
        drain = StderrLogDrain(_FakeProcess(None))
        await drain.stop()
        assert drain.lines == []

    asyncio.run(run())


# ── transport failures ────────────────────────────────────────────────────────


def test_a_missing_program_fails_at_once_not_after_the_timeout() -> None:
    endpoint = AcpEndpoint.stdio(["definitely-not-a-program-9f3"])

    async def run() -> str:
        try:
            await spawn_command(endpoint, TranscriptRecorder())
        except AcpError as exc:
            return exc.code
        return "no error"

    assert asyncio.run(run()) == "acp_agent_not_found"


def test_an_http_submission_without_the_extra_names_the_fix(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "acp.http", None)

    with pytest.raises(AcpError) as caught:
        spawn_url(AcpEndpoint.http("https://host/agent"), TranscriptRecorder())

    assert caught.value.code == "acp_transport_unavailable"
    assert "agent-client-protocol[http]" in caught.value.message
