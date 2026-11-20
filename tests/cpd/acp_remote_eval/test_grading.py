# -*- coding: utf-8 -*-
"""Automated grading runs one at a time, because the engine it calls does not.

``pawbench/grader.py`` swaps ``sys.modules["subprocess"]`` for a logging wrapper
around every call and restores whatever it saw (:153-181).  That is safe for the
command-line run it was written for -- one task, one process -- and unsafe here,
where the runtime grades up to ``max_concurrent_jobs`` attempts at once, each in
its own thread.  Two overlapping windows leave a wrapper installed for the life
of the daemon, and each leftover nests inside the next one.

So these cases pin the serialization the service adds, pin that a failed check
script frees the worker, pin what is deliberately *not* serialized -- the judge's
HTTP wait, which is the slow part and holds no process-global state -- and pin
the wall clock that keeps a hung script from costing the service its liveness.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pawbench.cpd.acp_remote_eval.service import grading as grading_module
from pawbench.cpd.acp_remote_eval.service.config import JudgeConfig
from pawbench.cpd.acp_remote_eval.service.grading import (
    GRADING_ERROR,
    JUDGE_UNAVAILABLE,
    UNTRUSTED_BEGIN,
    UNTRUSTED_END,
    _GRADING_POOL,
    JudgeReply,
    JudgeUnavailable,
    LlmJudge,
    Scorer,
)
from pawbench.task_loader import TaskLoader

from support import write_task

#: How long a case may take before it is a hang rather than a slow machine.
CASE_TIMEOUT_SECONDS = 15

#: Written to tmp_path and imported by the check scripts below.  A module is the
#: only way a script exec'd in a worker thread can report back to the case.
PROBE_SOURCE = '''
import threading

_state = threading.Lock()
inside = 0
peak = 0
names = []
gate = threading.Event()


def enter(block):
    global inside, peak
    with _state:
        inside += 1
        peak = max(peak, inside)
        names.append(threading.current_thread().name)
    if block:
        gate.wait(10)


def leave():
    global inside
    with _state:
        inside -= 1
'''


@pytest.fixture()
def probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "grading_probe.py").write_text(PROBE_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("grading_probe")
    try:
        yield module
    finally:
        sys.modules.pop("grading_probe", None)


def check_script(task_id: str, body: str) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        grading_type="automated",
        automated_checks=f"```python\n{body}\n```",
    )


def observing_task(task_id: str, *, block: bool) -> SimpleNamespace:
    return check_script(
        task_id,
        "import grading_probe\n"
        "def grade(transcript, workspace):\n"
        f"    grading_probe.enter({block})\n"
        "    try:\n"
        "        return {'ok': 1}\n"
        "    finally:\n"
        "        grading_probe.leave()\n",
    )


def test_two_gradings_never_share_the_subprocess_patch(probe) -> None:
    """The second grading must not start while the first is inside the engine."""
    real_subprocess = sys.modules["subprocess"]
    scorer = Scorer()

    async def run() -> list:
        first = asyncio.create_task(
            scorer.score(observing_task("blocked", block=True), {})
        )
        while not probe.inside:
            await asyncio.sleep(0.01)
        second = asyncio.create_task(
            scorer.score(observing_task("waiting", block=False), {})
        )
        # Every chance to overlap, if the lock were not there.
        await asyncio.sleep(0.05)
        probe.gate.set()
        return list(await asyncio.gather(first, second))

    outcomes = asyncio.run(asyncio.wait_for(run(), CASE_TIMEOUT_SECONDS))

    assert probe.peak == 1, "two check scripts ran inside the engine at once"
    assert [outcome.score for outcome in outcomes] == [1.0, 1.0]
    assert sys.modules["subprocess"] is real_subprocess


def test_a_raising_check_script_frees_the_grading_worker(probe) -> None:
    """One broken task must not lock every later grading out of the engine."""
    broken = check_script(
        "broken",
        "def grade(transcript, workspace):\n"
        "    raise RuntimeError('check script blew up')\n",
    )
    scorer = Scorer()

    outcome = asyncio.run(
        asyncio.wait_for(scorer.score(broken, {}), CASE_TIMEOUT_SECONDS)
    )

    assert outcome.score is None
    assert outcome.failure_reason == GRADING_ERROR
    # A worker still held would time out here rather than answer.
    assert _GRADING_POOL.submit(lambda: "free").result(CASE_TIMEOUT_SECONDS) == "free"

    later = asyncio.run(
        asyncio.wait_for(
            scorer.score(observing_task("later", block=False), {}),
            CASE_TIMEOUT_SECONDS,
        )
    )
    assert later.score == 1.0
    assert probe.peak == 1


def test_check_scripts_run_on_the_grading_pool_not_the_data_plane_executor(probe) -> None:
    """A hung script leaks its worker permanently, so it must not be a shared one.

    ``asyncio.to_thread``'s default executor is what writes rows and beats the
    lease; enough leaked workers there and live jobs are settled as dead.  The
    thread name is the observable difference between the two executors.
    """
    asyncio.run(
        asyncio.wait_for(
            Scorer().score(observing_task("pooled", block=False), {}),
            CASE_TIMEOUT_SECONDS,
        )
    )

    assert probe.names, "the check script never ran"
    assert all(name.startswith("pawbench-grading") for name in probe.names)


class RecordingJudge:
    """Answers once, and remembers that it was asked."""

    def __init__(self) -> None:
        self.calls = 0

    async def ask(self, prompt: str, *, task_id: str = "") -> JudgeReply:
        self.calls += 1
        return JudgeReply(
            text='{"total": 0.8, "scores": {"answer": 0.8}}',
            requested_model="judge-model",
            served_model="judge-model",
        )


def test_the_judge_does_not_wait_for_the_grading_worker(tmp_path: Path) -> None:
    """Serializing the check scripts must not serialize the judge's HTTP wait."""
    task = judged_task(tmp_path, "judged")
    judge = RecordingJudge()
    release = threading.Event()
    # Occupied from the pool's own worker, never from this thread: a main thread
    # holding it would turn a red case into a five-minute interpreter shutdown.
    occupied = _GRADING_POOL.submit(release.wait, CASE_TIMEOUT_SECONDS)
    try:
        outcome = asyncio.run(
            asyncio.wait_for(
                Scorer(judge=judge).score(task, {}), CASE_TIMEOUT_SECONDS
            )
        )
    finally:
        release.set()
        occupied.result(CASE_TIMEOUT_SECONDS)

    assert judge.calls == 1
    assert outcome.grading_type == "llm_judge"


