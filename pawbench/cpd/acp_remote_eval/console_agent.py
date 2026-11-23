# -*- coding: utf-8 -*-
"""The QwenPaw console, spoken to as if it were an ACP agent.

**Why not ``qwenpaw acp``.** An evaluation can reach QwenPaw over stdio
(``qwenpaw acp``, through :mod:`.bridge`), and that lane is deliberately
ephemeral: the launcher passes ``--runtime-provider``, the ACP server then marks
the session ``qwenpaw.ephemeral``, and ``SessionSaveHook`` returns before it
writes anything. Nothing lands in ``~/.qwenpaw/workspaces/<agent>`` -- no
``chats.json`` row, no ``sessions/console/*.json``. The console's list is the
former and its history is the latter, so a run made that way is invisible on the
agent's own console page however long it ran. Whoever is watching the agent
under test is told to go read our report instead, which is not the same thing as
watching the agent.

The console's own HTTP API does the opposite. ``POST /api/console/chat`` takes a
``session_id`` the caller chooses, registers the chat, streams the turn as the
same SSE envelope the web UI renders, and -- because the request carries no
``qwenpaw.ephemeral`` -- lets the save hook do its job. A conversation per
attempt therefore exists in the console, under the id the report quotes, with
the tool calls the agent actually made.

So this module is an ACP ``Agent`` whose backend is that endpoint: the handshake
calls state what we already know, and ``prompt`` posts one turn and translates
the SSE envelope back into ``session/update`` notifications.

Three consequences worth stating, because they are choices rather than oversights:

* **The model is the agent's own.** ``--runtime-provider`` is what makes the
  stdio lane ephemeral, so there is no ephemeral provider here: the console
  answers with whatever model that agent is configured with. An evaluation of
  "this agent, as its owner runs it" is the reading we want; a run pinned to a
  different model would have to go through the stdio lane.
* **The console owns persistence.** This module never writes a session file. It
  posts a turn and lets QwenPaw store it, which is the only way the console's own
  history view and ours can disagree about nothing.
* **A turn that produced nothing is a failure, not an answer.** The console has
  four ways of saying "this did not work" -- a non-SSE body, a 200 whose stream
  carries ``{"error": ...}``, a ``response.status`` of ``failed``, and a stream
  that closes without a single event -- and every one of them used to arrive here
  as ``end_turn`` with no content. A silently empty answer is scored as an
  answer, so all four raise :class:`ConsoleError` instead: the attempt fails
  loudly, and the report says the console refused rather than "the agent said
  nothing".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from functools import partial
from typing import Any, AsyncIterator, Mapping, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: The console serves its REST surface under this prefix (``/api/chats``,
#: ``/api/console/chat``); the base URL a caller passes is the bare origin.
API_PREFIX = "/api"

#: The console's chat route, relative to :data:`API_PREFIX`.
CHAT_ROUTE = "/console/chat"
STOP_ROUTE = "/console/chat/stop"
CHATS_ROUTE = "/chats"

#: Content blocks the console understands as a user turn. Text and a link are
#: all our prompts carry; anything else is flattened to a line of text so a
#: modality the console cannot take is still visible to the agent.
_TEXT_BLOCK = "text"

#: What a tool call looks like in the console's stream: a ``data`` content block
#: carrying the platform's function-call record.
_CALL_OUTPUT_KEY = "output"

#: A read timeout of ``None`` is deliberate: one turn can reason for minutes,
#: and the evaluation's own task timeout is what bounds it. Connect and write
#: stay finite so a dead port fails fast instead of holding a queue slot.
CONNECT_TIMEOUT = 30.0

#: Stop is a courtesy call on a path where the client is already giving up: the
#: harness waits five seconds for ``session/cancel`` before it moves on
#: (``harness.py``), so a stop that takes longer than that is a stop nobody
#: learns the outcome of. Kept under the harness's budget on purpose.
STOP_TIMEOUT = 4.0

#: The longest silence tolerated between two console events. Reasoning turns
#: emit deltas continuously, so minutes of nothing means the run is gone rather
#: than slow; without this the attempt sits until the task timeout and the report
#: cannot tell "hung" from "still thinking".
IDLE_TIMEOUT = 300.0

#: Size of the shared connection pool. The service already gates how many jobs
#: run at once (``max_concurrent_jobs``, 4 by default) and one attempt holds one
#: stream, so this is headroom rather than a limit -- but it is stated, because
#: httpx's silent default is what turns a capacity problem into a 30-second queue
#: and then a ``PoolTimeout`` that reads like "the console is down".
MAX_CONNECTIONS = 32


class ConsoleError(ValueError):
    """The console refused a call, or answered with something unusable.

    ``code`` is the machine-readable half: the harness records it, so
    ``console_unreachable`` and ``console_capacity`` must not be confused, and
    neither may be confused with ``console_empty_turn`` -- the last one means the
    console answered fine and said nothing, which is a real (and reportable)
    outcome of an evaluation rather than an infrastructure failure.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def mint_session_id(now: float | None = None) -> str:
    """A session handle shaped like the ones the console shows its user."""
    import secrets
    import string
    import time

    millis = int((time.time() if now is None else now) * 1000)
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(7))
    return f"{millis}-{suffix}"


