#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate the `workspace_files:` block of PawBench task files from their assets directory.

For every task md given (or every md in the tasks dir), scan
``data/<dataset>/assets/<md-stem>/`` and rewrite the frontmatter block as:

    workspace_files:
    - source: assets/<md-stem>/<relative/path>
      dest: <relative/path>

Only the ``workspace_files`` block is touched; every other frontmatter field and the whole
body are preserved byte for byte.

Usage:
    python3 sync_workspace_files.py                       # all tasks
    python3 sync_workspace_files.py T151_self-built_weekly_expense_digest.md
    python3 sync_workspace_files.py --check ...           # report drift, change nothing
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

FM_RE = re.compile(r"^---\s*\n(.*?)\n---(\n.*)?", re.DOTALL)
# A top-level YAML key: starts at column 0, word chars, then a colon.
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*:(?:\s|$)")
SKIP_NAMES = {".gitkeep", ".DS_Store"}

SKIP_SUFFIX = {".pyc", ".pyo", ".so", ".dylib"}


def find_repo_root(explicit: str | None = None) -> Path:
    """Locate the PawBench checkout.

    Order: --repo / $PAWBENCH_ROOT, then walk up from this script, then from cwd.
    The script may live outside the checkout (e.g. a shared ~/.codebuddy/skills copy),
    so a script-relative search alone is not enough.
    """
    raw = explicit or os.environ.get("PAWBENCH_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (start, *start.parents):
            if (parent / "pawbench" / "task_loader.py").is_file() and (parent / "data").is_dir():
                return parent
    raise SystemExit(
        "ERROR: cannot locate the PawBench repo root. Run from inside the checkout, "
        "or pass --repo /path/to/PawBench (or set PAWBENCH_ROOT)."
    )


def collect(asset_dir: Path) -> list[tuple[str, str]]:
    if not asset_dir.is_dir():
        return []
    out = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIX:
            continue
        rel = path.relative_to(asset_dir).as_posix()
        out.append((f"assets/{asset_dir.name}/{rel}", rel))
    return out


def render(entries: list[tuple[str, str]]) -> str:
    if not entries:
        return "workspace_files: []\n"
    lines = ["workspace_files:"]
    for source, dest in entries:
        lines.append(f"- source: {source}")
        lines.append(f"  dest: {dest}")
    return "\n".join(lines) + "\n"


def rewrite(text: str, entries: list[tuple[str, str]]) -> str:
    block = render(entries)
    fm_match = FM_RE.match(text)
    if not fm_match:
        raise ValueError("no YAML frontmatter")
    front = fm_match.group(1)
    body = fm_match.group(2)

    lines = front.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("workspace_files:")), None)

    if start is None:
        new_lines = lines[:] + block.rstrip("\n").split("\n")
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if KEY_RE.match(lines[i])),
            len(lines),
        )
        # `block` already ends with "\n"; split() leaves one trailing "" entry to absorb it.
        new_lines = lines[:start] + block.split("\n")[:-1] + lines[end:]

    return "---\n" + "\n".join(new_lines).strip("\n") + "\n---" + (body or "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="task md paths (default: all tasks in the dataset)")
    ap.add_argument("--dataset", default="pawbench-v1.0")
    ap.add_argument("--check", action="store_true", help="report drift without writing")
    ap.add_argument("--repo", default=None, help="path to the PawBench checkout (default: auto-detect)")
    args = ap.parse_args()

    root = find_repo_root(args.repo)
    tasks_dir = root / "data" / args.dataset / "tasks"
    assets_dir = root / "data" / args.dataset / "assets"

    if args.files:
        targets = [Path(f) for f in args.files]
        targets = [t if t.is_absolute() else (Path.cwd() / t) for t in targets]
        missing = [t for t in targets if not t.is_file()]
        if missing:
            raise SystemExit(f"ERROR: no such file: {missing[0]}")
    else:
        targets = sorted(tasks_dir.glob("*.md"))

    changed = 0
    for md in targets:
        text = md.read_text(encoding="utf-8")
        entries = collect(assets_dir / md.stem)
        try:
            new_text = rewrite(text, entries)
        except ValueError:
            print(f"SKIP  {md.name}: no valid frontmatter")
            continue

        if new_text == text:
            continue
        changed += 1
        if args.check:
            print(f"DRIFT {md.name}: workspace_files has {len(entries)} asset(s) declared differently")
        else:
            md.write_text(new_text, encoding="utf-8")
            print(f"SYNC  {md.name}: {len(entries)} workspace file(s)")

    if args.check:
        if changed:
            print(f"\n{changed} file(s) out of sync")
            return 1
        print("all files in sync")
        return 0
    print(f"\nupdated {changed} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
