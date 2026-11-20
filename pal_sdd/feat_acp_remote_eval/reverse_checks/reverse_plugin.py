"""Reverse plugin: do the plugin contract cases actually judge?

``test_plugin.py`` has two halves, and they need different mutations.  The cases
that read files instead of calling the code cannot be exercised by in-memory
rebinding -- the mutation has to land in the file the host parses.  The proxy
cases do run the backend, so their mutations edit the shipped source and let
pytest import it again.  Either way each entry writes one broken version of a
shipped file, names the case that must go red, and the directory is restored
from a byte snapshot afterwards -- the plugin tree is untracked in git, so
``git checkout`` is not a way back.

**Do not run while anybody is reading `plugins/pawbench-eval/`**: the files are
briefly wrong in place.  Restore is verified by sha256 per file, so a crash in
the middle shows up as ``RESTORE_FAILED`` rather than as a mysterious diff.

Run:  /Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python \
        pal_sdd/feat_acp_remote_eval/reverse_checks/reverse_plugin.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO = Path("/Users/anderson/Desktop/ClawParterner/CPDPawBench")
PY = sys.executable
CASES = "tests/cpd/acp_remote_eval/test_plugin.py"
PLUGIN = REPO / "plugins" / "pawbench-eval"
BACKEND = "backend/main.py"
UI = "ui/index.js"
SKILL = "skills/pawbench-datasets/SKILL.md"
TEMPLATE = "skills/pawbench-datasets/templates/task.md"
#: A private basetemp: pytest reuses ``<tmp>/pytest-of-<user>`` and this
#: machine's filesystem shim raises EEXIST on the second ``makedirs`` of an
#: existing base, which shows up as an error in every ``tmp_path`` case.
BASETEMP = Path(tempfile.gettempdir()) / "pawbench-reverse-plugin"


def patch(relative: str, anchor: str, replacement: str) -> Callable[[], None]:
    """Break one promise by editing the text the host reads."""

    def apply() -> None:
        target = PLUGIN / relative
        text = target.read_text(encoding="utf-8")
        if anchor not in text:
            raise LookupError(f"anchor gone: {anchor!r} in {relative}")
        target.write_text(text.replace(anchor, replacement), encoding="utf-8")

    return apply


def move(source: str, destination: str) -> Callable[[], None]:
    """Put a file where the installer will not look, which is what happens by accident."""

    def apply() -> None:
        payload = (PLUGIN / source).read_bytes()
        (PLUGIN / source).unlink()
        target = PLUGIN / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    return apply


#: name -> (the breakage, the case that must go red)
MUTATIONS: dict[str, tuple[Callable[[], None], str]] = {
    "TOOL_DRIFT": (
        patch(SKILL, "pawbench_describe_dataset", "pawbench_describe_datasets"),
        "every_tool_the_skill_names_exists",
    ),
    "GATE_DRIFT": (
        patch(SKILL, 'mcp: ["pawbench-eval"]', 'mcp: ["pawbench-eval-mcp"]'),
        "gated_on_the_server_the_service_mounts",
    ),
    "REPO_PATH": (
        patch(BACKEND, "_APP_DIR = Path(__file__).resolve().parent.parent",
              '_APP_DIR = Path("plugins/pawbench-eval")'),
        "anchors_on_its_own_location",
    ),
    "SKILLS_TYPO": (
        patch(
            BACKEND,
            '_SKILLS_DIR = _PLUGIN_ROOT / "skills"',
            '_SKILLS_DIR = _PLUGIN_ROOT / "skill"',
        ),
        "registers_the_skills_directory",
    ),
    "BULLET_CRITERIA": (
        patch(TEMPLATE, "- [ ] ", "- "),
        "task_skeleton_is_a_package",
    ),
    "TYPE_DRIFT": (
        patch("plugin.json", '"type": "app"', '"type": "bundle"'),
        "manifest_answers_what_the_installer_asks",
    ),
    "DEPS_MOVED": (
        move("requirements.txt", "requirements-moved.txt"),
        "dependency_list_sits_where_the_installer_reads_it",
    ),
    # ── the page and the service, which is where a rename costs a 404 ──
    "ENTRY_PAGE_DRIFT": (
        patch(UI, 'path: "/apps/pawbench-eval"', 'path: "/apps/pawbench-eval-board"'),
        "frontend_registers_the_page_the_manifest_advertises",
    ),
    "ENDPOINT_DRIFT": (
        patch(UI, '"/v1/datasets/resolve"', '"/v1/datasets/resolv"'),
        "dashboard_still_calls_every_endpoint",
    ),
    "REPORT_QUERY_DRIFT": (
        patch(UI, '"/report?format="', '"/report?fmt="'),
        "dashboard_still_calls_every_endpoint",
    ),
    "COLOUR_LITERAL": (
        patch(UI, "strokeColor: s.token.colorPrimary", 'strokeColor: "#3b6ef6"'),
        "takes_no_colour_literals",
    ),
    # ── the proxy, which is where a mistake leaks a credential ──
    "TOKEN_ECHO": (
        patch(BACKEND, '"has_token": bool(token),\n        "token_hint"',
              '"has_token": bool(token),\n        "token": token,\n        "token_hint"'),
        "never_hands_the_token_back",
    ),
    "WRONG_CREDENTIAL": (
        patch(BACKEND, 'outgoing["Authorization"] = f"Bearer {token}"',
              'outgoing["Authorization"] = f"Bearer {token}-typo"'),
        "service_token_is_added",
    ),
    "IGNORE_OFF": (
        patch(".gitignore", "data/", "logs/"),
        "runtime_state_is_kept_out",
    ),
    "CHMOD_OFF": (
        patch(BACKEND, "os.chmod(tmp, 0o600)", "os.chmod(tmp, 0o644)"),
        "not_world_readable",
    ),
    "PREFIX_DOUBLE": (
        patch(BACKEND, '"/v1/{rest:path}"', '"/pawbench-eval/v1/{rest:path}"'),
        "never_hides_its_routes",
    ),
    "ORIGIN_GUARD_OFF": (
        patch(BACKEND,
              "if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):",
              "if False:"),
        "fetch_relays_only_the_configured_origin",
    ),
}


def snapshot() -> dict[str, bytes]:
    return {
        str(path.relative_to(PLUGIN)): path.read_bytes()
        for path in sorted(PLUGIN.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def restore(files: dict[str, bytes]) -> list[str]:
    """Put every byte back and return the files that did not come back clean.

    Files a mutation created are removed first; the ones in the snapshot are
    rewritten.  ``mkdir`` is only called for a directory that is missing --
    ``mkdir(exist_ok=True)`` on an existing directory raises on this machine
    (the filesystem shim reports its own ``EEXIST``), and a half-finished
    restore deletes the plugin.
    """
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            if str(path.relative_to(PLUGIN)) not in files:
                path.unlink()
    for relative, payload in files.items():
        target = PLUGIN / relative
        if not target.parent.is_dir():
            target.parent.mkdir(parents=True)
        target.write_bytes(payload)
    return [
        relative for relative, payload in files.items()
        if hashlib.sha256((PLUGIN / relative).read_bytes()).hexdigest()
        != hashlib.sha256(payload).hexdigest()
    ]


def run() -> tuple[int, str]:
    shutil.rmtree(BASETEMP, ignore_errors=True)
    proc = subprocess.run(
        [PY, "-m", "pytest", CASES, "-q", f"--basetemp={BASETEMP}"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    files = snapshot()
    code, output = run()
    baseline = next(
        (line for line in output.splitlines() if "passed" in line or "failed" in line), "",
    )
    print(f"BASELINE: {baseline.strip()}")
    if code != 0:
        print("baseline is not green; refusing to run mutations")
        return 2

    survivors: list[str] = []
    for name, (breakage, expected) in MUTATIONS.items():
        try:
            breakage()
        except LookupError as exc:
            print(f"{name:16s} SKIP      {exc}")
            survivors.append(name)
            continue
        try:
            code, output = run()
        except subprocess.TimeoutExpired:
            print(f"{name:16s} HARNESS_ERROR: mutation timed out")
            restore(files)
            return 2
        finally:
            dirty = restore(files)
        if dirty:
            print(f"{name:16s} RESTORE_FAILED: {dirty}")
            return 2
        if code not in (0, 1) or any(
            line.startswith("ERROR ") or "INTERNALERROR" in line
            for line in output.splitlines()
        ):
            print(f"{name:16s} HARNESS_ERROR: pytest exited {code}\n{output[-2000:]}")
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
            f"{name:16s} {verdict:9s} expected={expected} "
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