class ConsoleAgent:
    """An ACP agent implemented by one QwenPaw console.

    ``agent`` is passed as ``X-Agent-Id`` -- the same header the console's own
    front end sends to switch agents -- so an evaluation of ``pawbench_eval``
    lands in that agent's chat list rather than the default one's.
    """

    def __init__(
        self,
        base_url: str,
        *,
        agent: str | None = None,
        user_id: str = "default",
        channel: str = "console",
        client: Any = None,
        rename_chats: bool = True,
        idle_timeout: float = IDLE_TIMEOUT,
    ) -> None:
        base = str(base_url or "").strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ConsoleError(
                "console_url_unsupported",
                f"a console URL must be http(s), got {base!r}",
            )
        if not base.endswith(API_PREFIX):
            base = f"{base}{API_PREFIX}"
        self.base_url = base
        self.agent = (agent or "").strip() or None
        self.user_id = user_id
        self.channel = channel
        self.rename_chats = rename_chats
        self.idle_timeout = float(idle_timeout)
        self._client = client
        self._sessions: dict[str, _Session] = {}
        #: Stops still in flight, by session. Held so the event loop cannot
        #: collect one while the client that asked for the cancel is already
        #: gone -- and so two callers asking for the same stop share one request.
        self._stopping: dict[str, asyncio.Task[None]] = {}
        self._owns_client = client is None
        self._closed = False

    # ── plumbing ──────────────────────────────────────────────────────────────

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._closed:
            raise ConsoleError(
                "console_closed",
                "this console agent was closed; a closed agent does not open new connections",
            )
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=None, write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_CONNECTIONS // 2,
                keepalive_expiry=30.0,
            ),
            headers=self._headers(),
            trust_env=False,
        )
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"X-Agent-Id": self.agent} if self.agent else {}

    async def close(self) -> None:
        """Release what this object opened, and nothing that was lent to it."""
        self._closed = True
        if not self._owns_client:
            # The caller built the client and may want it back; dropping it here
            # would make the next call build a fresh one against the real network
            # stack, which is a behaviour change nobody asked for.
            return
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def route(self, session_id: str, connection: Any) -> None:
        """Remember which client connection opened *session_id*.

        Same contract as the stdio lane's router: an update belongs to the
        connection that opened the session, not to whichever one is asking.
        """
        state = self._sessions.get(session_id)
        if state is None:
            state = self._sessions[session_id] = _Session(session_id)
        if state.connection is not None and state.connection is not connection:
            # Two connections claiming one session is how a client reconnects,
            # so the newcomer wins -- but not silently: from here on the previous
            # one's updates are dropped, and that is worth one line.
            logger.warning(
                "session %s moved to a new connection", session_id, extra={"session_id": session_id}
            )
        state.connection = connection

    def owner(self, session_id: str) -> Any:
        state = self._sessions.get(session_id)
        return state.connection if state is not None else None

    # ── ACP handshake ─────────────────────────────────────────────────────────

    async def initialize(self, **kwargs: Any) -> Any:
        from acp.schema import AgentCapabilities, Implementation, InitializeResponse

        return InitializeResponse(
            protocol_version=int(kwargs.get("protocol_version") or 1),
            agent_capabilities=AgentCapabilities(load_session=True),
            agent_info=Implementation(name="qwenpaw-console", title="QwenPaw console", version="1"),
        )

    async def new_session(
        self,
        cwd: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> Any:
        from acp.schema import NewSessionResponse

        handle = session_id or mint_session_id()
        self._remember(handle, cwd)
        return NewSessionResponse(session_id=handle)

    async def load_session(
        self,
        cwd: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> Any:
        """Adopt the caller's id.

        The console has no "load" of its own: a chat is created on the first
        turn, under whatever ``session_id`` that turn names. Adopting here is
        therefore honest -- and it is what makes the report's id the one the
        console page shows.
        """
        from acp.schema import LoadSessionResponse

        if not session_id:
            raise ConsoleError("console_session_missing", "session/load needs a session id")
        self._remember(session_id, cwd)
        return LoadSessionResponse()

    async def resume_session(
        self,
        cwd: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> Any:
        from acp.schema import ResumeSessionResponse

        if not session_id:
            raise ConsoleError("console_session_missing", "session/resume needs a session id")
        self._remember(session_id, cwd)
        return ResumeSessionResponse()

    async def close_session(self, session_id: str = "", **kwargs: Any) -> Any:
        """Forget the session; the console keeps the conversation."""
        state = self._sessions.get(session_id)
        if state is None:
            return
        if state.running:
            # Popping now would strand the turn that is still producing updates:
            # it holds its own reference, but every later ``_emit`` looks the
            # state up again and would find no connection. Let the turn's own
            # ``finally`` do the forgetting.
            state.closing = True
            await self._stop(session_id)
            return
        self._sessions.pop(session_id, None)

    async def cancel(self, session_id: str = "", **kwargs: Any) -> None:
        await self._stop(session_id)

    # ── one turn ──────────────────────────────────────────────────────────────

    async def prompt(
        self,
        prompt: Sequence[Any] = (),
        session_id: str = "",
        **kwargs: Any,
    ) -> Any:
        """Post one turn and stream it back as ACP updates."""
        from acp.schema import PromptResponse

        if not session_id:
            raise ConsoleError("console_session_missing", "prompt needs a session id")
        state = self._remember(session_id, "")
        if state.running:
            # The console answers 409 in this case; saying so here keeps the
            # message ours instead of a rejection from three layers down, and
            # stops the two turns from overwriting each other's ``running`` flag.
            raise ConsoleError(
                "console_session_busy",
                f"a turn is already running on {session_id}; the console runs one at a time",
            )
        text = _prompt_text(prompt)
        if not text:
            return PromptResponse(stop_reason="end_turn")

        body = {
            "session_id": session_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "input": [{"content": [{"type": _TEXT_BLOCK, "text": text}]}],
        }
        turn = _Turn(session_id)
        state.running = True
        try:
            stop_reason = await self._stream_turn(body, turn)
        except asyncio.CancelledError:
            # The client went away mid-turn. The console keeps running
            # otherwise: it has no idea the connection dropped.
            state.running = False
            self._release(session_id, state)
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await self._stop(session_id)
            raise
        except BaseException:
            state.running = False
            self._release(session_id, state)
            raise

        state.running = False
        if self.rename_chats:
            await self._rename_from_cwd(session_id, state.cwd)
        self._release(session_id, state)
        usage = turn.usage()
        # The numbers go in the message, not only in ``extra``: the bridge
        # configures a plain ``%(message)s`` format, so an extra field is written
        # to the record and never to the log. "Which attempt, and did it die
        # silently" is exactly the question this line exists to answer.
        logger.info(
            "console turn finished: session=%s stop_reason=%s updates=%d skipped=%d tokens=%d",
            session_id,
            stop_reason,
            turn.updates,
            turn.skipped,
            usage.total_tokens if usage else 0,
            extra={
                "session_id": session_id,
                "stop_reason": stop_reason,
                "updates": turn.updates,
                "skipped": turn.skipped,
            },
        )
        return PromptResponse(stop_reason=stop_reason, usage=usage)

    async def _stream_turn(self, body: dict[str, Any], turn: "_Turn") -> str:
        """Read the SSE envelope, one ``session/update`` per interesting event."""
        import httpx

        stop_reason = ""
        try:
            async with self.client.stream("POST", CHAT_ROUTE, json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")
                    raise ConsoleError(
                        "console_chat_rejected",
                        f"POST {CHAT_ROUTE} answered {response.status_code}: {detail[:400]}",
                    )
                _require_event_stream(response)
                stop_reason = await self._read_events(response, turn)
        except ConsoleError:
            raise
        except httpx.PoolTimeout as exc:
            # A full pool is our own sizing problem, not a dead console, and the
            # two send the next reader to different places.
            raise ConsoleError(
                "console_capacity",
                f"no free connection to the console for {turn.session_id} "
                f"({MAX_CONNECTIONS} in flight): {exc!r}",
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            # Only the wire is translated: a bug in the mapping below (a schema
            # field the SDK refuses, say) must stay a bug, not be reported as
            # "the console is unreachable" and send the next reader to the wrong
            # process.
            raise ConsoleError(
                "console_unreachable", f"POST {CHAT_ROUTE} failed: {exc!r}"
            ) from exc

        if not stop_reason:
            # The stream closed without a verdict. Whatever was said still
            # counts, but the end of the turn was not announced.
            stop_reason = "end_turn"
        if turn.updates == 0 and stop_reason != "cancelled":
            # An attempt whose transcript is empty is scored as an empty answer.
            # Nothing was said *and* nothing was sent to the client: that is a
            # failure of this lane, and it belongs in the report as one.
            raise ConsoleError(
                "console_empty_turn",
                f"the console streamed no content for {turn.session_id} "
                f"({turn.payloads} payloads, stop_reason={stop_reason})",
            )
        return stop_reason

    async def _read_events(self, response: Any, turn: "_Turn") -> str:
        """Drive the SSE iterator, with a silence limit between two events."""
        events = _sse_payloads(response)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(anext(events), timeout=self.idle_timeout)
                except StopAsyncIteration:
                    return ""
                except asyncio.TimeoutError:
                    raise ConsoleError(
                        "console_stalled",
                        f"the console sent nothing for {self.idle_timeout:.0f}s on "
                        f"{turn.session_id}; the run is gone, not slow",
                    ) from None
                turn.payloads += 1
                stop_reason = await self._apply(payload, turn)
                if stop_reason:
                    return stop_reason
        finally:
            with contextlib.suppress(Exception):
                await events.aclose()

    async def _apply(self, payload: Mapping[str, Any], turn: "_Turn") -> str:
        """One SSE payload → zero or more ACP updates. Returns a stop reason at the end."""
        try:
            return await self._translate(payload, turn)
        except ConsoleError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            # One malformed event must not cost the rest of the turn: the console
            # is an external shape, and dropping the whole run because a single
            # ``data`` block surprised the SDK would blame the agent under test
            # for our translation. Counted, logged, and reported in the summary.
            turn.skipped += 1
            logger.warning(
                "skipping an untranslatable console event: session=%s object=%s type=%s reason=%r",
                turn.session_id,
                str(payload.get("object") or ""),
                str(payload.get("type") or ""),
                exc,
            )
            return ""

    async def _translate(self, payload: Mapping[str, Any], turn: "_Turn") -> str:
        from acp.schema import (
            AgentMessageChunk,
            AgentThoughtChunk,
            TextContentBlock,
            ToolCallProgress,
            ToolCallStart,
        )

        if payload.get("error"):
            # ``console.py`` turns a failed stream into exactly this envelope;
            # treating it as "the turn ended" is how a crashed run became a
            # scored empty answer.
            raise ConsoleError(
                "console_stream_error",
                f"the console reported an error for {turn.session_id}: {payload['error']}",
            )

        kind = str(payload.get("object") or "")
        if kind == "message":
            turn.note_message(str(payload.get("id") or ""), str(payload.get("type") or "message"))
            return ""

        if kind == "content":
            content_type = str(payload.get("type") or "")

            if content_type == _TEXT_BLOCK:
                text = str(payload.get("text") or "")
                if not text:
                    return ""
                message = turn.resolve_message(payload.get("msg_id"))
                chunk = AgentThoughtChunk if turn.is_reasoning(message) else AgentMessageChunk
                if payload.get("delta"):
                    turn.streamed.add(message)
                elif message in turn.streamed:
                    # The whole of this message already went out as deltas. The
                    # final row repeats it -- with a null ``msg_id``, which is
                    # why the key is the message and not the payload's string.
                    return ""
                await self._emit(turn, chunk(content=TextContentBlock(type="text", text=text)))
                return ""

            if content_type == "data":
                await self._tool(payload, turn)
                return ""

            if content_type == "refusal":
                # A refusal is the model's answer about the task, not a block to
                # be summarised: judge it on its words.
                text = str(payload.get("text") or payload.get("refusal") or "").strip()
                message = turn.resolve_message(payload.get("msg_id"))
                await self._emit(
                    turn,
                    AgentMessageChunk(content=TextContentBlock(type="text", text=text or "[refusal]")),
                )
                turn.noted.add((message, content_type))
                return ""

            # Images, files, audio: the console's own view has the block; the
            # transcript needs a marker so a reader knows one was there.
            message = turn.resolve_message(payload.get("msg_id"))
            if (message, content_type) in turn.noted:
                return ""
            turn.noted.add((message, content_type))
            logger.debug(
                "content block kept in the console only: type=%s message=%s", content_type, message
            )
            placeholder = f"[{content_type or 'content'}]"
            await self._emit(
                turn, AgentMessageChunk(content=TextContentBlock(type="text", text=placeholder))
            )
            return ""

        if kind == "response":
            status = str(payload.get("status") or "")
            if status == "completed":
                return "end_turn"
            if status == "cancelled":
                return "cancelled"
            if status == "failed":
                raise ConsoleError(
                    "console_run_failed",
                    f"the console reported the run as failed for {turn.session_id}",
                )
            return ""

        if kind == "event" or payload.get("type") == "turn_usage":
            usage = payload.get("usage")
            if isinstance(usage, Mapping):
                turn.absorb_usage(usage)
        return ""

    async def _tool(self, payload: Mapping[str, Any], turn: "_Turn") -> None:
        """One ``data`` block → a tool call, a tool result, or both."""
        from acp.schema import ToolCallProgress, ToolCallStart

        data = payload.get("data")
        call = dict(data) if isinstance(data, Mapping) else {}
        call_id = str(call.get("call_id") or "")
        if not call_id:
            return
        name = str(call.get("name") or "").strip()
        state = turn.calls.setdefault(call_id, _Call())
        has_output = _CALL_OUTPUT_KEY in call

        # Neither ``delta`` nor ``status`` decides whether a call exists: the
        # console varies both between events and between versions, and a tool
        # call that silently disappears because one field was absent is worse
        # than one whose arguments arrived half-built. The start waits only for
        # something to put in it -- the console sends an empty ``arguments``
        # delta first, and announcing a call with no arguments at all would be a
        # transcript that says the agent ran ``ls`` with nothing.
        if name and not state.started:
            ready = bool(call.get("arguments")) or has_output or not payload.get("delta")
            if ready:
                state.started = True
                await self._emit(
                    turn,
                    ToolCallStart(
                        tool_call_id=call_id,
                        title=name,
                        name=name,
                        status="in_progress",
                        raw_input=_parse_arguments(call.get("arguments")),
                    ),
                )

        if not has_output:
            return
        final = not payload.get("delta")
        if state.answer_started and not final:
            # Output deltas are the same text growing; one copy is what a reader
            # wants, and the closing non-delta row carries the whole of it.
            return
        state.answer_started = True
        await self._emit(
            turn,
            ToolCallProgress(
                tool_call_id=call_id,
                status="failed" if call.get("state") == "error" else "completed",
                raw_output=call.get(_CALL_OUTPUT_KEY),
            ),
        )

    async def _emit(self, turn: "_Turn", update: Any) -> None:
        connection = self.owner(turn.session_id)
        if connection is None:
            logger.debug("dropping update for %s: no connection holds it", turn.session_id)
            return
        try:
            await connection.session_update(session_id=turn.session_id, update=update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - any write failure means the client is gone
            # The client is gone, so this turn has no reader left. Stop the
            # console run rather than leaving it writing into the void, and fail
            # the turn: a prompt that "succeeds" while nobody received anything
            # is exactly the silent-empty-answer shape this module refuses.
            state = self._sessions.get(turn.session_id)
            if state is not None:
                state.connection = None
            logger.warning(
                "session/update could not be delivered; stopping the console run: session=%s reason=%r",
                turn.session_id,
                exc,
            )
            await self._stop(turn.session_id)
            raise ConsoleError(
                "console_client_gone",
                f"the client stopped reading {turn.session_id}: {exc!r}",
            ) from exc
        turn.updates += 1

    def _remember(self, session_id: str, cwd: str) -> "_Session":
        state = self._sessions.get(session_id)
        if state is None:
            state = self._sessions[session_id] = _Session(session_id)
        if cwd:
            state.cwd = cwd
        return state

    def _release(self, session_id: str, state: "_Session") -> None:
        """Drop what a finished turn held, so a long-lived bridge does not grow.

        The connection is the expensive part: it is a closed ASGI object that
        would otherwise stay referenced for the life of the process. Routing is
        re-established by the next call that names this session (``prompt``
        routes before it posts), so nothing downstream needs the stale one.
        """
        state.connection = None
        if state.closing:
            self._sessions.pop(session_id, None)

    # ── console-side bookkeeping ──────────────────────────────────────────────

    async def _stop(self, session_id: str) -> None:
        """Ask the console to stop the run behind this session.

        The stop route takes a chat id *or* a session id -- it looks the chat up
        itself when the id it was given is not a chat (``post_console_chat_stop``
        falls back to ``get_chat_id_by_session``) -- so no listing is needed on
        this path. That matters: the cancel path has a five-second budget from
        the harness, and a full ``GET /api/chats`` in front of every stop was
        both a growth problem and a way to spend the budget before asking.

        The request runs in its own task, shielded from the caller. A real run
        showed why: the client that cancelled closed its connection immediately
        afterwards, and the stop's ``connect_tcp`` came back as ``CancelledError``
        -- the console never heard about the cancellation, so "we cancelled" was
        a claim the log could not support. A shield makes the stop outlive the
        request that asked for it.

        One stop per session at a time. A cancel from the harness arrives twice as
        often as not -- once as ``session/cancel`` and once as the prompt task
        being cancelled -- and asking the console to stop twice in the same
        instant made the second answer "nothing was running", which reads like a
        failure in the log that the first one already contradicted.

        Best effort by design: a stop that fails must not turn a cancel into an
        error the caller has to interpret. It is not silent, though -- a stop the
        console did not perform is the difference between "we cancelled" and "it
        is still running", which is the one thing an operator needs to know.
        """
        if not session_id:
            return
        pending = self._stopping.get(session_id)
        if pending is None or pending.done():
            pending = asyncio.ensure_future(self._request_stop(session_id))
            self._stopping[session_id] = pending
            pending.add_done_callback(partial(self._forget_stop, session_id))
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            logger.warning(
                "the client left while the stop was in flight; the stop continues in "
                "the background: session=%s",
                session_id,
            )
            raise

    def _forget_stop(self, session_id: str, task: Any) -> None:
        if self._stopping.get(session_id) is task:
            self._stopping.pop(session_id, None)

    async def _request_stop(self, session_id: str) -> None:
        import httpx

        try:
            response = await asyncio.wait_for(
                self.client.post(
                    STOP_ROUTE, params={"chat_id": session_id}, timeout=STOP_TIMEOUT
                ),
                timeout=STOP_TIMEOUT + 1.0,
            )
            response.raise_for_status()
            stopped = bool((response.json() or {}).get("stopped"))
        except (httpx.HTTPError, OSError, ValueError, asyncio.TimeoutError) as exc:
            logger.warning(
                "console stop failed; the run may still be going: session=%s reason=%r",
                session_id,
                exc,
            )
            return
        if stopped:
            logger.info("console run stopped: session=%s", session_id)
        else:
            logger.warning(
                "console had no run to stop (already finished, or the id named another chat): session=%s",
                session_id,
            )

    async def _chat_id(self, session_id: str) -> str:
        """The console's own id for this chat, which is what ``PUT /chats/{id}`` wants."""
        state = self._sessions.get(session_id)
        if state is not None and state.chat_id:
            return state.chat_id
        import httpx

        try:
            response = await self.client.get(
                CHATS_ROUTE, params={"user_id": self.user_id}, timeout=STOP_TIMEOUT
            )
            response.raise_for_status()
            chats = response.json()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            logger.warning(
                "chat lookup failed; the console keeps the name it chose: session=%s reason=%r",
                session_id,
                exc,
            )
            return ""
        for chat in chats if isinstance(chats, list) else []:
            if str(chat.get("session_id") or "") == session_id:
                chat_id = str(chat.get("id") or "")
                if state is not None:
                    state.chat_id = chat_id
                return chat_id
        return ""

    async def _rename_from_cwd(self, session_id: str, cwd: str) -> None:
        """Give the chat a name that says which evaluation it belongs to.

        The console names a chat after its first words, which for a task prompt
        is prose. A run is easier to find by ``job / task`` -- and the cwd we
        were given already carries both, because the harness roots every attempt
        in ``.../jobs/<job>/<task>/attempt-<n>/session``.

        Bounded on purpose: the answer is already in hand by now, and a console
        that is slow to list chats must not turn a finished turn into a timeout
        the harness records as a failed attempt.
        """
        title = chat_title(cwd)
        if not title:
            return
        import httpx

        try:
            chat_id = await asyncio.wait_for(self._chat_id(session_id), timeout=STOP_TIMEOUT)
            if not chat_id:
                return
            await asyncio.wait_for(
                self.client.put(
                    f"{CHATS_ROUTE}/{chat_id}", json={"name": title}, timeout=STOP_TIMEOUT
                ),
                timeout=STOP_TIMEOUT,
            )
        except (httpx.HTTPError, OSError, ValueError, asyncio.TimeoutError) as exc:
            # A name is a convenience; the conversation is the deliverable.
            logger.warning(
                "chat rename failed; the console keeps the name it chose: session=%s reason=%r",
                session_id,
                exc,
            )


class _Session:
    """What the console side remembers about one ACP session."""

    __slots__ = ("session_id", "cwd", "connection", "chat_id", "running", "closing")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.cwd = ""
        self.connection: Any = None
        self.chat_id = ""
        self.running = False
        self.closing = False


class _Call:
    """What has already been sent for one tool call."""

    __slots__ = ("started", "answer_started")

    def __init__(self) -> None:
        self.started = False
        self.answer_started = False


class _Turn:
    """Per-turn bookkeeping: which messages streamed, how many tokens, how noisy.

    Text is deduplicated by **message**, not by the payload's ``msg_id``: the
    console streams a message under its id and then repeats the whole text in a
    closing row whose ``msg_id`` is ``None``. Keying on the payload string made
    those two different messages, so every answer was sent twice -- and made the
    reasoning lookup miss, so a thought could arrive as an answer.
    """

    __slots__ = (
        "session_id",
        "message_types",
        "current_message",
        "streamed",
        "noted",
        "calls",
        "updates",
        "payloads",
        "skipped",
        "_usage",
    )

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.message_types: dict[str, str] = {}
        self.current_message = ""
        self.streamed: set[str] = set()
        self.noted: set[tuple[str, str]] = set()
        self.calls: dict[str, _Call] = {}
        self.updates = 0
        self.payloads = 0
        self.skipped = 0
        self._usage: dict[str, int] = {}

    def note_message(self, message_id: str, kind: str) -> None:
        if not message_id:
            return
        self.message_types[message_id] = kind
        self.current_message = message_id

    def resolve_message(self, raw: Any) -> str:
        """Which message a content payload belongs to.

        A row without ``msg_id`` continues whatever message the console last
        named, which is what the UI does with it.
        """
        message_id = str(raw or "")
        if message_id:
            self.current_message = message_id
            return message_id
        return self.current_message

    def is_reasoning(self, message_id: str) -> bool:
        return self.message_types.get(message_id) == "reasoning"

    def absorb_usage(self, usage: Mapping[str, Any]) -> None:
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
        completion = usage.get("completion_tokens") or usage.get("output_tokens")
        if isinstance(prompt, int) and prompt >= 0:
            self._usage["input_tokens"] = prompt
        if isinstance(completion, int) and completion >= 0:
            self._usage["output_tokens"] = completion

    def usage(self) -> Any:
        """ACP ``Usage`` for the report, or ``None`` when the console said nothing."""
        if not self._usage:
            return None
        from acp.schema import Usage

        total = self._usage.get("input_tokens", 0) + self._usage.get("output_tokens", 0)
        return Usage(
            input_tokens=self._usage.get("input_tokens", 0),
            output_tokens=self._usage.get("output_tokens", 0),
            total_tokens=total,
        )


# ── payload helpers ───────────────────────────────────────────────────────────


def _prompt_text(prompt: Sequence[Any]) -> str:
    """The turn as plain text: text blocks in order, links named after them."""
    parts: list[str] = []
    links: list[str] = []
    for block in prompt or []:
        text = _block_text(block)
        if text:
            parts.append(text)
        uri = _block_uri(block)
        if uri:
            links.append(uri)
    if links:
        parts.append("附件：\n" + "\n".join(f"- {uri}" for uri in links))
    return "\n\n".join(part for part in parts if part.strip()).strip()


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, Mapping):
        return str(block.get("text") or "")
    return str(getattr(block, "text", "") or "")


def _block_uri(block: Any) -> str:
    if isinstance(block, Mapping):
        uri = block.get("uri")
    else:
        uri = getattr(block, "uri", None)
    return str(uri) if uri else ""


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """A tool call's arguments as an object, so a client can render the fields.

    Always a mapping: the ACP schema types ``raw_input`` as an object, so a JSON
    array or scalar passed through as-is would raise inside the SDK and cost the
    turn (see ``_apply`` for why that is the wrong failure).
    """
    if isinstance(raw, Mapping):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return {"arguments": text}
    return dict(value) if isinstance(value, Mapping) else {"arguments": value}


def _require_event_stream(response: Any) -> None:
    """Refuse a 200 that is not an event stream.

    A console behind a proxy that answered JSON -- or an error page with a 200 --
    would otherwise be read as "the stream ended", which is the empty-answer
    shape again.
    """
    content_type = str(response.headers.get("content-type") or "").split(";")[0].strip()
    if content_type == "text/event-stream":
        return
    raise ConsoleError(
        "console_not_sse",
        f"POST {CHAT_ROUTE} answered {response.status_code} as {content_type or 'no content type'}; "
        "an event stream was required",
    )


async def _sse_payloads(response: Any) -> AsyncIterator[dict[str, Any]]:
    """One decoded JSON object per SSE ``data:`` block.

    The console writes each event as a single ``data:`` line followed by a blank
    line, so a block is the join of its data lines -- a payload is never
    ``[DONE]``-style sentinel, and a malformed line is skipped rather than
    ending the turn.
    """
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
            continue
        if line.strip():
            continue
        payload = _decode("".join(buffer))
        buffer.clear()
        if payload is not None:
            yield payload
    payload = _decode("".join(buffer))
    if payload is not None:
        yield payload


def _decode(raw: str) -> dict[str, Any] | None:
    """A payload, or ``None`` for something that is not one.

    A skipped block is a gap in the transcript, so it is logged -- by size, not
    by content: these lines carry the task prompt and the agent's answer, and a
    log is the last place that belongs.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        logger.warning("skipping a malformed SSE block: bytes=%d", len(text))
        return None
    return dict(value) if isinstance(value, Mapping) else None


def chat_title(cwd: str) -> str:
    """``job / task`` from an attempt directory, or ``""`` for anything else.

    Only our own layout is renamed: a cwd shaped like someone's project must not
    have its chat relabelled with path fragments.
    """
    parts = [part for part in _path_parts(cwd) if part]
    for index, part in enumerate(parts):
        if part != "jobs" or index + 2 >= len(parts):
            continue
        job, task = parts[index + 1], parts[index + 2]
        attempt = ""
        for tail in parts[index + 3 :]:
            if tail.startswith("attempt-"):
                attempt = tail.split("-", 1)[1]
                break
        suffix = f"（第 {attempt} 次）" if attempt.isdigit() else ""
        return f"{task} · {job}{suffix}"[:500]
    return ""


def _path_parts(path: str) -> list[str]:
    text = str(path or "").strip()
    if not text:
        return []
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        text = parsed.path
    return [part for part in text.replace("\\", "/").split("/") if part]


__all__ = ["ConsoleAgent", "ConsoleError", "chat_title", "mint_session_id"]
