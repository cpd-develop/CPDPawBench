# -*- coding: utf-8 -*-
"""Reverse verification for L17: remove each half of the gate, expect red.

Same contract as ``reverse_l19.py`` -- a case that stays green with its fix
taken out pins nothing, so the report that matters is the list of survivors.
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
UPLOAD_TEST = "tests/cpd/acp_remote_eval/test_datasets_api.py::"

GATE_FIX = """        async with request.app.state.package_uploads:
            upload = await _stream_body_to_file(
                request,
                datasets_module.MAX_PACKAGE_BYTES,
                Path(control.datasets.config.custom_dir),
            )
            try:"""
GATE_OLD = """        if True:
            upload = await _stream_body_to_file(
                request,
                datasets_module.MAX_PACKAGE_BYTES,
                Path(control.datasets.config.custom_dir),
            )
            try:"""

ROOM_FIX = """    for volume in (_existing_parent(Path(tempfile.gettempdir())), _existing_parent(package_dir)):
        free = shutil.disk_usage(volume).free
        if free < wanted:
            raise DatasetError(
                "package_disk_full",
                f"the volume holding {volume} has {free} bytes free and this "
                f"package says it is {wanted}",
            )
"""
ROOM_OLD = ""

LOG_FIX = """_PACKAGE_GUARD_CODES = frozenset(
    {"package_unsafe_path", "package_too_large", "package_disk_full"}
)"""
LOG_OLD = """_PACKAGE_GUARD_CODES = frozenset({"package_unsafe_path", "package_too_large"})"""

CASES = [
    (
        "no concurrency gate (api.py)",
        API,
        GATE_FIX,
        GATE_OLD,
        [UPLOAD_TEST + "test_two_packages_land_and_a_third_waits_its_turn"],
    ),
    (
        "no free-space check (api.py)",
        API,
        ROOM_FIX,
        ROOM_OLD,
        [
            UPLOAD_TEST + "test_a_disk_without_room_is_said_before_the_package_arrives",
            UPLOAD_TEST + "test_a_full_package_volume_is_refused_though_the_temp_directory_is_empty",
        ],
    ),
    (
        "disk refusal not a guard, so no warning (api.py)",
        API,
        LOG_FIX,
        LOG_OLD,
        [UPLOAD_TEST + "test_a_disk_without_room_is_said_before_the_package_arrives"],
    ),
]


def run(relative: str, test_ids: list[str]) -> tuple[int, str]:
    stem = Path(relative)
    for cached in glob(str(REPO / stem.parent / "__pycache__" / f"{stem.stem}.*.pyc")):
        os.remove(cached)
    completed = subprocess.run(
        [str(PYTHON), "-m", "pytest", *test_ids, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    tail = [line for line in completed.stdout.splitlines() if "passed" in line or "failed" in line]
    return completed.returncode, " | ".join(tail[-1:]) or completed.stdout[-300:]


def main() -> int:
    survivors = []
    baseline = run(CASES[0][1], [test_id for case in CASES for test_id in case[4]])
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
            code, summary = run(relative, test_ids)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