# ── the judge lane ────────────────────────────────────────────────────────────
#
# Until now this lane had no direct case: the runner and the e2e pair reach it
# only through a whole job.  What is pinned here is the part the module docstring
# says it holds hardest -- "the subject did badly" versus "we could not measure"
# -- plus the two promises design §11/§13 make about the key and the served model.

FAKE_KEY = "sk-fake-not-a-real-key-4f9c"
KEY_ENV = "PAWBENCH_TEST_JUDGE_KEY"
SUBJECT_WORDS = "the subject wrote this exact sentence"


def judge_config(**overrides) -> JudgeConfig:
    fields = dict(
        base_url="https://judge.invalid/v1",
        model="judge-model",
        pinned_model="",
        api_key_env=KEY_ENV,
        timeout_seconds=5.0,
        max_attempts=3,
        base_delay_seconds=0.01,
    )
    fields.update(overrides)
    return JudgeConfig(**fields)


def completion(text: str, *, model: str = "free/router-a") -> httpx.Response:
    return httpx.Response(
        200, json={"model": model, "choices": [{"message": {"content": text}}]}
    )


class Route:
    """A scripted endpoint: answers in order, repeats the last, keeps requests."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers[min(len(self.requests) - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def payload(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture()
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, FAKE_KEY)


@pytest.fixture()
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the backoff instead of serving it."""
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record)
    return recorded


def ask(
    route: Route, config: JudgeConfig | None = None, *, task_id: str = ""
) -> JudgeReply:
    async def run() -> JudgeReply:
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            judge = LlmJudge(config or judge_config(), client=client)
            return await judge.ask("grade this", task_id=task_id)

    return asyncio.run(asyncio.wait_for(run(), CASE_TIMEOUT_SECONDS))


def judged_task(tmp_path: Path, task_id: str, *, grading_type: str = "llm_judge"):
    path = write_task(
        tmp_path, task_id, grading_type=grading_type, rubric="Score the answer."
    )
    return TaskLoader(tmp_path / "tasks").load_task(path)


