# -*- coding: utf-8 -*-
"""The pilot seed: fifteen ids, and the gate that says they still cover the run.

``test_datasets.py`` proves the catalogue machinery; this module proves the one
hand-written list the service ships with, which is a different kind of claim.  A
seed list rots quietly -- a task retired upstream, a fixture file dropped from a
task -- and each time it does, the pilot keeps submitting a plausible number of
questions while exercising less and less of the data plane.  So the cases here
run against the *real* catalogue, and the gaps are asserted one constraint at a
time so the message an operator gets names the thing they have to fix.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pawbench.cpd.acp_remote_eval.service.daemon import main
from pawbench.cpd.acp_remote_eval.service.datasets import (
    BuiltinCatalog,
    DatasetError,
    DatasetService,
    TaskSummary,
)
from pawbench.cpd.acp_remote_eval.service.pilot import (
    MIN_ATTACHMENT_TASKS,
    MIN_TASKS,
    PILOT_DESCRIPTION,
    PILOT_OWNER,
    PILOT_TASK_IDS,
    attachment_kinds,
    composition_gaps,
    seed_pilot,
)
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import dataset_service, eval_config, write_task

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CATALOGUE = REPO_ROOT / "data" / "pawbench-v1.0"


def summary(
    task_id: str,
    *,
    grading_type: str = "automated",
    environment: str = "closed",
    fixtures: tuple[str, ...] = (),
) -> TaskSummary:
    """A catalogue entry with only what the composition rules read."""
    return TaskSummary(
        task_id=task_id,
        name=task_id,
        file_stem=task_id,
        path=Path(f"{task_id}.md"),
        grading_type=grading_type,
        timeout_seconds=300,
        workspace_files=tuple(
            {"source": f"fixtures/{name}", "dest": f"fixtures/{name}"} for name in fixtures
        ),
        labels={"environment": environment},
    )


def pilot_like_summaries() -> list[TaskSummary]:
    """A doctored set that satisfies every rule, for the negative cases to break."""
    attached = [
        summary(f"xlsx_{index}", fixtures=(f"book{index}.xlsx",))
        for index in range(MIN_ATTACHMENT_TASKS)
    ]
    return (
        attached
        + [summary("png_1", fixtures=("shot.png",))]
        + [summary("open_research", grading_type="llm_judge", environment="open")]
        + [summary(f"text_{index}") for index in range(9)]
    )


# ── the shipped list ──────────────────────────────────────────────────────────


def test_the_shipped_seed_passes_its_own_gate() -> None:
    """The point of this case: the seed we actually ship is checked, not assumed.

    It reads the real catalogue, so it goes red on the day a task is retired or
    loses its fixture -- which is the day the pilot stops proving the data plane.
    """
    catalogue = BuiltinCatalog(REAL_CATALOGUE).tasks
    missing = [task_id for task_id in PILOT_TASK_IDS if task_id not in catalogue]
    chosen = [catalogue[task_id] for task_id in PILOT_TASK_IDS if task_id in catalogue]

    assert missing == []
    assert len(chosen) == 15
    assert composition_gaps(chosen, missing_ids=missing) == []


def test_the_seed_covers_the_fixture_kinds_its_comments_claim() -> None:
    """xlsx, png and pdf each have to be there for real, not by comment.

    :func:`attachment_kinds` reads the front matter, so this is where a line
    annotated ``# pdf`` is checked against the task's own ``workspace_files``.
    """
    catalogue = BuiltinCatalog(REAL_CATALOGUE).tasks
    kinds: set[str] = set()
    attached = 0
    for task_id in PILOT_TASK_IDS:
        found = attachment_kinds(catalogue[task_id])
        kinds |= found
        attached += bool(found)

    assert {"xlsx", "png", "pdf"} <= kinds
    assert attached >= MIN_ATTACHMENT_TASKS


def test_the_seed_carries_everything_a_submission_needs(store: Store, tmp_path: Path) -> None:
    """Not just a list: the seeded view has to resolve for the runner."""
    config = eval_config(tmp_path, builtin_root=REAL_CATALOGUE)
    datasets = dataset_service(store, config)

    record = seed_pilot(datasets, config.datasets)

    assert record is not None
    assert record["owner"] == PILOT_OWNER
    assert record["kind"] == "builtin_view"
    assert record["filter_spec"] == {"task_ids": list(PILOT_TASK_IDS)}
    # The stored list is in catalogue order: ``apply_filter`` decides that, and
    # the seed only promises the same membership.
    assert sorted(record["task_ids"]) == sorted(PILOT_TASK_IDS)
    resolved = {task.task_id for task in datasets.tasks_for_run(record["id"])}
    assert resolved == set(PILOT_TASK_IDS)


# ── the gate, one constraint at a time ────────────────────────────────────────


def test_a_complete_seed_reports_no_gap() -> None:
    assert composition_gaps(pilot_like_summaries()) == []


def test_the_gate_is_the_number_the_seed_advertises() -> None:
    """A pilot one question short of its own description is a broken pilot.

    ``MIN_TASKS`` used to sit at ten while the shipped list and the text shown on
    the dashboard both said fifteen, so the count constraint never bit on the seed
    it exists to protect: four tasks could go away and the service would still
    call what it serves a fifteen-task pilot.
    """
    catalogue = BuiltinCatalog(REAL_CATALOGUE).tasks
    chosen = [catalogue[task_id] for task_id in PILOT_TASK_IDS]

    assert len(chosen) == MIN_TASKS
    assert str(len(PILOT_TASK_IDS)) in PILOT_DESCRIPTION
    assert any("task(s) resolved" in gap for gap in composition_gaps(chosen[:-1]))


def _attached_only(suffix: str) -> list[TaskSummary]:
    return [summary(f"a_{index}", fixtures=(f"book{index}.{suffix}",)) for index in range(15)]


@pytest.mark.parametrize(
    "broken,phrase",
    [
        ([summary(f"t_{index}") for index in range(15)], "carry a fixture"),
        (_attached_only("txt"), "fixtures cover"),
        (
            [
                summary(f"a_{index}", fixtures=(f"book{index}.xlsx", f"note{index}.md"))
                for index in range(15)
            ],
            "fixtures cover",
        ),
        ([s for s in pilot_like_summaries() if s.task_id != "open_research"], "labels.environment"),
        (
            [
                summary(
                    s.task_id,
                    grading_type="automated",
                    environment=s.labels["environment"],
                    fixtures=tuple(str(f["source"]).split("/")[-1] for f in s.workspace_files),
                )
                for s in pilot_like_summaries()
            ],
            "graded by",
        ),
        (pilot_like_summaries()[: MIN_TASKS - 1], "task(s) resolved"),
    ],
)
def test_each_missing_dimension_is_named(broken: list[TaskSummary], phrase: str) -> None:
    gaps = composition_gaps(broken)

    assert any(phrase in gap for gap in gaps), gaps


def test_a_retired_task_is_reported_rather_than_absorbed() -> None:
    """The filter drops unknown ids silently by design, so the gate has to look."""
    gaps = composition_gaps(pilot_like_summaries(), missing_ids=["task_upstream_retired"])

    assert gaps[0] == "1 id(s) the catalogue no longer has: task_upstream_retired"


def test_several_broken_dimensions_are_all_listed_at_once() -> None:
    """One gap per restart would turn a re-cut catalogue into an afternoon."""
    gaps = composition_gaps([summary(f"t_{index}") for index in range(15)])

    assert len(gaps) >= 4
    assert "no task with labels.environment ['open']" in gaps


# ── seeding a service ─────────────────────────────────────────────────────────


def test_seeding_twice_leaves_the_first_seed_alone(
    store: Store, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = eval_config(tmp_path, builtin_root=REAL_CATALOGUE)
    datasets = dataset_service(store, config)
    first = seed_pilot(datasets, config.datasets)
    assert first is not None

    with caplog.at_level(logging.INFO):
        again = seed_pilot(datasets, config.datasets)

    assert again == first
    assert "pilot dataset already present" in caplog.text


def test_a_pilot_id_somebody_else_holds_is_left_alone(store: Store, tmp_path: Path) -> None:
    """Not taken over, and not a startup failure either: it is their dataset."""
    config = eval_config(tmp_path, builtin_root=REAL_CATALOGUE)
    datasets = dataset_service(store, config)
    datasets.create_builtin_view(
        dataset_id="pilot_v1",
        name="Mine",
        owner="dev-9",
        filter_spec={"task_ids": ["task_calendar"]},
    )

    record = seed_pilot(datasets, config.datasets)

    assert record["owner"] == "dev-9"
    assert record["task_ids"] == ["task_calendar"]


def test_a_pilot_that_stopped_covering_says_so_at_every_start(
    store: Store, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Left alone *and* reported -- the two halves of the same decision.

    Taking over somebody else's dataset would rewrite tasks they chose, so the
    seed is not enforced here.  Without the warning that meant a pilot whose
    attachment tasks were retired upstream booted quietly, said nothing, and kept
    submitting questions that never touched the data plane -- the exact invisible
    failure this module exists to prevent.
    """
    config = eval_config(tmp_path, builtin_root=REAL_CATALOGUE)
    datasets = dataset_service(store, config)
    datasets.create_builtin_view(
        dataset_id="pilot_v1",
        name="Mine",
        owner="dev-9",
        filter_spec={"task_ids": ["task_calendar", "task_shell_command_generator"]},
    )

    with caplog.at_level(logging.WARNING):
        record = seed_pilot(datasets, config.datasets)

    assert record["owner"] == "dev-9"
    told = [entry for entry in caplog.records if hasattr(entry, "gaps")]
    assert [(r.dataset_id, r.owner, r.levelno) for r in told] == [
        ("pilot_v1", "dev-9", logging.WARNING)
    ]
    assert any("carry a fixture" in gap for gap in told[0].gaps)


