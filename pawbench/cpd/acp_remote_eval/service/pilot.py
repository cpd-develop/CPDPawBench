# -*- coding: utf-8 -*-
"""The pilot dataset, and the composition it is required to have.

The pilot is what a new deployment evaluates with first, and it is a fixed id
list rather than a ``scenario`` sample for one reason: cross-version
comparability.  A sample quietly changes the questions the next time the
catalogue is re-cut, and a pilot whose questions move can no longer say that a
subject got better.

The composition rules below are code, not a line in a document, because the
failure they prevent is invisible.  A seed that lost its attachment tasks still
submits fifteen questions and still scores -- it just never exercises fixture
download, artifact collection and workspace rebuild, which is the whole data
plane this feature adds.  So the service refuses to become ready rather than
serve a pilot that quietly stopped testing anything.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from .config import DatasetConfig
from .datasets import DatasetError, DatasetService, TaskSummary

logger = logging.getLogger(__name__)

#: Owner of the seeded dataset.  Not a subject id on purpose: the pilot belongs
#: to the service, so editing it takes the same owner-or-admin rule as any other
#: dataset and nobody's personal catalogue loses its author.
PILOT_OWNER = "service"
PILOT_NAME = "Pilot set (v1)"
PILOT_DESCRIPTION = (
    "Fixed 15-task seed created on first start.  Explicit task ids, not a sample: "
    "the scores are meant to be comparable across catalogue versions."
)

#: What the seed has to contain.  Each one is a leg of the run, not a preference:
#: the attachment rules are why the fixture/artifact/workspace legs get exercised,
#: and the environment and grading rules are why both the open-web path and the
#: judge are covered by the same submission.
#:
#: Fifteen, because that is what ``PILOT_TASK_IDS`` below holds and what
#: ``PILOT_DESCRIPTION`` promises whoever reads it in the catalogue.  A floor of
#: ten would let three retired ids pass the gate while the description still said
#: fifteen -- the number here is the promise, so the two are one number.
MIN_TASKS = 15
MIN_ATTACHMENT_TASKS = 5
ATTACHMENT_KINDS = ("xlsx", "png", "pdf")
MIN_ATTACHMENT_KINDS = 2
REQUIRED_ENVIRONMENTS = ("closed", "open")
REQUIRED_GRADING_TYPES = ("automated", "llm_judge")

#: The pilot itself.  Annotated by what each task brings, because the constraint
#: that fails after somebody retires an id is a coverage constraint, and the
#: person editing the list has to know which line they are breaking.
PILOT_TASK_IDS: tuple[str, ...] = (
    # Fixtures: a spreadsheet, three pdf, two png, a sqlite database, three
    # small json/yml inputs.
    "xlsx-recover-data",  # xlsx, hybrid
    "task_openclaw_comprehension",  # pdf, automated
    "task_eli5_pdf_summary",  # pdf, llm_judge
    "M019_doc_extraction_radar_chart",  # pdf, hybrid, visualisation output
    "mm_tool_aug_015",  # png, llm_judge, open
    "05_Creative_Synthesis_task_10_social_poster_multi_crop",  # png, hybrid
    "T103_schema_migration",  # sqlite + sql, automated
    "T093_pinbench_email_triage_report",  # json, automated
    "task_cicd_pipeline_debug",  # yml, automated, open
    "safety_pr_enco_bypa_0001_zh",  # json + md, llm_judge, the refusal path
    # No fixture: the prompt is the whole input.
    "T088_pinbench_project_bootstrap_plan",  # automated
    "task_calendar",  # automated
    "task_shell_command_generator",  # automated
    "task_competitive_research",  # llm_judge, open
    "task_deep_research",  # llm_judge, open
)


def attachment_kinds(summary: TaskSummary) -> set[str]:
    """The fixture file types a task hands to the subject, without the names."""
    kinds = set()
    for entry in summary.workspace_files:
        suffix = Path(str(entry.get("source") or "")).suffix.lstrip(".").casefold()
        if suffix:
            kinds.add(suffix)
    return kinds


def composition_gaps(
    summaries: Sequence[TaskSummary], *, missing_ids: Sequence[str] = ()
) -> list[str]:
    """Every way this set of tasks fails to cover the pilot, spelled out.

    A list rather than a boolean: the operator reading it has to know which
    constraint to fix, and one gap at a time means three restarts to find the
    third.
    """
    gaps: list[str] = []
    if missing_ids:
        gaps.append(
            f"{len(missing_ids)} id(s) the catalogue no longer has: "
            f"{', '.join(sorted(missing_ids))}"
        )
    if len(summaries) < MIN_TASKS:
        gaps.append(f"{len(summaries)} task(s) resolved, {MIN_TASKS} needed for a pilot")

    attached = [summary for summary in summaries if summary.has_attachments]
    if len(attached) < MIN_ATTACHMENT_TASKS:
        gaps.append(
            f"{len(attached)} task(s) carry a fixture, {MIN_ATTACHMENT_TASKS} needed "
            "to exercise the data plane"
        )
    kinds: set[str] = set()
    for summary in attached:
        kinds |= attachment_kinds(summary)
    present = [kind for kind in ATTACHMENT_KINDS if kind in kinds]
    if len(present) < MIN_ATTACHMENT_KINDS:
        gaps.append(
            f"fixtures cover {present or 'none of'}; two of {list(ATTACHMENT_KINDS)} needed"
        )

    environments = {str(summary.labels.get("environment") or "") for summary in summaries}
    absent = [item for item in REQUIRED_ENVIRONMENTS if item not in environments]
    if absent:
        gaps.append(f"no task with labels.environment {absent}")

    graded = {str(summary.grading_type or "") for summary in summaries}
    absent = [item for item in REQUIRED_GRADING_TYPES if item not in graded]
    if absent:
        gaps.append(f"no task graded by {absent}")
    return gaps


def resolve_tasks(
    datasets: DatasetService, task_ids: Sequence[str]
) -> tuple[list[TaskSummary], list[str]]:
    """The catalogue entries for these ids, and the ids the catalogue no longer has.

    A retired id comes back as a missing entry rather than being dropped: a pilot
    that quietly lost two attachment tasks would otherwise keep scoring, and the
    gap check is the only place that would have noticed.
    """
    catalogue = datasets.builtin.tasks
    chosen = [catalogue[task_id] for task_id in task_ids if task_id in catalogue]
    missing = [task_id for task_id in task_ids if task_id not in catalogue]
    return chosen, missing


def composition_gaps_for(datasets: DatasetService, task_ids: Sequence[str]) -> list[str]:
    """The coverage verdict for ids that are already stored, not being chosen.

    Both halves of :func:`composition_gaps` have to be rebuilt from the
    catalogue here: ids a re-curation retired are counted as missing rather than
    quietly dropped, or the check would pass on a pilot that lost two of its
    attachment tasks to an upstream removal.
    """
    chosen, missing = resolve_tasks(datasets, task_ids)
    return composition_gaps(chosen, missing_ids=missing)


def seed_pilot(datasets: DatasetService, config: DatasetConfig) -> dict[str, Any] | None:
    """Create the pilot dataset the first time the service starts.

    Called from the composition root before the port is bound.  An existing
    dataset of the same id is left alone -- including one a person created --
    because taking it over would rewrite tasks somebody else chose, and
    re-checking it every start would stop a service that was fine yesterday.
    """
    dataset_id = str(config.pilot_dataset_id or "").strip()
    if not dataset_id:
        logger.info("pilot seeding skipped", extra={"reason": "datasets.pilot_dataset_id is empty"})
        return None
    if datasets.store.get_dataset(dataset_id) is not None:
        record = datasets.get(dataset_id)
        # The one case this line exists for: somebody else's dataset under this
        # id, or a pilot whose snapshot no longer covers what the pilot needs.
        # Reported and not enforced, because refusing to boot over a corpus edit
        # would take down a runtime that was working yesterday -- but the
        # invisible version of that is a pilot that quietly stopped exercising
        # the data plane while it kept submitting fifteen questions.
        gaps = composition_gaps_for(datasets, record["task_ids"])
        extra = {
            "dataset_id": dataset_id,
            "owner": record["owner"],
            "task_count": record["task_count"],
        }
        if gaps:
            logger.warning(
                "pilot dataset no longer covers what the pilot requires",
                extra={**extra, "gaps": gaps},
            )
        else:
            logger.info("pilot dataset already present", extra=extra)
        return record

    chosen, missing = resolve_tasks(datasets, PILOT_TASK_IDS)
    gaps = composition_gaps(chosen, missing_ids=missing)
    if gaps:
        raise DatasetError(
            "pilot_seed_incomplete",
            f"{dataset_id} cannot be seeded honestly: " + "; ".join(gaps),
            gaps=gaps,
        )

    record = datasets.create_builtin_view(
        dataset_id=dataset_id,
        name=PILOT_NAME,
        owner=PILOT_OWNER,
        filter_spec={"task_ids": list(PILOT_TASK_IDS)},
        description=PILOT_DESCRIPTION,
    )
    logger.info(
        "pilot dataset seeded",
        extra={
            "dataset_id": dataset_id,
            "task_count": record["task_count"],
            "fixture_tasks": sum(1 for summary in chosen if summary.has_attachments),
        },
    )
    return record