def score_via(route: Route, task, config: JudgeConfig | None = None):
    execution = {
        "transcript": [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": SUBJECT_WORDS}],
                },
            }
        ],
        "workspace": "",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            judge = LlmJudge(config or judge_config(), client=client)
            return await Scorer(judge=judge).score(task, execution)

    return asyncio.run(asyncio.wait_for(run(), CASE_TIMEOUT_SECONDS))


def test_no_key_means_unavailable_and_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unconfigured judge is "we could not look", not a zero."""
    monkeypatch.delenv(KEY_ENV, raising=False)
    route = Route(completion('{"total": 1.0}'))

    outcome = score_via(route, judged_task(tmp_path, "nokey"))

    assert outcome.score is None
    assert outcome.failure_reason == JUDGE_UNAVAILABLE
    assert route.requests == [], "a request went out without a key"


def test_the_served_model_is_recorded_not_the_requested_one(
    tmp_path: Path, keyed
) -> None:
    """Free routing changes who answered; the row must say who did."""
    route = Route(completion('{"total": 0.7}', model="free/router-b"))

    outcome = score_via(route, judged_task(tmp_path, "served"))

    assert outcome.score == pytest.approx(0.7)
    assert outcome.judge_served_models == ("free/router-b",)
    assert route.payload()["model"] == "judge-model"


def test_a_pinned_model_is_what_gets_requested(tmp_path: Path, keyed) -> None:
    route = Route(completion('{"total": 0.7}'))

    score_via(route, judged_task(tmp_path, "pinned"), judge_config(pinned_model="pinned/x"))

    assert route.payload()["model"] == "pinned/x"


def test_a_rejected_key_is_not_retried(keyed, delays) -> None:
    """401 is a configuration problem: retrying it is a storm, not patience."""
    route = Route(httpx.Response(401, json={"error": "bad key"}))

    with pytest.raises(JudgeUnavailable) as caught:
        ask(route, judge_config(max_attempts=4))

    assert len(route.requests) == 1
    assert delays == []
    assert "401" in str(caught.value)


def test_retry_after_is_honoured_up_to_the_ceiling(keyed, delays) -> None:
    """A free route can ask for minutes; the slot is not worth that wait."""
    route = Route(
        httpx.Response(429, headers={"Retry-After": "600"}),
        completion('{"total": 0.5}'),
    )

    reply = ask(route, judge_config(max_attempts=2))

    assert reply.text == '{"total": 0.5}'
    # The literal, not MAX_JUDGE_BACKOFF_SECONDS: importing the ceiling by value
    # would let the assertion follow it to 600 and still pass.
    assert delays == [30.0]


def test_a_short_retry_after_is_not_padded_to_the_backoff(keyed, delays) -> None:
    route = Route(
        httpx.Response(429, headers={"Retry-After": "0.5"}),
        completion('{"total": 0.5}'),
    )

    ask(route, judge_config(max_attempts=2, base_delay_seconds=0.01))

    assert delays == [0.5]


def test_a_transport_failure_is_retried_and_named(keyed, delays) -> None:
    route = Route(httpx.ConnectError("route unreachable"))

    with pytest.raises(JudgeUnavailable) as caught:
        ask(route, judge_config(max_attempts=3))

    assert len(route.requests) == 3
    assert len(delays) == 2
    assert "ConnectError" in str(caught.value)
    assert FAKE_KEY not in str(caught.value)


def test_an_answer_with_no_number_is_a_grading_error(tmp_path: Path, keyed) -> None:
    """A rubric or model problem, not a capacity problem: different reason."""
    route = Route(completion("I cannot grade this task."))

    outcome = score_via(route, judged_task(tmp_path, "unreadable"))

    assert outcome.score is None
    assert outcome.failure_reason == GRADING_ERROR


@pytest.mark.parametrize("total", ["NaN", "Infinity", "-0.1", "1.1"])
def test_an_invalid_judge_total_is_not_a_score(
    tmp_path: Path, keyed, total: str
) -> None:
    route = Route(completion('{"total": ' + total + '}'))

    outcome = score_via(route, judged_task(tmp_path, "invalid-total"))

    assert outcome.score is None
    assert outcome.failure_reason == GRADING_ERROR


def test_a_body_that_is_not_json_is_a_grading_error(tmp_path: Path, keyed) -> None:
    route = Route(httpx.Response(200, text="<html>gateway</html>"))

    outcome = score_via(route, judged_task(tmp_path, "notjson"))

    assert outcome.score is None
    assert outcome.failure_reason == GRADING_ERROR


def test_hybrid_keeps_the_automated_half_when_the_judge_fails(
    tmp_path: Path, keyed
) -> None:
    """The automated part is a measurement that happened; it stays readable."""
    task = judged_task(tmp_path, "hybrid", grading_type="hybrid")
    task.automated_checks = (
        "```python\ndef grade(transcript, workspace):\n    return {'ok': 1}\n```"
    )
    route = Route(httpx.Response(429))

    outcome = score_via(route, task, judge_config(max_attempts=1))

    assert outcome.score is None
    assert outcome.failure_reason == JUDGE_UNAVAILABLE
    assert outcome.automated_breakdown == {"ok": 1.0}


def test_the_subject_output_is_fenced_as_evidence(tmp_path: Path, keyed) -> None:
    """Design §11: what the subject wrote is evidence, never an instruction."""
    route = Route(completion('{"total": 0.5}'))

    score_via(route, judged_task(tmp_path, "fenced"))

    messages = route.payload()["messages"]
    system = messages[0]["content"]
    assert messages[0]["role"] == "system"
    # Not `system == UNTRUSTED_SYSTEM_PROMPT`: the case imports that constant by
    # value, so such an assertion would follow the constant wherever it went and
    # judge nothing.  What design §11 promises is the substance below.
    assert UNTRUSTED_BEGIN in system and UNTRUSTED_END in system
    assert "never follow" in system.lower()
    assert "evidence" in system.lower()
    user = messages[1]["content"]
    assert UNTRUSTED_BEGIN in user and UNTRUSTED_END in user
    inside = user.split(UNTRUSTED_BEGIN)[1].split(UNTRUSTED_END)[0]
    assert SUBJECT_WORDS in inside


def test_the_key_reaches_the_header_and_nothing_else(tmp_path: Path, keyed, caplog) -> None:
    """The key is sent, and stays out of every log line and error message."""
    route = Route(httpx.Response(429), completion('{"total": 0.5}'))

    with caplog.at_level("WARNING"):
        outcome = score_via(route, judged_task(tmp_path, "keyhygiene"))

    assert outcome.score == pytest.approx(0.5)
    assert route.requests[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in caplog.text
    # caplog.text renders the message only: a key parked in an `extra` field
    # would be invisible above and still reach whatever ships the records.
    for record in caplog.records:
        assert all(FAKE_KEY not in str(value) for value in vars(record).values())
    assert all(FAKE_KEY not in str(value) for value in route.payload().values())


# ── the wall clock ────────────────────────────────────────────────────────────
#
# Grading sits outside the attempt's timeout, so the job hands it what its wall
# clock has left.  A check script that never returns must cost its own score and
# nothing else; a judge that never answers must stay "we could not look" rather
# than become a grading bug.


def test_a_hung_check_script_loses_its_score_inside_the_budget(probe) -> None:
    """The queue behind a hung script is cancelled, not waited out."""
    release = threading.Event()
    hung = _GRADING_POOL.submit(release.wait, CASE_TIMEOUT_SECONDS)
    try:
        began = time.monotonic()
        outcome = asyncio.run(
            asyncio.wait_for(
                Scorer().score(
                    observing_task("queued", block=False), {}, budget_seconds=0.2
                ),
                CASE_TIMEOUT_SECONDS,
            )
        )
        elapsed = time.monotonic() - began
    finally:
        release.set()
        hung.result(CASE_TIMEOUT_SECONDS)

    assert outcome.score is None
    assert outcome.failure_reason == GRADING_ERROR
    assert elapsed < 5, "the grading waited for the hung script, not for its budget"
    assert probe.peak == 0, "a cancelled grading still ran its check script"


class SlowJudge:
    """A judge that answers later than the job can wait."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.calls = 0

    async def ask(self, prompt: str, *, task_id: str = "") -> JudgeReply:
        self.calls += 1
        await asyncio.sleep(self.seconds)
        return JudgeReply(
            text='{"total": 0.9}',
            requested_model="judge-model",
            served_model="judge-model",
        )


