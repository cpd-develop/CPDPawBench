# -*- coding: utf-8 -*-
"""``session/update`` notifications turned into the transcript the grader reads.

The scoring side already knows how to summarise an OpenClaw event list
(``pawbench/grader.py:_summarize_transcript``: ``message`` events whose content
blocks are ``text`` / ``toolCall``, plus ``toolResult`` turns).  Remote agents
speak ACP instead, so everything about them has to pass through this mapping
once -- that keeps ``pawbench/grader.py`` untouched, which matters because it
is shared with the community harnesses (design section 2.1).

Two outputs, deliberately different:

* ``events`` -- normalised, capped, and what the judge prompt is built from.
* the JSONL file -- every notification verbatim, for the detail view and for
  arguing with a score later.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

#: A remote agent may stream for its whole timeout window and we do not control
#: it, so the in-memory transcript needs a ceiling: four concurrent jobs each
#: holding a megabyte-per-minute stream is how a service gets OOM-killed
#: mid-report.  The JSONL keeps everything regardless.
MAX_EVENTS_IN_MEMORY = 4000

#: Flushed every N lines so a crash mid-run still leaves most of the stream
#: without turning every chunk into its own write syscall.
_FLUSH_EVERY_LINES = 32

#: Keys a harness may use to say which model answered.  Matched case- and
#: separator-insensitively against every dict in the notification.
_MODEL_KEYS = frozenset(
    {
        "model",
        "modelid",
        "modelname",
        "modelversion",
        "servedmodel",
        "responsemodel",
        "upstreammodel",
    }
)

#: Non-text content blocks become this marker instead of their bytes: a base64
#: image in the transcript reaches the judge prompt, where it is both noise and
#: a token-bill explosion.
_BLOCK_PLACEHOLDERS = {
    "image": "[image]",
    "audio": "[audio]",
    "resource": "[resource]",
    "resource_link": "[resource_link]",
}


def update_payload(update: Any) -> dict[str, Any]:
    """The wire form of one notification: camelCase keys, no empty fields."""
    dump = getattr(update, "model_dump", None)
    if callable(dump):
        return dict(dump(by_alias=True, exclude_none=True, mode="json"))
    if isinstance(update, Mapping):
        return dict(update)
    return {"sessionUpdate": "unknown", "value": str(update)}


def events_for_update(update: Any) -> list[dict[str, Any]]:
    """OpenClaw transcript events for one ``session/update`` (possibly none)."""
    payload = update_payload(update)
    handler = _HANDLERS.get(str(payload.get("sessionUpdate") or ""))
    return handler(payload) if handler is not None else []


def find_model_reported(update: Any) -> str:
    """A model id the agent stated about itself, or ``""``.

    We never configure the subject's model (design section 7), so this is the
    only way a report can say what was actually run.  Silence stays silence --
    the caller records ``unknown`` rather than guessing from the product name.
    """
    return _find_model(update_payload(update))


def message_event(
    role: str, blocks: list[dict[str, Any]], *, usage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One OpenClaw ``message`` event, the shape ``grader.py`` walks."""
    message: dict[str, Any] = {"role": role, "content": blocks}
    if usage:
        message["usage"] = usage
    return {"type": "message", "message": message}


class TranscriptRecorder:
    """Accumulates one attempt's update stream and mirrors it to JSONL.

    Called from the ACP client's ``session_update`` handler, i.e. always on the
    service event loop -- no locking, and nothing here may block.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.events: list[dict[str, Any]] = []
        self.update_count = 0
        self.dropped_events = 0
        self.counts_by_kind: dict[str, int] = {}
        self._model_reported = ""
        self._lines_since_flush = 0
        self._handle = self._open()

    # ── ingest ────────────────────────────────────────────────────────────────

    def record(self, update: Any, *, session_id: str = "") -> dict[str, Any]:
        """Take one notification; returns its payload for the caller to reuse."""
        payload = update_payload(update)
        kind = str(payload.get("sessionUpdate") or "unknown")
        self.update_count += 1
        self.counts_by_kind[kind] = self.counts_by_kind.get(kind, 0) + 1
        if not self._model_reported:
            self._model_reported = _find_model(payload)
        self._append(payload)
        for event in events_for_update(update):
            if len(self.events) >= MAX_EVENTS_IN_MEMORY:
                self.dropped_events += 1
                continue
            self.events.append(event)
        return payload

    def note(self, text: str) -> None:
        """Record an evaluation-side event that the agent never sent.

        Used for what happened *around* the run -- a cancel, a refused
        delegation -- because a reader of the detail view needs to be able to
        tell "the agent said nothing" from "we stopped listening".
        """
        self.events.append(message_event("user", [{"type": "text", "text": text}]))

    @property
    def subject_model_reported(self) -> str:
        return self._model_reported or "unknown"

    def stats(self) -> dict[str, Any]:
        return {
            "updates": self.update_count,
            "events": len(self.events),
            "dropped_events": self.dropped_events,
            "by_kind": dict(sorted(self.counts_by_kind.items())),
            "transcript_path": str(self.path) if self.path else "",
        }

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "TranscriptRecorder":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ── jsonl ─────────────────────────────────────────────────────────────────

    def _open(self) -> Any:
        if self.path is None:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.path.open("a", encoding="utf-8")

    def _append(self, payload: Mapping[str, Any]) -> None:
        if self._handle is None:
            return
        row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        row.update(payload)
        self._handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._lines_since_flush += 1
        if self._lines_since_flush >= _FLUSH_EVERY_LINES:
            self._handle.flush()
            self._lines_since_flush = 0


# ── per-kind mapping ──────────────────────────────────────────────────────────


def _content_events(role: str, prefix: str = "") -> Callable[..., list[dict[str, Any]]]:
    def handler(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        block = _text_block(payload.get("content"))
        if not block["text"]:
            return []
        if prefix:
            block = {"type": "text", "text": f"{prefix} {block['text']}"}
        return [message_event(role, [block])]

    return handler


def _tool_call_events(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``tool_call`` / ``tool_call_update`` → a call event plus its result.

    ACP streams a tool call as an evolving record: the first notification
    carries the input, later ones add status and output.  Emitting the call on
    every update would repeat it in the judge prompt, so only the parts that
    are new get an event.
    """
    events: list[dict[str, Any]] = []
    arguments = _as_mapping(payload.get("rawInput"))
    name = str(payload.get("name") or payload.get("title") or "tool")
    if arguments or payload.get("status") in (None, "pending", "in_progress"):
        events.append(
            message_event(
                "assistant",
                [{"type": "toolCall", "name": name, "arguments": arguments}],
            )
        )
    events.extend(_file_edit_events(payload, name))
    for block in _tool_output_blocks(payload):
        events.append(message_event("toolResult", [block]))
    return events