def test_an_empty_pilot_dataset_id_disables_seeding(store: Store, tmp_path: Path) -> None:
    config = eval_config(tmp_path, builtin_root=REAL_CATALOGUE)
    datasets = DatasetService(
        store, replace(config.datasets, pilot_dataset_id=""), BuiltinCatalog(REAL_CATALOGUE)
    )

    assert seed_pilot(datasets, datasets.config) is None
    assert store.get_dataset("pilot_v1") is None


def test_a_short_catalogue_writes_nothing_and_says_why(
    store: Store, tmp_path: Path
) -> None:
    """The refusal is what J9 asks for: no dataset, and the gaps in the message."""
    root = tmp_path / "builtin"
    for index in range(3):
        write_task(root, f"t_{index}")
    config = eval_config(tmp_path, builtin_root=root)
    datasets = DatasetService(store, config.datasets, BuiltinCatalog(root))

    with pytest.raises(DatasetError) as refused:
        seed_pilot(datasets, config.datasets)

    assert refused.value.code == "pilot_seed_incomplete"
    assert store.get_dataset("pilot_v1") is None
    assert any("carry a fixture" in gap for gap in refused.value.details["gaps"])


# ── readiness ─────────────────────────────────────────────────────────────────


def test_the_service_refuses_to_start_on_a_seed_it_cannot_honour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``main`` exits before binding a port rather than serving a short pilot."""
    root = tmp_path / "builtin"
    write_task(root, "t_only")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "service:\n"
        "  public_base_url: http://127.0.0.1:8471\n"
        f"datasets:\n  builtin_dir: {root}\n"
        f"exchange:\n  exchange_dir: {tmp_path / 'exchange'}\n",
        encoding="utf-8",
    )
    started: list[Any] = []

    async def fake_serve(service: Any) -> None:
        started.append(service)

    monkeypatch.setattr("pawbench.cpd.acp_remote_eval.service.daemon.serve", fake_serve)

    with caplog.at_level(logging.ERROR):
        assert main(["--config", str(config_path), "--log-level", "critical"]) == 2

    assert started == []
    # The gaps are structured context on the record; the daemon's own formatter
    # is what renders them into the operator's line.
    refused = [r for r in caplog.records if "refused to start" in r.getMessage()]
    assert [(r.code, bool(r.gaps)) for r in refused] == [("pilot_seed_incomplete", True)]
    assert any("carry a fixture" in gap for gap in refused[0].gaps)
