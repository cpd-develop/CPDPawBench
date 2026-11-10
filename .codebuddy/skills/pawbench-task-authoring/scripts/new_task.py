#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scaffold a new PawBench v1.0 task: allocate an id, create the md + assets dir.

Usage:
    python3 new_task.py --slug weekly_expense_digest --source self-built \
        --name "Weekly Expense Digest" --category Data_Analytics \
        --grading-type hybrid --timeout 600

Run from anywhere; paths are resolved relative to the PawBench repo root, which is
located by walking up from this file until a directory containing ``pawbench/`` and
``data/`` is found.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

VALID_GRADING = ("automated", "llm_judge", "hybrid")
STEM_RE = re.compile(r"^T(\d+)_")


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


def next_index(tasks_dir: Path) -> int:
    highest = 0
    for md in tasks_dir.glob("T*.md"):
        m = STEM_RE.match(md.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def slugify(raw: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug or "untitled"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="short snake_case task slug")
    ap.add_argument("--source", default="self-built", help="source suite tag, e.g. claweval / self-built")
    ap.add_argument("--name", default=None, help="human title (default: slug title-cased)")
    ap.add_argument("--category", default="General")
    ap.add_argument("--grading-type", default="hybrid", choices=VALID_GRADING)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--scenario", default="TODO/TODO")
    ap.add_argument("--dataset", default="pawbench-v1.0")
    ap.add_argument("--id", default=None, help="override the frontmatter id (default: slug)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    ap.add_argument("--repo", default=None, help="path to the PawBench checkout (default: auto-detect)")
    args = ap.parse_args()

    root = find_repo_root(args.repo)
    tasks_dir = root / "data" / args.dataset / "tasks"
    assets_dir = root / "data" / args.dataset / "assets"
    if not tasks_dir.is_dir():
        raise SystemExit(f"ERROR: tasks dir not found: {tasks_dir}")

    slug = slugify(args.slug)
    source = slugify(args.source)
    index = next_index(tasks_dir)
    stem = f"T{index:03d}_{source}_{slug}"
    md_path = tasks_dir / f"{stem}.md"
    asset_dir = assets_dir / stem

    if md_path.exists() and not args.force:
        raise SystemExit(f"ERROR: {md_path} already exists (use --force)")

    template = (Path(__file__).resolve().parent.parent / "assets" / "task_template.md").read_text(
        encoding="utf-8"
    )

    weights = {
        "automated": "",
        "llm_judge": "",
        "hybrid": "grading_weights:\n  automated: 0.35\n  llm_judge: 0.65\n",
    }[args.grading_type]

    body = template
    body = body.replace("__ID__", args.id or slug)
    body = body.replace("__NAME__", args.name or args.slug.replace("_", " ").title())
    body = body.replace("__CATEGORY__", args.category)
    body = body.replace("__SCENARIO__", args.scenario)
    body = body.replace("grading_type: hybrid", f"grading_type: {args.grading_type}")
    body = body.replace("timeout_seconds: 600", f"timeout_seconds: {args.timeout}")
    if args.grading_type == "hybrid":
        body = body.replace(
            "grading_weights:\n  automated: 0.35\n  llm_judge: 0.65\n", weights
        )
    else:
        body = body.replace("grading_weights:\n  automated: 0.35\n  llm_judge: 0.65\n", "")

    # Drop sections that do not apply to the chosen grading type.
    if args.grading_type == "llm_judge":
        body = _drop_section(body, "## Automated Checks")
    if args.grading_type == "automated":
        body = _drop_section(body, "## LLM Judge Rubric")

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(body, encoding="utf-8")
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / ".gitkeep").touch()

    print(f"created  {md_path.relative_to(root)}")
    print(f"created  {asset_dir.relative_to(root)}/")
    print(f"id       {args.id or slug}")
    print("")
    print("next: fill in the sections, add assets, then run sync_workspace_files.py + validate_tasks.py")
    return 0


def _drop_section(body: str, heading: str) -> str:
    lines = body.split("\n")
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith(heading):
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
