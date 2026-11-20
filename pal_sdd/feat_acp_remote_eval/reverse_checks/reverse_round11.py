"""Reverse round 11: do the judge-lane cases actually judge?

Twelve cases were added for a lane that had no direct case at all.  A case that
passes against both the code and a broken version of it is decoration, so each
mutation here breaks one promise and names the case that must go red.

**In-memory only.**  Every mutation is applied by a pytest plugin that rebinds a
module attribute after import; no file under ``pawbench/`` is written, so this is
safe to run while an independent reviewer is reading the same sources.  The
trade-off is recorded in the README: a stale anchor here fails silently instead
of printing SKIP, so the harness checks that the *expected* case went red, not
merely that something did.

Run:  python reverse_checks/reverse_round11.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PY = sys.executable
CASES = "tests/cpd/acp_remote_eval/test_grading.py"
MODULE = "pawbench.cpd.acp_remote_eval.service.grading"

#: name -> (plugin body, the case substring that must go red)
MUTATIONS: dict[str, tuple[str, str]] = {
    "BACKOFF_CAP": (
        "g.LlmJudge._delay = lambda self, attempt, retry_after: max("
        "self.config.base_delay_seconds * (2 ** (attempt - 1)), retry_after)",
        "retry_after_is_honoured_up_to_the_ceiling",
    ),
    "RETRY_ALL": (
        "g._is_retryable = lambda status_code: True",
        "a_rejected_key_is_not_retried",
    ),
    "SERVED_LOST": (
        "import dataclasses\n"
        "_orig_reply = g._reply_from\n"
        "g._reply_from = lambda response, *, requested_model: dataclasses.replace("
        "_orig_reply(response, requested_model=requested_model), "
        "served_model=requested_model)",
        "the_served_model_is_recorded",
    ),
    "FENCE_LOST": (
        'g.UNTRUSTED_SYSTEM_PROMPT = "You are a grading function."',
        "the_subject_output_is_fenced_as_evidence",
    ),
    "REASON_MERGED": (
        "g.JudgeUnreadable.reason = g.JUDGE_UNAVAILABLE",
        "is_a_grading_error",
    ),
    "BREAKDOWN_DROPPED": (
        "import dataclasses\n"
        "_orig_score = g.Scorer.score\n"
        "async def _score(self, task, execution_result, *, budget_seconds=None):\n"
        "    out = await _orig_score(self, task, execution_result, "
        "budget_seconds=budget_seconds)\n"
        "    if out.score is None:\n"
        "        return dataclasses.replace(out, automated_breakdown={})\n"
        "    return out\n"
        "g.Scorer.score = _score",
        "hybrid_keeps_the_automated_half",
    ),
    "KEY_LOGGED": (
        "_orig_warning = g.logger.warning\n"
        "g.logger.warning = lambda msg, *a, **k: _orig_warning("
        'str(msg) + " key=" + g.os.environ.get("PAWBENCH_TEST_JUDGE_KEY", ""), *a, **k)',
        "the_key_reaches_the_header_and_nothing_else",
    ),
}

ANCHORS = {
    "BACKOFF_CAP": "LlmJudge._delay",
    "RETRY_ALL": "_is_retryable",
    "SERVED_LOST": "_reply_from",
    "FENCE_LOST": "UNTRUSTED_SYSTEM_PROMPT",
    "REASON_MERGED": "JudgeUnreadable.reason",
    "BREAKDOWN_DROPPED": "Scorer.score",
    "KEY_LOGGED": "logger.warning",
}
PLUGIN = (
    "import {module} as g\n"
    "from functools import reduce\n"
    "assert reduce(getattr, {anchor!r}.split('.'), g) is not None\n\n"
    "{body}\n"
)


def run(plugin_dir: Path | None, name: str | None) -> tuple[int, str]:
    env = os.environ.copy()
    if plugin_dir:
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(plugin_dir), env.get("PYTHONPATH", "")) if part
        )

    command = [PY, "-m", "pytest", CASES, "-q"]
    if name:
        command += ["-p", f"mut_{name.lower()}"]
    proc = subprocess.run(
        command,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    code, output = run(None, None)
    baseline = next(
        (line for line in output.splitlines() if "passed" in line or "failed" in line),
        "",
    )
    print(f"BASELINE: {baseline.strip()}")
    if code != 0:
        print("baseline is not green; refusing to run mutations")
        return 2

    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        plugin_dir = Path(scratch)
        for name, (body, expected) in MUTATIONS.items():
            (plugin_dir / f"mut_{name.lower()}.py").write_text(
                PLUGIN.format(module=MODULE, anchor=ANCHORS[name], body=body),
                encoding="utf-8",
            )
            try:
                code, output = run(plugin_dir, name)
            except subprocess.TimeoutExpired:
                print(f"{name:18s} HARNESS_ERROR: mutation timed out")
                return 2
            if code not in (0, 1) or any(
                line.startswith("ERROR ") or "INTERNALERROR" in line
                for line in output.splitlines()
            ):
                print(f"{name:18s} HARNESS_ERROR: pytest exited {code}\n{output[-2000:]}")
                return 2
            failed = [
                line.split("::")[-1].strip()
                for line in output.splitlines()
                if line.startswith("FAILED")
            ]
            hit = [case for case in failed if expected in case]
            verdict = "RED" if hit else "SURVIVED"
            if not hit:
                survivors.append(name)
            print(
                f"{name:18s} {verdict:9s} expected={expected} "
                f"failed={len(failed)} {hit if hit else failed}"
            )

    print(f"\nmutations judged red: {len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)}")
    if survivors:
        print(f"SURVIVORS: {survivors}")
        return 1
    print("zero survivors")
    return 0


if __name__ == "__main__":
    sys.exit(main())