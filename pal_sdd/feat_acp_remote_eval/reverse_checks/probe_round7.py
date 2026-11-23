# -*- coding: utf-8 -*-
"""Read-only probes over the dataset catalogue and the report readers.

Nothing here writes to the repository: the fixtures live in a TemporaryDirectory
and the modules are patched in memory only.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "cpd" / "acp_remote_eval"))

from support import dataset_service, eval_config, write_task  # noqa: E402
from pawbench.cpd.acp_remote_eval.service import datasets as ds_mod  # noqa: E402
from pawbench.cpd.acp_remote_eval.service.datasets import (  # noqa: E402
    BuiltinCatalog,
    MAX_INDEX_CACHE,
)
from pawbench.cpd.acp_remote_eval.service.store import Store  # noqa: E402

FILTER_KEYS = frozenset(
    {"scenario", "capability", "complexity", "environment", "modality", "source",
     "grading_type", "task_ids"}
)


def make_service(tmp: Path):
    builtin_root = tmp / "builtin"
    write_task(builtin_root, "mail_l1", scenario="Office_Productivity/Email")
    write_task(builtin_root, "chart_open", scenario="Data_Analytics/Visualization",
               environment="open")
    config = eval_config(tmp, builtin_root=builtin_root)
    store = Store(tmp / "state.db")
    return store, dataset_service(store, config), builtin_root


def probe_duplicate_category(tmp: Path) -> None:
    store, service, _ = make_service(tmp)
    try:
        service.create_builtin_view(
            dataset_id="dup", name="dup", owner="owner",
            filter_spec={"task_ids": ["mail_l1"]},
            categories=["Office Tooling", "office   tooling"],
        )
        service.ensure_category("Office Tooling", "owner")
        rows = {row["name"]: row["dataset_count"] for row in service.list_categories()}
        print("A) dataset_count for a category carried once by one dataset:", rows)
        print("A) stored categories column:", store.get_dataset("dup")["categories"])
        print("A) datasets_with_category ->", store.datasets_with_category("office tooling"))
    finally:
        store.close()


def probe_eviction_race(tmp: Path) -> None:
    """Two request threads reaching a full cache at once."""
    store, service, _ = make_service(tmp)
    try:
        for index in range(MAX_INDEX_CACHE + 2):
            package = tmp / f"pkg-{index}"
            write_task(package, f"cust_{index}")
            service.register_custom(
                dataset_id=f"ds_{index}", name="set", owner="owner", source_dir=package
            )
        service._indexes.clear()  # noqa: SLF001 - probe the cold path
        for index in range(MAX_INDEX_CACHE):
            service.describe(f"ds_{index}")  # leave the cache exactly full
        assert len(service._indexes) == MAX_INDEX_CACHE, len(service._indexes)
        victims = [f"ds_{MAX_INDEX_CACHE}", f"ds_{MAX_INDEX_CACHE + 1}"]

        real = ds_mod._load_task_summaries
        gate = threading.Barrier(2, timeout=5)

        def slow(tasks_dir: Path):
            gate.wait()
            time.sleep(0.01)
            return real(tasks_dir)

        ds_mod._load_task_summaries = slow
        results: list = []

        def call(name: str) -> None:
            try:
                results.append(("ok", name, len(service.describe(name)["tasks"])))
            except BaseException as exc:  # noqa: BLE001
                results.append(("raised", name, f"{type(exc).__name__}: {exc}"))

        try:
            threads = [threading.Thread(target=call, args=(name,)) for name in victims]
            for item in threads:
                item.start()
            for item in threads:
                item.join()
            print("B) threads racing a full cache:", results)
        except threading.BrokenBarrierError as exc:
            print("B) barrier broke (fewer than two threads reached the parse):", exc)
        finally:
            ds_mod._load_task_summaries = real
    finally:
        store.close()


def probe_report_passes(tmp: Path) -> None:
    """How many full task-body parses one rendered markdown report costs."""
    import types

    from pawbench.cpd.acp_remote_eval.service.reports import Reports
    from support import make_exchange, job_row
    from datetime import datetime, timezone

    store, service, builtin_root = make_service(tmp)
    try:
        config = eval_config(tmp, builtin_root=builtin_root)
        exchange = make_exchange(store, tmp)
        reports = Reports(store, exchange, service, clock=exchange.clock)
        service.create_builtin_view(
            dataset_id="ds_p", name="p", owner="o",
            filter_spec={"task_ids": ["mail_l1", "chart_open"]},
        )
        store.insert_job(job_row("j-1", status="finished",
                                 finished_at=datetime.now(timezone.utc).isoformat()))
        store.insert_job_dataset(
            {"job_id": "j-1", "dataset_id": "ds_p", "dataset_kind": "builtin_view",
             "requested_by": "o", "resolved_task_ids": ["mail_l1", "chart_open"]}
        )
        store.insert_job_tasks([
            {"job_id": "j-1", "task_id": t, "attempt": 1, "status": "finished",
             "score": 1.0, "grading_type": "automated"}
            for t in ("mail_l1", "chart_open")
        ])

        counts = {"bodies": 0, "tasks_for_run": 0, "job_tasks": 0, "artifacts": 0}
        real_bodies = Reports._bodies

        def counted_bodies(self, job_id):  # noqa: ANN001
            counts["bodies"] += 1
            return real_bodies(self, job_id)

        real_tasks = ds_mod.DatasetService.tasks_for_run

        def counted_tasks(self, dataset_id):  # noqa: ANN001
            counts["tasks_for_run"] += 1
            return real_tasks(self, dataset_id)

        real_list = store.list_job_tasks
        real_art = store.list_artifacts
        store.list_job_tasks = lambda *a, **k: (counts.__setitem__(
            "job_tasks", counts["job_tasks"] + 1), real_list(*a, **k))[1]
        store.list_artifacts = lambda *a, **k: (counts.__setitem__(
            "artifacts", counts["artifacts"] + 1), real_art(*a, **k))[1]
        Reports._bodies = counted_bodies
        ds_mod.DatasetService.tasks_for_run = counted_tasks
        try:
            reports.report("j-1", fmt="md")
            print("C) one rendered markdown report:", counts)
            counts.update(bodies=0, tasks_for_run=0, job_tasks=0, artifacts=0)
            reports.job_detail("j-1")
            print("C) one job_detail (the polled route):", counts)
        finally:
            Reports._bodies = real_bodies
            ds_mod.DatasetService.tasks_for_run = real_tasks
            store.list_job_tasks = real_list
            store.list_artifacts = real_art
    finally:
        store.close()


def main() -> int:
    for name, probe in (("dup-category", probe_duplicate_category),
                        ("eviction-race", probe_eviction_race),
                        ("report-passes", probe_report_passes)):
        with tempfile.TemporaryDirectory(prefix=f"probe-{name}-") as tmp:
            print(f"--- {name} ---")
            try:
                probe(Path(tmp))
            except Exception as exc:  # noqa: BLE001
                print("probe failed:", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
