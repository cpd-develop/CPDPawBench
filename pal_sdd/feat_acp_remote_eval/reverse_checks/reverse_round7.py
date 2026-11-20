# -*- coding: utf-8 -*-
"""Reverse verification for the tenth batch (L18): take each optimisation out, expect red.

Same contract as ``reverse_round6.py`` -- a case that stays green with its fix
removed pins nothing, so the report that matters is the list of survivors.  Two
of these mutations remove a *half* of a fix rather than the whole thing: the
cache without its invalidation check, the shared artifact read in the document
but not in the zip.  Those are the shapes the regression would actually take.
"""

import hashlib
import os
import subprocess
import sys
from glob import glob
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
PYTHON = Path("/Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python")

DATASETS = "pawbench/cpd/acp_remote_eval/service/datasets.py"
REPORTS = "pawbench/cpd/acp_remote_eval/service/reports.py"
DATASET_TEST = "tests/cpd/acp_remote_eval/test_datasets.py::"
REPORT_TEST = "tests/cpd/acp_remote_eval/test_reports.py::"

COUNTS_ONCE = """        counts = self.store.category_dataset_counts()
        return [
            {**record, "dataset_count": counts.get(record["name"], 0)}
            for record in self.store.list_categories()
        ]"""
COUNTS_PER_CATEGORY = """        return [
            {**record, "dataset_count": self.store.datasets_with_category(record["name"])}
            for record in self.store.list_categories()
        ]"""

CACHE_ON = """        with self._index_lock:
            cached = self._indexes.get(dataset_id)
            if cached is not None and cached[0] == signature:
                return cached[1]"""
CACHE_OFF = """        with self._index_lock:
            cached = None
            if cached is not None and cached[0] == signature:
                return cached[1]"""

SIGNATURE_CHECK = """            if cached is not None and cached[0] == signature:"""
SIGNATURE_IGNORED = """            if cached is not None:"""

CACHE_BOUND = """            if dataset_id not in self._indexes and len(self._indexes) >= MAX_INDEX_CACHE:
                self._indexes.pop(next(iter(self._indexes)))
"""

SUBSET_READ = """        record = self.get(dataset_id)
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
        return tasks"""
CORPUS_WALK = """        record = self.get(dataset_id)
        loader = TaskLoader(self._tasks_dir(record))
        wanted = set(record["task_ids"])
        return [task for task in loader.load_all_tasks() if task.task_id in wanted]"""

DETAIL_HELPER_CALL = """        artifacts = _artifacts_by_task(self.store, job_id)
"""
DETAIL_SLICE = """                self._task_entry(job_id, row, tier, bodies, artifacts.get(str(row["task_id"]), []))"""
DETAIL_PER_TASK = """                self._task_entry(
                    job_id,
                    row,
                    tier,
                    bodies,
                    self.store.list_artifacts(job_id, task_id=str(row["task_id"])),
                )"""

ZIP_ONE_READ = """    by_task = _artifacts_by_task(exchange.store, job_id)"""
ZIP_PER_TASK = """    class _PerTaskArtifacts:
        def __init__(self, store, job_id):
            self._store = store
            self._job_id = job_id

        def get(self, task_id, default=()):
            return self._store.list_artifacts(self._job_id, task_id=task_id)

    by_task = _PerTaskArtifacts(exchange.store, job_id)"""

CASES = [
    (
        "category counts back to one catalogue read per label (datasets.py)",
        DATASETS,
        [(COUNTS_ONCE, COUNTS_PER_CATEGORY)],
        [DATASET_TEST + "test_category_counts_read_the_catalogue_once_not_once_per_category"],
    ),
    (
        "the parsed task index dropped on every request (datasets.py)",
        DATASETS,
        [(CACHE_ON, CACHE_OFF)],
        [DATASET_TEST + "test_a_package_is_parsed_once_until_one_of_its_files_changes"],
    ),
    (
        "a cache that never noticed an edited task file (datasets.py)",
        DATASETS,
        [(SIGNATURE_CHECK, SIGNATURE_IGNORED)],
        [DATASET_TEST + "test_a_package_is_parsed_once_until_one_of_its_files_changes"],
    ),
    (
        "the index cache given no bound (datasets.py)",
        DATASETS,
        [(CACHE_BOUND, "")],
        [DATASET_TEST + "test_the_index_cache_does_not_grow_with_the_catalogue"],
    ),
    (
        "tasks_for_run back to parsing the whole corpus (datasets.py)",
        DATASETS,
        [(SUBSET_READ, CORPUS_WALK)],
        [DATASET_TEST + "test_tasks_for_run_reads_only_the_tasks_the_dataset_selected"],
    ),
    (
        "job detail back to one artifact query per task (reports.py)",
        REPORTS,
        [(DETAIL_HELPER_CALL, ""), (DETAIL_SLICE, DETAIL_PER_TASK)],
        [REPORT_TEST + "test_job_detail_reads_the_artifact_rows_once_for_a_whole_job"],
    ),
    (
        "the zip bundle back to one artifact query per task (reports.py)",
        REPORTS,
        [(ZIP_ONE_READ, ZIP_PER_TASK)],
        [REPORT_TEST + "test_job_detail_reads_the_artifact_rows_once_for_a_whole_job"],
    ),
]


def run(test_ids: list[str]) -> tuple[int, str]:
    for cached in glob(str(REPO / "pawbench/cpd/**/__pycache__/*.pyc"), recursive=True):
        os.remove(cached)
    for cached in glob(str(REPO / "tests/cpd/**/__pycache__/*.pyc"), recursive=True):
        os.remove(cached)
    completed = subprocess.run(
        [str(PYTHON), "-m", "pytest", *test_ids, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    tail = [line for line in completed.stdout.splitlines() if "passed" in line or "failed" in line]
    return completed.returncode, " | ".join(tail[-1:]) or completed.stdout[-400:]


def main() -> int:
    survivors = []
    every_case = [test_id for case in CASES for test_id in case[3]]
    baseline = run(sorted(set(every_case)))
    if baseline[0]:
        print(f"ABORT: the pins do not pass on unmutated code -- {baseline[1]}")
        return 1
    print(f"BASELINE {baseline[1]}")
    for label, relative, edits, test_ids in CASES:
        path = REPO / relative
        original = path.read_text(encoding="utf-8")
        missing = [needle for needle, _ in edits if needle not in original]
        if missing:
            print(f"SKIP  {label}: the fix text is not where the script thinks it is")
            survivors.append(label)
            continue
        digest = hashlib.sha256(original.encode()).hexdigest()
        try:
            mutated = original
            for needle, replacement in edits:
                mutated = mutated.replace(needle, replacement, 1)
            path.write_text(mutated, encoding="utf-8")
            code, summary = run(test_ids)
            verdict = "RED " if code else "GREEN"
            if code == 0:
                survivors.append(label)
            print(f"{verdict} {label}: {summary}")
        finally:
            path.write_text(original, encoding="utf-8")
            restored = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            assert restored == digest, relative
    print(f"restored: {len(CASES)} mutations back to the committed code")
    if survivors:
        print("SURVIVORS (a case that does not pin its fix):")
        for label in survivors:
            print("  -", label)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
