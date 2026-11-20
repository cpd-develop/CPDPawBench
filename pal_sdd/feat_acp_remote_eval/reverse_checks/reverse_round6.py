# -*- coding: utf-8 -*-
"""Reverse verification for the sixth round's fixes: remove each one, expect red.

Same contract as ``reverse_l19.py`` and ``reverse_l17.py`` -- a case that stays
green with its fix taken out pins nothing, so the report that matters is the list
of survivors.  Two of these cases exist because the reviewer found an assertion
that was watching the wrong step, so they mutate the *placement* of a fix rather
than its presence.
"""

import hashlib
import os
import subprocess
import sys
from glob import glob
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
PYTHON = Path("/Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python")

API = "pawbench/cpd/acp_remote_eval/service/api.py"
DATASETS = "pawbench/cpd/acp_remote_eval/service/datasets.py"
REPORTS = "pawbench/cpd/acp_remote_eval/service/reports.py"
UPLOAD_TEST = "tests/cpd/acp_remote_eval/test_datasets_api.py::"
DATASET_TEST = "tests/cpd/acp_remote_eval/test_datasets.py::"
REPORT_TEST = "tests/cpd/acp_remote_eval/test_reports.py::"
CONTROL_TEST = "tests/cpd/acp_remote_eval/test_control_api.py::"

# The upload route as it now stands, and the three ways of breaking the gate
# without deleting it: streaming outside the permit, the package volume left out
# of the pre-flight, the failed write left unmapped.
GATE_IN = """        async with request.app.state.package_uploads:
            upload = await _stream_body_to_file(
                request,
                datasets_module.MAX_PACKAGE_BYTES,
                Path(control.datasets.config.custom_dir),
            )
            try:"""
GATE_OUT = """        upload = await _stream_body_to_file(
            request,
            datasets_module.MAX_PACKAGE_BYTES,
            Path(control.datasets.config.custom_dir),
        )
        async with request.app.state.package_uploads:
            try:"""

TWO_VOLUMES = """    for volume in (_existing_parent(Path(tempfile.gettempdir())), _existing_parent(package_dir)):"""
ONE_VOLUME = """    for volume in (_existing_parent(Path(tempfile.gettempdir())),):"""

FAILED_WRITE = """    except OSError as failure:
        # The volume filled up under us after the pre-flight said otherwise --
        # somebody else's write got there first.  Same number and same fields as
        # the refusal above, because what the operator does is identical.
        path.unlink(missing_ok=True)
        raise DatasetError(
            "package_disk_full",
            f"the write stopped after {size} bytes on a volume holding "
            f"{wanted} ({type(failure).__name__})",
        ) from None
"""

NAMES_BEFORE_COPY = """        wanted_categories = list(
            dict.fromkeys(self._category_name_or_refuse(item) for item in categories)
        )
        target = self._custom_dir(dataset_id)
        _copy_package(Path(source_dir), target)
        resolved_categories = [
            self.ensure_category(item, owner)["name"] for item in wanted_categories
        ]"""
NAMES_AFTER_COPY = """        target = self._custom_dir(dataset_id)
        _copy_package(Path(source_dir), target)
        resolved_categories = [
            self.ensure_category(item, owner)["name"] for item in categories
        ]"""

DEEP_LINE = """        except (ValueError, RecursionError):
            row = None"""
DEEP_LINE_OLD = """        except ValueError:
            row = None"""

# The control-plane body ceiling: the routes that parse a document, and the depth
# a document can have before the parser's stack gives out.
JSON_CAPPED = (
    """    raw = await _read_body(request, MAX_JSON_BODY_BYTES, SubmissionError, "body_too_large")"""
)
JSON_UNCAPPED = """    raw = await request.body()"""

DEEP_DOCUMENT = """    except (ValueError, RecursionError):
        # ``json`` descends"""
DEEP_DOCUMENT_OLD = """    except ValueError:
        # ``json`` descends"""

