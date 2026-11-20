"""Read-only probe: what concurrent automated grading does to the service process.

The core grader (pawbench/grader.py:141) execs the task's own check script and,
around the call, swaps sys.modules["subprocess"] for a logging wrapper (:170),
restoring it in a finally (:177-181).  That swap is process-global, while this
service grades up to max_concurrent_jobs attempts at once, each in its own
asyncio.to_thread worker (service/grading.py:266, service/runtime.py:241).

Every measurement runs in a *child* process: contextlib.redirect_stdout is
process-global too, so capturing inside a thread would swallow the other
thread's output -- and a child's real stdout is exactly what the daemon's
stdout would be, which is the thing the leak question asks about.

Writes nothing to the repository.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
sys.path.insert(0, str(REPO))

from pawbench.grader import _grade_automated  # noqa: E402

REAL_SUBPROCESS = sys.modules["subprocess"]
MARKER = "FAKE-CREDENTIAL-do-not-use-8f3a"
AFTER_MARKER = "FAKE-AFTER-RACE-do-not-use-2b71"
SLEEP_SECONDS = 0.30
STAGGERS = (0.0, 0.02, 0.05, 0.10, 0.15)
CHILD_TIMEOUT = 120


def task(task_id: str, body: str) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        automated_checks=f"```python\n{body}\n```",
    )


SLEEPING = task(
    "sleeping",
    "import time\n"
    "def grade(transcript, workspace):\n"
    f"    time.sleep({SLEEP_SECONDS})\n"
    "    return {'ok': 1}\n",
)

def spawning(task_id: str, import_line: str, indent: str) -> SimpleNamespace:
    return task(
        task_id,
        f"{import_line}"
        "def grade(transcript, workspace):\n"
        f"{indent}subprocess.run(['echo', '{MARKER}'], "
        "capture_output=True, text=True)\n"
        f"{indent}return {{'ok': 1}}\n",
    )


# The exec at :141 runs *before* the swap at :170, so a top-level import binds
# the real module; only an import inside grade() can see the wrapper.
SPAWNING_TOP = spawning("spawning_top", "import subprocess\n", "    ")
SPAWNING_INSIDE = spawning("spawning_inside", "", "    import subprocess\n    ")


def grade(item: SimpleNamespace) -> None:
    _grade_automated(item, {"transcript": [], "workspace": ""})


# ── child modes: no redirection, the grader prints to real stdout ─────────────


def child_round(delay: float) -> int:
    """Two gradings whose patch windows overlap, then one unrelated call."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(grade, SLEEPING)
        time.sleep(delay)
        second = pool.submit(grade, SLEEPING)
        first.result()
        second.result()

    left = sys.modules.get("subprocess")
    intact = left is REAL_SUBPROCESS
    import subprocess as later

    later.run(["echo", AFTER_MARKER], capture_output=True, text=True)
    print(
        f"RESULT intact={intact} kind={type(left).__name__} "
        f"later_call_wrapped={later is not REAL_SUBPROCESS}"
    )
    return 0


def child_leak(where: str) -> int:
    """One grading whose script runs a subprocess carrying a fake secret."""
    grade(SPAWNING_TOP if where == "top" else SPAWNING_INSIDE)
    left = sys.modules.get("subprocess") is not REAL_SUBPROCESS
    print(f"RESULT import={where} single_grading_wrapper_left={left}")
    return 0


# ── parent: spawn, then read what actually reached the child's stdout ─────────


def run_child(mode: str, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), mode, *args],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT,
        cwd=str(REPO),
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"child {mode} {args} exited {proc.returncode}\n{proc.stderr[-2000:]}"
        )
    return proc.stdout


def result_line(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("RESULT "))


def main() -> int:
    print(f"real subprocess module: {REAL_SUBPROCESS!r}")
    print(f"each grading sleeps {SLEEP_SECONDS:.2f}s inside its patch window")

    intact_rounds = 0
    wrapped_later = 0
    for delay in STAGGERS:
        output = run_child("round", f"{delay}")
        fields = dict(
            part.split("=", 1) for part in result_line(output).split()[1:]
        )
        intact = fields["intact"] == "True"
        later_wrapped = fields["later_call_wrapped"] == "True"
        intact_rounds += intact
        wrapped_later += later_wrapped
        echoed = AFTER_MARKER in output
        print(
            f"stagger {delay:.2f}s -> intact={intact} "
            f"left_as={fields['kind']} "
            f"later_call_wrapped={later_wrapped} later_stdout_echoed={echoed}"
        )

    total = len(STAGGERS)
    print(f"rounds leaving the real module in place: {intact_rounds}/{total}")
    print(f"rounds where a later unrelated call was wrapped: {wrapped_later}/{total}")

    for where in ("top", "inside"):
        output = run_child("leak", where)
        leaked = MARKER in output
        print(
            f"import {where}: grading script's subprocess stdout reaches "
            f"process stdout: {leaked}"
        )
        if leaked:
            line = next(line for line in output.splitlines() if MARKER in line)
            print(f"  line as printed: {line.strip()[:160]}")
        print(f"  {result_line(output)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "round":
        sys.exit(child_round(float(sys.argv[2])))
    if len(sys.argv) > 1 and sys.argv[1] == "leak":
        sys.exit(child_leak(sys.argv[2]))
    sys.exit(main())