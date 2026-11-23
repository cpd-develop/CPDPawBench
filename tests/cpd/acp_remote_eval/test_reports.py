# -*- coding: utf-8 -*-
"""What a reader is shown about a job -- and what each sensitivity tier hides.

``test_jobs.py`` and ``test_runner.py`` answer whether a job moved.  This module
answers the second question, the one a submitter asks the dashboard and then
forwards to the team that owns the agent: what did the subject do, what did it
score, which file do I hand over.

The tiers are the thing under test, so most cases assert in both directions --
a field present at ``full`` *and* absent at ``shared``.  A one-sided test passes
when somebody widens a tier by accident, and that is the failure mode that
matters, because ``shared`` is the document a submitter sends to the people
being evaluated.  The report-file cases cover the lifecycle around it (render
once per fingerprint, presigned link, zip only where files are not being
forwarded), and the transcript cases cover the paging that keeps one read from
becoming the whole stream.

Rows are seeded through the real store and uploaded files through the real
exchange -- token, quarantine, fsync, artifact row -- because the full tier's
download links point at paths *it* chose; a hand-written ``artifacts`` row would
test a file layout the service never produces.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import logging
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from pawbench.cpd.acp_remote_eval.service import reports as reports_mod
from pawbench.cpd.acp_remote_eval.service.api import ControlPlane, create_app
from pawbench.cpd.acp_remote_eval.service.attempts import AttemptRegistry
from pawbench.cpd.acp_remote_eval.service.auth import StaticConfigVerifier, add_subject
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetService
from pawbench.cpd.acp_remote_eval.service.jobs import JobService
from pawbench.cpd.acp_remote_eval.service.queue import JobQueue, QueueLimits
from pawbench.cpd.acp_remote_eval.service.reports import (
    DEFAULT_TRANSCRIPT_PAGE,
    MAX_TRANSCRIPT_PAGE,
    SENSITIVITY_FULL,
    SENSITIVITY_SHARED,
    ReportError,
    Reports,
)
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import (
    NOW,
    dataset_service,
    eval_config,
    job_row,
    leakage_rules,
    make_exchange,
    write_task,
)

JOB = "job-1"
ACP_URL = "http://127.0.0.1:9000/rpc"
TASKS = ("mail_a", "mail_b", "chart_c")
REPO_ROOT = Path(__file__).resolve().parents[3]

#: ``mail_b`` is the one judge task in the catalogue, so it is the only task whose
#: rubric text exists to be leaked -- see
#: :func:`test_the_rubric_text_only_ever_reaches_the_full_tier`.
RUBRIC_MAIL_B = "Award 1.0 when the reply is polite."

#: The two fixtures ``mail_a`` hands over, and the bytes of the one that is not
#: text.  A one-pixel PNG is enough: the preview decides by extension, and an
#: image the browser could not draw would prove nothing about the route.
NOTE_DEST = "fixtures/note.txt"
NOTE_TEXT = "content of note.txt"
SHOT_DEST = "fixtures/shot.png"
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)

#: The 23 keys every recorded leaderboard document in ``submissions/`` carries.
#: Spelled out rather than read from one file, because it is the contract a
#: remote run has to keep; the files are checked against it as corroboration.
LEADERBOARD_KEYS = frozenset(
    {
        "automated",
        "by_capability",
        "by_category",
        "by_channel",
        "by_complexity",
        "by_environment",
        "by_grading",
        "by_modality",
        "by_scenario",
        "by_scenario_top",
        "by_source",
        "by_subcategory",
        "harness",
        "judge",
        "missing_metadata",
        "model",
        "overall",
        "run",
        "tasks",
        "tasks_errored",
        "tasks_missing",
        "tasks_total",
        "updated",
    }
)


@dataclass
class Env:
    """The four objects a reader needs, plus the directories they read from."""

    store: Store
    exchange: Any
    datasets: DatasetService
    reports: Reports
    config: Any
    tmp_path: Path
    builtin_root: Path


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    """Three tasks whose labels differ on every slice dimension at once.

    ``mail_a`` deliberately carries two capabilities, a channel and a
    subcategory: a task like that is why the slices are buckets rather than
    one-choice-per-task, and it is only provable with real front matter.  Its
    channel is ``image`` and its type ``multimodal`` because that is the real
    taxonomy (``references/taxonomy.md``) -- and because a task carrying both is
    the only way to see the two slices stay apart.

    ``mail_a`` also carries two fixtures, one of each shape the preview has to
    answer for: a text file to show, and a PNG to draw.  ``chart_c`` carries
    none, so every attachment test has a task that must report nothing rather
    than an empty section.
    """
    root = tmp_path / "builtin"
    write_task(
        root,
        "mail_a",
        scenario="Office_Productivity/Email",
        capability=["Tool_Use", "Retrieval"],
        modality="multimodal",
        channels=("image",),
        subcategory="GitHub",
        grading_type="automated",
        fixtures=("note.txt", "shot.png"),
    )
    # The helper writes text into every fixture; the extension is what the
    # preview sniffs for an image, and a real PNG header keeps the file honest
    # for anything downstream that looks at the bytes.
    (root / "fixtures" / "shot.png").write_bytes(PNG_BYTES)
    write_task(
        root,
        "mail_b",
        scenario="Office_Productivity/Email",
        capability="Tool_Use",
        complexity="L3",
        grading_type="llm_judge",
        rubric=RUBRIC_MAIL_B,
    )
    write_task(
        root,
        "chart_c",
        scenario="Data_Analytics/Visualization",
        capability="Code",
        complexity="L2",
        grading_type="automated",
        subcategory="Spreadsheets",
    )
    return root


@pytest.fixture()
def env(store: Store, tmp_path: Path, builtin_root: Path) -> Env:
    config = eval_config(tmp_path, builtin_root=builtin_root)
    datasets = dataset_service(store, config)
    exchange = make_exchange(store, tmp_path, now=NOW)
    reports = Reports(store, exchange, datasets, clock=exchange.clock)
    datasets.create_builtin_view(
        dataset_id="ds_pilot",
        name="Pilot set",
        owner="dev-1",
        filter_spec={"task_ids": list(TASKS)},
    )
    store.insert_job(
        job_row(
            JOB,
            acp_url=ACP_URL,
            status="finished",
            product="qwenpaw",
            purpose="pilot",
            env_fingerprint={"os": "linux"},
            finished_at="2026-11-10T02:20:00+00:00",
        )
    )
    store.insert_job_dataset(
        {
            "job_id": JOB,
            "dataset_id": "ds_pilot",
            "dataset_kind": "builtin_view",
            "requested_by": "dev-1",
            "resolved_task_ids": list(TASKS),
        }
    )
    store.insert_job_tasks(
        [
            {
                "job_id": JOB,
                "task_id": task_id,
                "attempt": 1,
                "status": "pending",
                "grading_type": grading_type,
            }
            for task_id, grading_type in zip(TASKS, ("automated", "llm_judge", "automated"))
        ]
    )
    return Env(
        store=store,
        exchange=exchange,
        datasets=datasets,
        reports=reports,
        config=config,
        tmp_path=tmp_path,
        builtin_root=builtin_root,
    )


# ── seeding helpers ───────────────────────────────────────────────────────────


def finish(env: Env, task_id: str, score: float | None, **fields: Any) -> None:
    """Close one task row the way the runner does, so the report reads live rows."""
    values: dict[str, Any] = {
        "status": "finished",
        "score": score,
        "started_at": "2026-11-10T02:00:00+00:00",
        "finished_at": "2026-11-10T02:04:00+00:00",
        "duration_s": 240.0,
        "subject_model_reported": "subject-model-1",
        "workspace_path": str(env.tmp_path / "work" / task_id),
    }
    values.update(fields)
    env.store.update_job_task(JOB, task_id, 1, **values)


def score_all(env: Env, scores: dict[str, float | None]) -> None:
    for task_id, score in scores.items():
        finish(env, task_id, score)


def task_at(detail: dict[str, Any], task_id: str) -> dict[str, Any]:
    """One task entry by id -- ``list_job_tasks`` orders by task_id, not by the
    order the job ran them in, so an index here would be a coincidence."""
    return next(task for task in detail["tasks"] if task["task_id"] == task_id)


def upload(env: Env, task_id: str, path: str, data: bytes = b"result-bytes") -> None:
    """One artifact through the data plane, so the row and the bytes agree."""
    token, _ = env.exchange.tokens.issue(
        JOB, task_id, 1, ttl_seconds=600, max_uploads=4, now=env.exchange.clock.now()
    )
    env.exchange.accept_artifact(
        job_id=JOB,
        task_id=task_id,
        attempt=1,
        token=token,
        raw_path=path,
        data=data,
    )


def write_transcript(
    env: Env, rows: list[dict[str, Any]], task_id: str = "mail_a", attempt: int = 1
) -> Path:
    path = env.exchange.attempt_dir(JOB, task_id, attempt) / "transcript.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def message_chunk(text: str) -> dict[str, Any]:
    """One ``agent_message_chunk`` as the recorder writes it: one block, no list."""
    return {
        "at": "2026-11-10T02:01:00+00:00",
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": text},
    }


def tool_call(
    title: str, raw_input: dict[str, Any], *, output: str = "42 rows read"
) -> dict[str, Any]:
    return {
        "at": "2026-11-10T02:01:05+00:00",
        "sessionUpdate": "tool_call",
        "toolCallId": "call-1",
        "title": title,
        "status": "completed",
        "rawInput": raw_input,
        # The wrapped block ACP actually sends for a tool result: the text sits
        # one level deeper than in a message chunk, which is what the timeline
        # summariser has to know.
        "content": [{"type": "content", "content": {"type": "text", "text": output}}],
    }


def plan_update(steps: int) -> dict[str, Any]:
    return {
        "at": "2026-11-10T02:01:02+00:00",
        "sessionUpdate": "plan_update",
        "entries": [{"content": f"step {index}", "status": "pending"} for index in range(steps)],
    }


def _artifact_reads(store: Store, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Every ``list_artifacts`` call as ``(job_id, task_id)``, in order.

    Counted rather than timed because the thing under test is how many reads one
    document costs: a three-task job's three identical queries are milliseconds
    and a poll multiplied, and no stopwatch tells them apart.
    """
    calls: list[tuple[str, Any]] = []
    real = store.list_artifacts

    def spy(job_id: str, task_id: str | None = None, *, kind: str | None = None) -> list:
        calls.append((job_id, task_id))
        return real(job_id, task_id, kind=kind)

    monkeypatch.setattr(store, "list_artifacts", spy)
    return calls


