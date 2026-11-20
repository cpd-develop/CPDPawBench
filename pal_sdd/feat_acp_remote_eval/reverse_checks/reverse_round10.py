"""Reverse check for 第十三批 (L35): the config fallback anchors.

Each mutation puts one default back to the repo-root shape it had before; the
paired test must go red.  Run alone -- it edits the source in place.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
PY = "/Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python"
CONFIG = REPO / "pawbench/cpd/acp_remote_eval/service/config.py"
TESTS = "tests/cpd/acp_remote_eval/test_config.py"

MUTATIONS = {
    "STATE_DB_ROOT_SHAPED": (
        '_path(service.get("state_db"), base, Path("runtime/state.db"))',
        '_path(service.get("state_db"), base, Path("service/state.db"))',
    ),
    "CUSTOM_DIR_ROOT_SHAPED": (
        '_path(datasets.get("custom_dir"), base, Path("runtime/datasets"))',
        '_path(datasets.get("custom_dir"), base, Path("service/datasets"))',
    ),
    "EXCHANGE_DIR_ROOT_SHAPED": (
        '"exchange_dir": "runtime/exchange",',
        '"exchange_dir": "service/exchange",',
    ),
    "BUILTIN_DIR_ROOT_SHAPED": (
        'Path("../../../../data/pawbench-v1.0"),',
        'Path("data/pawbench-v1.0"),',
    ),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> tuple[int, str]:
    done = subprocess.run(
        [PY, "-m", "pytest", TESTS, "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = [line for line in done.stdout.splitlines() if "passed" in line or "failed" in line]
    return done.returncode, (tail[-1] if tail else done.stdout[-200:])


def purge_pycache() -> None:
    for path in REPO.rglob("__pycache__"):
        if "cpd" in str(path):
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    original = CONFIG.read_text(encoding="utf-8")
    digest = sha(CONFIG)
    survivors: list[str] = []
    try:
        purge_pycache()
        code, line = run()
        print(f"BASELINE {line}")
        if code != 0:
            print("BASELINE is not green -- aborting")
            return 2
        for name, (anchor, replacement) in MUTATIONS.items():
            if original.count(anchor) != 1:
                print(f"{name}: SKIP (anchor found {original.count(anchor)} times)")
                survivors.append(name)
                continue
            CONFIG.write_text(original.replace(anchor, replacement), encoding="utf-8")
            purge_pycache()
            code, line = run()
            verdict = "RED" if code != 0 else "SURVIVED"
            print(f"{name}: {verdict} -- {line}")
            if code == 0:
                survivors.append(name)
    finally:
        CONFIG.write_text(original, encoding="utf-8")
        purge_pycache()
        restored = sha(CONFIG) == digest
        print(f"restored sha256 match: {restored}")
        if not restored:
            return 2
    print(f"survivors: {survivors or 'none'}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
