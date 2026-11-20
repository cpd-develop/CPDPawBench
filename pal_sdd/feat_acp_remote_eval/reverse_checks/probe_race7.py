# -*- coding: utf-8 -*-
"""How often does the index-cache eviction line actually lose a race?

Runs the real ``_index`` from many threads with the interpreter's switch interval
turned down, with the cache re-filled to exactly full on every round.
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
from pawbench.cpd.acp_remote_eval.service.datasets import MAX_INDEX_CACHE  # noqa: E402
from pawbench.cpd.acp_remote_eval.service.store import Store  # noqa: E402


def main() -> int:
    sys.setswitchinterval(1e-6)
    with tempfile.TemporaryDirectory(prefix="race-") as raw:
        tmp = Path(raw)
        builtin_root = tmp / "builtin"
        write_task(builtin_root, "mail_l1", scenario="Office_Productivity/Email")
        config = eval_config(tmp, builtin_root=builtin_root)
        store = Store(tmp / "state.db")
        service = dataset_service(store, config)
        total = MAX_INDEX_CACHE + 6
        for index in range(total):
            package = tmp / f"pkg-{index}"
            write_task(package, f"cust_{index}")
            service.register_custom(
                dataset_id=f"ds_{index}", name="s", owner="o", source_dir=package
            )
        real = ds_mod._load_task_summaries
        delays = []

        def slow(tasks_dir: Path):
            time.sleep(0.001)  # keep the threads inside the parse at the same moment
            return real(tasks_dir)

        ds_mod._load_task_summaries = slow
        errors: dict[str, int] = {}
        rounds, threads_per_round = 300, 6

        for round_index in range(rounds):
            cold = [f"ds_{(round_index * 3 + slot) % total}" for slot in range(threads_per_round)]
            service._indexes.clear()  # noqa: SLF001
            for index in range(MAX_INDEX_CACHE):
                service._indexes[f"warm_{index}"] = (((),), {})  # noqa: SLF001
            gate = threading.Barrier(threads_per_round, timeout=10)

            def call(dataset_id: str) -> None:
                gate.wait()
                try:
                    service.describe(dataset_id)
                except BaseException as exc:  # noqa: BLE001
                    key = f"{type(exc).__name__}: {exc}"
                    errors[key] = errors.get(key, 0) + 1

            pool = [threading.Thread(target=call, args=(name,)) for name in cold]
            for item in pool:
                item.start()
            for item in pool:
                item.join()
        ds_mod._load_task_summaries = real
        store.close()
        print(f"rounds={rounds} threads={threads_per_round} "
              f"describes={rounds * threads_per_round} errors={errors or 'none'}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