GUARDED_WALK = """    try:
        with handle:
            for line in handle:
                if not line.strip():
                    continue
                if start <= total < start + page:
                    window.append(line.rstrip("\\n"))
                total += 1
    except OSError:"""
UNGUARDED_WALK = """    if True:
        with handle:
            for line in handle:
                if not line.strip():
                    continue
                if start <= total < start + page:
                    window.append(line.rstrip("\\n"))
                total += 1
    if False:"""

CASES = [
    (
        "the gate moved in past the streaming step (api.py)",
        API,
        GATE_IN,
        GATE_OUT,
        [UPLOAD_TEST + "test_two_packages_land_and_a_third_waits_its_turn"],
    ),
    (
        "only the temp volume measured (api.py)",
        API,
        TWO_VOLUMES,
        ONE_VOLUME,
        [UPLOAD_TEST + "test_a_full_package_volume_is_refused_though_the_temp_directory_is_empty"],
    ),
    (
        "a write that fails under the pre-flight left unmapped (api.py)",
        API,
        FAILED_WRITE,
        "",
        [UPLOAD_TEST + "test_a_write_that_fails_under_the_pre_flight_is_the_same_refusal"],
    ),
    (
        "category names judged after the copy they can no longer undo (datasets.py)",
        DATASETS,
        NAMES_BEFORE_COPY,
        NAMES_AFTER_COPY,
        [
            DATASET_TEST + "test_a_refused_category_leaves_the_stored_package_and_its_row_alone",
            DATASET_TEST + "test_a_refused_category_does_not_leave_a_package_directory_without_a_row",
        ],
    ),
    (
        "the deep line back to a 500 (reports.py)",
        REPORTS,
        DEEP_LINE,
        DEEP_LINE_OLD,
        [REPORT_TEST + "test_a_line_that_is_too_deep_to_parse_costs_a_count_and_not_the_page"],
    ),
    (
        "a read that fails halfway back to a 500 (reports.py)",
        REPORTS,
        GUARDED_WALK,
        UNGUARDED_WALK,
        [REPORT_TEST + "test_a_transcript_that_fails_mid_read_is_unreadable_and_not_a_half_page"],
    ),
    (
        "the control body ceiling taken back off (api.py)",
        API,
        JSON_CAPPED,
        JSON_UNCAPPED,
        [
            CONTROL_TEST
            + "test_a_control_body_is_read_up_to_a_ceiling_and_not_as_far_as_the_caller_sends"
        ],
    ),
    (
        "a document too deep to parse back to a 500 (api.py)",
        API,
        DEEP_DOCUMENT,
        DEEP_DOCUMENT_OLD,
        [CONTROL_TEST + "test_json_nested_past_the_recursion_limit_is_the_callers_error_not_ours"],
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
    every_case = [test_id for case in CASES for test_id in case[4]]
    baseline = run(every_case)
    if baseline[0]:
        print(f"ABORT: the pins do not pass on unmutated code -- {baseline[1]}")
        return 1
    print(f"BASELINE {baseline[1]}")
    for label, relative, needle, replacement, test_ids in CASES:
        path = REPO / relative
        original = path.read_text(encoding="utf-8")
        if needle not in original:
            print(f"SKIP  {label}: the fix text is not where the script thinks it is")
            survivors.append(label)
            continue
        digest = hashlib.sha256(original.encode()).hexdigest()
        try:
            path.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
            code, summary = run(test_ids)
            verdict = "RED " if code else "GREEN"
            if code == 0:
                survivors.append(label)
            print(f"{verdict} {label}: {summary}")
        finally:
            path.write_text(original, encoding="utf-8")
            restored = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            assert restored == digest, relative
    print(f"restored: {len(CASES)} files back to their fix")
    if survivors:
        print("SURVIVORS (a case that does not pin its fix):")
        for label in survivors:
            print("  -", label)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
