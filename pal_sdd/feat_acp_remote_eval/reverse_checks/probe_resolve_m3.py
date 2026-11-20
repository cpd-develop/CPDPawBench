"""Read-only timing probe: what the submit form's resolve panel actually costs.

Feeds design_acp_remote_eval.md question 2 (inline resolve vs a two-step wizard).
Writes nothing into the repository: the store lives in a scratch directory.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests/cpd/acp_remote_eval"))

from support import dataset_service, eval_config  # noqa: E402

from pawbench.cpd.acp_remote_eval.service.pilot import seed_pilot  # noqa: E402
from pawbench.cpd.acp_remote_eval.service.store import Store  # noqa: E402

CORPUS = REPO / "data/pawbench-v1.0"


def timed(label: str, fn, rounds: int = 6):
    samples = []
    result = None
    for _ in range(rounds):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    warm = sorted(samples[1:])
    print(
        f"{label}: first {samples[0]:.2f}ms, "
        f"warm median {warm[len(warm) // 2]:.2f}ms, max {max(samples):.2f}ms"
    )
    return result


def main() -> int:
    with tempfile.TemporaryDirectory() as scratch:
        workdir = Path(scratch)
        config = eval_config(workdir, builtin_root=CORPUS)
        store = Store(config.service.state_db)
        datasets = dataset_service(store, config)
        record = seed_pilot(datasets, config.datasets)
        pilot_id = record["id"]
        print(f"pilot id={pilot_id} tasks={len(record['task_ids'])}")

        resolved = timed("resolve(pilot)", lambda: datasets.resolve({"datasets": [pilot_id]}))
        print(f"  resolved task_count={len(resolved.task_ids)}")
        timed("describe(pilot)", lambda: datasets.describe(pilot_id))
        tasks = timed("tasks_for_run(pilot)", lambda: datasets.tasks_for_run(pilot_id))
        print(f"  runner got {len(tasks)} tasks")
        timed("list_catalog", lambda: datasets.list_catalog())
        timed("list_categories", lambda: datasets.list_categories())
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())