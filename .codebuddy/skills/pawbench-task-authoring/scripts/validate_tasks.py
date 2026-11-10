#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate PawBench task files against the runner's real parsing contract.

Mirrors the logic in pawbench/task_loader.py, pawbench/backend.py and pawbench/grader.py so a
task that is silently skipped or graded 0 fails loudly here instead.

Usage:
    python3 validate_tasks.py                        # whole dataset
    python3 validate_tasks.py path/to/T151_*.md ...  # specific files
    python3 validate_tasks.py --strict               # warnings are errors too
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import posixpath
import re
import sys
import sysconfig
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("ERROR: PyYAML is required (pip install pyyaml)")

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+)$")
CRITERIA_RE = re.compile(r"^-\s+\[[ x]\]\s+(.+)$")
PY_FENCE_RE = re.compile(r"```python\s*\n(.*?)\n\s*```", re.DOTALL)
WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:/")

VALID_GRADING = ("automated", "llm_judge", "hybrid")
VALID_COMPLEXITY = ("L1", "L2", "L3")
VALID_ENVIRONMENT = ("closed", "open")
VALID_MODALITY = ("text", "multimodal")
CAPABILITIES = {
    "Logic_Reasoning",
    "Math_Computation",
    "Code_Manipulation",
    "Tool_Use",
    "Skill_Use",
    "Planning",
    "Self_Verification",
}


class Report:
    def __init__(self, strict: bool) -> None:
        self.strict = strict
        self.errors = 0
        self.warnings = 0
        self.files = 0

    def error(self, path: Path, msg: str) -> None:
        self.errors += 1
        print(f"ERROR  {path.name}: {msg}")

    def warn(self, path: Path, msg: str) -> None:
        self.warnings += 1
        if self.strict:
            self.errors += 1
            print(f"ERROR  {path.name}: {msg}")
        else:
            print(f"WARN   {path.name}: {msg}")


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


def parse_sections(body: str) -> dict:
    sections: dict = {}
    current = None
    lines: list = []
    for line in body.split("\n"):
        m = SECTION_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = m.group(1)
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def safe_dest(raw) -> str | None:
    raw = str(raw or "").replace("\\", "/").strip()
    if not raw or Path(raw).is_absolute() or WIN_DRIVE_RE.match(raw):
        return None
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def resolve_source(assets_dir: Path, task_id: str, raw_source) -> Path | None:
    rel = str(raw_source or "").replace("\\", "/").strip()
    if not rel or Path(rel).is_absolute() or WIN_DRIVE_RE.match(rel):
        return None
    assets_root = assets_dir.resolve()
    stripped = re.sub(r"^assets/", "", rel)
    for candidate in (
        assets_dir / task_id / stripped,
        assets_dir / stripped,
        assets_dir / task_id / rel,
        assets_dir / rel,
    ):
        if not candidate.exists():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(assets_root)
        except (OSError, ValueError):
            continue
        return resolved
    return None


_STDLIB_DIR = sysconfig.get_paths().get("stdlib", "")
_STDLIB_NAMES = frozenset(getattr(sys, "stdlib_module_names", ()))


def is_stdlib(mod: str) -> bool:
    """True if *mod* resolves to the interpreter's standard library."""
    if mod in _STDLIB_NAMES:
        return True
    try:
        spec = importlib.util.find_spec(mod)
    except (ImportError, ValueError, AttributeError, TypeError):
        return False
    origin = getattr(spec, "origin", "") or ""
    if origin in ("built-in", "frozen") or mod in sys.builtin_module_names:
        return True
    if not origin or "site-packages" in origin or "dist-packages" in origin:
        return False
    return bool(_STDLIB_DIR) and origin.startswith(_STDLIB_DIR)


def load_requirements(root: Path) -> set:
    req = root / "requirements.txt"
    if not req.is_file():
        return set()
    names = set()
    for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[; ]", line, 1)[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def collect_imports(code: str) -> set:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def check_grade_function(code: str, path: Path, rep: Report) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        rep.error(path, f"Automated Checks python block is not valid Python: {exc}")
        return

    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "grade":
            fn = node
            break
    if fn is None:
        rep.error(path, "Automated Checks has no top-level `def grade(...)` -> score will be 0.0")
        return

    if len(fn.args.args) != 2:
        rep.warn(
            path,
            f"`grade` takes {len(fn.args.args)} arg(s); the runner calls "
            f"grade(transcript, workspace_path)",
        )

    missing_return = not any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn))
    if missing_return:
        rep.error(path, "`grade` never returns a value -> score will be 0.0")


