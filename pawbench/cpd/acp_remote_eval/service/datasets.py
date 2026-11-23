# -*- coding: utf-8 -*-
"""Dataset catalogue, categories and selector resolution (design section 4).

Two kinds of dataset exist and, after creation, are treated identically by the
selector:

``builtin_view``
    A saved slice of ``data/pawbench-v1.0``.  The filter is resolved to an
    explicit ``task_ids`` snapshot at creation time -- a live view would change
    the questions under a result record whenever the community re-curates the
    task set, and a benchmark result that cannot say which 15 questions it ran
    is not reproducible.

``custom``
    A package uploaded through ``POST /v1/datasets`` (task markdown plus
    fixtures), validated before it is registered.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pawbench.task_loader import Task, TaskLoader

from .auth import Principal, SCOPE_ADMIN
from .config import DatasetConfig, SCORE_HIJACK_FILENAMES
from .store import Store, utc_now_iso

logger = logging.getLogger(__name__)

KIND_BUILTIN_VIEW = "builtin_view"
KIND_CUSTOM = "custom"

#: File names a grading process picks up automatically, so a package carrying
#: them would be editing the machine that scores it.  Same policy as the
#: artifact PUT endpoint -- one list, or a task file would pass where the same
#: name uploaded as an artifact would not.
FORBIDDEN_PACKAGE_NAMES = SCORE_HIJACK_FILENAMES

#: The same hazard by pattern: pytest collects these modules without being
#: asked, so an exact-name list cannot cover them.
_FORBIDDEN_NAME_PATTERNS = ("test_*.py", "*_test.py")

#: Quotas on one uploaded package.  Validation opens every task file and the
#: copy moves all of them, so an unbounded upload is a full disk on the machine
#: that also runs everyone else's evaluations.
MAX_PACKAGE_FILES = 2000
MAX_PACKAGE_BYTES = 256 * 1024 * 1024

#: How much of one member is held in memory while the quota is counted.  A
#: fixture is a spreadsheet or an image, so anything larger is the archive
#: lying about its own size -- which is why the copy is streamed, not ``read()``.
_UNPACK_CHUNK_BYTES = 1024 * 1024

#: How many datasets keep their parsed task index between requests.  The
#: dashboard polls ``describe`` and a report reads the same summaries for every
#: job it renders, so without this each poll parses every markdown file in the
#: package again.  Entries hold labels and file paths, never task bodies, and
#: the cache is bounded on purpose: every member may create a dataset, so an
#: unbounded per-id cache is a leak with a friendly name.  When full, the
#: entry added earliest goes.
MAX_INDEX_CACHE = 32

#: The task files a cached index was parsed from, as ``(name, size, mtime_ns)``.
#: Two uploads matching on all three numbers are the same bytes for our purposes.
_TaskSignature = tuple[tuple[str, int, int], ...]

#: How many ids one log line may name.  A dataset can hold hundreds of tasks, and
#: a warning that pastes them all turns the search for the failing one into a
#: scroll; the count rides along so the truncation is visible.
MAX_LOGGED_TASK_IDS = 20

_REQUIRED_FRONTMATTER_KEYS = ("grading_type", "timeout_seconds")
_REQUIRED_LABEL_KEYS = ("capabilities", "scenario", "complexity", "environment")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_WHITESPACE_RE = re.compile(r"\s+")


class DatasetError(ValueError):
    """A dataset request that must be refused, with a stable error code."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class TaskSummary:
    """Everything the catalogue may say about a task without leaking answers."""

    task_id: str
    name: str
    file_stem: str
    path: Path
    grading_type: str
    timeout_seconds: int
    workspace_files: tuple[Mapping[str, str], ...]
    labels: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_attachments(self) -> bool:
        return bool(self.workspace_files)

    def matches(self, key: str, wanted: set[str]) -> bool:
        return bool(wanted & self.values_for(key))

    def values_for(self, key: str) -> set[str]:
        labels = self.labels
        if key == "scenario":
            return {_text(labels.get("scenario"))}
        if key == "complexity":
            return {_text(labels.get("complexity"))}
        if key == "environment":
            return {_text(labels.get("environment"))}
        if key == "capability":
            return _text_set(labels.get("capabilities"))
        if key == "modality":
            modality = labels.get("modality")
            if isinstance(modality, Mapping):
                found = {_text(modality.get("type"))}
                found |= _text_set(modality.get("channels"))
                return found
            return {_text(modality)}
        if key == "grading_type":
            return {self.grading_type}
        if key == "source":
            return {_text(labels.get("source"))}
        raise KeyError(f"unsupported filter key: {key}")

    def to_catalog_entry(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "grading_type": self.grading_type,
            "timeout_seconds": self.timeout_seconds,
            "has_attachments": self.has_attachments,
            "attachment_count": len(self.workspace_files),
            "labels": dict(self.labels),
        }


@dataclass(frozen=True)
class ResolveResult:
    """A selector expanded to concrete tasks, with the dedup accounting."""

    task_ids: tuple[str, ...]
    by_dataset: dict[str, int]
    by_category: dict[str, int]
    duplicates_removed: int
    unknown_ids: tuple[str, ...]
    sources_by_task: dict[str, tuple[str, ...]] = field(default_factory=dict)
    categories_expanded: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def task_count(self) -> int:
        return len(self.task_ids)

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_ids": list(self.task_ids),
            "task_count": self.task_count,
            "task_ids_digest": digest_task_ids(self.task_ids),
            "by_dataset": dict(self.by_dataset),
            "by_category": dict(self.by_category),
            "duplicates_removed": self.duplicates_removed,
            "unknown_ids": list(self.unknown_ids),
            "categories_expanded": {
                key: list(value) for key, value in self.categories_expanded.items()
            },
        }