# ── the two tiers ─────────────────────────────────────────────────────────────


def test_shared_detail_shows_the_prompt_and_hides_the_rubric(env: Env) -> None:
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})

    shared = task_at(env.reports.job_detail(JOB, SENSITIVITY_SHARED), "mail_a")
    full = task_at(env.reports.job_detail(JOB, SENSITIVITY_FULL), "mail_a")

    # What the team being evaluated needs in order to act on the result.
    assert shared["prompt"] == "Write output/result.txt with the answer."
    assert shared["labels"]["scenario"] == "Office_Productivity/Email"
    assert shared["score"] == 0.5
    assert shared["duration_s"] == 240.0
    assert shared["subject_model_reported"] == "subject-model-1"
    # What stays behind: the answer-adjacent text and our own paths.  The list is
    # the scanner's, so the tier this case checks and the case that greps a
    # captured response body cannot drift apart.  Keys only, and deliberately so:
    # ``mail_a`` is graded by a checker, so its rubric excerpt is ``None`` here by
    # design -- the case below reads a judge task and checks the text itself.
    for field in sorted(leakage_rules().SHARED_ONLY_FIELDS):
        assert field not in shared, field
        assert field in full, field


def test_the_rubric_text_only_ever_reaches_the_full_tier(env: Env) -> None:
    """K2's headline field followed as text, not as a key name.

    A key-presence check passes on a task whose rubric is ``None`` -- and every
    task in this catalogue except ``mail_b`` is graded by a checker, so that is
    the usual case here.  This is the one place the answer text itself is
    followed, and it is checked in both directions: a shared document that does
    not carry it, and the same renderer at the same format on the full tier that
    does.  Without the second half the first half passes for free.

    The markdown renderer is deliberately not asserted on: it never prints the
    excerpt, so "absent from the md" would prove nothing about the trimming.
    """
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})

    shared = env.reports.job_detail(JOB, SENSITIVITY_SHARED)
    full = env.reports.job_detail(JOB, SENSITIVITY_FULL)
    assert task_at(full, "mail_b")["rubric_excerpt"] == RUBRIC_MAIL_B

    body = json.dumps(shared, ensure_ascii=False)
    assert RUBRIC_MAIL_B not in body
    assert "polite" not in body, "a paraphrase into another key is just as loud"

    for sensitivity, expected in ((SENSITIVITY_SHARED, False), (SENSITIVITY_FULL, True)):
        link = env.reports.report(JOB, fmt="json", sensitivity=sensitivity)
        written = env.exchange.report_path(JOB, str(link["filename"])).read_text("utf-8")
        assert ("polite" in written) is expected, sensitivity


def test_full_detail_carries_the_judge_reasoning_and_download_links(env: Env) -> None:
    finish(env, "mail_b", 0.25, judge_notes=["tone"], judge_served_models=["free/router-a"])
    upload(env, "mail_b", "output/result.csv")

    entry = task_at(env.reports.job_detail(JOB, SENSITIVITY_FULL), "mail_b")
    shared_entry = task_at(env.reports.job_detail(JOB, SENSITIVITY_SHARED), "mail_b")

    assert entry["judge_notes"] == ["tone"]
    assert entry["judge_served_models"] == ["free/router-a"]
    assert entry["expected_behavior"] == "A file is written."
    assert entry["artifacts"] == shared_entry["artifacts"]
    assert entry["downloads"] == [
        {
            "path": "output/result.csv",
            "href": f"/v1/jobs/{JOB}/tasks/mail_b/attempts/1/artifacts",
            "query": {"path": "output/result.csv"},
        }
    ]


