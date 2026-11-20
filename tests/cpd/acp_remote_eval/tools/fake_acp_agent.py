# -*- coding: utf-8 -*-
"""A stand-in subject agent: its own process, real ACP, real HTTP.

Two things this proves that an in-process double cannot.  First, our client
talks the wire the way the official SDK's does -- if we mis-serialise a
notification, the failure shows up here rather than in front of a customer.
Second, the data-plane URLs work from a process that shares nothing with the
service but a port on localhost, which is exactly what a remote agent sees.

Modes are command-line flags because a submission selects an agent by command
line; the harness should not have to know this tool exists.

    python fake_acp_agent.py --mode artifacts --model fake-model-1
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from acp import run_agent
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

MODES = ("artifacts", "zero", "refused-paths", "stderr-flood", "hang")
_MANIFEST_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def log(message: str) -> None:
    """Progress goes to stderr: it is what a real harness does, and it is what
    the evaluation side has to keep reading or the pipe fills up."""
    print(f"[fake-acp] {message}", file=sys.stderr, flush=True)


def extract_manifest(text: str) -> dict[str, Any]:
    match = _MANIFEST_FENCE.search(text)
    if match is None:
        raise ValueError("no json manifest block in the prompt")
    return json.loads(match.group(1))


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed http(s) URLs
        return response.read()


def put(url: str, token: str, data: bytes) -> int:
    request = urllib.request.Request(  # noqa: S310 - fixed http(s) URLs
        url,
        data=data,
        method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


class FakeAcpAgent:
    """The smallest agent that exercises the same calls a real one makes."""

    def __init__(self, *, mode: str = "artifacts", model: str = "") -> None:
        self.mode = mode
        self.model = model
        self.conn: Any = None
        self.cwd = Path(".")
        self.cancelled = False
        self.sessions: dict[str, str] = {}

    # ── connection ────────────────────────────────────────────────────────────

    def on_connect(self, conn: Any) -> None:
        self.conn = conn

    async def initialize(self, **kwargs: Any) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=kwargs.get("protocol_version", 1),
            agent_capabilities={"loadSession": True, "prompt": {"image": True}},
            agent_info={"name": "fake-acp-agent", "version": "1", "title": "Fake ACP agent"},
        )

    async def new_session(self, cwd: str, **kwargs: Any) -> NewSessionResponse:
        session_id = str(uuid.uuid4())
        self.cwd = Path(cwd)
        self.sessions[session_id] = cwd
        self.cwd.mkdir(parents=True, exist_ok=True)
        log(f"session {session_id[:8]} cwd={cwd}")
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> Any:
        """Adopt the caller's id, the way an agent with ``loadSession`` does."""
        self.cwd = Path(cwd)
        self.sessions[session_id] = cwd
        self.cwd.mkdir(parents=True, exist_ok=True)
        log(f"load_session {session_id[:8]} cwd={cwd}")
        return {}

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self.cancelled = True
        log("cancel received")

    # ── the task ──────────────────────────────────────────────────────────────

    async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> PromptResponse:
        text = "\n".join(
            str(getattr(block, "text", "") or "")
            for block in prompt
            if getattr(block, "type", "") == "text"
        )
        manifest = extract_manifest(text)
        await self._say(session_id, f"task {manifest['task_id']} accepted, mode {self.mode}")
        await self._plan(
            session_id,
            [
                {"content": "fetch fixtures", "priority": "high", "status": "pending"},
                {"content": "write one answer per fixture", "priority": "high", "status": "pending"},
            ],
        )

        if self.mode == "hang":
            await self._say(session_id, "thinking, indefinitely")
            while not self.cancelled:
                await asyncio.sleep(0.05)
            return PromptResponse(stop_reason="cancelled")

        if self.mode == "stderr-flood":
            for index in range(2000):
                log(f"noise {index}")

        written = await self._fetch_fixtures(session_id, manifest)
        answers = [_answer_for(name, data) for name, data in written]
        if not answers:
            # A text-only task still has an answer; an agent that only typed it
            # into the chat is the ``zero`` mode, not this one.
            answers = [("output/answer.md", b"# answer\n\nwritten without any fixture\n")]

        if self.mode == "zero":
            await self._say(session_id, "done, but I am keeping the files to myself")
            return PromptResponse(stop_reason="end_turn")

        if self.mode == "refused-paths":
            codes = await self._upload(session_id, manifest, [("conftest.py", b"import os")])
            await self._say(session_id, f"refused-path statuses: {codes}")
            return PromptResponse(stop_reason="end_turn")

        codes = await self._upload(session_id, manifest, answers)
        await self._say(session_id, f"uploaded {len(answers)} files, statuses {sorted(set(codes))}")
        return PromptResponse(stop_reason="end_turn")

    # ── steps ─────────────────────────────────────────────────────────────────

    async def _fetch_fixtures(self, session_id: str, manifest: dict) -> list[tuple[str, bytes]]:
        written: list[tuple[str, bytes]] = []
        for asset in manifest.get("assets") or []:
            call_id = str(uuid.uuid4())
            await self._tool(
                session_id,
                call_id,
                title=f"GET {asset['dest']}",
                name="http_get",
                status="in_progress",
                raw_input={"url": asset["url"][:60], "dest": asset["dest"]},
            )
            data = fetch(asset["url"])
            digest = hashlib.sha256(data).hexdigest()
            target = self.cwd / asset["dest"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append((asset["dest"], data))
            await self._tool(
                session_id,
                call_id,
                status="completed",
                raw_output={"bytes": len(data), "sha256_prefix": digest[:8], "matches": digest == asset["sha256"]},
            )
        return written

    async def _upload(
        self, session_id: str, manifest: dict, files: list[tuple[str, bytes]]
    ) -> list[int]:
        template = str(manifest["upload"]["url"])
        token = str(manifest["upload"]["headers"]["Authorization"]).removeprefix("Bearer ")
        statuses: list[int] = []
        for path, data in files:
            call_id = str(uuid.uuid4())
            await self._tool(
                session_id, call_id, title=f"PUT {path}", name="http_put", status="in_progress"
            )
            status = put(template.replace("{path}", path), token, data)
            statuses.append(status)
            (self.cwd / path).parent.mkdir(parents=True, exist_ok=True)
            (self.cwd / path).write_bytes(data)
            await self._tool(
                session_id, call_id, status="completed", raw_output={"status": status}
            )
        return statuses

    # ── notifications ─────────────────────────────────────────────────────────

    async def _say(self, session_id: str, text: str) -> None:
        meta = {"model": self.model} if self.model else None
        await self.conn.session_update(
            session_id=session_id,
            update=AgentMessageChunk(
                content=TextContentBlock(text=text),
                field_meta=meta,
            ),
        )

    async def _plan(self, session_id: str, entries: list[dict]) -> None:
        await self.conn.session_update(
            session_id=session_id, update=AgentPlanUpdate(entries=entries)
        )

    async def _tool(self, session_id: str, call_id: str, **fields: Any) -> None:
        first = fields.get("status") == "in_progress"
        model = ToolCallStart if first else ToolCallProgress
        kwargs = {"tool_call_id": call_id, **fields}
        if first:
            kwargs.setdefault("title", "tool")
            kwargs.setdefault("name", "tool")
        await self.conn.session_update(session_id=session_id, update=model(**kwargs))


def _answer_for(dest: str, data: bytes) -> tuple[str, bytes]:
    stem = Path(dest).stem
    body = (
        f"# {stem}\n\n"
        f"source: {dest}\n"
        f"bytes: {len(data)}\n"
        f"sha256: {hashlib.sha256(data).hexdigest()}\n"
    )
    return f"output/{stem}.md", body.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="artifacts")
    parser.add_argument("--model", default="", help="model id to report in _meta")
    arguments = parser.parse_args(argv)
    agent = FakeAcpAgent(mode=arguments.mode, model=arguments.model)
    asyncio.run(run_agent(agent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