def digest_task_ids(task_ids: Sequence[str]) -> str:
    """Short stable fingerprint of a resolved task list."""
    joined = "\n".join(sorted(task_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def normalize_category_name(name: str) -> str:
    """casefold + collapse inner whitespace; the stored form of a category."""
    return _WHITESPACE_RE.sub(" ", str(name or "").strip()).casefold()


class BuiltinCatalog:
    """The task markdown shipped under ``data/pawbench-v1.0``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        # ``(signature, summaries)``, the same shape one entry of
        # ``DatasetService._indexes`` holds.  One attribute, so publishing is one
        # write: a reader either sees the whole pair or the one before it, and no
        # lock is needed to make the two fields agree with each other.
        self._index_pair: tuple[_TaskSignature, dict[str, TaskSummary]] | None = None

    @property
    def tasks(self) -> dict[str, TaskSummary]:
        """The corpus index, as current as the task files on disk.

        Called by the filter resolver, by ``describe`` for a builtin view, and by
        the report renderer.  It re-checks the files rather than parsing once per
        process because the labelling flow edits ``data/pawbench-v1.0`` while the
        daemon runs, and a report carries this index *next to* the freshly-read
        task bodies: an index that never expires puts two corpus versions inside
        one document, with yesterday's labels above today's prompt.  The check is
        a directory listing -- measured 0.55 ms over the shipped 150 tasks,
        against 163 ms to re-parse them.

        Two workers that both find a changed corpus parse it twice rather than
        queueing behind one another, which is the same trade :meth:`_index` makes.
        """
        signature = _task_file_signature(self.tasks_dir)
        cached = self._index_pair
        if cached is not None and cached[0] == signature:
            return cached[1]
        tasks = _load_task_summaries(self.tasks_dir)
        self._index_pair = (signature, tasks)
        return tasks

    @property
    def tasks_dir(self) -> Path:
        candidate = self.root / "tasks"
        return candidate if candidate.is_dir() else self.root

    def apply_filter(self, spec: Mapping[str, Any], allowed_keys: frozenset[str]) -> list[str]:
        if not spec:
            raise DatasetError("empty_filter", "a builtin view needs at least one filter key")
        unknown = sorted(str(key) for key in spec if key not in allowed_keys)
        if unknown:
            raise DatasetError(
                "unknown_filter_key",
                f"unsupported filter keys: {unknown}; allowed: {sorted(allowed_keys)}",
            )

        explicit = spec.get("task_ids")
        # One reference to the index for the whole filter: each read re-checks the
        # corpus's file list, and a loop over 150 tasks would pay for that 150
        # times.
        tasks = self.tasks
        # Unknown ids inside a filter are dropped rather than raised: the pilot
        # seed lists task ids by hand, and a task retired upstream should shrink
        # the view, not break every submission that references it.
        candidates = (
            [task_id for task_id in _as_list(explicit) if task_id in tasks]
            if explicit
            else list(tasks)
        )

        matched = []
        for task_id in candidates:
            summary = tasks[task_id]
            if all(
                key == "task_ids" or summary.matches(key, _as_value_set(value))
                for key, value in spec.items()
            ):
                matched.append(task_id)
        return sorted(matched)


class DatasetService:
    """Create, list, categorise and resolve datasets."""

    def __init__(
        self,
        store: Store,
        config: DatasetConfig,
        builtin: BuiltinCatalog | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.builtin = builtin if builtin is not None else BuiltinCatalog(config.builtin_dir)
        self._indexes: dict[str, tuple[_TaskSignature, dict[str, TaskSummary]]] = {}
        # Every dataset and report route reaches this service through
        # ``asyncio.to_thread``, so two workers can land on the same cache at the
        # same time; the lock covers the read-modify-write of one entry, including
        # the eviction that picks which key to drop.
        self._index_lock = threading.Lock()

    # ── creation ──────────────────────────────────────────────────────────────

    def create_builtin_view(
        self,
        *,
        dataset_id: str,
        name: str,
        owner: str,
        filter_spec: Mapping[str, Any],
        categories: Sequence[str] = (),
        description: str = "",
        actor: str = "",
    ) -> dict[str, Any]:
        """Save one slice of the built-in corpus as a dataset anybody may name.

        Called when a view is first minted; re-cutting one that already exists
        goes through :meth:`edit_builtin_view`, which is where the owner check is.
        That path lands here too, so *actor* says who asked for this write while
        *owner* stays who the stored view belongs to -- without the two, an admin
        fixing somebody else's filter is logged as that somebody creating it.
        """
        dataset_id = self._check_id(dataset_id)
        self._check_no_takeover(dataset_id, owner, KIND_BUILTIN_VIEW)
        task_ids = self.builtin.apply_filter(filter_spec, self.config.builtin_view_filter_keys)
        self._check_task_limit(task_ids)
        if not task_ids:
            raise DatasetError(
                "empty_selection", "the filter resolved to zero tasks; widen it before saving"
            )
        # Filed as a set: two spellings of one name normalize to one category, and
        # storing it twice would show the tag twice in the picker.
        resolved_categories = list(
            dict.fromkeys(self.ensure_category(item, owner)["name"] for item in categories)
        )
        record = {
            "id": dataset_id,
            "name": name or dataset_id,
            "owner": owner,
            "kind": KIND_BUILTIN_VIEW,
            "description": description,
            "categories": resolved_categories,
            "task_ids": task_ids,
            "filter_spec": dict(filter_spec),
        }
        self.store.upsert_dataset(record)
        logger.info(
            "builtin view stored",
            extra={
                "dataset_id": record["id"],
                "task_count": len(task_ids),
                "by": actor or owner,
            },
        )
        return self.get(record["id"])

    def edit_builtin_view(
        self,
        *,
        dataset_id: str,
        principal: Principal,
        filter_spec: Mapping[str, Any],
        name: str = "",
        categories: Sequence[str] = (),
        description: str = "",
    ) -> dict[str, Any]:
        """Re-cut a saved view -- the restricted half of the dataset rule (D15).

        Creating is open to every whitelisted subject, so a stranger who points
        :meth:`create_builtin_view` at somebody else's id gets ``dataset_exists``:
        the right answer when the id was a guess, a dead end when it was chosen.
        This call carries the principal, so it answers with the ownership rule
        instead.  The stored owner is kept -- an admin who re-cuts a view to fix a
        bad filter does not take the view over.

        An empty *name*, *categories* or *description* means "leave as stored";
        un filing a dataset is a different act and goes through
        :meth:`assign_categories`.
        """
        existing = self.get(dataset_id)
        if existing["kind"] != KIND_BUILTIN_VIEW:
            raise DatasetError(
                "dataset_kind_fixed",
                f"{dataset_id} holds an uploaded package; replace it by posting the "
                "archive to /v1/datasets/packages",
                kind=existing["kind"],
            )
        if existing["owner"] != principal.subject and not principal.can(SCOPE_ADMIN):
            raise DatasetError(
                "not_dataset_owner",
                f"only {existing['owner']} or an admin can edit this dataset",
            )
        return self.create_builtin_view(
            dataset_id=dataset_id,
            name=name or existing["name"],
            owner=existing["owner"],
            filter_spec=filter_spec,
            categories=list(categories) or existing["categories"],
            description=description or existing["description"],
            actor=principal.subject,
        )

    def register_custom(
        self,
        *,
        dataset_id: str,
        name: str,
        owner: str,
        source_dir: Path,
        categories: Sequence[str] = (),
        description: str = "",
    ) -> dict[str, Any]:
        self._check_package_footprint(Path(source_dir))
        package = validate_package(Path(source_dir))
        if not package.ok:
            raise DatasetError(
                "package_invalid",
                "uploaded dataset failed validation",
                items=package.as_payload()["items"],
            )
        self._check_task_limit(package.task_ids)

        dataset_id = self._check_id(dataset_id)
        # Everything that can still refuse is refused here, before the copy.
        # ``_copy_package`` replaces the target directory, so a refusal that comes
        # after it -- a takeover that is not this caller's to make, a category
        # name that cleans down to nothing -- would leave the stored row naming
        # files that are gone, or a directory no row names.
        self._check_no_takeover(dataset_id, owner, KIND_CUSTOM)
        # The same set rule as the builtin view, applied before the copy: the
        # refusal has to happen while nothing on disk has moved yet.
        wanted_categories = list(
            dict.fromkeys(self._category_name_or_refuse(item) for item in categories)
        )
        target = self._custom_dir(dataset_id)
        _copy_package(Path(source_dir), target)
        resolved_categories = [
            self.ensure_category(item, owner)["name"] for item in wanted_categories
        ]
        record = {
            "id": dataset_id,
            "name": name or dataset_id,
            "owner": owner,
            "kind": KIND_CUSTOM,
            "description": description,
            "categories": resolved_categories,
            "task_ids": list(package.task_ids),
            "filter_spec": None,
        }
        self.store.upsert_dataset(record)
        logger.info(
            "custom dataset registered",
            extra={
                "dataset_id": dataset_id,
                "task_count": len(package.task_ids),
                # An upload can only land on the caller's own id, so here the
                # stored owner and the one who pressed send are the same person.
                "by": owner,
            },
        )
        return self.get(dataset_id)

    def register_custom_archive(
        self,
        *,
        dataset_id: str,
        name: str,
        owner: str,
        archive: Path,
        categories: Sequence[str] = (),
        description: str = "",
    ) -> dict[str, Any]:
        """Register an uploaded zip, unpacked only into a directory we throw away.

        *archive* is a file the route streamed to disk and handed over; this call
        does not own it, but it never keeps a copy either.

        The staging tree goes whatever happens.  A package that
        :func:`validate_package` refuses has already been written to disk once,
        and leaving it there would put unregistered -- therefore unchecked --
        task files on a path the runner can be pointed at.
        """
        with tempfile.TemporaryDirectory(prefix="pawbench-package-") as staging:
            unpack_package(archive, Path(staging))
            return self.register_custom(
                dataset_id=dataset_id,
                name=name,
                owner=owner,
                source_dir=Path(staging),
                categories=categories,
                description=description,
            )

    # ── reading ───────────────────────────────────────────────────────────────

    def get(self, dataset_id: str) -> dict[str, Any]:
        record = self.store.get_dataset(dataset_id)
        if record is None:
            raise DatasetError("dataset_not_found", f"no such dataset: {dataset_id}")
        return record

    def list_catalog(self) -> dict[str, Any]:
        """Directory listing: no task bodies, no rubric, no grading code."""
        datasets = []
        for record in self.store.list_datasets():
            datasets.append(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "owner": record["owner"],
                    "kind": record["kind"],
                    "description": record["description"],
                    "categories": record["categories"],
                    "task_count": record["task_count"],
                    "updated_at": record["updated_at"],
                }
            )
        return {
            "datasets": datasets,
            "categories": self.list_categories(),
            "label_distribution": self._distribution(),
        }

    def describe(self, dataset_id: str) -> dict[str, Any]:
        record = self.get(dataset_id)
        summaries = self.task_summaries(record)
        return {
            "id": record["id"],
            "name": record["name"],
            "owner": record["owner"],
            "kind": record["kind"],
            "description": record["description"],
            "categories": record["categories"],
            "filter_spec": record["filter_spec"],
            "task_count": len(summaries),
            "tasks": [summary.to_catalog_entry() for summary in summaries],
        }

    def task_summaries(self, record: Mapping[str, Any]) -> list[TaskSummary]:
        index = self._index(record["id"])
        return [index[task_id] for task_id in record["task_ids"] if task_id in index]

    def tasks_for_run(self, dataset_id: str) -> list[Task]:
        """Full task objects for the runner; never exposed through the catalogue.

        Only the prompt, labels and attachment list leave here -- the grading
        text stays with the grader, and ``service.reports`` reads the same bodies
        to fill the detail view (design section 4.1).

        Parsed through the index instead of ``load_all_tasks()``: the dataset
        record already says which ids it holds, so a builtin view over the whole
        corpus would otherwise parse every task file in it to keep the fifteen it
        selected.
        """
        record = self.get(dataset_id)
        index = self._index(record["id"])
        loader = TaskLoader(self._tasks_dir(record))
        tasks: list[Task] = []
        absent: list[str] = []
        for task_id in record["task_ids"]:
            summary = index.get(task_id)
            if summary is None or not summary.path.is_file():
                absent.append(task_id)
                continue
            try:
                tasks.append(loader.load_task(summary.path))
            except ValueError as failure:
                # Reading the index used to do this skipping inside
                # ``load_all_tasks()``; keeping it here means one unparseable file
                # costs the task it sits in, not the whole run.
                logger.warning(
                    "dataset task skipped",
                    extra={
                        "dataset_id": dataset_id,
                        "task_id": task_id,
                        "reason": str(failure),
                    },
                )
        if absent:
            # The other half of that semantics, and the half that used to be
            # silent: a task the snapshot names but the index no longer holds is
            # one the run will not execute, and the report reader sees a row with
            # no labels and no prompt and no way to tell "retired" from "broken".
            # Aggregated to one line because the dashboard polls the report route,
            # which reaches here on every poll.
            logger.warning(
                "dataset tasks not on disk",
                extra={
                    "dataset_id": dataset_id,
                    "task_ids": absent[:MAX_LOGGED_TASK_IDS],
                    "absent_count": len(absent),
                    "task_count": len(tasks),
                },
            )
        return tasks

    def root_for(self, dataset_id: str) -> Path:
        """The directory a dataset's fixtures are relative to.

        The runner needs it to serve ``workspace_files[].source``, and it is a
        different directory for each kind -- the builtin corpus versus the
        unpacked upload -- so it cannot be a constant.
        """
        return self._dataset_root(self.get(dataset_id))

    # ── deletion ──────────────────────────────────────────────────────────────

    def delete_dataset(self, dataset_id: str, principal: Principal) -> None:
        record = self.get(dataset_id)
        if record["owner"] != principal.subject and not principal.can(SCOPE_ADMIN):
            raise DatasetError(
                "not_dataset_owner",
                f"only {record['owner']} or an admin can delete this dataset",
            )
        refs = self.store.dataset_job_refs(dataset_id)
        if refs:
            raise DatasetError(
                "dataset_referenced",
                f"{len(refs)} job(s) reference this dataset; it cannot be deleted",
                job_ids=refs[:20],
            )
        self.store.delete_dataset(dataset_id)
        logger.info(
            "dataset deleted",
            # Both names, because an admin deleting somebody's set is the one
            # case where they are not the same person -- and the only one where
            # "who removed these task files" has to be answered from the log.
            extra={"dataset_id": dataset_id, "by": principal.subject, "owner": record["owner"]},
        )

    # ── categories ────────────────────────────────────────────────────────────

    @staticmethod
    def _category_name_or_refuse(name: str) -> str:
        """The stored form of *name*, or the refusal explaining why there is none.

        Split out because a caller that is about to spend a disk write needs the
        answer before it spends it -- see :meth:`register_custom`.
        """
        normalized = normalize_category_name(name)
        if not normalized:
            raise DatasetError("invalid_category_name", "category name is empty after cleaning")
        return normalized

    def ensure_category(self, name: str, created_by: str, description: str = "") -> dict[str, Any]:
        """Idempotent create, so a skill can file a dataset without asking first."""
        normalized = self._category_name_or_refuse(name)
        existing = self.store.get_category(normalized)
        if existing is not None:
            return {**existing, "created": False}
        try:
            self.store.insert_category(
                {"name": normalized, "description": description, "created_by": created_by}
            )
        except sqlite3.IntegrityError:
            # The read above cannot settle it: two workers filing the same new
            # name both see nothing, and the primary key decides which one wrote.
            # Without this the loser answers 500 for a category that now exists,
            # which is the first thing a dashboard does when it groups a set.
            logger.info(
                "category created elsewhere",
                extra={"category": normalized, "by": created_by},
            )
            return {**self.store.get_category(normalized), "created": False}
        logger.info("category created", extra={"category": normalized, "by": created_by})
        return {**self.store.get_category(normalized), "created": True}

    def list_categories(self) -> list[dict[str, Any]]:
        counts = self.store.category_dataset_counts()
        return [
            {**record, "dataset_count": counts.get(record["name"], 0)}
            for record in self.store.list_categories()
        ]

    def delete_category(self, name: str, principal: Principal) -> None:
        normalized = normalize_category_name(name)
        record = self.store.get_category(normalized)
        if record is None:
            raise DatasetError("category_not_found", f"no such category: {name}")
        if record["created_by"] != principal.subject and not principal.can(SCOPE_ADMIN):
            raise DatasetError(
                "not_category_owner",
                f"category {normalized} is maintained by {record['created_by']}",
            )
        references = self.store.datasets_with_category(normalized)
        if references:
            raise DatasetError(
                "category_referenced",
                f"{references} dataset(s) still use this category",
                dataset_count=references,
            )
        self.store.delete_category(normalized)

    def assign_categories(
        self,
        dataset_id: str,
        principal: Principal,
        *,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> dict[str, Any]:
        record = self.get(dataset_id)
        # Categories are how a dataset turns up inside someone else's selector,
        # and a new one is attributed to whoever is named below -- so this needs
        # the same owner-or-admin rule that guards deletion.  Without it any
        # whitelisted subject could relabel another person's dataset.
        if record["owner"] != principal.subject and not principal.can(SCOPE_ADMIN):
            raise DatasetError(
                "not_dataset_owner",
                f"only {record['owner']} or an admin can change these categories",
            )
        # Canonicalised up front, not only on the way out: rows written before
        # the create path started collapsing spellings can carry one name twice,
        # or carry it in a spelling nothing else uses.  Every comparison below is
        # against a normalized name, so a row read raw would keep a copy that no
        # ``remove`` can reach -- the operator un-files a tag and sees it stay,
        # and ``delete_category`` keeps refusing on a reference that is gone.
        current = list(
            dict.fromkeys(normalize_category_name(name) for name in record["categories"])
        )
        for name in add:
            category = normalize_category_name(name)
            if not category:
                raise DatasetError("invalid_category_name", f"unusable category name: {name!r}")
            self.ensure_category(category, principal.subject)
            if category not in current:
                current.append(category)
        dropped = {normalize_category_name(name) for name in remove}
        current = [item for item in current if item not in dropped]
        self.store.execute(
            "UPDATE datasets SET categories = ?, updated_at = ? WHERE id = ?",
            (_json(current), utc_now_iso(), dataset_id),
        )
        return self.get(dataset_id)

    # ── selector ──────────────────────────────────────────────────────────────

    def resolve(self, selector: Mapping[str, Any]) -> ResolveResult:
        """Expand {datasets, categories} into a de-duplicated task list."""
        dataset_ids = _as_list(selector.get("datasets"))
        category_names = [normalize_category_name(n) for n in _as_list(selector.get("categories"))]
        if not dataset_ids and not category_names:
            raise DatasetError("empty_selector", "select at least one dataset or category")

        unknown: list[str] = []
        by_dataset: dict[str, int] = {}
        by_category: dict[str, int] = {}
        expanded: dict[str, tuple[str, ...]] = {}
        sources_by_task: dict[str, list[str]] = {}
        ordered: list[str] = []

        members: list[tuple[str, list[str]]] = []
        for dataset_id in dataset_ids:
            record = self.store.get_dataset(dataset_id)
            if record is None:
                unknown.append(dataset_id)
                continue
            members.append((f"dataset:{dataset_id}", list(record["task_ids"])))
        for category in category_names:
            if self.store.get_category(category) is None:
                unknown.append(category)
                continue
            included = [
                record for record in self.store.list_datasets() if category in record["categories"]
            ]
            if not included:
                by_category[category] = 0
                continue
            merged: list[str] = []
            for record in included:
                for task_id in record["task_ids"]:
                    if task_id not in merged:
                        merged.append(task_id)
            expanded[category] = tuple(sorted(record["id"] for record in included))
            members.append((f"category:{category}", merged))

        for source, task_ids in members:
            kind = source.split(":", 1)[0]
            name = source.split(":", 1)[1]
            if kind == "dataset":
                by_dataset[name] = by_dataset.get(name, 0) + len(task_ids)
            else:
                by_category[name] = len(task_ids)
            for task_id in task_ids:
                origins = sources_by_task.setdefault(task_id, [])
                if source not in origins:
                    origins.append(source)
                if task_id not in ordered:
                    ordered.append(task_id)

        duplicates_removed = sum(len(ids) for _, ids in members) - len(ordered)
        self._check_task_limit(ordered)
        return ResolveResult(
            task_ids=tuple(ordered),
            by_dataset=by_dataset,
            by_category=by_category,
            duplicates_removed=duplicates_removed,
            unknown_ids=tuple(unknown),
            sources_by_task={key: tuple(value) for key, value in sources_by_task.items()},
            categories_expanded=expanded,
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _check_id(self, dataset_id: str) -> str:
        if not _ID_RE.match(str(dataset_id or "")):
            raise DatasetError(
                "invalid_dataset_id",
                "dataset id must match [A-Za-z0-9][A-Za-z0-9._-]{0,79}",
            )
        return str(dataset_id)

    def _check_package_footprint(self, package_dir: Path) -> None:
        """Refuse a package that does not fit, before any of it is read.

        Validation opens every task file and the copy moves all of them, so the
        quota is the difference between a refused upload and a full disk.
        """
        files = 0
        total_bytes = 0
        for path in _all_files(package_dir):
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
        if files > MAX_PACKAGE_FILES or total_bytes > MAX_PACKAGE_BYTES:
            raise DatasetError(
                "package_too_large",
                f"{files} files totalling {total_bytes} bytes is over the quota of "
                f"{MAX_PACKAGE_FILES} files / {MAX_PACKAGE_BYTES} bytes",
            )

    def _check_no_takeover(self, dataset_id: str, owner: str, kind: str) -> None:
        """Refuse a create that would silently rewrite someone else's dataset.

        ``upsert_dataset`` keeps the stored owner and the stored kind, so without
        this the second person's tasks, categories and description land in a
        dataset the catalogue still attributes to the first -- and every job they
        submit afterwards is graded against files they never chose.  Editing
        another person's dataset is the restricted half of the creation rule, so
        the only way through is to delete it first, which is where the ownership
        check is enforced with a principal in hand.

        The kind check is the same defect one level down: a create that arrives
        with the *owner's* id but the other kind would swap ``task_ids`` and
        ``filter_spec`` under a row that still reads ``custom`` in the catalogue,
        which is a dataset whose listing lies about what it holds.
        """
        existing = self.store.get_dataset(dataset_id)
        if existing is None:
            return
        if existing["owner"] != owner:
            raise DatasetError(
                "dataset_exists",
                f"dataset {dataset_id} belongs to {existing['owner']}; "
                "use a new id or have the owner delete it",
                owner=existing["owner"],
            )
        if existing["kind"] != kind:
            raise DatasetError(
                "dataset_kind_fixed",
                f"{dataset_id} was created as {existing['kind']}; delete it and "
                "re-create it if it should hold something else",
                kind=existing["kind"],
            )

    def _check_task_limit(self, task_ids: Sequence[str]) -> None:
        if len(task_ids) > self.config.max_task_ids_per_dataset:
            raise DatasetError(
                "too_many_tasks",
                f"a dataset may hold at most {self.config.max_task_ids_per_dataset} tasks",
                task_count=len(task_ids),
            )

    def _custom_dir(self, dataset_id: str) -> Path:
        return Path(self.config.custom_dir) / dataset_id

    def _dataset_root(self, record: Mapping[str, Any]) -> Path:
        if record["kind"] == KIND_CUSTOM:
            return self._custom_dir(record["id"])
        return self.config.builtin_dir

    def _index(self, dataset_id: str) -> dict[str, TaskSummary]:
        record = self.get(dataset_id)
        if record["kind"] == KIND_BUILTIN_VIEW:
            return self.builtin.tasks
        tasks_dir = self._tasks_dir(record)
        signature = _task_file_signature(tasks_dir)
        with self._index_lock:
            cached = self._indexes.get(dataset_id)
            if cached is not None and cached[0] == signature:
                return cached[1]
        # Parsing runs outside the lock: it is the slow part, and two workers that
        # both miss pay for the directory walk twice rather than queueing behind it.
        summaries = _load_task_summaries(tasks_dir)
        with self._index_lock:
            if dataset_id not in self._indexes and len(self._indexes) >= MAX_INDEX_CACHE:
                self._indexes.pop(next(iter(self._indexes)))
            self._indexes[dataset_id] = (signature, summaries)
        return summaries

    def _tasks_dir(self, record: Mapping[str, Any]) -> Path:
        """Where a dataset's markdown lives: the package's ``tasks/``, or its root."""
        root = self._dataset_root(record)
        tasks_dir = root / "tasks"
        return tasks_dir if tasks_dir.is_dir() else root

    def _distribution(self) -> dict[str, dict[str, int]]:
        buckets: dict[str, dict[str, int]] = {}
        for summary in self.builtin.tasks.values():
            for key in ("scenario", "complexity", "environment", "grading_type"):
                values = summary.values_for(key)
                counts = buckets.setdefault(key, {})
                for value in values:
                    if value:
                        counts[value] = counts.get(value, 0) + 1
        return buckets


@dataclass(frozen=True)
class PackageValidation:
    ok: bool
    task_ids: tuple[str, ...]
    items: tuple[Mapping[str, str], ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "task_ids": list(self.task_ids),
            "items": [dict(item) for item in self.items],
        }


def validate_package(package_dir: Path) -> PackageValidation:
    """Static check of an uploaded dataset before it is registered.

    Runs on the service host, so the file-name blacklist is the part that
    matters most: a package containing ``conftest.py`` would otherwise be
    collected by the grading process.
    """
    if not package_dir.is_dir():
        return PackageValidation(False, (), ({"file": str(package_dir), "code": "not_a_directory",
                                              "message": "uploaded package is not a directory"},))
    problems: list[dict[str, str]] = []
    parsed = [(path, _try_load(path)) for path in _markdown_files(package_dir)]
    if not any(task is not None for _, task in parsed):
        problems.append(
            {"file": ".", "code": "no_task_files", "message": "no task markdown found in package"}
        )

    for path in _all_files(package_dir):
        if path.is_symlink():
            problems.append(
                {"file": _rel(path, package_dir), "code": "symlink_refused",
                 "message": "symlinks are not unpacked into a workspace"}
            )
        if _is_forbidden_package_file(path):
            problems.append(
                {"file": _rel(path, package_dir), "code": "forbidden_file_name",
                 "message": f"{path.name} would be picked up by the grading process"}
            )

    task_ids: list[str] = []
    for md, loaded in parsed:
        if isinstance(loaded, str):
            problems.append({"file": _rel(md, package_dir), "code": "unparsable",
                             "message": loaded})
            continue
        if loaded is None:
            continue
        problems.extend(_task_problems(loaded, md, package_dir))
        if loaded.task_id in task_ids:
            problems.append({"file": _rel(md, package_dir), "code": "duplicate_task_id",
                             "message": f"task id {loaded.task_id} appears twice"})
        else:
            task_ids.append(loaded.task_id)

    return PackageValidation(not problems, tuple(sorted(task_ids)), tuple(problems))


def _try_load(md: Path) -> Task | str | None:
    """Parse one markdown file: Task, ``None`` for a non-task file, or the error text."""
    try:
        return TaskLoader(md.parent).load_task(md)
    except ValueError as exc:
        # A README in the package is normal; a file with front matter is meant to be a task.
        return None if not _has_front_matter(md) else str(exc)


def _has_front_matter(md: Path) -> bool:
    text = md.read_text(encoding="utf-8", errors="replace")
    return bool(re.match(r"^---\s*\n", text))


def _task_problems(task: Task, md: Path, package_dir: Path) -> list[dict[str, str]]:
    problems = []
    relative = _rel(md, package_dir)
    if not task.prompt:
        problems.append({"file": relative, "code": "missing_prompt",
                         "message": "the task needs a '## Prompt' section"})
    for key in _REQUIRED_FRONTMATTER_KEYS:
        if key not in task.frontmatter:
            problems.append({"file": relative, "code": "missing_frontmatter",
                             "message": f"front matter must define {key}"})
    if "workspace_files" not in task.frontmatter:
        problems.append(
            {"file": relative, "code": "missing_frontmatter",
             "message": "front matter must declare workspace_files (empty list when none)"}
        )
    labels = task.frontmatter.get("labels") or {}
    if not isinstance(labels, Mapping):
        problems.append({"file": relative, "code": "missing_labels",
                         "message": "labels must be a mapping"})
    else:
        for key in _REQUIRED_LABEL_KEYS:
            if not labels.get(key):
                problems.append({"file": relative, "code": "missing_labels",
                                 "message": f"labels.{key} is required for slice reporting"})
    for entry in task.workspace_files or []:
        source = str((entry or {}).get("source") or "")
        if not source:
            problems.append({"file": relative, "code": "missing_fixture",
                             "message": "workspace_files entry needs a source"})
            continue
        if Path(source).is_absolute() or ".." in Path(source).parts:
            problems.append({"file": relative, "code": "unsafe_fixture_path",
                             "message": f"fixture source must stay inside the package: {source}"})
            continue
        if not (package_dir / source).is_file():
            problems.append({"file": relative, "code": "fixture_not_found",
                             "message": f"declared fixture is missing from the package: {source}"})
    return problems


def _markdown_files(package_dir: Path) -> list[Path]:
    tasks_dir = package_dir / "tasks"
    return sorted((tasks_dir if tasks_dir.is_dir() else package_dir).glob("*.md"))


def _all_files(package_dir: Path) -> Iterable[Path]:
    return (path for path in sorted(package_dir.rglob("*")) if path.is_file() or path.is_symlink())


def _is_forbidden_package_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in FORBIDDEN_PACKAGE_NAMES
        or path.suffix.lower() == ".pth"
        or any(fnmatch(name, pattern) for pattern in _FORBIDDEN_NAME_PATTERNS)
    )


def unpack_package(archive: Path, target: Path) -> int:
    """Lay one uploaded zip out under *target* and return the number of files.

    This is the only place the service writes submission bytes to disk, so it
    answers the three ways a zip is used against an unpacker: a member name that
    walks out of the destination (zip-slip), a symlink pointing wherever its
    author liked, and an archive whose uncompressed size is orders above its own.
    The two quotas are the ones :meth:`DatasetService.register_custom` already
    applies to a directory -- checked here against the central directory, before
    a byte is written, because a declared size that lies is caught again while
    streaming.

    *archive* is a path, not the bytes: the quota is hundreds of megabytes and
    ``ZipFile`` reads its central directory from wherever it is standing, so
    holding the upload in memory would be a third copy of a file that is about to
    be read from disk anyway.

    Members are written relative to *target*, and a package zipped as a folder
    (what "compress" produces on every OS) has all its paths under one root
    directory.  That single root is dropped: the validator looks for ``tasks``
    next to the directory it is handed, so keeping it would refuse a correct
    package for the shape of the file manager it was zipped from.
    """
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DatasetError(
            "package_not_zip", "the upload is not a readable zip archive"
        ) from exc
    with bundle:
        members = bundle.infolist()
        if len([item for item in members if not item.is_dir()]) > MAX_PACKAGE_FILES:
            raise DatasetError(
                "package_too_large",
                f"{len(members)} entries is over the quota of {MAX_PACKAGE_FILES} files",
            )
        declared = sum(int(item.file_size or 0) for item in members)
        if declared > MAX_PACKAGE_BYTES:
            raise DatasetError(
                "package_too_large",
                f"the archive declares {declared} bytes, over the quota of {MAX_PACKAGE_BYTES}",
            )
        prefix = _common_zip_root(members)
        root = target.resolve()
        written = 0
        budget = MAX_PACKAGE_BYTES
        for member in members:
            name = _entry_relative_path(member.filename, prefix)
            destination = root if name == "" else root / name
            if destination != root and root not in destination.parents:
                # The name check below is the message; this one is the guarantee,
                # and it stays because a name can be well-formed and still resolve
                # somewhere else once symlinks inside the archive are in play.
                raise DatasetError("package_unsafe_path", f"unzips outside the package: {name}")
            if _is_symlink_member(member):
                raise DatasetError(
                    "package_unsafe_path",
                    f"a package may not contain a symlink: {member.filename}",
                )
            try:
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source:
                    budget -= _write_capped(source, destination, budget)
            except (OSError, NotImplementedError) as exc:
                # Two shapes the checks above cannot see: a member whose
                # compression this build cannot decode (``zipfile`` answers
                # ``NotImplementedError`` only when the entry is opened, not from
                # the central directory), and two members that want the same spot
                # -- ``tasks/a.md`` as a file and ``tasks/a.md/b.md`` as a path
                # gives ``NotADirectoryError`` on the second.  Both say the
                # package cannot be laid out, which is what ``package_invalid``
                # already promises; letting them out raw would cost the uploader
                # a 500 for a file they can go and re-pack.
                #
                # ``type(exc).__name__`` rather than the exception text: an
                # ``OSError`` here quotes the destination, a server-side temp path
                # this caller has no use for and no business seeing.
                raise DatasetError(
                    "package_invalid",
                    f"{member.filename} cannot be unpacked ({type(exc).__name__})",
                ) from exc
            written += 1
        return written


def _common_zip_root(members: Sequence[zipfile.ZipInfo]) -> str:
    """The one directory every member shares, or ``""`` when there is none.

    ``..`` never counts as that directory.  An archive whose sole root is
    ``..`` -- what ``zip -r ../x .`` writes -- would otherwise have the prefix
    stripped and come out as a plain relative path, and the traversal guard
    below would then be looking at a name the archiver rewrote for it.
    """
    top_level = set()
    for member in members:
        parts = str(member.filename).split("/")
        if not parts[0] or parts[0] == ".." or len(parts) < 2:
            return ""
        top_level.add(parts[0])
    return top_level.pop() + "/" if len(top_level) == 1 else ""


def _entry_relative_path(raw: str, prefix: str) -> str:
    """The member's path inside the package, with the shared root removed.

    A zip stores ``/`` regardless of where it was made, so a backslash is not a
    separator here -- it is a file name a POSIX reader would never open, and the
    task loader cannot see it either.  Refusing it beats inventing a second
    path dialect for one platform's archiver.
    """
    name = str(raw).replace("\\", "/")
    if name.startswith(prefix) and len(name) > len(prefix):
        name = name[len(prefix) :]
    if "\x00" in name or "\\" in str(raw) or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise DatasetError("package_unsafe_path", f"not a relative package path: {raw}")
    if any(part == ".." for part in name.split("/")):
        raise DatasetError("package_unsafe_path", f"walks out of the package: {raw}")
    return name


def _is_symlink_member(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(member.external_attr >> 16)


def _write_capped(source: Any, destination: Path, allowed: int) -> int:
    """Copy one member, refusing it as soon as the shared budget runs out."""
    written = 0
    with open(destination, "wb") as sink:
        while True:
            chunk = source.read(_UNPACK_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > allowed:
                sink.truncate(0)
                raise DatasetError(
                    "package_too_large",
                    f"the package passed {MAX_PACKAGE_BYTES} bytes while unpacking",
                )
            sink.write(chunk)
    return written


def _copy_package(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                    symlinks=False)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _task_file_signature(tasks_dir: Path) -> _TaskSignature:
    """The task files' names, sizes and modification times -- what an index goes stale about.

    ``TaskLoader`` reads every ``*.md`` in this directory, so a cached index is
    only as current as these numbers.  Checking them costs a directory listing,
    which is the point: hashing the contents would be the read we are trying to
    skip.  A file that vanished mid-flight has no entry, so it changes the
    signature too.
    """
    if not tasks_dir.is_dir():
        return ()
    signature: list[tuple[str, int, int]] = []
    for path in sorted(tasks_dir.glob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((path.name, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


def _load_task_summaries(tasks_dir: Path) -> dict[str, TaskSummary]:
    summaries: dict[str, TaskSummary] = {}
    if not tasks_dir.is_dir():
        return summaries
    for task in TaskLoader(tasks_dir).load_all_tasks():
        summaries[task.task_id] = _to_summary(task)
    return summaries


def _to_summary(task: Task) -> TaskSummary:
    labels = dict(task.frontmatter.get("labels") or {})
    if task.frontmatter.get("origin_benchmark"):
        labels.setdefault("source", str(task.frontmatter["origin_benchmark"]))
    return TaskSummary(
        task_id=task.task_id,
        name=task.name,
        file_stem=task.file_path.stem if task.file_path else task.task_id,
        path=task.file_path or Path(""),
        grading_type=task.grading_type,
        timeout_seconds=int(task.timeout_seconds or 0),
        workspace_files=tuple(dict(entry) for entry in (task.workspace_files or [])),
        labels=labels,
    )


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    raise DatasetError("invalid_selector", f"expected a list, got: {value!r}")


def _as_value_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return {str(item) for item in value}
    if isinstance(value, Iterable):
        return {str(item) for item in value}
    return {str(value)}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _text_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Iterable):
        return {str(item) for item in value}
    return {str(value)}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