def test_the_judge_lane_stops_at_the_jobs_wall_clock(tmp_path: Path) -> None:
    """Retries are bounded by the job, not by attempts x timeout x backoff."""
    task = judged_task(tmp_path, "slowjudge")
    judge = SlowJudge(seconds=CASE_TIMEOUT_SECONDS)

    began = time.monotonic()
    outcome = asyncio.run(
        asyncio.wait_for(
            Scorer(judge=judge).score(task, {}, budget_seconds=0.2),
            CASE_TIMEOUT_SECONDS,
        )
    )
    elapsed = time.monotonic() - began

    assert outcome.score is None
    assert outcome.failure_reason == JUDGE_UNAVAILABLE
    assert judge.calls == 1
    assert elapsed < 5, "the judge lane ignored the budget it was handed"


def test_the_retry_log_names_the_task(keyed, delays, caplog) -> None:
    """Four jobs share one route: a retry without a subject cannot be traced."""
    route = Route(httpx.Response(429), completion('{"total": 0.5}'))

    with caplog.at_level("WARNING"):
        ask(route, judge_config(max_attempts=2), task_id="task-42")

    retries = [r for r in caplog.records if r.message == "judge retry scheduled"]
    assert len(retries) == 1
    assert retries[0].task_id == "task-42"


