# -*- coding: utf-8 -*-
"""Dataset catalogue, categories, selector resolution and package validation."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Sequence

import pytest

from pawbench.cpd.acp_remote_eval.service import datasets as datasets_module
from pawbench.cpd.acp_remote_eval.service.auth import SCOPE_ADMIN, SCOPE_SUBMIT, Principal
from pawbench.cpd.acp_remote_eval.service.config import DatasetConfig
from pawbench.cpd.acp_remote_eval.service.datasets import (
    BuiltinCatalog,
    DatasetError,
    DatasetService,
    MAX_INDEX_CACHE,
    normalize_category_name,
    validate_package,
)
from pawbench.cpd.acp_remote_eval.service.store import Store
from pawbench.task_loader import Task, TaskLoader

from support import write_task

FILTER_KEYS = frozenset(
    {
        "scenario",
        "capability",
        "complexity",
        "environment",
        "modality",
        "source",
        "grading_type",
        "task_ids",
    }
)

ADMIN = Principal("admin", "Admin", frozenset({SCOPE_SUBMIT, SCOPE_ADMIN}))
OWNER = Principal("owner", "Owner", frozenset({SCOPE_SUBMIT}))
OTHER = Principal("other", "Other", frozenset({SCOPE_SUBMIT}))


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    root = tmp_path / "builtin"
    write_task(root, "mail_l1", scenario="Office_Productivity/Email", complexity="L1")
    write_task(root, "mail_l3", scenario="Office_Productivity/Email", complexity="L3")
    write_task(
        root,
        "chart_open",
        scenario="Data_Analytics/Visualization",
        environment="open",
        grading_type="llm_judge",
        capability=["Code_Manipulation", "Planning"],
    )
    write_task(
        root,
        "xlsx_with_file",
        scenario="Office_Productivity/Spreadsheet",
        modality="multimodal",
        grading_type="hybrid",
        fixtures=("budget.xlsx",),
    )
    write_task(root, "from_claw", scenario="Knowledge/QA", source="claw-eval")
    return root


@pytest.fixture()
def service(tmp_path: Path, builtin_root: Path) -> DatasetService:
    config = DatasetConfig(
        builtin_dir=builtin_root,
        custom_dir=tmp_path / "service" / "datasets",
        max_task_ids_per_dataset=500,
        builtin_view_filter_keys=FILTER_KEYS,
        category_create_scope="any",
        category_delete_scope="owner_or_admin",
        pilot_dataset_id="pilot_v1",
    )
    store = Store(tmp_path / "state.db")
    service = DatasetService(store, config, BuiltinCatalog(builtin_root))
    yield service
    store.close()


def view(spec: dict, *, dataset_id: str = "ds", owner: str = "owner", **kwargs) -> dict:
    return {
        "dataset_id": dataset_id,
        "name": kwargs.pop("name", dataset_id),
        "owner": owner,
        "filter_spec": spec,
        **kwargs,
    }


# ── filtering ────────────────────────────────────────────────────────────────


def test_apply_filter_single_key(service: DatasetService) -> None:
    ids = service.builtin.apply_filter({"environment": "open"}, FILTER_KEYS)
    assert ids == ["chart_open"]


def test_apply_filter_lists_are_or_within_key_and_are_and_across(service: DatasetService) -> None:
    catalog = service.builtin
    assert catalog.apply_filter({"complexity": ["L1", "L3"]}, FILTER_KEYS) == [
        "chart_open",
        "from_claw",
        "mail_l1",
        "mail_l3",
        "xlsx_with_file",
    ], "the fixture set has only L1 and L3 tasks"
    assert catalog.apply_filter(
        {"scenario": "Office_Productivity/Email", "complexity": "L3"}, FILTER_KEYS
    ) == ["mail_l3"]
    assert catalog.apply_filter({"capability": "Planning"}, FILTER_KEYS) == ["chart_open"]


def test_filter_keys_read_their_way(service: DatasetService) -> None:
    catalog = service.builtin
    assert catalog.apply_filter({"modality": "multimodal"}, FILTER_KEYS) == ["xlsx_with_file"]
    assert catalog.apply_filter({"grading_type": "hybrid"}, FILTER_KEYS) == ["xlsx_with_file"]
    assert catalog.apply_filter({"source": "claw-eval"}, FILTER_KEYS) == ["from_claw"]
    assert catalog.apply_filter({"task_ids": ["mail_l1", "nope"]}, FILTER_KEYS) == ["mail_l1"]


def test_task_ids_narrows_with_other_keys(service: DatasetService) -> None:
    assert service.builtin.apply_filter(
        {"task_ids": ["mail_l1", "mail_l3", "chart_open"], "environment": "open"}, FILTER_KEYS
    ) == ["chart_open"]


def test_unknown_filter_keys_are_refused(service: DatasetService) -> None:
    with pytest.raises(DatasetError) as caught:
        service.builtin.apply_filter({"difficulty": "L2"}, FILTER_KEYS)
    assert caught.value.code == "unknown_filter_key"

    with pytest.raises(DatasetError) as empty:
        service.builtin.apply_filter({}, FILTER_KEYS)
    assert empty.value.code == "empty_filter"


def test_key_allowed_by_config_only(service: DatasetService) -> None:
    narrowed = FILTER_KEYS - {"source"}
    with pytest.raises(DatasetError) as caught:
        service.builtin.apply_filter({"source": "claw-eval"}, narrowed)
    assert caught.value.code == "unknown_filter_key"


# ── builtin views ────────────────────────────────────────────────────────────


def test_builtin_view_stores_a_task_id_snapshot(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"scenario": "Office_Productivity/Email"}))
    assert record["task_ids"] == ["mail_l1", "mail_l3"]
    assert record["kind"] == "builtin_view"
    assert record["filter_spec"] == {"scenario": "Office_Productivity/Email"}

    service.builtin.tasks.pop("mail_l3")
    assert service.get(record["id"])["task_ids"] == ["mail_l1", "mail_l3"], (
        "the snapshot must survive re-curation of the task set"
    )


def test_builtin_view_rejects_empty_selection(service: DatasetService) -> None:
    with pytest.raises(DatasetError) as caught:
        service.create_builtin_view(**view({"scenario": "Nowhere/Nothing"}))
    assert caught.value.code == "empty_selection"


def test_creating_over_another_subjects_view_is_refused(service: DatasetService) -> None:
    """Dataset ids are not a race for the first writer to overwrite.

    Creation is open to everyone, but the upsert keeps the stored owner, so
    without this the second person's tasks land in a dataset the catalogue
    still attributes to the first -- and every job submitted against it is
    then graded on files its owner never chose.
    """
    service.create_builtin_view(**view({"environment": "open"}, dataset_id="shared"))

    with pytest.raises(DatasetError) as caught:
        service.create_builtin_view(
            **view({"task_ids": ["mail_l1"]}, dataset_id="shared", owner="other")
        )
    assert caught.value.code == "dataset_exists"
    assert caught.value.details["owner"] == "owner"

    kept = service.get("shared")
    assert kept["task_ids"] == ["chart_open"], "the refusal wrote nothing"
    assert kept["owner"] == "owner"


def test_the_owner_may_recreate_their_own_view(service: DatasetService) -> None:
    """Same owner, same id: the edit path the dataset skill re-registers through."""
    service.create_builtin_view(**view({"environment": "open"}, dataset_id="mine"))
    updated = service.create_builtin_view(**view({"task_ids": ["mail_l1"]}, dataset_id="mine"))

    assert updated["task_ids"] == ["mail_l1"]
    assert updated["owner"] == "owner"


def test_dataset_task_limit_is_enforced(tmp_path: Path, builtin_root: Path) -> None:
    config = DatasetConfig(
        builtin_dir=builtin_root,
        custom_dir=tmp_path / "datasets",
        max_task_ids_per_dataset=2,
        builtin_view_filter_keys=FILTER_KEYS,
        category_create_scope="any",
        category_delete_scope="owner_or_admin",
        pilot_dataset_id="pilot_v1",
    )
    tiny = DatasetService(Store(tmp_path / "state.db"), config, BuiltinCatalog(builtin_root))
    with pytest.raises(DatasetError) as caught:
        tiny.create_builtin_view(**view({"complexity": ["L1", "L3"]}))
    assert caught.value.code == "too_many_tasks"
    assert caught.value.details["task_count"] == 5


# ── categories ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [("Office  Docs", "office docs"), ("  office docs ", "office docs"), ("OFFICE DOCS", "office docs")],
)
def test_category_names_normalise(raw: str, expected: str) -> None:
    assert normalize_category_name(raw) == expected


def test_ensure_category_is_idempotent(service: DatasetService) -> None:
    first = service.ensure_category("Office  Docs", "owner")
    assert first["created"] is True
    assert first["name"] == "office docs"

    second = service.ensure_category("office docs", "someone-else")
    assert second["created"] is False
    assert second["created_by"] == "owner", "the first creator keeps ownership"
    assert len(service.list_categories()) == 1


def test_category_creation_is_open_but_deletion_is_not(service: DatasetService) -> None:
    service.ensure_category("office docs", OTHER.subject)
    record = service.create_builtin_view(**view({"environment": "open"}, categories=["Office Docs"]))
    assert record["categories"] == ["office docs"]

    with pytest.raises(DatasetError) as caught:
        service.delete_category("office docs", Principal("stranger", "S", frozenset({SCOPE_SUBMIT})))
    assert caught.value.code == "not_category_owner"

    with pytest.raises(DatasetError) as stranger:
        service.assign_categories(
            record["id"],
            Principal("stranger", "S", frozenset({SCOPE_SUBMIT})),
            add=["tagged by a stranger"],
        )
    assert stranger.value.code == "not_dataset_owner"
    assert record["categories"] == ["office docs"], "a stranger cannot relabel a dataset"

    service.assign_categories(record["id"], ADMIN, remove=["office docs"])
    service.delete_category("office docs", OTHER)
    assert service.list_categories() == []


def test_category_with_references_cannot_be_deleted(service: DatasetService) -> None:
    service.create_builtin_view(**view({"environment": "open"}, categories=["open set"]))
    with pytest.raises(DatasetError) as caught:
        service.delete_category("open set", ADMIN)
    assert caught.value.code == "category_referenced"
    assert caught.value.details["dataset_count"] == 1


def test_assign_categories_updates_counts(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"environment": "open"}))
    updated = service.assign_categories(record["id"], OWNER, add=["Open Set"])
    assert updated["categories"] == ["open set"]
    assert service.list_categories()[0]["dataset_count"] == 1


# ── selector resolution ──────────────────────────────────────────────────────


def test_resolve_dataset_only(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"scenario": "Office_Productivity/Email"}))
    result = service.resolve({"datasets": [record["id"]]})
    assert result.task_ids == ("mail_l1", "mail_l3")
    assert result.by_dataset == {record["id"]: 2}
    assert result.duplicates_removed == 0
    assert result.sources_by_task["mail_l1"] == (f"dataset:{record['id']}",)
    assert result.to_payload()["task_ids_digest"]


def test_resolve_mixed_selection_deduplicates(service: DatasetService) -> None:
    emails = service.create_builtin_view(
        **view({"scenario": "Office_Productivity/Email"}, dataset_id="emails")
    )
    broad = service.create_builtin_view(
        **view({"task_ids": ["mail_l1", "chart_open"]}, dataset_id="broad"), categories=["Pilot"]
    )

    result = service.resolve({"datasets": ["emails"], "categories": ["pilot"]})

    assert result.task_ids == ("mail_l1", "mail_l3", "chart_open"), "first-seen order is kept"
    assert result.duplicates_removed == 1
    assert result.by_category == {"pilot": 2}, "counted from the category's own datasets"
    assert result.by_dataset == {"emails": 2}, "category pulls are reported under the category"
    assert result.categories_expanded == {"pilot": ("broad",)}
    assert result.to_payload()["categories_expanded"] == {"pilot": ["broad"]}
    assert result.sources_by_task["mail_l1"] == ("dataset:emails", "category:pilot")
    assert result.sources_by_task["mail_l3"] == ("dataset:emails",)


def test_resolve_reports_unknown_ids_without_failing(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"environment": "open"}))
    result = service.resolve({"datasets": [record["id"], "ghost"], "categories": ["nope"]})
    assert result.unknown_ids == ("ghost", "nope")
    assert result.task_ids == ("chart_open",)


def test_resolve_empty_selector_is_an_error(service: DatasetService) -> None:
    with pytest.raises(DatasetError) as caught:
        service.resolve({"datasets": [], "categories": []})
    assert caught.value.code == "empty_selector"


def test_resolve_category_without_datasets_counts_zero(service: DatasetService) -> None:
    service.ensure_category("unused", "owner")
    result = service.resolve({"categories": ["unused"]})
    assert result.task_ids == ()
    assert result.by_category == {"unused": 0}


# ── dataset deletion ─────────────────────────────────────────────────────────


def test_dataset_deletion_checks_owner_then_references(service: DatasetService, store: Store) -> None:
    record = service.create_builtin_view(**view({"environment": "open"}, owner="owner"))
    service.store.insert_job_dataset(
        {"job_id": "job-1", "dataset_id": record["id"], "dataset_kind": "builtin_view"}
    )

    with pytest.raises(DatasetError) as stranger:
        service.delete_dataset(record["id"], OTHER)
    assert stranger.value.code == "not_dataset_owner"

    with pytest.raises(DatasetError) as referenced:
        service.delete_dataset(record["id"], OWNER)
    assert referenced.value.code == "dataset_referenced"
    assert referenced.value.details["job_ids"] == ["job-1"]

    service.store.delete_dataset(record["id"])
    assert service.store.get_dataset(record["id"]) is None


@pytest.fixture()
def store(service: DatasetService) -> Store:
    return service.store


# ── who did the write ────────────────────────────────────────────────────────


def said(caplog: pytest.LogCaptureFixture, *fields: str) -> list[tuple]:
    """The values of *fields* for every record that carries all of them.

    Selected by the ``extra`` keys rather than the message wording, so these
    assertions say what a line in the log can answer and not how it is phrased.
    """
    return [
        tuple(getattr(record, name) for name in fields)
        for record in caplog.records
        if all(hasattr(record, name) for name in fields)
    ]


def test_a_saved_view_names_the_subject_and_not_only_the_dataset(
    service: DatasetService, caplog: pytest.LogCaptureFixture
) -> None:
    """"Who keeps rewriting this set" needs a name in the record.

    A row that says only ``ds`` is a row nobody can follow up on: the catalogue
    shows the owner, and the owner is precisely the person who did not necessarily
    make this write.
    """
    with caplog.at_level(logging.INFO):
        service.create_builtin_view(**view({"environment": "open"}))

    assert said(caplog, "dataset_id", "by", "task_count") == [("ds", "owner", 1)]


def test_an_admins_recut_is_logged_as_the_admin(
    service: DatasetService, caplog: pytest.LogCaptureFixture
) -> None:
    """``actor`` exists because ``owner`` already means something else.

    :meth:`.DatasetService.edit_builtin_view` re-enters the create path carrying
    the *stored* owner, which is what keeps an admin's fix from taking over the
    view.  Reading that same value back as the author of the write turned every
    admin correction into a record saying the owner edited their own dataset --
    the one case where the log does not just omit the culprit but names the wrong
    person.
    """
    service.create_builtin_view(**view({"environment": "open"}, dataset_id="mine"))

    with caplog.at_level(logging.INFO):
        service.edit_builtin_view(
            dataset_id="mine", principal=ADMIN, filter_spec={"task_ids": ["mail_l1"]}
        )

    assert said(caplog, "dataset_id", "by") == [("mine", "admin")]
    assert service.get("mine")["owner"] == "owner", "the recut kept the author"


def test_a_deleted_dataset_names_the_operator_and_the_author(
    service: DatasetService, caplog: pytest.LogCaptureFixture
) -> None:
    """Two names, because the task files go with the row.

    An admin clearing somebody else's set is the one case where the two differ,
    and both parties have to be findable afterwards: the operator is who to ask,
    the author is who will notice the loss.
    """
    service.create_builtin_view(**view({"environment": "open"}, dataset_id="mine"))

    with caplog.at_level(logging.INFO):
        service.delete_dataset("mine", ADMIN)

    assert said(caplog, "dataset_id", "by", "owner") == [("mine", "admin", "owner")]


# ── catalog views ────────────────────────────────────────────────────────────


def test_catalog_listing_excludes_grading_material(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"environment": "open"}, description="open set"))
    catalog = service.list_catalog()
    entry = next(item for item in catalog["datasets"] if item["id"] == record["id"])
    assert entry["task_count"] == 1
    assert entry["categories"] == []
    assert "task_ids" not in entry, "the listing is for choosing, not for reading questions"
    assert catalog["label_distribution"]["environment"] == {"closed": 4, "open": 1}

    described = service.describe(record["id"])
    assert [task["task_id"] for task in described["tasks"]] == ["chart_open"]
    assert described["tasks"][0]["has_attachments"] is False
    payload = json.dumps(described)
    for forbidden in ("Write output/result.txt", "A file is written.", "conftest"):
        assert forbidden not in payload


def test_attachment_tasks_report_their_fixtures(service: DatasetService) -> None:
    record = service.create_builtin_view(**view({"task_ids": ["xlsx_with_file"]}))
    described = service.describe(record["id"])
    assert described["tasks"][0]["attachment_count"] == 1


# ── custom packages ──────────────────────────────────────────────────────────


def test_valid_package_registers_and_resolves(tmp_path: Path, service: DatasetService) -> None:
    package = tmp_path / "package"
    write_task(package, "cust_a", scenario="Custom/One")
    write_task(package, "cust_b", scenario="Custom/One", fixtures=["input.csv"])

    record = service.register_custom(
        dataset_id="cust-1", name="Custom set", owner="owner", source_dir=package
    )
    assert record["kind"] == "custom"
    assert record["task_ids"] == ["cust_a", "cust_b"]
    assert service.resolve({"datasets": ["cust-1"]}).task_ids == ("cust_a", "cust_b")

    described = service.describe("cust-1")
    assert described["tasks"][1]["attachment_count"] == 1
    assert (service.config.custom_dir / "cust-1" / "tasks" / "cust_a.md").is_file()


def test_registering_over_another_subjects_package_keeps_its_files(
    tmp_path: Path, service: DatasetService
) -> None:
    """The refusal happens before the copy, not after the damage.

    ``_copy_package`` replaces the target directory, so an id taken from its
    owner would otherwise delete their fixtures on the way to a database write
    that is going to be refused anyway.
    """
    first = tmp_path / "package-first"
    write_task(first, "cust_a", scenario="Custom/One")
    service.register_custom(dataset_id="cust-1", name="First", owner="owner", source_dir=first)
    kept = service.config.custom_dir / "cust-1" / "tasks" / "cust_a.md"
    assert kept.is_file()

    second = tmp_path / "package-second"
    write_task(second, "cust_b", scenario="Custom/Two")
    with pytest.raises(DatasetError) as caught:
        service.register_custom(
            dataset_id="cust-1", name="Second", owner="other", source_dir=second
        )
    assert caught.value.code == "dataset_exists"

    assert kept.is_file(), "the owner's package is still on disk"
    assert not (service.config.custom_dir / "cust-1" / "tasks" / "cust_b.md").exists()
    assert service.get("cust-1")["task_ids"] == ["cust_a"]


def test_a_refused_category_leaves_the_stored_package_and_its_row_alone(
    tmp_path: Path, service: DatasetService
) -> None:
    """A label is judged before the copy that replaces the old package.

    ``_copy_package`` deletes the target directory, so a package that is going to
    be refused for a category name nobody can file has to be refused while the
    files behind the stored row are still on disk.  Refused afterwards it leaves a
    dataset whose row names tasks that no longer exist, and every reader of that
    id resolves tasks the runner then finds no fixture for.
    """
    first = tmp_path / "package-first"
    write_task(first, "cust_a", scenario="Custom/One")
    service.register_custom(dataset_id="cust-1", name="First", owner="owner", source_dir=first)
    kept = service.config.custom_dir / "cust-1" / "tasks" / "cust_a.md"

    second = tmp_path / "package-second"
    write_task(second, "cust_b", scenario="Custom/Two")
    with pytest.raises(DatasetError) as caught:
        service.register_custom(
            dataset_id="cust-1",
            name="Second",
            owner="owner",
            source_dir=second,
            categories=["   "],
        )
    assert caught.value.code == "invalid_category_name"

    assert kept.is_file(), "the row still points at files that are still there"
    assert not (service.config.custom_dir / "cust-1" / "tasks" / "cust_b.md").exists()
    assert service.get("cust-1")["task_ids"] == ["cust_a"]


def test_a_refused_category_does_not_leave_a_package_directory_without_a_row(
    tmp_path: Path, service: DatasetService
) -> None:
    """The same refusal on a new id must not create the directory either.

    Nothing sweeps an unregistered package directory, and the runner is pointed at
    these paths -- so a directory with no row behind it is unchecked task files
    sitting on a path a job can be given.
    """
    package = tmp_path / "package"
    write_task(package, "cust_a", scenario="Custom/One")

    with pytest.raises(DatasetError) as caught:
        service.register_custom(
            dataset_id="cust-2",
            name="Fresh",
            owner="owner",
            source_dir=package,
            categories=["   "],
        )
    assert caught.value.code == "invalid_category_name"
    assert not (service.config.custom_dir / "cust-2").exists()


def test_a_test_module_in_the_package_is_refused(tmp_path: Path, service: DatasetService) -> None:
    """Pytest collects these names without being asked, on the scoring machine."""
    package = tmp_path / "pkg"
    write_task(package, "task_a", scenario="Custom/One")
    (package / "tasks" / "test_helpers.py").write_text(
        "def test_always_passes():\n    assert True\n", encoding="utf-8"
    )

    with pytest.raises(DatasetError) as caught:
        service.register_custom(
            dataset_id="pkg-1", name="Pkg", owner="owner", source_dir=package
        )

    assert caught.value.code == "package_invalid"
    codes = [item["code"] for item in caught.value.details["items"]]
    assert "forbidden_file_name" in codes


def test_an_oversized_package_is_refused_before_anything_is_read(
    tmp_path: Path, service: DatasetService, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "big"
    write_task(package, "task_a", scenario="Custom/One")
    write_task(package, "task_b", scenario="Custom/One")
    monkeypatch.setattr(
        "pawbench.cpd.acp_remote_eval.service.datasets.MAX_PACKAGE_FILES", 1
    )

    with pytest.raises(DatasetError) as caught:
        service.register_custom(
            dataset_id="big-1", name="Big", owner="owner", source_dir=package
        )

    assert caught.value.code == "package_too_large"
    assert not (service.config.custom_dir / "big-1").exists()


def test_invalid_package_is_refused_item_by_item(tmp_path: Path, service: DatasetService) -> None:
    package = tmp_path / "bad"
    write_task(package, "ok_task")
    broken = package / "tasks" / "broken.md"
    broken.write_text(
        "---\nid: broken\nname: broken\ncategory: x\n---\nnothing useful\n", encoding="utf-8"
    )
    (package / "tasks" / "conftest.py").write_text("import os\n", encoding="utf-8")
    (package / "tasks" / "README.md").write_text("# notes\n", encoding="utf-8")
    missing = package / "tasks" / "ghost.md"
    missing.write_text(
        "---\n"
        "id: ghost\n"
        "name: ghost\n"
        "category: x\n"
        "grading_type: automated\n"
        "timeout_seconds: 60\n"
        "workspace_files:\n"
        "- source: fixtures/gone.csv\n"
        "  dest: fixtures/gone.csv\n"
        "labels:\n"
        "  capabilities:\n"
        "  - Tool_Use\n"
        "  scenario: A/B\n"
        "  complexity: L1\n"
        "  environment: closed\n"
        "---\n\n## Prompt\n\ndo it\n",
        encoding="utf-8",
    )

    with pytest.raises(DatasetError) as caught:
        service.register_custom(dataset_id="bad-1", name="Bad", owner="owner", source_dir=package)
    assert caught.value.code == "package_invalid"

    codes = {item["code"] for item in caught.value.details["items"]}
    assert {"missing_prompt", "missing_frontmatter", "missing_labels"} <= codes
    assert "forbidden_file_name" in codes
    assert "fixture_not_found" in codes
    assert "no_task_files" not in codes, "README.md must not be reported as a task"
    assert not (service.config.custom_dir / "bad-1").exists()


def test_validate_package_reports_symlinks(tmp_path: Path) -> None:
    package = tmp_path / "link"
    write_task(package, "with_link")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = package / "fixtures" / "link.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    result = validate_package(package)
    assert result.ok is False
    assert "symlink_refused" in {item["code"] for item in result.items}


# ── one pass per poll ────────────────────────────────────────────────────────
#
# The dashboard polls the catalogue endpoints, so work here is multiplied by the
# number of open browsers rather than by how often a person clicks.  These cases
# count queries and parses instead of measuring time: a loop that re-reads the
# table per category or re-parses a package per request is far too fast to catch
# with a stopwatch, and far too easy to put back without anyone noticing.


def _dataset_table_reads(store: Store, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every query that reads the ``datasets`` table, recorded as it runs."""
    seen: list[str] = []
    real = store.query

    def spy(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if "FROM datasets" in sql:
            seen.append(sql)
        return real(sql, params)

    monkeypatch.setattr(store, "query", spy)
    return seen


def _parsed_dirs(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every directory the catalogue parses from markdown, in call order."""
    parsed: list[Path] = []
    real = datasets_module._load_task_summaries

    def spy(tasks_dir: Path) -> dict[str, Any]:
        parsed.append(tasks_dir)
        return real(tasks_dir)

    monkeypatch.setattr(datasets_module, "_load_task_summaries", spy)
    return parsed


def test_category_counts_read_the_catalogue_once_not_once_per_category(
    service: DatasetService, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        service.create_builtin_view(
            **view({"environment": "open"}, dataset_id=f"ds_{index}", categories=[f"open {index}"])
        )
    reads = _dataset_table_reads(service.store, monkeypatch)

    rows = service.list_categories()

    assert [row["dataset_count"] for row in rows] == [1, 1, 1, 1]
    assert len(reads) == 1, f"{len(reads)} reads of the datasets table for one listing"


def test_a_package_is_parsed_once_until_one_of_its_files_changes(
    tmp_path: Path, service: DatasetService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves, because a cache that never goes stale is a wrong answer.

    ``describe`` is the endpoint the picker calls for every row it shows, so
    parsing the package per request is the cost this trades away -- and the only
    thing that makes the trade safe is noticing an edited task file.  The rewrite
    adds a capability line rather than only a new mtime: size is one of the three
    numbers the signature reads, and it stays true on a filesystem with coarse
    timestamps.
    """
    package = tmp_path / "package"
    write_task(package, "cust_a", scenario="Custom/One")
    write_task(package, "cust_b", scenario="Custom/One")
    service.register_custom(
        dataset_id="cust-1", name="Custom set", owner="owner", source_dir=package
    )
    parses = _parsed_dirs(monkeypatch)

    first = service.describe("cust-1")
    second = service.describe("cust-1")

    assert second == first
    assert len(parses) == 1, "two describes parsed the same package twice"

    write_task(service.config.custom_dir / "cust-1", "cust_b", capability=["Tool_Use", "Retrieval"])

    described = service.describe("cust-1")

    assert len(parses) == 2, "an edited task file was served from a stale index"
    assert [task["task_id"] for task in described["tasks"]] == ["cust_a", "cust_b"]


def test_the_index_cache_does_not_grow_with_the_catalogue(
    tmp_path: Path, service: DatasetService
) -> None:
    """Every member may create a dataset, so a per-id cache needs an exit.

    The bound is the leak guard, and eviction has to stay harmless: the dataset
    whose entry was dropped is still described correctly, one parse later.
    """
    for index in range(MAX_INDEX_CACHE + 1):
        package = tmp_path / f"package-{index}"
        write_task(package, f"cust_{index}")
        service.register_custom(
            dataset_id=f"ds_{index}", name=f"set {index}", owner="owner", source_dir=package
        )
        service.describe(f"ds_{index}")

    assert len(service._indexes) <= MAX_INDEX_CACHE
    assert [task["task_id"] for task in service.describe("ds_0")["tasks"]] == ["cust_0"]


def test_tasks_for_run_reads_only_the_tasks_the_dataset_selected(
    service: DatasetService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's task list comes from the snapshot, not from a corpus walk.

    ``load_all_tasks`` parses every markdown file in the directory, which for a
    view over two of the corpus's tasks means five parses to keep two -- and the
    report renderer calls this once per dataset in a job.  The guard is the
    assertion here: a loader that refuses to walk the directory still has to
    hand back the selected tasks.
    """
    record = service.create_builtin_view(**view({"task_ids": ["mail_l1", "chart_open"]}))
    assert len(service.builtin.tasks) == 5, "the corpus index is warm before the patch"

    class NoWalkingLoader(TaskLoader):
        def load_all_tasks(self) -> list[Task]:
            raise AssertionError("tasks_for_run parsed the whole corpus")

    monkeypatch.setattr(datasets_module, "TaskLoader", NoWalkingLoader)

    tasks = service.tasks_for_run(record["id"])

    assert [task.task_id for task in tasks] == ["chart_open", "mail_l1"]


# ── the same cache with company on it ────────────────────────────────────────
#
# Every dataset and report route runs in its own worker thread, so the index is
# shared state even though nothing here is async.  These three cases cover what
# a single-threaded test cannot see: two workers reaching the same entry, a
# stored row that says more than it means, and a file that is there for the
# index but not for the reader.


def test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key(
    tmp_path: Path, service: DatasetService
) -> None:
    """Read, parse, write-and-evict has to be one step or the third one lies.

    Without a lock both workers pick the *same* oldest key to drop, and the
    second ``pop`` raises ``KeyError`` for a key the first already removed -- a
    request that fails on cache pressure, which is exactly when a dashboard
    reloads.  The sleep belongs to the test's dict, not to the service: it holds
    the winner at the moment of removal, so the interleaving is a fact about this
    run rather than a matter of thread luck.
    """
    for index in range(MAX_INDEX_CACHE):
        package = tmp_path / f"package-{index}"
        write_task(package, f"cust_{index}")
        service.register_custom(
            dataset_id=f"ds_{index}", name=f"set {index}", owner="owner", source_dir=package
        )
        service.describe(f"ds_{index}")

    class SlowEvictDict(dict):
        def pop(self, *args: Any, **kwargs: Any) -> Any:
            time.sleep(0.05)
            return dict.pop(self, *args, **kwargs)

    service._indexes = SlowEvictDict(service._indexes)
    for index in (MAX_INDEX_CACHE, MAX_INDEX_CACHE + 1):
        package = tmp_path / f"package-{index}"
        write_task(package, f"cust_{index}")
        service.register_custom(
            dataset_id=f"ds_{index}", name=f"set {index}", owner="owner", source_dir=package
        )

    failures: list[Exception] = []

    def describe(dataset_id: str) -> None:
        try:
            service.describe(dataset_id)
        except Exception as failure:  # noqa: BLE001 - the race's answer is the assertion
            failures.append(failure)

    workers = [
        threading.Thread(target=describe, args=(f"ds_{index}",))
        for index in (MAX_INDEX_CACHE, MAX_INDEX_CACHE + 1)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert not failures, f"consecutive describes failed with {failures}"
    # The count alone passed either way, so it says what the eviction was for: one
    # entry dropped, and neither of the two datasets that paid for the room loses
    # the cache entry it just wrote into it.
    survivors = set(service._indexes)
    assert len(survivors) == MAX_INDEX_CACHE, "exactly one eviction, not one per worker"
    assert {f"ds_{MAX_INDEX_CACHE}", f"ds_{MAX_INDEX_CACHE + 1}"} <= survivors


def test_a_category_filed_on_one_dataset_twice_is_one_dataset(service: DatasetService) -> None:
    """Both halves, because the duplicate rows are already in databases.

    Two spellings of one name normalize to one category, and the create path used
    to file it once per spelling: the same dataset then reads as two on the
    category list and in the number ``delete_category`` quotes when it refuses --
    an operator told a wrong thing about somebody else's data.  The write side has
    to stop making those rows and the read side still has to be right about the
    ones that exist.
    """
    record = service.create_builtin_view(
        **view(
            {"environment": "open"},
            dataset_id="ds_twice",
            categories=["Field Kit", "field  kit"],
        )
    )
    assert record["categories"] == ["field kit"]

    stored = dict(service.get("ds_twice"))
    stored["categories"] = ["field kit", "field kit"]
    service.store.upsert_dataset(stored)

    rows = [item for item in service.list_categories() if item["name"] == "field kit"]
    assert [row["dataset_count"] for row in rows] == [1]

    with pytest.raises(DatasetError) as refused:
        service.delete_category("Field Kit", OWNER)
    assert refused.value.details["dataset_count"] == 1


def test_an_unparseable_task_file_costs_its_task_and_not_the_run(
    tmp_path: Path,
    service: DatasetService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A file the index vouched for and the reader cannot parse is not a failed run.

    This is the narrow half of that disagreement: the corpus's own parser builds
    the index from the same files it reads here, so in normal service a broken
    file is missing from the index and the run never reaches this ``except`` --
    what the patch does is keep the signature unchanged while the read fails,
    which is what a file edited inside one timestamp tick looks like to us.  The
    common case, a task that is simply not on disk any more, is
    :func:`test_a_task_that_vanished_from_disk_is_reported_once_per_run`.
    """
    package = tmp_path / "package"
    write_task(package, "cust_a")
    write_task(package, "cust_b")
    service.register_custom(
        dataset_id="cust-1", name="Custom set", owner="owner", source_dir=package
    )
    service.describe("cust-1")

    class HalfBrokenLoader(TaskLoader):
        def load_task(self, task_file: Path) -> Task:
            if task_file.stem == "cust_b":
                raise ValueError(f"No YAML front-matter found in {task_file}")
            return TaskLoader.load_task(self, task_file)

    monkeypatch.setattr(datasets_module, "TaskLoader", HalfBrokenLoader)

    with caplog.at_level(logging.WARNING):
        tasks = service.tasks_for_run("cust-1")

    assert [task.task_id for task in tasks] == ["cust_a"]
    assert said(caplog, "dataset_id", "task_id") == [("cust-1", "cust_b")]


def test_a_corpus_edit_reaches_the_view_that_was_already_saved(
    service: DatasetService,
    builtin_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One report cannot carry two versions of the corpus.

    A view's ``task_ids`` are a snapshot on purpose, but its labels, its slices
    and the runner's timeouts all come out of the builtin index -- which used to
    be parsed once per process and never again.  The labelling flow edits those
    files while the daemon runs, and the same report reads the task bodies fresh
    from disk, so the stale half sat beside the current one in one document:
    ``describe`` still said ``Office_Productivity/Email`` above a prompt that had
    already moved on.  The other half of the promise is the cost: re-checking the
    files on every read, re-parsing only when they moved.
    """
    service.create_builtin_view(
        **view({"scenario": "Office_Productivity/Email"}, dataset_id="mail")
    )
    before = {item["task_id"]: item for item in service.describe("mail")["tasks"]}
    assert sorted(before) == ["mail_l1", "mail_l3"]
    assert before["mail_l3"]["labels"]["scenario"] == "Office_Productivity/Email"

    real_load = datasets_module._load_task_summaries
    parses: list[Path] = []
    monkeypatch.setattr(
        datasets_module,
        "_load_task_summaries",
        lambda directory: (parses.append(directory), real_load(directory))[1],
    )
    service.describe("mail")
    service.describe("mail")
    assert parses == [], "an unchanged corpus is parsed once, not once per read"

    write_task(builtin_root, "mail_l3", scenario="Data_Analytics/Charts", complexity="L2")

    after = {item["task_id"]: item for item in service.describe("mail")["tasks"]}
    assert len(parses) == 1, "one changed file costs one walk"
    assert after["mail_l3"]["labels"]["scenario"] == "Data_Analytics/Charts"
    assert after["mail_l3"]["labels"]["complexity"] == "L2"
    bodies = {task.task_id: task for task in service.tasks_for_run("mail")}
    assert (
        bodies["mail_l3"].frontmatter["labels"]["scenario"]
        == after["mail_l3"]["labels"]["scenario"]
    ), "the index and the bodies are two halves of one read of the same files"


def test_a_task_that_vanished_from_disk_is_reported_once_per_run(
    tmp_path: Path,
    service: DatasetService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A task the snapshot names but the index no longer holds used to vanish quietly.

    That is the ordinary way a file goes wrong -- edited, replaced, deleted -- and
    the signature notices, so the rebuild drops it from the index and the run
    simply comes up short.  ``tasks_for_run`` skipped it without a word, and the
    reader of the detail view saw a row with no labels and no prompt and could
    not tell a retired task from a broken corpus.  One line for the whole run,
    because the dashboard polls the report route that calls this.
    """
    package = tmp_path / "package"
    for task_id in ("cust_a", "cust_b", "cust_c"):
        write_task(package, task_id)
    service.register_custom(
        dataset_id="cust-1", name="Custom set", owner="owner", source_dir=package
    )
    assert len(service.describe("cust-1")["tasks"]) == 3, "the index is warm with all three"

    stored_tasks = service._tasks_dir(service.get("cust-1"))
    for task_id in ("cust_b", "cust_c"):
        (stored_tasks / f"{task_id}.md").unlink()

    with caplog.at_level(logging.WARNING):
        tasks = service.tasks_for_run("cust-1")

    assert [task.task_id for task in tasks] == ["cust_a"]
    assert said(caplog, "dataset_id", "absent_count") == [("cust-1", 2)]
    assert said(caplog, "task_ids") == [(["cust_b", "cust_c"],)]


def test_unfiling_a_category_removes_every_copy_of_it(service: DatasetService) -> None:
    """Rows written before the canonicalising create still hold a name twice.

    The two copies are spelled differently, which is the part that cannot be
    fixed by de-duplicating alone: every comparison in ``assign_categories`` is
    against a normalized name, so a row read raw keeps a copy that no ``remove``
    can reach.  The operator who un-files a tag then sees it come back on the
    next page, and the number ``delete_category`` refuses on keeps counting a
    dataset that no longer carries the category.  Both directions go through
    this one write, so the test touches both: filing something new has to repair
    the row it reads, and filing nothing but removing has to empty it.
    """
    service.create_builtin_view(
        **view({"environment": "open"}, dataset_id="ds_two", categories=["Field Kit"])
    )
    stored = dict(service.get("ds_two"))
    stored["categories"] = ["Field Kit", "field  kit"]
    service.store.upsert_dataset(stored)

    after_add = service.assign_categories("ds_two", OWNER, add=["Office Docs"])
    assert after_add["categories"] == ["field kit", "office docs"]

    after_remove = service.assign_categories("ds_two", OWNER, remove=["Field Kit"])
    assert after_remove["categories"] == ["office docs"]
    service.delete_category("Field Kit", OWNER)


def test_the_worker_that_loses_a_category_race_reports_the_row_that_landed(
    service: DatasetService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read then a write is not one step, and the primary key picks the winner.

    Two dashboards filing the same new tag both see "absent"; the loser used to
    raise ``IntegrityError`` and the route turned it into a 500 for a category
    that exists by then.  The race is staged in the test instead of in threads:
    the first insert here is the other worker committing, and the second is what
    our own call really hits.
    """
    real_insert = service.store.insert_category

    def landed_first(category: dict[str, Any]) -> None:
        real_insert({**category, "created_by": "someone-else"})
        real_insert(category)

    monkeypatch.setattr(service.store, "insert_category", landed_first)

    answer = service.ensure_category("Field Kit", "owner")

    assert answer["created"] is False
    assert answer["created_by"] == "someone-else"
    assert [item["name"] for item in service.list_categories()] == ["field kit"]
