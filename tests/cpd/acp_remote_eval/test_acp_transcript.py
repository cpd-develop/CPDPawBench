# -*- coding: utf-8 -*-
"""``session/update`` → grader transcript mapping (design section 7).

The judge prompt is built from these events, so the contract that matters is
the one ``pawbench/grader.py:_summarize_transcript`` reads: ``message`` events
with ``text`` / ``toolCall`` blocks and ``toolResult`` turns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pawbench.cpd.acp_remote_eval.acp import transcript as tr
from acp import schema


def texts(events: list[dict[str, Any]]) -> list[str]:
    return [
        block["text"]
        for event in events
        for block in event["message"]["content"]
        if block.get("type") == "text"
    ]


def test_agent_message_chunk_becomes_an_assistant_text_event() -> None:
    update = schema.AgentMessageChunk(content=schema.TextContentBlock(text="done"))
    events = tr.events_for_update(update)
    assert events == [
        {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}
    ]


def test_thoughts_stay_in_the_transcript_but_are_labelled() -> None:
    update = schema.AgentThoughtChunk(content=schema.TextContentBlock(text="maybe csv"))
    assert texts(tr.events_for_update(update)) == ["[thought] maybe csv"]


def test_binary_chunks_record_that_they_happened_not_their_bytes() -> None:
    """A base64 image in the transcript would reach the judge prompt."""
    update = schema.AgentMessageChunk(
        content=schema.ImageContentBlock(data="AAACCCDDD" * 40, mime_type="image/png")
    )
    events = tr.events_for_update(update)
    assert texts(events) == ["[image]"]
    assert "AAACCC" not in json.dumps(events)


def test_empty_chunks_produce_no_event() -> None:
    assert tr.events_for_update(schema.AgentMessageChunk(content=schema.TextContentBlock(text=""))) == []


def tool_started() -> schema.ToolCallStart:
    return schema.ToolCallStart(
        tool_call_id="call-1",
        title="read fixtures/ledger.csv",
        name="read_file",
        status="in_progress",
        raw_input={"path": "fixtures/ledger.csv"},
    )


def test_a_tool_call_becomes_a_toolcall_event_with_its_arguments() -> None:
    events = tr.events_for_update(tool_started())
    block = events[0]["message"]["content"][0]
    assert events[0]["message"]["role"] == "assistant"
    assert block["type"] == "toolCall"
    assert block["name"] == "read_file"
    assert block["arguments"] == {"path": "fixtures/ledger.csv"}


def test_a_completed_tool_call_adds_the_result_without_repeating_the_call() -> None:
    update = schema.ToolCallProgress(
        tool_call_id="call-1",
        status="completed",
        raw_output={"rows": 12},
    )
    events = tr.events_for_update(update)
    assert [event["message"]["role"] for event in events] == ["toolResult"]
    assert any("rows" in text for text in texts(events))


def test_file_edits_keep_the_path_and_drop_the_text() -> None:
    update = schema.ToolCallProgress(
        tool_call_id="call-2",
        name="edit_file",
        status="completed",
        content=[
            schema.FileEditToolCallContent(
                path="output/memo.md", old_text="a" * 40, new_text="b" * 40
            )
        ],
    )
    events = tr.events_for_update(update)
    assert "bbbb" not in json.dumps(events)
    assert [
        block
        for event in events
        for block in event["message"]["content"]
        if block.get("type") == "toolCall"
    ] == [
        {"type": "toolCall", "name": "edit_file", "arguments": {"path": "output/memo.md"}}
    ]


def test_a_plan_becomes_one_bulleted_event() -> None:
    update = schema.AgentPlanUpdate(
        entries=[
            schema.PlanEntry(content="read the csv", priority="medium", status="completed"),
            schema.PlanEntry(content="write the memo", priority="medium", status="in_progress"),
        ]
    )
    assert texts(tr.events_for_update(update)) == [
        "- [completed] read the csv\n- [in_progress] write the memo"
    ]


@pytest.mark.parametrize("kind", ["usage_update", "available_commands_update", "config_option_update"])
def test_ui_and_accounting_notifications_do_not_pollute_the_prompt(kind: str) -> None:
    payload = {"sessionUpdate": kind, "used": 12}
    assert tr.events_for_update(payload) == []


def test_unknown_notifications_are_dropped_rather_than_raised() -> None:
    """A remote agent may use session updates newer than our SDK knows about."""
    assert tr.events_for_update({"sessionUpdate": "compaction_summary_chunk"}) == []


def test_update_payload_serialises_with_wire_names() -> None:
    payload = tr.update_payload(tool_started())
    assert payload["sessionUpdate"] == "tool_call"
    assert payload["toolCallId"] == "call-1"
    assert "fieldMeta" not in payload


# ── model self-report ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "meta,reported",
    [
        ({"model": "qwen3-coder"}, "qwen3-coder"),
        ({"model_id": "qwen3-coder"}, "qwen3-coder"),
        ({"nested": {"modelName": "qwen3-coder"}}, "qwen3-coder"),
        ({"served_model": "qwen3-coder-2026"}, "qwen3-coder-2026"),
    ],
)
def test_the_model_the_agent_states_is_picked_up(meta: dict, reported: str) -> None:
    update = schema.AgentMessageChunk(
        content=schema.TextContentBlock(text="hi"), field_meta=meta
    )
    assert tr.find_model_reported(update) == reported
    with tr.TranscriptRecorder() as recorder:
        recorder.record(update)
        assert recorder.subject_model_reported == reported


def test_a_blank_or_non_string_model_claim_is_not_a_report() -> None:
    assert tr.find_model_reported({"sessionUpdate": "tool_call", "_meta": {"model": "  "}}) == ""
    assert tr.find_model_reported({"sessionUpdate": "tool_call", "_meta": {"model": 7}}) == ""


def test_a_run_that_never_states_a_model_reports_unknown() -> None:
    with tr.TranscriptRecorder() as recorder:
        recorder.record(schema.AgentMessageChunk(content=schema.TextContentBlock(text="hi")))
        assert recorder.subject_model_reported == "unknown"


# ── recorder ──────────────────────────────────────────────────────────────────


def test_recorder_keeps_every_update_in_jsonl_and_the_summary_in_memory(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    with tr.TranscriptRecorder(path) as recorder:
        recorder.record(tool_started(), session_id="s1")
        recorder.record(
            schema.AgentMessageChunk(content=schema.TextContentBlock(text="ok")), session_id="s1"
        )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["sessionUpdate"] for row in rows] == ["tool_call", "agent_message_chunk"]
    assert all(row["at"].endswith("+00:00") for row in rows)
    assert recorder.update_count == 2
    assert len(recorder.events) == 2
    assert recorder.stats()["by_kind"] == {"agent_message_chunk": 1, "tool_call": 1}


def test_recorder_creates_its_directory_and_appends_across_reopens(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "transcript.jsonl"
    for _ in range(2):
        with tr.TranscriptRecorder(path) as recorder:
            recorder.record({"sessionUpdate": "plan", "entries": []})
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_a_flood_is_capped_in_memory_but_not_on_disk(tmp_path: Path, monkeypatch) -> None:
    """Four concurrent jobs must not turn a chatty agent into an OOM."""
    monkeypatch.setattr(tr, "MAX_EVENTS_IN_MEMORY", 3)
    path = tmp_path / "transcript.jsonl"
    with tr.TranscriptRecorder(path) as recorder:
        for index in range(10):
            recorder.record(
                schema.AgentMessageChunk(content=schema.TextContentBlock(text=f"chunk {index}"))
            )
    assert len(recorder.events) == 3
    assert recorder.stats()["dropped_events"] == 7
    assert len(path.read_text(encoding="utf-8").splitlines()) == 10


def test_notes_mark_what_the_agent_never_sent() -> None:
    with tr.TranscriptRecorder() as recorder:
        recorder.note("[evaluation] run canceled by submitter")
    assert texts(recorder.events) == ["[evaluation] run canceled by submitter"]
    assert recorder.update_count == 0
