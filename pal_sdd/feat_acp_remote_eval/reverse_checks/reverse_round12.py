"""Reverse round 12: does the console lane's early-warning set actually warn?

The first independent review of this lane raised 20 findings; the fixes are only
worth the diff if the cases added beside them go red when the fix is undone.
Each mutation below puts one promise back the way it was and names the case that
must fail.

**This one edits source.**  The mutations live inside method bodies (a removed
guard, a changed dedup key), which an in-memory attribute rebind cannot express
without restating the whole method -- and a restated method tests the restatement.
Every original byte is kept in memory and written back in ``finally``, and the
restore is verified by sha256, so a crash mid-run leaves a loud failure rather
than a dirty tree.  Do not run this while an independent reviewer is reading the
same files.

Run:  python pal_sdd/feat_acp_remote_eval/reverse_checks/reverse_round12.py
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
PY = sys.executable
CASES = "tests/cpd/acp_remote_eval/test_console_agent.py"
AGENT = REPO / "pawbench/cpd/acp_remote_eval/console_agent.py"
BRIDGE = REPO / "pawbench/cpd/acp_remote_eval/bridge.py"

#: name -> (file, text to replace, replacement, the case that must go red)
MUTATIONS: dict[str, tuple[Path, str, str, str]] = {
    # #4: a turn that produced nothing was a successful empty answer.
    "EMPTY_OK": (
        AGENT,
        "if turn.updates == 0 and stop_reason != \"cancelled\":",
        "if False:",
        "a_turn_that_says_nothing_is_a_failed_attempt",
    ),
    # #4: the console's own error envelope was read as "the turn ended".
    "ERROR_IGNORED": (
        AGENT,
        'if payload.get("error"):',
        "if False:",
        "a_stream_error_is_a_failed_attempt_not_an_empty_answer",
    ),
    # #4: any 200 was read as an event stream.
    "ANY_CONTENT_TYPE": (
        AGENT,
        '    if content_type == "text/event-stream":\n        return',
        "    if True:\n        return",
        "a_200_that_is_not_an_event_stream_is_a_failed_attempt",
    ),
    # #8: a failed run was indistinguishable from a finished one.
    "FAILED_AS_END": (
        AGENT,
        'if status == "failed":',
        "if False:",
        "a_failed_run_is_not_reported_as_a_finished_turn",
    ),
    # #17/#18: dedup keyed on the payload's msg_id string, which is null on the
    # closing row -- so every answer went out twice and reasoning read as answer.
    "DEDUPE_BY_STRING": (
        AGENT,
        '        message_id = str(raw or "")\n'
        "        if message_id:\n"
        "            self.current_message = message_id\n"
        "            return message_id\n"
        "        return self.current_message",
        '        return str(raw or "")',
        "the_answer_is_sent_once",
    ),
    # #2: stop resolved a chat id through a full unfiltered GET /api/chats.
    "STOP_VIA_LIST": (
        AGENT,
        "    async def _request_stop(self, session_id: str) -> None:\n        import httpx",
        "    async def _request_stop(self, session_id: str) -> None:\n"
        "        session_id = (await self._chat_id(session_id)) or session_id\n"
        "        import httpx",
        "a_cancelled_turn_stops_the_console_run",
    ),
    # #20: a tool call needed both "not delta" and status == completed to exist.
    "NEED_STATUS": (
        AGENT,
        'ready = bool(call.get("arguments")) or has_output or not payload.get("delta")',
        'ready = payload.get("status") == "completed" and not payload.get("delta")',
        "a_tool_call_survives_a_console_that_omits_delta_and_status",
    ),
    # #19: a refusal was flattened into a "[refusal]" marker.
    "REFUSAL_DROPPED": (
        AGENT,
        'if content_type == "refusal":',
        'if False:',
        "a_refusal_reaches_the_transcript_as_the_words_it_was",
    ),
    # #6: a failed write to a gone client ended the turn without stopping the run.
    "GONE_SWALLOWED": (
        AGENT,
        "        except Exception as exc:  # noqa: BLE001 - any write failure means the client is gone",
        "        except Exception as exc:  # noqa: BLE001\n            return",
        "a_client_that_stops_reading_stops_the_console_run",
    ),
    # #9: the connection was kept for the life of the process.
    "KEEP_CONNECTION": (
        AGENT,
        "        state.connection = None\n        if state.closing:",
        "        pass\n        if state.closing:",
        "a_finished_turn_lets_go_of_the_client_connection",
    ),
    # #12: no silence limit between two events.
    "NO_IDLE": (
        AGENT,
        "payload = await asyncio.wait_for(anext(events), timeout=self.idle_timeout)",
        "payload = await anext(events)",
        "a_console_that_goes_quiet_fails_the_turn_instead_of_hanging",
    ),
    # #7/routing: a session's connection was only established at session/new,
    # so the second turn of a session streamed to nobody.
    "DROP_ROUTE": (
        BRIDGE,
        'if session_id and name in _ROUTING_CALLS and callable(route):',
        "if False:",
        "a_second_turn_on_one_session_still_reaches_its_client",
    ),
    # #11: the stop was awaited directly, so the cancel that asked for it killed
    # it -- the console kept running while the harness logged "cancelled".  Found
    # on a real bridge: ``connect_tcp.failed exception=CancelledError()``.
    "NO_SHIELD": (
        AGENT,
        "await asyncio.shield(pending)",
        "await pending",
        "a_cancel_that_loses_its_client_still_stops_the_console_run",
    ),
    # real-run follow-up: the same cancel arrives twice, and two stops in the
    # same instant made the second answer "nothing was running".
    "STOP_TWICE": (
        AGENT,
        "        pending = self._stopping.get(session_id)\n"
        "        if pending is None or pending.done():",
        "        pending = self._stopping.get(session_id)\n"
        "        if True:",
        "two_callers_asking_to_stop_share_one_request",
    ),
    # #16: the summary's numbers were only in ``extra``, which the bridge's plain
    # ``%(message)s`` format never prints -- found by reading a real bridge log.
    "SUMMARY_HIDDEN": (
        AGENT,
        '            "console turn finished: session=%s stop_reason=%s updates=%d skipped=%d tokens=%d",\n'
        "            session_id,\n"
        "            stop_reason,\n"
        "            turn.updates,\n"
        "            turn.skipped,\n"
        "            usage.total_tokens if usage else 0,\n",
        '            "console turn finished",\n',
        "the_turn_summary_is_readable_in_a_plain_log_line",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> tuple[int, str]:
    command = [PY, "-m", "pytest", CASES, "-q"]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO))
    proc = subprocess.run(
        command, cwd=str(REPO), capture_output=True, text=True, timeout=900, env=env
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    code, output = run()
    baseline = next(
        (line for line in output.splitlines() if "passed" in line or "failed" in line), ""
    )
    print(f"BASELINE: {baseline.strip()}")
    if code != 0:
        print("baseline is not green; refusing to run mutations")
        return 2

    originals = {path: path.read_bytes() for path in {m[0] for m in MUTATIONS.values()}}
    sums = {path: digest(path) for path in originals}
    survivors: list[str] = []
    try:
        for name, (path, needle, replacement, expected) in MUTATIONS.items():
            text = originals[path].decode("utf-8")
            if text.count(needle) != 1:
                print(f"{name:18s} SKIP: anchor appears {text.count(needle)}x")
                survivors.append(name)
                continue
            path.write_text(text.replace(needle, replacement), encoding="utf-8")
            try:
                code, output = run()
            except subprocess.TimeoutExpired:
                print(f"{name:18s} HARNESS_ERROR: mutation timed out")
                return 2
            finally:
                path.write_bytes(originals[path])
            if code not in (0, 1) or "INTERNALERROR" in output or "error during collection" in output:
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
    finally:
        for path, blob in originals.items():
            path.write_bytes(blob)

    for path, before in sums.items():
        after = digest(path)
        print(f"restored {path.name}: {'ok' if after == before else 'DIFFERS ' + after}")

    print(f"\nmutations judged red: {len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)}")
    if survivors:
        print(f"SURVIVORS: {survivors}")
        return 1
    print("zero survivors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