def test_a_criterion_with_no_number_is_reported_not_silently_dropped(
    tmp_path: Path, keyed, caplog
) -> None:
    """A rubric answered in prose leaves the detail view short; say so once.

    ``criteria_scores`` is the shape that reaches this normalizer: under
    ``scores`` the engine drops a prose value itself (grader.py:658-662) before
    we ever see it.  That silence is core's and is registered, not fixed here.
    """
    route = Route(
        completion(
            '{"total": 0.5, "criteria_scores":'
            ' {"answer": 0.5, "style": {"score": "excellent"}}}'
        )
    )

    with caplog.at_level("WARNING"):
        outcome = score_via(route, judged_task(tmp_path, "dropped"))

    assert outcome.judge_notes["scores"] == {"answer": 0.5}
    dropped = [r for r in caplog.records if r.message == "judge criteria carried no number"]
    assert len(dropped) == 1, "one aggregated line, not one per criterion"
    assert dropped[0].dropped == 1
    assert dropped[0].criteria == ["style"]


def test_the_prompt_is_built_off_the_event_loop(
    tmp_path: Path, keyed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Summarizing walks the whole transcript; the loop is answering uploads."""
    threads: list[str] = []

    def prompt(task, execution_result) -> str:
        threads.append(threading.current_thread().name)
        return "grade this"

    monkeypatch.setattr(grading_module, "_judge_prompt", prompt)
    route = Route(completion('{"total": 0.5}'))

    score_via(route, judged_task(tmp_path, "offloop"))

    assert len(threads) == 1
    assert threads[0] != "MainThread"


def test_hybrid_stages_share_one_wall_clock(tmp_path: Path) -> None:
    task = judged_task(tmp_path, "hybrid-budget", grading_type="hybrid")
    task.automated_checks = (
        "```python\nimport time\ndef grade(transcript, workspace):\n"
        "    time.sleep(0.3)\n    return {'ok': 1}\n```"
    )
    judge = SlowJudge(seconds=0.3)

    outcome = asyncio.run(
        asyncio.wait_for(
            Scorer(judge=judge).score(task, {}, budget_seconds=0.5),
            CASE_TIMEOUT_SECONDS,
        )
    )

    assert judge.calls == 1
    assert outcome.failure_reason == JUDGE_UNAVAILABLE
    assert outcome.automated_breakdown == {"ok": 1.0}


def test_prompt_construction_uses_the_judge_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_prompt(task, execution_result) -> str:
        time.sleep(0.3)
        return "grade this"

    monkeypatch.setattr(grading_module, "_judge_prompt", slow_prompt)
    judge = RecordingJudge()
    outcome = asyncio.run(
        asyncio.wait_for(
            Scorer(judge=judge).score(
                judged_task(tmp_path, "slow-prompt"), {}, budget_seconds=0.1
            ),
            CASE_TIMEOUT_SECONDS,
        )
    )

    assert outcome.failure_reason == JUDGE_UNAVAILABLE
    assert judge.calls == 0