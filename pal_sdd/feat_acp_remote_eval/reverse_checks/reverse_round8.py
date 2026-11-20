# -*- coding: utf-8 -*-
"""Reverse verification for the eleventh batch (seventh round's fixes).

Same contract as ``reverse_round7.py``: a case that stays green with its fix
removed pins nothing, so the report that matters is the list of survivors.  The
first two mutations here are the whole lock and half of it -- the read half is
allowed to race (a duplicate parse costs work, not correctness), so only the
write-and-evict half may stay.
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
STORE = "pawbench/cpd/acp_remote_eval/service/store.py"
DATASET_TEST = "tests/cpd/acp_remote_eval/test_datasets.py::"

LOCKED_READ = """        with self._index_lock:
            cached = self._indexes.get(dataset_id)
            if cached is not None and cached[0] == signature:
                return cached[1]"""
OPEN_READ = """        cached = self._indexes.get(dataset_id)
        if cached is not None and cached[0] == signature:
            return cached[1]"""

LOCKED_WRITE = """        with self._index_lock:
            if dataset_id not in self._indexes and len(self._indexes) >= MAX_INDEX_CACHE:
                self._indexes.pop(next(iter(self._indexes)))
            self._indexes[dataset_id] = (signature, summaries)"""
OPEN_WRITE = """        if dataset_id not in self._indexes and len(self._indexes) >= MAX_INDEX_CACHE:
            self._indexes.pop(next(iter(self._indexes)))
        self._indexes[dataset_id] = (signature, summaries)"""

DISTINCT_NAMES = """            for name in dict.fromkeys(row.get("categories") or []):"""
EVERY_LISTING = """            for name in row.get("categories") or []:"""

SET_ON_WRITE = """        resolved_categories = list(
            dict.fromkeys(self.ensure_category(item, owner)["name"] for item in categories)
        )"""
LIST_ON_WRITE = """        resolved_categories = [self.ensure_category(item, owner)["name"] for item in categories]"""

LENIENT_LOAD = """            try:
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
                )"""
STRICT_LOAD = """            tasks.append(loader.load_task(summary.path))"""

RACE_TEST = DATASET_TEST + "test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key"

CASES = [
    (
        "the index cache given no lock at all (datasets.py)",
        DATASETS,
        [(LOCKED_READ, OPEN_READ), (LOCKED_WRITE, OPEN_WRITE)],
        [RACE_TEST],
    ),
    (
        "the evict-and-write half left unlocked (datasets.py)",
        DATASETS,
        [(LOCKED_WRITE, OPEN_WRITE)],
        [RACE_TEST],
    ),
    (
        "category counts back to tag occurrences (store.py)",
        STORE,
        [(DISTINCT_NAMES, EVERY_LISTING)],
        [DATASET_TEST + "test_a_category_filed_on_one_dataset_twice_is_one_dataset"],
    ),
    (
        "the create path back to filing one category per spelling (datasets.py)",
        DATASETS,
        [(SET_ON_WRITE, LIST_ON_WRITE)],
        [DATASET_TEST + "test_a_category_filed_on_one_dataset_twice_is_one_dataset"],
    ),
    (
        "one unparseable task file back to failing the run (datasets.py)",
        DATASETS,
        [(LENIENT_LOAD, STRICT_LOAD)],
        [DATASET_TEST + "test_an_unparseable_task_file_costs_its_task_and_not_the_run"],
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
