# -*- coding: utf-8 -*-
"""Reverse verification for the twelfth batch (eighth round's fixes).

Same contract as ``reverse_round8.py``: a case that stays green with its fix
removed pins nothing, so the report that matters is the list of survivors.
The three report-file mutations are deliberately separate -- a unique staged
name, the cleanup that pays for it, and the lock that decides whose bytes the
link describes -- because each is a different way the same 4 MB file goes wrong,
and only the first was visible in the reviewer's probe.
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

# ── reports.py: the staged name, its cleanup, and who writes the file ─────────

RANDOM_STAGED = """    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)"""
FIXED_STAGED = """    temporary = path.with_name(f".{path.name}.part")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)"""
STAGED_NO_CLEANUP = """    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.part")
    temporary.write_bytes(data)
    temporary.replace(path)"""

LOCKED_WRITE = """        with self._report_lock:
            if path.is_file():
                return _digest_and_size(path)
            _write(path, data)
            logger.info(
                "report rendered",
                extra={"job_id": job_id, "format": fmt, "sensitivity": tier, "bytes": len(data)},
            )"""
OPEN_WRITE = """        if path.is_file():
            return _digest_and_size(path)
        _write(path, data)
        logger.info(
            "report rendered",
            extra={"job_id": job_id, "format": fmt, "sensitivity": tier, "bytes": len(data)},
        )"""
LOCKED_OWN_NUMBERS = """        with self._report_lock:
            if path.is_file():
                return hashlib.sha256(data).hexdigest(), len(data)
            _write(path, data)
            logger.info(
                "report rendered",
                extra={"job_id": job_id, "format": fmt, "sensitivity": tier, "bytes": len(data)},
            )"""

# ── datasets.py: the corpus index, the vanished task, the category writes ────

GUARDED_INDEX = """        signature = _task_file_signature(self.tasks_dir)
        cached = self._index_pair
        if cached is not None and cached[0] == signature:
            return cached[1]
        tasks = _load_task_summaries(self.tasks_dir)
        self._index_pair = (signature, tasks)
        return tasks"""
PARSE_ONCE = """        cached = self._index_pair
        if cached is not None:
            return cached[1]
        tasks = _load_task_summaries(self.tasks_dir)
        self._index_pair = (_task_file_signature(self.tasks_dir), tasks)
        return tasks"""
ALWAYS_REPARSE = """        tasks = _load_task_summaries(self.tasks_dir)
        self._index_pair = (_task_file_signature(self.tasks_dir), tasks)
        return tasks"""

COLLECT_ABSENT = """            if summary is None or not summary.path.is_file():
                absent.append(task_id)
                continue"""
SKIP_ABSENT = """            if summary is None or not summary.path.is_file():
                continue"""

AGGREGATED_LOG = """        if absent:
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
            )"""
PER_TASK_LOG = """        for task_id in absent:
            logger.warning(
                "dataset tasks not on disk",
                extra={
                    "dataset_id": dataset_id,
                    "task_ids": [task_id],
                    "absent_count": 1,
                    "task_count": len(tasks),
                },
            )"""

READ_CANONICAL = """        current = list(
            dict.fromkeys(normalize_category_name(name) for name in record["categories"])
        )"""
READ_RAW_DEDUPED = """        current = list(dict.fromkeys(record["categories"]))"""
READ_RAW = """        current = list(record["categories"])"""

ADD_LOOP = """        for name in add:
            category = normalize_category_name(name)
            if not category:
                raise DatasetError("invalid_category_name", f"unusable category name: {name!r}")
            self.ensure_category(category, principal.subject)
            if category not in current:
                current.append(category)"""

DROP_ALL = """        dropped = {normalize_category_name(name) for name in remove}
        current = [item for item in current if item not in dropped]"""
DROP_FIRST = """        for name in remove:
            category = normalize_category_name(name)
            if category in current:
                current.remove(category)"""

DEDUPED_ASSIGN = "\n".join([READ_CANONICAL, ADD_LOOP, DROP_ALL])
# The half-fix the first run of this script could not tell apart: collapsing
# exact duplicates is not the same as reading the row in the spelling every
# comparison uses, and only a row with two spellings of one name shows it.
RAW_DEDUPE_ONLY = "\n".join([READ_RAW_DEDUPED, ADD_LOOP, DROP_ALL])
REMOVE_FIRST = "\n".join([READ_RAW, ADD_LOOP, DROP_FIRST])

KEY_RACE_CATCH = """        try:
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
            return {**self.store.get_category(normalized), "created": False}"""
KEY_RACE_RAISES = """        self.store.insert_category(
            {"name": normalized, "description": description, "created_by": created_by}
        )"""

STALENESS_TEST = DATASET_TEST + "test_a_corpus_edit_reaches_the_view_that_was_already_saved"
ABSENT_TEST = DATASET_TEST + "test_a_task_that_vanished_from_disk_is_reported_once_per_run"
UNFILING_TEST = DATASET_TEST + "test_unfiling_a_category_removes_every_copy_of_it"
CATEGORY_RACE_TEST = (
    DATASET_TEST + "test_the_worker_that_loses_a_category_race_reports_the_row_that_landed"
)
STAGED_TEST = REPORT_TEST + "test_two_writers_of_one_report_name_use_different_temporaries"
CLEANUP_TEST = REPORT_TEST + "test_a_failed_report_write_leaves_no_temporary_behind"
LANDING_TEST = REPORT_TEST + "test_two_requests_for_one_fingerprint_agree_on_the_file_that_landed"

CASES = [
    (
        "the staged report name back to one fixed .part (reports.py)",
        REPORTS,
        [(RANDOM_STAGED, FIXED_STAGED)],
        [STAGED_TEST],
    ),
    (
        "the staged report file left behind when the write fails (reports.py)",
        REPORTS,
        [(RANDOM_STAGED, STAGED_NO_CLEANUP)],
        [CLEANUP_TEST],
    ),
    (
        "the write-and-measure step given no lock (reports.py)",
        REPORTS,
        [(LOCKED_WRITE, OPEN_WRITE)],
        [LANDING_TEST],
    ),
    (
        "the losing renderer kept, with the lock still held (reports.py)",
        REPORTS,
        [(LOCKED_WRITE, LOCKED_OWN_NUMBERS)],
        [LANDING_TEST],
    ),
    (
        "the corpus index back to parsed once per process (datasets.py)",
        DATASETS,
        [(GUARDED_INDEX, PARSE_ONCE)],
        [STALENESS_TEST],
    ),
    (
        "the corpus index parsed on every read (datasets.py)",
        DATASETS,
        [(GUARDED_INDEX, ALWAYS_REPARSE)],
        [STALENESS_TEST],
    ),
    (
        "a vanished task file back to a silent skip (datasets.py)",
        DATASETS,
        [(COLLECT_ABSENT, SKIP_ABSENT), (AGGREGATED_LOG, "")],
        [ABSENT_TEST],
    ),
    (
        "the vanished-task warning back to one line per task (datasets.py)",
        DATASETS,
        [(AGGREGATED_LOG, PER_TASK_LOG)],
        [ABSENT_TEST],
    ),
    (
        "the category write back to the old row, first copy removed (datasets.py)",
        DATASETS,
        [(DEDUPED_ASSIGN, REMOVE_FIRST)],
        [UNFILING_TEST],
    ),
    (
        "the category row read raw instead of canonicalised (datasets.py)",
        DATASETS,
        [(DEDUPED_ASSIGN, RAW_DEDUPE_ONLY)],
        [UNFILING_TEST],
    ),
    (
        "the losing category insert back to IntegrityError (datasets.py)",
        DATASETS,
        [(KEY_RACE_CATCH, KEY_RACE_RAISES)],
        [CATEGORY_RACE_TEST],
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