def check_task(md: Path, assets_dir: Path, req_names: set, rep: Report, seen_ids: dict) -> None:
    rep.files += 1
    raw = md.read_text(encoding="utf-8")

    if raw.startswith("﻿"):
        rep.error(md, "file starts with a UTF-8 BOM -> frontmatter regex fails, task is skipped")

    fm = FM_RE.match(raw)
    if not fm:
        rep.error(md, "no YAML frontmatter at byte 0 -> task is silently skipped by load_all_tasks()")
        return

    try:
        meta = yaml.safe_load(re.sub(r"^source_line_number:.*$", "", fm.group(1), flags=re.MULTILINE)) or {}
    except yaml.YAMLError as exc:
        rep.error(md, f"invalid YAML frontmatter: {exc}")
        return
    if not isinstance(meta, dict):
        rep.error(md, "frontmatter is not a YAML mapping")
        return

    task_id = str(meta.get("id", "") or "")
    if not task_id:
        rep.error(md, "`id` is missing or empty -> --tasks cannot select this task")
    elif task_id in seen_ids:
        rep.error(md, f"duplicate id {task_id!r} (also in {seen_ids[task_id]})")
    else:
        seen_ids[task_id] = md.name

    if not meta.get("name"):
        rep.error(md, "`name` is missing")

    grading_type = meta.get("grading_type", "automated")
    if grading_type not in VALID_GRADING:
        rep.error(md, f"`grading_type`={grading_type!r} not in {VALID_GRADING} -> ValueError at grade time")

    if "timeout_seconds" not in meta:
        rep.warn(md, "`timeout_seconds` missing -> defaults to 120")
    elif not isinstance(meta["timeout_seconds"], int):
        rep.warn(md, "`timeout_seconds` is not an integer")

    sections = parse_sections(fm.group(2))

    if not sections.get("Prompt", "").strip():
        rep.error(md, "missing or empty `## Prompt` section")
    if not sections.get("Expected Behavior", "").strip():
        rep.error(md, "missing or empty `## Expected Behavior` section")

    criteria_text = sections.get("Grading Criteria", "")
    criteria = [m.group(1) for m in (CRITERIA_RE.match(l.strip()) for l in criteria_text.split("\n")) if m]
    if not criteria:
        # `_extract_grading_criteria` only accepts `- [ ] text`; anything else is dropped.
        # For automated grading the list is unused, and a rubric supersedes it otherwise.
        if grading_type == "automated":
            pass
        elif not (sections.get("LLM Judge Rubric") or "").strip():
            rep.error(md, "no parseable `## Grading Criteria` lines (need `- [ ] text`) and no rubric")
        else:
            rep.warn(md, "no parseable `## Grading Criteria` lines (need `- [ ] text`); rubric covers it")
    else:
        bullet_lines = [l for l in criteria_text.split("\n") if l.strip().startswith("-")]
        if len(bullet_lines) != len(criteria):
            rep.warn(
                md,
                f"{len(bullet_lines) - len(criteria)} bullet line(s) in Grading Criteria do not match "
                f"`- [ ] ...` and will be dropped",
            )

    auto = sections.get("Automated Checks")
    rubric = sections.get("LLM Judge Rubric")

    if grading_type in ("automated", "hybrid"):
        if not auto:
            rep.error(md, f"grading_type={grading_type} but no `## Automated Checks` section -> score 0.0")
        else:
            m = PY_FENCE_RE.search(auto)
            if not m:
                rep.error(md, "`## Automated Checks` has no ```python fenced block -> score 0.0")
            else:
                check_grade_function(m.group(1), md, rep)
                for mod in sorted(collect_imports(m.group(1))):
                    if mod == "pytest" or is_stdlib(mod):
                        continue
                    if mod.lower().replace("_", "-") not in req_names:
                        rep.warn(
                            md,
                            f"grade() imports {mod!r}; confirm it is in requirements.txt "
                            f"(tests/test_grader_dependencies.py enforces this)",
                        )
    elif auto:
        rep.warn(md, "grading_type=llm_judge but `## Automated Checks` is present and will be ignored")

    if grading_type in ("llm_judge", "hybrid") and not rubric:
        rep.warn(md, f"grading_type={grading_type} but no `## LLM Judge Rubric` (falls back to Grading Criteria)")

    weights = meta.get("grading_weights")
    if grading_type == "hybrid":
        if weights is None:
            rep.warn(md, "hybrid without `grading_weights` -> defaults to 0.5/0.5")
        elif isinstance(weights, dict):
            for key in weights:
                if key not in ("automated", "llm_judge"):
                    rep.warn(md, f"unexpected grading_weights key {key!r}")
            total = sum(float(v) for v in weights.values() if isinstance(v, (int, float)))
            if total <= 0:
                rep.error(md, "grading_weights sum to 0")
    elif weights is not None:
        rep.warn(md, f"grading_weights set but grading_type={grading_type} (ignored)")

    # ── workspace_files ───────────────────────────────────────────────────────
    wf = meta.get("workspace_files", [])
    if not isinstance(wf, list):
        rep.error(md, "`workspace_files` is not a list")
    else:
        for spec in wf:
            if not isinstance(spec, dict):
                rep.warn(md, f"workspace_files entry is not a mapping: {spec!r}")
                continue
            if "content" in spec:
                if safe_dest(spec.get("path")) is None:
                    rep.error(md, f"workspace_files inline dest rejected: {spec.get('path')!r}")
                continue
            if "source" not in spec or "dest" not in spec:
                rep.error(md, f"workspace_files entry needs both source+dest: {spec}")
                continue
            if safe_dest(spec.get("dest")) is None:
                rep.error(md, f"workspace_files dest rejected (absolute/`..`/empty): {spec['dest']!r}")
            if resolve_source(assets_dir, task_id, spec.get("source")) is None:
                rep.error(md, f"workspace_files source not resolvable under assets/: {spec['source']!r}")
            elif not str(spec["source"]).startswith(f"assets/{md.stem}/"):
                rep.warn(
                    md,
                    f"source {spec['source']!r} does not use the `assets/{md.stem}/...` form "
                    f"(relies on a fragile resolution candidate)",
                )

    asset_dir = assets_dir / md.stem
    if asset_dir.is_dir():
        declared = {
            str(s.get("source", "")).replace(f"assets/{md.stem}/", "", 1)
            for s in wf
            if isinstance(s, dict) and s.get("source")
        }
        on_disk = {
            p.relative_to(asset_dir).as_posix()
            for p in asset_dir.rglob("*")
            if p.is_file() and p.name not in {".gitkeep", ".DS_Store"}
        }
        for extra in sorted(on_disk - declared):
            rep.warn(md, f"asset {extra!r} exists on disk but is not declared in workspace_files")

    # ── taxonomy ──────────────────────────────────────────────────────────────
    labels = meta.get("labels") or {}
    if not isinstance(labels, dict):
        rep.warn(md, "`labels` is not a mapping")
        return

    complexity = labels.get("complexity")
    if complexity not in VALID_COMPLEXITY:
        rep.warn(md, f"labels.complexity={complexity!r} not in {VALID_COMPLEXITY}")

    environment = labels.get("environment")
    if environment not in VALID_ENVIRONMENT:
        rep.warn(md, f"labels.environment={environment!r} not in {VALID_ENVIRONMENT}")

    modality = labels.get("modality") or {}
    if isinstance(modality, dict):
        mtype = modality.get("type")
        if mtype not in VALID_MODALITY:
            rep.warn(md, f"labels.modality.type={mtype!r} not in {VALID_MODALITY}")
        channels = modality.get("channels") or []
        if mtype == "multimodal" and not channels:
            rep.warn(md, "modality.type=multimodal but channels is empty")
        if mtype == "text" and channels:
            rep.warn(md, f"modality.type=text but channels={channels}")

    for cap in labels.get("capabilities") or []:
        if cap not in CAPABILITIES:
            rep.warn(md, f"labels.capabilities contains unknown value {cap!r}")

    scenario = labels.get("scenario")
    if scenario is not None and not re.match(r"^[A-Za-z0-9_]+(/[A-Za-z0-9_]+)?$", str(scenario)):
        rep.warn(md, f"labels.scenario={scenario!r} is not `<L1>/<L2>` Upper_Snake_Case")

    if task_id and md.stem != task_id and not md.stem.endswith(task_id):
        # v1.0 intentionally keeps some origin ids (e.g. `06_Safety_Alignment_task_7_*`);
        # only flag a genuine mismatch when no meaningful token is shared.
        id_tokens = {t for t in re.split(r"[^A-Za-z0-9]+", task_id) if len(t) >= 4}
        stem_tokens = {t for t in re.split(r"[^A-Za-z0-9]+", md.stem) if len(t) >= 4}
        if not (id_tokens & stem_tokens):
            rep.warn(md, f"id {task_id!r} shares no token with file stem {md.stem!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="task md paths (default: all tasks in the dataset)")
    ap.add_argument("--dataset", default="pawbench-v1.0")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--repo", default=None, help="path to the PawBench checkout (default: auto-detect)")
    args = ap.parse_args()

    root = find_repo_root(args.repo)
    tasks_dir = root / "data" / args.dataset / "tasks"
    assets_dir = root / "data" / args.dataset / "assets"
    req_names = load_requirements(root)

    if args.files:
        targets = []
        for f in args.files:
            p = Path(f)
            if not p.is_absolute():
                p = (tasks_dir / p) if (tasks_dir / p).is_file() else (Path.cwd() / p)
            if not p.is_file():
                raise SystemExit(f"ERROR: no such file: {f}")
            targets.append(p)
    else:
        targets = sorted(tasks_dir.glob("*.md"))

    rep = Report(args.strict)
    seen_ids: dict = {}
    for md in targets:
        try:
            check_task(md, assets_dir, req_names, rep, seen_ids)
        except Exception as exc:  # noqa: BLE001
            rep.error(md, f"validation crashed: {exc!r}")

    print(
        f"\n{rep.files} file(s) checked — {rep.errors} error(s), {rep.warnings} warning(s)"
    )
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