def _plan_events(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("entries") or payload.get("plan") or []
    lines = []
    for entry in entries if isinstance(entries, list) else []:
        item = entry if isinstance(entry, Mapping) else {}
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- [{item.get('status', 'pending')}] {content}")
    return [message_event("assistant", [{"type": "text", "text": "\n".join(lines)}])] if lines else []


def _file_edit_events(payload: Mapping[str, Any], tool_name: str) -> list[dict[str, Any]]:
    """A ``diff`` tool-call block: the path, never the text it changed.

    File contents come back as artifacts and are judged from there; the
    transcript only needs to show that the agent edited something.
    """
    blocks = []
    for item in payload.get("content") or []:
        edit = item if isinstance(item, Mapping) else {}
        if str(edit.get("type")) == "diff":
            blocks.append(
                {
                    "type": "toolCall",
                    "name": str(edit.get("name") or tool_name or "edit_file"),
                    "arguments": {"path": str(edit.get("path", ""))},
                }
            )
    return [message_event("assistant", blocks)] if blocks else []


def _planned_text(prefix: str, key: str) -> Callable[..., list[dict[str, Any]]]:
    def handler(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        value = str(payload.get(key) or "").strip()
        if not value:
            return []
        return [message_event("assistant", [{"type": "text", "text": f"{prefix} {value}"}])]

    return handler


# ``agent_thought_chunk`` is the agent's scratchpad: kept because it is the only
# evidence a harness that logs nothing else will give us, and prefixed so a
# reader of the detail view can tell it apart from a spoken answer.
_HANDLERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "agent_message_chunk": _content_events("assistant"),
    "agent_thought_chunk": _content_events("assistant", "[thought]"),
    "user_message_chunk": _content_events("user"),
    "tool_call": _tool_call_events,
    "tool_call_update": _tool_call_events,
    "plan": _plan_events,
    "plan_update": _plan_events,
    "plan_removed": _planned_text("[plan removed]", "plan_id"),
    "current_mode_update": _planned_text("[mode]", "current_mode_id"),
    "session_info_update": _planned_text("[title]", "title"),
    # Client-visible UI hints, not conversation.  The detail view renders them
    # from the JSONL; in the judge prompt they would only cost tokens.
    "available_commands_update": lambda payload: [],
    "config_option_update": lambda payload: [],
    "usage_update": lambda payload: [],
}


# ── small helpers ─────────────────────────────────────────────────────────────


def _text_block(content: Any) -> dict[str, str]:
    block = content if isinstance(content, Mapping) else {}
    kind = str(block.get("type") or "text")
    if kind == "text":
        return {"type": "text", "text": str(block.get("text", ""))}
    if kind in _BLOCK_PLACEHOLDERS:
        return {"type": "text", "text": _BLOCK_PLACEHOLDERS[kind]}
    return {"type": "text", "text": f"[{kind}]"} if kind else {"type": "text", "text": ""}


def _tool_output_blocks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_output = payload.get("rawOutput")
    if raw_output not in (None, "", {}, []):
        return [{"type": "text", "text": _flatten(raw_output)}]
    blocks = []
    for item in payload.get("content") or []:
        item = item if isinstance(item, Mapping) else {}
        inner = item.get("content")
        if inner is not None:
            blocks.append(_text_block(inner))
    return [block for block in blocks if block["text"]]


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _find_model(payload: Any) -> str:
    """Depth-first search for a stated model id, ``_meta`` branches first."""
    for key in ("_meta", "fieldMeta"):
        found = _scan_model(_as_mapping(payload.get(key)))
        if found:
            return found
    return _scan_model(payload)


def _scan_model(value: Any, depth: int = 0) -> str:
    if depth > 4 or not isinstance(value, Mapping):
        return ""
    for key, item in value.items():
        if _normalize_key(key) in _MODEL_KEYS and isinstance(item, str) and item.strip():
            return item.strip()
    for item in value.values():
        if isinstance(item, Mapping):
            found = _scan_model(item, depth + 1)
            if found:
                return found
    return ""


def _normalize_key(key: Any) -> str:
    return str(key).replace("_", "").replace("-", "").casefold()