def test_job_detail_reads_the_artifact_rows_once_for_a_whole_job(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One read for the document, however many tasks it walks (L18).

    ``GET /v1/jobs/{id}/detail`` is the route the dashboard polls, and shaping
    each task's ``artifacts`` and ``downloads`` from a query of its own made that
    poll cost one read per task.  The fix is one read, not one less answer -- so
    the case checks the count *and* that every task still gets its own slice,
    including the one with nothing uploaded.  The zip shares the helper, so it is
    measured too: bundling a job costs one read more than its document, not one
    per task.
    """
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})
    upload(env, "mail_a", "output/plot.png")
    upload(env, "mail_b", "output/result.csv")

    calls = _artifact_reads(env.store, monkeypatch)
    detail = env.reports.job_detail(JOB, SENSITIVITY_FULL)

    assert [call[1] for call in calls] == [None], f"one artifact read per task: {calls}"
    assert task_at(detail, "mail_a")["artifacts"][0]["path"] == "output/plot.png"
    assert task_at(detail, "mail_b")["downloads"][0]["path"] == "output/result.csv"
    assert task_at(detail, "chart_c")["artifacts"] == []
    assert task_at(detail, "chart_c")["downloads"] == []

    document_reads = len(calls)
    env.reports.report(JOB, fmt="zip", sensitivity=SENSITIVITY_FULL)

    assert calls[document_reads:] == [(JOB, None), (JOB, None)], (
        f"the bundle re-read per task: {calls[document_reads:]}"
    )


def test_no_tier_publishes_the_grading_code(env: Env) -> None:
    """The answer key is not a sensitivity level, so neither document may hold it."""
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})

    for tier in (SENSITIVITY_SHARED, SENSITIVITY_FULL):
        rendered = json.dumps(env.reports.job_detail(JOB, tier))

        for field in sorted(leakage_rules().ANSWER_KEY_FIELDS):
            assert field not in rendered, f"{tier} detail published {field}"


def test_the_forwardable_documents_pass_the_leakage_scan(env: Env) -> None:
    """K2: everything a submitter can hand over, run through the scanner's rules.

    The scanner is a command line first -- someone points it at a captured
    response before forwarding it -- so the case scans what that person would
    scan: the payloads and the rendered files, at both tiers, rather than a
    re-serialization the service never wrote.

    The two halves prove different things, and only one of them is about this
    service.  The clean half is the production check -- it goes red when the
    trimming in ``reports.py`` stops trimming.  The planted half checks the
    scanner itself still fires: a vocabulary that silently matches nothing would
    keep the first half green forever, which is the failure mode of every grep
    based guard.
    """
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})
    rules = leakage_rules()

    payloads = {
        "shared detail": (rules.FORWARDABLE, env.reports.job_detail(JOB, SENSITIVITY_SHARED)),
        "results": (rules.FORWARDABLE, env.reports.results(JOB)),
        "full detail": (rules.INTERNAL, env.reports.job_detail(JOB, SENSITIVITY_FULL)),
    }
    bodies: dict[str, tuple[str, str]] = {}
    for sensitivity in (SENSITIVITY_SHARED, SENSITIVITY_FULL):
        tier = rules.FORWARDABLE if sensitivity == SENSITIVITY_SHARED else rules.INTERNAL
        for fmt in ("md", "html", "json"):
            link = env.reports.report(JOB, fmt=fmt, sensitivity=sensitivity)
            path = env.exchange.report_path(JOB, str(link["filename"]))
            bodies[f"{fmt} report @ {sensitivity}"] = (tier, path.read_text(encoding="utf-8"))

    findings = {
        name: rules.find_in_payload(body, tier) for name, (tier, body) in payloads.items()
    }
    findings.update(
        {name: rules.find_in_text(body, tier) for name, (tier, body) in bodies.items()}
    )
    assert {name: hits for name, hits in findings.items() if hits} == {}

    planted = rules.find_in_payload(
        {"tasks": [{"task_id": "mail_a", "rubric_excerpt": "awards 0.5 for tone"}]},
        rules.FORWARDABLE,
    )
    assert "key rubric_excerpt (at tasks[0].rubric_excerpt)" in planted, planted
    assert rules.find_in_text("## Expected behavior\n\nA file is written.\n") == [
        "marker heading (line 1)"
    ]
    # The other half of the rule: a prompt that talks about marking schemes is
    # not a leak, and a scan that says otherwise gets ignored the next time it
    # fires on a real report.
    assert rules.find_in_text("## How to write a rubric for the essay\n") == []


def test_a_scan_that_never_ran_does_not_report_a_clean_bill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit code 0 has to mean "these documents are clean", not "I found nothing".

    Pointed at a typo'd path the scanner used to print ``0 finding(s)`` and leave,
    which is the one answer a person forwarding a report cannot tell apart from
    safety.  So the three outcomes are separate codes, and a finding is actionable
    without being a copy: it names the field and the line it is on in the file as
    written, never its value -- the value may be the rubric, and a CI console is
    not where an answer sheet belongs.
    """
    rules = leakage_rules()
    out = tmp_path / "out"
    out.mkdir()

    assert rules.main([str(tmp_path / "typo")]) == 2
    assert rules.main([str(out)]) == 2

    (out / "report.md").write_text("# Job job-1\n\n- score: 0.5\n", encoding="utf-8")
    assert rules.main([str(out)]) == 0

    capture = out / "detail.json"
    capture.write_text(
        '{"tasks": [{"rubric_excerpt": "awards 0.5 for tone"}]}', encoding="utf-8"
    )
    assert rules.main([str(out)]) == 1

    assert rules.scan_file(capture) == [
        "field rubric_excerpt (line 1)",
        "key rubric_excerpt (at tasks[0].rubric_excerpt)",
    ], "one line on disk, one line in the finding"

    captured = capsys.readouterr()
    assert "rubric_excerpt" in captured.err
    assert "tone" not in captured.err


def test_a_misspelled_sensitivity_is_refused_not_defaulted(env: Env) -> None:
    """Quietly serving ``shared`` to a caller who typed ``fulll`` is the leak.

    The same reason ``FULL`` in caps is accepted: a tier name is a word, and
    refusing the casing would only teach callers to hard-code lowercase.
    """
    with pytest.raises(ReportError) as refused:
        env.reports.job_detail(JOB, "fulll")

    assert refused.value.code == "sensitivity_unknown"
    assert sorted(refused.value.details["allowed"]) == ["full", "shared"]

    assert env.reports.job_detail(JOB, "FULL")["sensitivity"] == SENSITIVITY_FULL


def test_detail_of_a_job_that_is_not_there_says_so(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.job_detail("job-nope", SENSITIVITY_SHARED)

    assert refused.value.code == "job_not_found"


def test_detail_lists_the_snapshots_the_job_ran_from(env: Env) -> None:
    detail = env.reports.job_detail(JOB, SENSITIVITY_SHARED)

    assert detail["sources"] == [
        {
            "dataset_id": "ds_pilot",
            "dataset_kind": "builtin_view",
            "requested_by": "dev-1",
            "task_count": 3,
            "task_ids": ["mail_a", "mail_b", "chart_c"],
        }
    ]
    assert detail["progress"]["total"] == 3
    assert detail["window"] == {"kind": "now", "not_before": None, "not_after": None}


# ── results: the leaderboard shape ────────────────────────────────────────────


def test_results_has_every_key_a_recorded_submission_carries(env: Env) -> None:
    score_all(env, {"mail_a": 0.5, "mail_b": 0.75, "chart_c": 1.0})

    payload = env.reports.results(JOB)

    assert LEADERBOARD_KEYS <= set(payload)
    samples = sorted(REPO_ROOT.glob("submissions/*.json"))
    assert samples, "expected the recorded submissions to compare against"
    for sample in samples:
        recorded = json.loads(sample.read_text(encoding="utf-8"))
        assert set(recorded) - set(payload) == set(), sample.name


def test_a_task_with_two_capabilities_is_counted_in_both_buckets(env: Env) -> None:
    """The slice asks "where is this subject weak", so a task joins every bucket
    it belongs to instead of being assigned to one -- and the modality buckets
    stay apart, because a channel is not a modality."""
    score_all(env, {"mail_a": 0.4, "mail_b": 0.8, "chart_c": 1.0})

    results = env.reports.results(JOB)

    assert results["by_capability"] == {"Code": 1.0, "Retrieval": 0.4, "Tool_Use": 0.6}
    assert results["by_scenario"] == {
        "Data_Analytics/Visualization": 1.0,
        "Office_Productivity/Email": 0.6,
    }
    assert results["by_scenario_top"] == {"Data_Analytics": 1.0, "Office_Productivity": 0.6}
    assert results["by_subcategory"] == {"GitHub": 0.4, "Spreadsheets": 1.0}
    assert results["by_channel"] == {"image": 0.4}
    # ``mail_a`` is both a channel and a modality: the union that a catalogue
    # filter wants would put ``image`` in here as well.
    assert results["by_modality"] == {"multimodal": 0.4, "text": 0.9}
    assert results["by_complexity"] == {"L1": 0.4, "L2": 1.0, "L3": 0.8}
    assert results["by_grading"] == {"automated": 0.7, "llm_judge": 0.8}
    assert results["by_category"] == {"office": 0.7333}


def test_tasks_that_never_scored_stay_out_of_the_mean(env: Env) -> None:
    """A skipped task is the service's fault, so counting it as a zero turns an
    outage into a capability result (design section 7)."""
    finish(env, "mail_a", 1.0)
    finish(env, "mail_b", None, status="missing", failure_reason="no_artifacts")
    finish(env, "chart_c", None, status="skipped", failure_reason="deadline")

    results = env.reports.results(JOB)
    detail = env.reports.job_detail(JOB, SENSITIVITY_SHARED)

    assert results["overall"] == 1.0
    assert results["tasks"] == 1
    assert results["tasks_total"] == 3
    assert results["tasks_missing"] == 1
    assert results["missing_metadata"] == 1
    assert detail["progress"] == {
        "total": 3,
        "by_status": {"finished": 1, "missing": 1, "skipped": 1},
        "scored": 1,
    }
    assert detail["score"] == {"mean": 1.0, "count": 1, "best": 1.0, "worst": 1.0}


def test_results_says_what_the_subjects_claimed_and_where_they_ran(env: Env) -> None:
    finish(env, "mail_a", 1.0, subject_model_reported="qwen3.7-max")
    finish(env, "mail_b", 1.0, subject_model_reported="glm-5.1")
    finish(env, "chart_c", None, subject_model_reported=None)

    results = env.reports.results(JOB)

    # The third subject never named its model; the list is what was claimed, so
    # a silent entry would read as if it had claimed something.
    assert results["model"] == "glm-5.1, qwen3.7-max"
    assert results["harness"] == "qwenpaw"
    assert results["environment"] == {
        "fingerprint": {"os": "linux"},
        "acp_url": ACP_URL,
        "product": "qwenpaw",
    }
    assert results["task_scores"][0] == {
        "task_id": "chart_c",
        "attempt": 1,
        "status": "finished",
        "score": None,
        "grading_type": "automated",
    }


def test_a_forwardable_report_drops_the_endpoints_credential(env: Env) -> None:
    """``shared`` is the tier a submitter sends to the team being evaluated.

    An ACP address that carries its key as ``user:token@host`` or as ``?key=``
    passes the endpoint check -- that is exactly how a hosted agent is reached --
    so the credential has to be cut where the payload is built.  Leaving it in
    would hand the subject team their own secret back, in a document designed to
    be forwarded, and the runner still gets the full address from the job row.
    """
    secret = "hunter2-key"
    env.store.update_job(
        JOB, acp_url=f"http://agent:{secret}@eval.example.com/rpc?key={secret}&v=2"
    )

    detail = env.reports.job_detail(JOB, sensitivity=SENSITIVITY_SHARED)
    results = env.reports.results(JOB)

    assert detail["acp_url"] == "http://eval.example.com/rpc"
    assert results["environment"]["acp_url"] == "http://eval.example.com/rpc"
    assert secret not in json.dumps(detail)
    assert secret not in json.dumps(results)

    for fmt in ("md", "json"):
        link = env.reports.report(JOB, fmt=fmt, sensitivity=SENSITIVITY_SHARED)
        written = env.exchange.report_path(JOB, str(link["filename"])).read_text(
            encoding="utf-8"
        )
        assert secret not in written, f"{fmt} quoted the endpoint credential"


# ── one task ──────────────────────────────────────────────────────────────────


def test_task_detail_defaults_to_the_latest_attempt(env: Env) -> None:
    finish(env, "mail_a", 0.2)
    env.store.insert_job_tasks(
        [{"job_id": JOB, "task_id": "mail_a", "attempt": 2, "status": "pending"}]
    )
    env.store.update_job_task(JOB, "mail_a", 2, status="finished", score=0.9)

    latest = env.reports.task_detail(JOB, "mail_a", SENSITIVITY_SHARED)
    first = env.reports.task_detail(JOB, "mail_a", SENSITIVITY_SHARED, attempt=1)

    assert (latest["attempt"], latest["score"]) == (2, 0.9)
    assert (first["attempt"], first["score"]) == (1, 0.2)
    assert latest["transcript"]["total_events"] == 0


def test_an_attempt_that_was_never_recorded_is_not_found(env: Env) -> None:
    finish(env, "mail_a", 0.2)

    with pytest.raises(ReportError) as refused:
        env.reports.task_detail(JOB, "mail_a", SENSITIVITY_SHARED, attempt=7)

    assert refused.value.code == "task_not_found"


def test_a_dataset_that_disappeared_still_leaves_a_readable_report(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """The rows are the result; the catalogue is a convenience.

    A dataset deleted after the job ran must not blank the report -- and must
    not fail quietly either, which is what the warning line is for.
    """
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})
    env.store.insert_job_dataset(
        {
            "job_id": JOB,
            "dataset_id": "ds_gone",
            "dataset_kind": "custom",
            "requested_by": "dev-1",
            "resolved_task_ids": ["mail_a"],
        }
    )

    with caplog.at_level(logging.WARNING):
        detail = env.reports.job_detail(JOB, SENSITIVITY_SHARED)

    assert [task["score"] for task in detail["tasks"]] == [0.5, 0.5, 0.5]
    # The names come off the log record, not the rendered line: the dataset id is
    # structured context, and a message that only says "incomplete" is the
    # one-line-never-minds log the logging rule exists to keep out.
    warned = [r for r in caplog.records if "report sources incomplete" in r.getMessage()]
    assert [(r.job_id, r.dataset_id) for r in warned] == [(JOB, "ds_gone")]


# ── transcript ────────────────────────────────────────────────────────────────


def test_transcript_pages_and_never_carries_a_text_body(env: Env) -> None:
    secret = "the subject's own file contents, " * 4
    write_transcript(
        env,
        [
            message_chunk(secret),
            tool_call("Read inbox.csv", {"path": "fixtures/inbox.csv"}),
            plan_update(3),
        ],
    )

    page = env.reports.transcript(JOB, "mail_a", limit=2)

    assert page["total_events"] == 3
    assert page["cursor"] == 0
    assert [event["kind"] for event in page["events"]] == ["agent_message_chunk", "tool_call"]
    assert page["next_cursor"] == 2
    assert secret not in json.dumps(page)
    # Sizes instead of text; the tool's identity instead of its arguments.
    assert page["events"][0]["chars"] == len(secret)
    assert page["events"][1]["tool"] == "Read inbox.csv"
    assert page["events"][1]["status"] == "completed"
    assert page["events"][1]["result_chars"] == len("42 rows read")
    assert page["events"][1]["args"] == {"path": "fixtures/inbox.csv"}

    rest = env.reports.transcript(JOB, "mail_a", cursor=2, limit=2)
    assert rest["events"] == [{"kind": "plan_update", "at": plan_update(3)["at"], "steps": 3}]
    assert rest["next_cursor"] is None


def test_a_long_argument_is_previewed_not_copied(env: Env) -> None:
    body = "print('hello')\n" * 40
    write_transcript(env, [tool_call("Write script.py", {"contents": body, "path": "a.py"})])

    args = env.reports.transcript(JOB, "mail_a")["events"][0]["args"]

    assert args["path"] == "a.py"
    kept = reports_mod._ARG_PREVIEW_CHARS
    assert args["contents"] == f"{body[:kept]}… +{len(body) - kept} chars"
    assert body not in json.dumps(args)


def test_more_arguments_than_shown_are_counted_not_dropped(env: Env) -> None:
    many = {f"field_{index}": str(index) for index in range(15)}
    write_transcript(env, [tool_call("Search", many)])

    args = env.reports.transcript(JOB, "mail_a")["events"][0]["args"]

    assert len([key for key in args if key != "…"]) == 12
    assert args["…"] == "3 more field(s)"


def test_transcript_limit_is_capped_at_one_page(env: Env) -> None:
    write_transcript(env, [message_chunk("x") for _ in range(30)])

    page = env.reports.transcript(JOB, "mail_a", limit=MAX_TRANSCRIPT_PAGE * 10)

    assert page["limit"] == MAX_TRANSCRIPT_PAGE
    assert len(page["events"]) == 30
    assert page["next_cursor"] is None


def test_a_run_without_a_transcript_reads_as_empty(env: Env) -> None:
    finish(env, "mail_a", None, status="failed", failure_reason="agent_refused")

    page = env.reports.transcript(JOB, "mail_a")

    assert page == {
        "task_id": "mail_a",
        "attempt": 1,
        "cursor": 0,
        "limit": DEFAULT_TRANSCRIPT_PAGE,
        "total_events": 0,
        "next_cursor": None,
        "events": [],
        "transcript_state": "absent",
        "damaged_events": 0,
    }


def test_an_unknown_task_in_a_transcript_is_not_found_rather_than_empty(env: Env) -> None:
    """The route answers for the task it was given, so a typo has to say so."""
    write_transcript(env, [message_chunk("x")], task_id="mail_b")

    with pytest.raises(ReportError) as refused:
        env.reports.transcript(JOB, "mail_zzz")

    assert refused.value.code == "task_not_found"


def test_a_damaged_transcript_costs_a_count_and_not_the_page(env: Env) -> None:
    """A truncated write or a stray byte damages its line, not the run.

    Both shapes come from outside this service: a harness killed mid-flush leaves
    a half-written last line, and a stream written byte by byte can carry one byte
    that is not valid UTF-8.  Each used to answer 500 for the whole page, which is
    the page the reader needs in order to work out why the run failed.
    """
    path = write_transcript(env, [message_chunk("first")])
    with path.open("ab") as handle:
        handle.write(
            b'{"sessionUpdate":"agent_message_chunk","content":{"type":"text",'
            b'"text":"caf\xe9"}}\n'
        )
        handle.write(b'{"sessionUpdate": "tool_call", "title": "Read\n')
        handle.write(b"[1, 2, 3]\n")

    page = env.reports.transcript(JOB, "mail_a")

    assert page["total_events"] == 4
    assert page["transcript_state"] == "ok"
    assert [event["kind"] for event in page["events"]] == ["agent_message_chunk"] * 2
    assert page["damaged_events"] == 2
    # The undecodable byte became one replacement character instead of taking its
    # line with it -- and the page still round-trips through JSON, which a lone
    # surrogate would not survive on the way out of the route.
    assert page["events"][1]["chars"] == 4
    assert json.loads(json.dumps(page)) == page


def test_a_damaged_line_is_stepped_over_and_not_reread(env: Env) -> None:
    """The cursor counts lines rather than events, or page two repeats page one.

    At a page size of one, a cursor advanced only by the events made hands back
    the same broken line forever.  The reader sees a transcript that never ends
    and no way to tell that it is stuck.
    """
    path = write_transcript(env, [])
    with path.open("ab") as handle:
        handle.write(b'{"sessionUpdate": "tool_call", "title": "Read\n')
        handle.write(b'{"sessionUpdate":"plan_update","entries":[1,2]}\n')

    first = env.reports.transcript(JOB, "mail_a", limit=1)
    second = env.reports.transcript(JOB, "mail_a", cursor=first["next_cursor"], limit=1)

    assert (first["events"], first["damaged_events"], first["next_cursor"]) == ([], 1, 1)
    assert [event["kind"] for event in second["events"]] == ["plan_update"]
    assert second["next_cursor"] is None


def test_a_transcript_the_service_cannot_open_says_which_of_the_two_it_is(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """An unreadable file has to be told apart from a run that wrote nothing.

    A page of empty events is the honest answer for both, so the distinction lives
    in ``transcript_state`` and in the log line: the first is a fact about the
    subject, the second is a fact about this deployment's disk, and only the
    second is somebody's action item.
    """
    attempt_dir = env.exchange.attempt_dir(JOB, "mail_a", 1)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "transcript.jsonl").mkdir()

    with caplog.at_level(logging.WARNING):
        page = env.reports.transcript(JOB, "mail_a")

    assert page["transcript_state"] == "unreadable"
    assert page["events"] == []
    told = [record for record in caplog.records if hasattr(record, "transcript_state")]
    assert [(r.job_id, r.task_id, r.attempt, r.levelno) for r in told] == [
        (JOB, "mail_a", 1, logging.WARNING)
    ]


def test_a_line_that_is_too_deep_to_parse_costs_a_count_and_not_the_page(
    env: Env,
) -> None:
    """Nesting deeper than the interpreter parses is bad input, not a bug here.

    ``json`` raises ``RecursionError`` -- not a ``ValueError`` -- on a line nested
    past its limit, and a transcript line is partly the subject's own doing: its
    tool calls are what made the payload deep.  Caught with the other bad shapes,
    one line costs a count; left out, it 500s the other two hundred lines.
    """
    path = write_transcript(env, [message_chunk("first")])
    with path.open("ab") as handle:
        handle.write(b'{"sessionUpdate":"plan_update","entries":')
        # Measured on this interpreter: at the default limit of 1000 the C scanner
        # parses 5000 levels without complaining and raises at 20000, so the depth
        # has to sit well past the point where it gives up -- a shallower line
        # would be a passing test that never reached the branch.
        handle.write(b"[" * 50000)
        handle.write(b"]" * 50000 + b"}\n")

    page = env.reports.transcript(JOB, "mail_a")

    assert page["transcript_state"] == "ok"
    assert [event["kind"] for event in page["events"]] == ["agent_message_chunk"]
    assert page["damaged_events"] == 1


def test_a_transcript_that_fails_mid_read_is_unreadable_and_not_a_half_page(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same fact whether the disk fails before the first byte or after the fifth.

    ``_read_window`` mapped ``open()`` failures to ``unreadable`` and left the
    iteration outside that mapping, so a volume that died one line in answered 500
    while a volume that never answered gave a readable page saying it could not be
    read -- which makes what the reader sees depend on how far the read got.
    """
    write_transcript(env, [message_chunk("first")])
    real_open = Path.open

    class FailsAfterOneLine:
        def __init__(self, handle) -> None:
            self.handle = handle
            self.lines = iter(handle)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def __iter__(self):
            return self

        def __next__(self) -> str:
            # The file behind this handle has one line in it; pretending the read
            # stops there is the only way to reach the mid-iteration branch from
            # a test, since nothing this service controls can half-read a file.
            line = next(self.lines, "")
            if not line:
                raise OSError(5, "Input/output error")
            return line

    def open_then_fail(target, *args, **kwargs):
        handle = real_open(target, *args, **kwargs)
        if Path(target).name != "transcript.jsonl":
            return handle
        return FailsAfterOneLine(handle)

    monkeypatch.setattr(Path, "open", open_then_fail)

    page = env.reports.transcript(JOB, "mail_a")

    assert page["transcript_state"] == "unreadable"
    assert page["events"] == []


# ── report files ──────────────────────────────────────────────────────────────


def test_a_report_is_reused_until_the_numbers_move(env: Env, monkeypatch) -> None:
    """The fingerprint in the name is the whole cache policy (design section 4.1).

    ``_write`` is counted rather than the file's mtime because the promise is
    "render once per state of the job", and a re-render that happened to produce
    identical bytes would still be the churn this avoids.
    """
    written: list[str] = []

    def count_writes(path: Path, data: bytes) -> None:
        written.append(path.name)
        path.write_bytes(data)

    monkeypatch.setattr(reports_mod, "_write", count_writes)
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})

    first = env.reports.report(JOB)
    again = env.reports.report(JOB)
    markdown = env.reports.report(JOB, fmt="md")
    finish(env, "chart_c", 0.25)
    after_change = env.reports.report(JOB)

    assert again == first
    assert written == [first["filename"], markdown["filename"], after_change["filename"]]
    assert markdown["filename"].endswith("-shared.md")
    assert after_change["filename"] != first["filename"]
    assert after_change["stale_before"] != first["stale_before"]
    assert env.reports.report(JOB, sensitivity=SENSITIVITY_FULL)["filename"].endswith("-full.json")


def test_a_rendered_report_is_the_document_the_route_would_serve(env: Env) -> None:
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})

    doc = env.reports.report(JOB, fmt="md")
    on_disk = env.exchange.report_path(JOB, doc["filename"]).read_text(encoding="utf-8")

    assert on_disk.startswith(f"# Job {JOB}")
    assert "subcategory: GitHub=0.5" in on_disk
    assert doc["size"] == len(on_disk.encode())
    assert doc["sha256"]
    assert urlsplit(doc["url"]).path == f"/v1/reports/{JOB}/{doc['filename']}"
    assert set(parse_qs(urlsplit(doc["url"]).query)) == {"expires", "sig"}


# ── the same files with two requests on them ─────────────────────────────────
#
# Every read route runs in its own worker thread, so one job's report can be
# rendered by two of them at the same moment.  A fingerprint-named file makes
# that look harmless -- both writers aim at one name -- which is exactly how the
# half-written one got cached as the correct report.  The sleeps and the markers
# belong to the tests, not to the service: they make "who landed first" a fact
# about this run rather than a matter of thread luck.


def test_two_writers_of_one_report_name_use_different_temporaries(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The staged name is per write, not per final file.

    Both writers used to share ``.report-<name>.part``, so the second one's
    ``open(..., 'wb')`` truncated the first one's bytes and the first then
    moved a 4,000,028-byte hybrid into place and called it the report.  Counting
    the names is how to check that without depending on how long a multi-megabyte
    write takes on this machine.
    """
    target = env.exchange.report_path(JOB, "report-both-writers.json")
    staged: list[str] = []
    real_replace = Path.replace

    def record(self: Path, destination: Path) -> None:
        staged.append(self.name)
        real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", record)

    def write(index: int) -> None:
        reports_mod._write(target, json.dumps({"worker": index}).encode())

    workers = [threading.Thread(target=write, args=(index,)) for index in (0, 1)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(staged) == 2
    assert staged[0] != staged[1], "one fixed name is one shared buffer"
    assert json.loads(target.read_text())["worker"] in (0, 1), "one whole document landed"
    assert list(target.parent.glob(".*.part")) == []


def test_a_failed_report_write_leaves_no_temporary_behind(env: Env) -> None:
    """A name nobody else owns is a name nobody else will ever clean up.

    The fixed staged name used to be overwritten by the next attempt, so a
    failure left at most one stray file; with a fresh name per write, the same
    failure piles a partial report in the directory the links serve from.
    Something else owning the final name is the cheapest way to make ``replace``
    fail on purpose.
    """
    target = env.exchange.report_path(JOB, "report-blocked.json")
    target.mkdir()

    with pytest.raises(OSError):
        reports_mod._write(target, b"{}")

    assert list(target.parent.glob(".*.part")) == []


def test_two_requests_for_one_fingerprint_agree_on_the_file_that_landed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whoever loses the write reports the winner's bytes.

    ``generated_at`` is in the payload but not in the fingerprint, so two
    renders of one fingerprint are not the same bytes; the marker below stands
    in for that second of clock.  The ``sha256`` and ``size`` returned here
    travel with the link -- a submitter forwards them to the team that owns the
    agent -- so they have to describe the file at the end of it.

    The first writer is held open instead of left to the scheduler: without the
    lock the other request passes the "still no file" check, lands its own bytes
    over the first one, and both answers then describe a document that is not on
    disk.  Which of the two is slowed down does not matter, so neither does
    which thread happens to run first.
    """
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})
    real_render = reports_mod.Reports._render
    markers = itertools.count()

    def marked_render(self, fmt, payload, job_id, rows, tier):
        data = real_render(self, fmt, payload, job_id, rows, tier)
        return data + f"<!-- render {next(markers)} -->\n".encode()

    monkeypatch.setattr(reports_mod.Reports, "_render", marked_render)

    real_write = reports_mod._write
    writes = itertools.count()

    def slow_first_write(path: Path, data: bytes) -> None:
        if next(writes) == 0:
            time.sleep(0.2)
        real_write(path, data)

    monkeypatch.setattr(reports_mod, "_write", slow_first_write)

    answers: list[dict[str, Any]] = []

    def request() -> None:
        answers.append(env.reports.report(JOB, fmt="md"))

    workers = [threading.Thread(target=request) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(answers) == 2
    assert len({answer["filename"] for answer in answers}) == 1
    landed = env.exchange.report_path(JOB, answers[0]["filename"]).read_bytes()
    assert len({answer["sha256"] for answer in answers}) == 1
    assert {answer["size"] for answer in answers} == {len(landed)}
    assert hashlib.sha256(landed).hexdigest() == answers[0]["sha256"]
    assert landed.count(b"<!-- render") == 1, "one whole document, not two of them"


def test_zip_is_refused_at_the_tier_that_gets_forwarded(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.report(JOB, fmt="zip", sensitivity=SENSITIVITY_SHARED)

    assert refused.value.code == "sensitivity_format_mismatch"
    assert refused.value.details["required"] == SENSITIVITY_FULL


def test_zip_at_full_bundles_the_detail_document_transcripts_and_files(env: Env) -> None:
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})
    write_transcript(env, [message_chunk("working")])
    upload(env, "mail_b", "output/result.csv")

    doc = env.reports.report(JOB, fmt="zip", sensitivity=SENSITIVITY_FULL)
    with zipfile.ZipFile(env.exchange.report_path(JOB, doc["filename"])) as archive:
        assert sorted(archive.namelist()) == [
            "artifacts/mail_b-1/output/result.csv",
            "detail-full.json",
            "transcripts/mail_a-1.jsonl",
        ]
        assert json.loads(archive.read("detail-full.json"))["sensitivity"] == SENSITIVITY_FULL
        assert archive.read("artifacts/mail_b-1/output/result.csv") == b"result-bytes"


def test_an_unknown_report_format_names_the_four_that_exist(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.report(JOB, fmt="pdf")

    assert refused.value.code == "report_format_unsupported"
    assert refused.value.details["allowed"] == ["json", "md", "html", "zip"]


def test_an_artifact_path_outside_the_upload_tree_is_refused(env: Env) -> None:
    from pawbench.cpd.acp_remote_eval.service.exchange import ExchangeError

    with pytest.raises(ExchangeError) as refused:
        env.reports.artifact_file(JOB, "mail_a", 1, "../../etc/passwd")

    assert refused.value.code == "path_escape"


def test_a_missing_artifact_is_not_found_rather_than_empty(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.artifact_file(JOB, "mail_a", 1, "output/never-uploaded.csv")

    assert refused.value.code == "artifact_not_found"


# ── the question's own files, and what a preview shows of either kind ─────────


def test_a_task_lists_the_attachments_it_handed_the_agent(env: Env) -> None:
    detail = env.reports.task_detail(JOB, "mail_a")

    assert detail["has_attachments"] is True
    assert detail["attachments"] == [
        {"path": NOTE_DEST, "size": len(NOTE_TEXT), "copy": "dataset"},
        {"path": SHOT_DEST, "size": len(PNG_BYTES), "copy": "dataset"},
    ]


def test_a_task_without_attachments_reports_a_list_and_not_a_section(env: Env) -> None:
    detail = env.reports.task_detail(JOB, "chart_c")

    assert detail["has_attachments"] is False
    assert detail["attachments"] == []


def test_the_attachment_list_is_in_the_shared_tier_too(env: Env) -> None:
    """The attachment *is* part of the question, and shared already prints it.

    The bytes are the same door as an artifact download -- token only -- but the
    list of what was handed over cannot be a full-tier secret: a reader holding
    a shared report would be reading an answer to a question they cannot see.
    """
    shared = env.reports.task_detail(JOB, "mail_a", SENSITIVITY_SHARED)
    full = env.reports.task_detail(JOB, "mail_a", SENSITIVITY_FULL)

    assert shared["attachments"] == full["attachments"]


def test_a_text_attachment_previews_as_the_file_that_was_handed_over(env: Env) -> None:
    preview = env.reports.preview(JOB, "mail_a", 1, "attachment", NOTE_DEST)

    assert preview["kind"] == "text"
    assert preview["text"] == NOTE_TEXT
    assert preview["bytes"] == len(NOTE_TEXT)
    assert preview["shown_bytes"] == len(NOTE_TEXT)
    assert preview["truncated"] is False


def test_an_image_attachment_comes_back_drawable(env: Env) -> None:
    preview = env.reports.preview(JOB, "mail_a", 1, "attachment", SHOT_DEST)

    assert preview["kind"] == "image"
    assert preview["media_type"] == "image/png"
    prefix, _, encoded = preview["data_url"].partition(",")
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == PNG_BYTES


def test_an_attachment_the_task_never_declared_cannot_be_opened(env: Env) -> None:
    """The session directory also holds what the agent wrote there.

    A route that served any path under it would be a file browser over somebody
    else's run, so only the task's own declared fixtures are reachable -- even
    when the file is sitting right there.
    """
    written = env.exchange.session_file(JOB, "mail_a", 1, "output/answer.txt")
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text("the agent's own file", encoding="utf-8")

    with pytest.raises(ReportError) as refused:
        env.reports.preview(JOB, "mail_a", 1, "attachment", "output/answer.txt")

    assert refused.value.code == "attachment_not_found"


def test_a_text_artifact_is_trimmed_at_the_cap_and_says_so(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half a log still explains the failure; 64 MB in a dialog does not.

    The cap is patched down rather than the file patched up: the exchange in
    this fixture refuses artifacts over 4 KB, and what is under test is that the
    route stops at whatever the cap says -- not the size of the cap.
    """
    monkeypatch.setattr(reports_mod, "PREVIEW_TEXT_BYTES", 200)
    oversized = ("FATAL: it broke\n" * 40).encode()
    upload(env, "mail_b", "output/run.txt", oversized)

    preview = env.reports.preview(JOB, "mail_b", 1, "artifact", "output/run.txt")

    assert preview["kind"] == "text"
    assert preview["bytes"] == len(oversized)
    assert preview["shown_bytes"] == 200
    assert preview["truncated"] is True
    assert preview["text"].startswith("FATAL: it broke")


def test_a_binary_artifact_is_named_rather_than_dumped(env: Env) -> None:
    """A spreadsheet is neither text nor drawable, and mojibake is a worse
    answer than the download link a reader can act on."""
    upload(env, "mail_b", "output/book.xlsx", b"PK\x03\x04\x00\x00\x00binary")

    preview = env.reports.preview(JOB, "mail_b", 1, "artifact", "output/book.xlsx")

    assert preview["kind"] == "binary"
    assert preview["shown_bytes"] == 0
    assert "text" not in preview
    assert "data_url" not in preview


def test_a_preview_of_an_artifact_that_is_not_there_is_not_found(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.preview(JOB, "mail_b", 1, "artifact", "output/never-uploaded.csv")

    assert refused.value.code == "artifact_not_found"


def test_a_preview_of_a_kind_that_does_not_exist_names_the_two_that_do(env: Env) -> None:
    with pytest.raises(ReportError) as refused:
        env.reports.preview(JOB, "mail_a", 1, "transcript", NOTE_DEST)

    assert refused.value.code == "preview_kind_unsupported"
    assert refused.value.details["allowed"] == ["artifact", "attachment"]


def test_the_session_copy_answers_when_the_dataset_lost_the_file(env: Env) -> None:
    """A pruned package is not a reason to lose the question.

    The attempt's own copy was made before the agent ran, so it is the file that
    was actually in front of it -- and the only survivor once the fixture is
    gone from the dataset.  The row says which one it served, because "the
    dataset's file" and "the run's copy" are not the same claim.
    """
    (env.builtin_root / NOTE_DEST).unlink()
    laid_down = env.exchange.session_file(JOB, "mail_a", 1, NOTE_DEST)
    laid_down.parent.mkdir(parents=True, exist_ok=True)
    laid_down.write_text(NOTE_TEXT, encoding="utf-8")

    detail = env.reports.task_detail(JOB, "mail_a")
    assert detail["attachments"][0] == {
        "path": NOTE_DEST,
        "size": len(NOTE_TEXT),
        "copy": "attempt",
    }
    preview = env.reports.preview(JOB, "mail_a", 1, "attachment", NOTE_DEST)
    assert preview["text"] == NOTE_TEXT


# ── the same guarantees through HTTP ──────────────────────────────────────────


@pytest.fixture()
def tokens(env: Env) -> dict[str, str]:
    return {"dev-1": add_subject(env.tmp_path / "allowlist.yaml", "dev-1", display_name="Dev 1")}


@pytest.fixture()
def client(env: Env, tokens: dict[str, str]) -> TestClient:
    clock = env.reports.clock
    queue = JobQueue(
        env.store,
        env.config.schedule,
        QueueLimits(
            max_concurrent_jobs=env.config.service.max_concurrent_jobs,
            max_running_per_user=env.config.service.max_running_per_user,
        ),
        clock=clock,
    )
    control = ControlPlane(
        jobs=JobService(
            store=env.store,
            queue=queue,
            datasets=env.datasets,
            config=env.config,
            clock=clock,
        ),
        datasets=env.datasets,
        verifier=StaticConfigVerifier.from_file(env.tmp_path / "allowlist.yaml"),
        reports=env.reports,
    )
    return TestClient(
        create_app(exchange=env.exchange, registry=AttemptRegistry(), control=control)
    )


def auth(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['dev-1']}"}


def test_zip_at_shared_answers_400_over_http(client: TestClient, tokens: dict[str, str]) -> None:
    """400, not 403: both tiers are open to every whitelisted subject, so a
    permission error would tell the reader to request a scope that does not
    exist (design section 4.1, constraint 2)."""
    response = client.get(
        f"/v1/jobs/{JOB}/report", params={"format": "zip"}, headers=auth(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "sensitivity_format_mismatch"


def test_the_read_routes_answer_their_own_refusals(
    client: TestClient, tokens: dict[str, str]
) -> None:
    missing = client.get("/v1/jobs/job-nope/detail", headers=auth(tokens))
    typo = client.get(
        f"/v1/jobs/{JOB}/detail", params={"sensitivity": "everything"}, headers=auth(tokens)
    )
    paging = client.get(
        f"/v1/jobs/{JOB}/transcript",
        params={"task_id": "mail_a", "cursor": "-1"},
        headers=auth(tokens),
    )
    no_task = client.get(f"/v1/jobs/{JOB}/transcript", headers=auth(tokens))
    anonymous = client.get(f"/v1/jobs/{JOB}/results")

    assert missing.status_code == 404
    assert typo.status_code == 400 and typo.json()["error"] == "sensitivity_unknown"
    assert paging.status_code == 400 and paging.json()["error"] == "cursor_invalid"
    assert no_task.status_code == 400 and no_task.json()["error"] == "field_type_invalid"
    assert anonymous.status_code in (401, 403)


def test_detail_routes_over_http_match_the_object_level_ones(
    client: TestClient, tokens: dict[str, str], env: Env
) -> None:
    """One field list, three readers: the dashboard, the report file and the MCP
    tool cannot drift, because all three go through the same aggregation."""
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})

    served = client.get(f"/v1/jobs/{JOB}/detail", headers=auth(tokens)).json()

    assert served["sensitivity"] == SENSITIVITY_SHARED
    assert served["tasks"] == env.reports.job_detail(JOB, SENSITIVITY_SHARED)["tasks"]


def test_a_signed_report_link_serves_the_file(client: TestClient, env: Env) -> None:
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})
    doc = env.reports.report(JOB)
    parts = urlsplit(doc["url"])

    served = client.get(f"{parts.path}?{parts.query}")
    tampered = client.get(f"{parts.path}?{parts.query.replace('sig=', 'sig=x')}")
    broken = client.get(f"{parts.path}?expires=soon&sig=whatever")
    ghost = urlsplit(env.exchange.report_link(JOB, "report-0000000000000000-shared.json"))
    absent = client.get(f"{ghost.path}?{ghost.query}")

    assert served.status_code == 200
    assert json.loads(served.content)["sensitivity"] == SENSITIVITY_SHARED
    assert tampered.status_code == 403
    assert broken.status_code == 400
    assert absent.status_code == 404


def test_the_report_route_needs_no_token_and_no_link_needs_one(
    client: TestClient, tokens: dict[str, str], env: Env
) -> None:
    """The two doors are different on purpose: the control route renders and
    hands back a link, the serving route trusts the signature and nothing else."""
    score_all(env, {"mail_a": 0.5, "mail_b": 0.5, "chart_c": 0.5})
    doc = client.get(f"/v1/jobs/{JOB}/report", headers=auth(tokens)).json()
    parts = urlsplit(doc["url"])

    assert client.get(f"/v1/jobs/{JOB}/report").status_code in (401, 403)
    assert client.get(f"{parts.path}?{parts.query}").status_code == 200


def test_an_artifact_download_needs_the_callers_token(
    client: TestClient, tokens: dict[str, str], env: Env
) -> None:
    score_all(env, {"mail_b": 0.5})
    upload(env, "mail_b", "output/result.csv")
    href = f"/v1/jobs/{JOB}/tasks/mail_b/attempts/1/artifacts"

    served = client.get(href, params={"path": "output/result.csv"}, headers=auth(tokens))
    anonymous = client.get(href, params={"path": "output/result.csv"})
    escaping = client.get(href, params={"path": "../../etc/passwd"}, headers=auth(tokens))
    missing = client.get(href, params={"path": "output/nope.csv"}, headers=auth(tokens))
    unnamed = client.get(href, headers=auth(tokens))

    assert served.status_code == 200 and served.content == b"result-bytes"
    assert anonymous.status_code in (401, 403)
    assert escaping.status_code == 422 and escaping.json()["error"] == "path_escape"
    assert missing.status_code == 404 and missing.json()["error"] == "artifact_not_found"
    assert unnamed.status_code == 422 and unnamed.json()["error"] == "empty_path"



# ── the two ids that lead back to what actually happened ──────────────────────


def test_the_report_carries_the_ids_that_find_the_attempt(env: Env) -> None:
    """A score nobody can trace back to a run is a number, not a measurement.

    ``trace_id`` is ours and appears in this service's log lines for the
    attempt; ``session_id`` is the agent's own handle.  Both have to reach the
    reader at the shared tier, because that is the document a submitter
    forwards to the team that owns the agent.
    """
    finish(
        env,
        "mail_a",
        1.0,
        trace_id="8cc7763718eb468b",
        session_id="d5b16b29dc0d4a8d95b6f8552e656359",
    )

    shared = task_at(env.reports.job_detail(JOB, SENSITIVITY_SHARED), "mail_a")
    assert shared["trace_id"] == "8cc7763718eb468b"
    assert shared["session_id"] == "d5b16b29dc0d4a8d95b6f8552e656359"

    # And in the file, not only in the JSON: the markdown report is the thing
    # that gets pasted into a ticket.
    document = reports_mod._markdown(
        env.reports.job_detail(JOB, SENSITIVITY_SHARED), env.reports.results(JOB)
    )
    assert "8cc7763718eb468b" in document
    assert "d5b16b29dc0d4a8d95b6f8552e656359" in document


def test_the_exported_report_states_the_task_before_scoring_it(env: Env) -> None:
    """A score without the question is unarguable: the reader has to be able to
    see what the agent was asked without opening another system."""
    score_all(env, {"mail_a": 1.0, "mail_b": 0.5, "chart_c": 0.0})

    document = reports_mod._markdown(
        env.reports.job_detail(JOB, SENSITIVITY_SHARED), env.reports.results(JOB)
    )

    assert "Write output/result.txt with the answer." in document
    assert "artifacts:" in document


# ── the two file doors, through HTTP ──────────────────────────────────────────


def test_the_preview_and_attachment_routes_answer_what_the_reader_asked_for(
    client: TestClient, tokens: dict[str, str], env: Env
) -> None:
    """Both files a task has, over the route the dialog actually calls."""
    upload(env, "mail_b", "output/result.txt", b"the answer")
    base = f"/v1/jobs/{JOB}/tasks"

    attachment = client.get(
        f"{base}/mail_a/attempts/1/attachments/preview",
        params={"path": NOTE_DEST},
        headers=auth(tokens),
    )
    raw = client.get(
        f"{base}/mail_a/attempts/1/attachments",
        params={"path": NOTE_DEST},
        headers=auth(tokens),
    )
    artifact = client.get(
        f"{base}/mail_b/attempts/1/artifacts/preview",
        params={"path": "output/result.txt"},
        headers=auth(tokens),
    )

    assert attachment.status_code == 200
    assert attachment.json()["text"] == NOTE_TEXT
    assert raw.status_code == 200
    assert raw.content == NOTE_TEXT.encode()
    assert artifact.status_code == 200
    assert artifact.json()["text"] == "the answer"


def test_the_file_routes_answer_404_for_a_file_that_is_not_there(
    client: TestClient, tokens: dict[str, str]
) -> None:
    base = f"/v1/jobs/{JOB}/tasks/mail_a/attempts/1"

    missing_attachment = client.get(
        f"{base}/attachments", params={"path": "fixtures/nope.txt"}, headers=auth(tokens)
    )
    escaped = client.get(
        f"{base}/attachments",
        params={"path": "../../etc/passwd"},
        headers=auth(tokens),
    )
    missing_artifact = client.get(
        f"/v1/jobs/{JOB}/tasks/mail_b/attempts/1/artifacts/preview",
        params={"path": "output/never-uploaded.csv"},
        headers=auth(tokens),
    )

    assert missing_attachment.status_code == 404
    assert missing_attachment.json()["error"] == "attachment_not_found"
    # A traversal is answered as "not one of this task's files", which is the
    # stronger refusal: the declaration list decides before any path is joined,
    # so there is no second place where an escape could be let through.
    assert escaped.status_code == 404
    assert escaped.json()["error"] == "attachment_not_found"
    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["error"] == "artifact_not_found"
